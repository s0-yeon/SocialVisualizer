#!/usr/bin/env python3
"""
build_llamafactory_dataset.py (v2) — sft_pairs_v2/*.jsonl(build_sft_pairs.py v2 결과)를 받아서
실제 extract_graph 프롬프트(mail/messenger 최신 렌더링본)를 입혀 LLaMA-Factory용 학습 파일을 만든다.

v3의 mailgrapher_v3_lora.yaml / dataset_info.json 컨벤션을 그대로 따른다:
  - 포맷: alpaca가 아니라 **sharegpt** (conversations: [system, human, gpt])
  - 도메인별로 파일을 분리 (email / messenger), train/val도 분리
  - 메신저 train만 목표 비율(--target-ratio)에 맞춰 업샘플링, 파일명에 "_upsampled" 접미사

## system/human 분할 기준
graphrag가 실제로 LLM에 보내는 텍스트(extract_graph.txt 렌더링본)의 마지막 부분은:
    -Real Data-
    Entity_types: {entity_types}
    Text: {input_text}
    Output:
{entity_types}는 도메인 고정값이라 "Entity_types: ..." 줄까지는 매 예시 동일 → system.
{input_text}만 예시마다 다름 → 그 이후("Text: ...\nOutput:")는 human.
이렇게 나누면 실제 인덱싱 때 모델이 받는 토큰 시퀀스(system+human 이어붙인 것)가 원본 프롬프트와
글자 단위로 동일하면서, LLaMA-Factory의 sharegpt 학습 포맷(system 롤 지원)에도 맞는다.

## English summary
build_llamafactory_dataset.py (v2) takes sft_pairs_v2/*.jsonl (build_sft_pairs.py v2 output) and
attaches the real extract_graph prompt (latest rendered mail/messenger version) to produce
LLaMA-Factory training files.

Follows the v3 mailgrapher_v3_lora.yaml / dataset_info.json convention:
  - Format: **sharegpt** (conversations: [system, human, gpt]), not alpaca
  - Files are split by domain (email / messenger), each further split into train/val
  - Only the messenger train split is upsampled to the target ratio (--target-ratio),
    with an "_upsampled" suffix in the filename

system/human split rule: the tail of the text GraphRAG actually sends the LLM (the rendered
extract_graph.txt) ends with "-Real Data-\nEntity_types: {entity_types}\nText: {input_text}\nOutput:".
{entity_types} is fixed per domain, so everything up to "Entity_types: ..." is identical across
examples -> system. Only {input_text} differs per example, so everything from "Text: ..." onward
-> human. This keeps the token sequence the model actually sees at indexing time
(system+human concatenated) character-for-character identical to the original prompt, while
fitting LLaMA-Factory's sharegpt format (which supports a system role).

## 사용법
    python build_llamafactory_dataset.py \
        --sft-pairs-dir sft_pairs_v2 \
        --mail-prompt ".../rendered/mail/prompts/extract_graph.txt" \
        --mail-settings ".../rendered/mail/settings.yaml" \
        --messenger-prompt ".../rendered/messenger/prompts/extract_graph.txt" \
        --messenger-settings ".../rendered/messenger/settings.yaml" \
        --out-dir lora_training_data_v4 \
        --target-ratio 60:40 \
        --val-ratio 0.05

## 출력
    lora_training_data_v4/mailgrapher_v4_email_sft_train.jsonl
    lora_training_data_v4/mailgrapher_v4_email_sft_val.jsonl
    lora_training_data_v4/mailgrapher_v4_messenger_sft_train_upsampled.jsonl
    lora_training_data_v4/mailgrapher_v4_messenger_sft_val.jsonl
    lora_training_data_v4/dataset_info_snippet.json   (기존 dataset_info.json에 병합해서 쓸 스니펫)
"""
import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path

SEED = 20260818

REAL_DATA_MARKER = "-Real Data-"


# settings.yaml에서 entity_types 리스트를 정규식으로 추출함
def load_entity_types(settings_path: Path) -> list[str]:
    text = settings_path.read_text(encoding="utf-8")
    m = re.search(r"entity_types:\s*\[([^\]]*)\]", text)
    if not m:
        raise ValueError(f"entity_types를 {settings_path}에서 못 찾음")
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


# extract_graph.txt 렌더링본을 "-Real Data-" 마커 기준으로 system 고정부/human 템플릿으로 분할함
def build_system_and_human_template(prompt_path: Path, settings_path: Path):
    """extract_graph.txt를 (system 고정 프리픽스, human 템플릿) 으로 분할.

    human 템플릿은 아직 {input_text} 플레이스홀더를 갖고 있고, 예시별로 채워진다.
    """
    raw = prompt_path.read_text(encoding="utf-8")
    entity_types = load_entity_types(settings_path)
    filled = raw.replace("{entity_types}", ", ".join(entity_types))

    idx = filled.find(REAL_DATA_MARKER)
    if idx == -1:
        raise ValueError(f"{prompt_path}에 '{REAL_DATA_MARKER}' 마커가 없음 — 렌더링본 구조 확인 필요")

    # "-Real Data-\nEntity_types: ...\n" 까지 system, 그 다음 "Text: {input_text}..."부터 human
    real_data_block = filled[idx:]
    text_idx = real_data_block.find("\nText:")
    if text_idx == -1:
        raise ValueError(f"{prompt_path}의 '-Real Data-' 섹션에 'Text:' 줄이 없음")

    system_part = filled[: idx] + real_data_block[:text_idx]
    human_template = real_data_block[text_idx + 1 :]  # "Text: {input_text}\nOutput:" 부분

    if "{input_text}" not in human_template:
        raise ValueError(f"{prompt_path}: human 템플릿에 {{input_text}}가 없음")

    return system_part.strip("\n"), human_template


# sft_pairs_v2 디렉터리의 *.jsonl 파일들을 모두 읽어 행 리스트로 합침 (밑줄로 시작하는 파일은 제외)
def load_pairs(sft_pairs_dir: Path):
    rows = []
    for p in sorted(sft_pairs_dir.glob("*.jsonl")):
        if p.name.startswith("_"):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


# (domain, document_id) 기준으로 행들을 그룹핑함 (같은 문서의 여러 청크를 묶기 위함)
def group_by_document(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["domain"], r["id"])].append(r)
    return groups


# 문서(청크 그룹) 단위로 도메인별 train/val을 나눔 — 같은 문서의 청크가 train/val에 걸쳐 섞이지 않도록 함
def split_train_val(rows, val_ratio, seed):
    rng = random.Random(seed)
    groups = group_by_document(rows)
    by_domain_docs = defaultdict(list)
    for (domain, doc_id), group_rows in groups.items():
        by_domain_docs[domain].append((doc_id, group_rows))

    train, val = defaultdict(list), defaultdict(list)
    for domain, docs in by_domain_docs.items():
        docs = docs[:]
        rng.shuffle(docs)
        # 문서가 2개 이상일 때만 val을 떼어냄 (문서가 1개뿐이면 val 없이 전부 train)
        n_val_docs = max(1, round(len(docs) * val_ratio)) if len(docs) > 1 else 0
        val_docs = docs[:n_val_docs]
        train_docs = docs[n_val_docs:]
        for _, group_rows in val_docs:
            val[domain].extend(group_rows)
        for _, group_rows in train_docs:
            train[domain].extend(group_rows)
    return train, val


# target_ratio(예: 60:40)에 맞춰 메신저 train 샘플을 email 개수 기준으로 복제/샘플링함
def upsample_messenger(train_by_domain, target_ratio: str, seed):
    rng = random.Random(seed)
    if "email" not in train_by_domain or "messenger" not in train_by_domain:
        return train_by_domain.get("messenger", [])

    e_target, m_target = (int(x) for x in target_ratio.split(":"))
    n_email = len(train_by_domain["email"])
    desired_msg = round(n_email * m_target / e_target)

    pool = train_by_domain["messenger"][:]
    n_msg = len(pool)
    rng.shuffle(pool)
    if desired_msg <= n_msg:
        return pool[:desired_msg]
    # 목표 개수가 원본보다 많으면 통째로 반복(reps)한 뒤 나머지(remainder)만 앞에서 잘라 채운다
    reps = desired_msg // n_msg
    remainder = desired_msg % n_msg
    return pool * reps + pool[:remainder]


# SFT 쌍 한 건을 sharegpt 포맷(conversations: system/human/gpt)으로 변환함
def to_sharegpt(row, system_templates: dict, human_templates: dict) -> dict:
    domain = row["domain"]
    human = human_templates[domain].replace("{input_text}", row["input"])
    return {
        "conversations": [
            {"from": "system", "value": system_templates[domain]},
            {"from": "human", "value": human},
            {"from": "gpt", "value": row["output"]},
        ],
        "_meta": {
            "id": row["id"],
            "text_unit_id": row.get("text_unit_id"),
            "domain": domain,
            "room": row.get("room"),
            "match_method": row.get("match_method"),
            "match_score": row.get("match_score"),
        },
    }


# 행 리스트를 JSONL 파일로 저장함
def write_jsonl(rows, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# CLI 엔트리포인트: sft_pairs_v2를 읽어 프롬프트를 입히고 train/val + 업샘플링까지 거쳐 LLaMA-Factory용 jsonl과 dataset_info 스니펫을 만듦
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sft-pairs-dir", required=True, type=Path)
    ap.add_argument("--mail-prompt", required=True, type=Path)
    ap.add_argument("--mail-settings", required=True, type=Path)
    ap.add_argument("--messenger-prompt", required=True, type=Path)
    ap.add_argument("--messenger-settings", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--target-ratio", default="60:40", help="train 세트 email:messenger 목표 비율")
    ap.add_argument("--val-ratio", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    system_templates, human_templates = {}, {}
    system_templates["email"], human_templates["email"] = build_system_and_human_template(
        args.mail_prompt, args.mail_settings
    )
    system_templates["messenger"], human_templates["messenger"] = build_system_and_human_template(
        args.messenger_prompt, args.messenger_settings
    )

    rows = load_pairs(args.sft_pairs_dir)
    print(f"원본 매칭쌍 총 {len(rows)}건 (email {sum(1 for r in rows if r['domain']=='email')}, "
          f"messenger {sum(1 for r in rows if r['domain']=='messenger')})")

    train_by_domain, val_by_domain = split_train_val(rows, args.val_ratio, args.seed)
    msg_upsampled = upsample_messenger(train_by_domain, args.target_ratio, args.seed)

    n_email = len(train_by_domain.get("email", []))
    n_msg_up = len(msg_upsampled)
    print(f"문서 단위 분리 후 train: email {n_email}건, messenger(원본) {len(train_by_domain.get('messenger', []))}건")
    print(f"메신저 업샘플링({args.target_ratio}) 후: {n_msg_up}건 "
          f"(합계 {n_email + n_msg_up}건 중 email {n_email/(n_email+n_msg_up)*100:.0f}% / "
          f"messenger {n_msg_up/(n_email+n_msg_up)*100:.0f}%)")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    files_written = {}
    for domain in ["email", "messenger"]:
        train_rows = train_by_domain.get(domain, []) if domain == "email" else msg_upsampled
        val_rows = val_by_domain.get(domain, [])

        train_suffix = "_upsampled" if domain == "messenger" else ""
        train_path = args.out_dir / f"mailgrapher_v4_{domain}_sft_train{train_suffix}.jsonl"
        val_path = args.out_dir / f"mailgrapher_v4_{domain}_sft_val.jsonl"

        write_jsonl([to_sharegpt(r, system_templates, human_templates) for r in train_rows], train_path)
        write_jsonl([to_sharegpt(r, system_templates, human_templates) for r in val_rows], val_path)
        print(f"  -> {train_path} ({len(train_rows)}건)")
        print(f"  -> {val_path} ({len(val_rows)}건)")
        files_written[f"mailgrapher_v4_{domain}"] = train_path.name
        files_written[f"mailgrapher_v4_{domain}_val"] = val_path.name

    # 참고용 최대 길이 통계 (전체 원본 rows 기준, train/val 합쳐서)
    # 예시 하나의 system+human+output 총 글자 수를 구함 (최대 길이 참고 통계용)
    def total_len(r, domain):
        human = human_templates[domain].replace("{input_text}", r["input"])
        return len(system_templates[domain]) + len(human) + len(r["output"])

    max_chars = max(total_len(r, r["domain"]) for r in rows)
    print(f"\n참고: system+human+output 최대 글자 수 = {max_chars:,}자")

    dataset_info_snippet = {}
    for key, fname in files_written.items():
        dataset_info_snippet[key] = {
            "file_name": fname,
            "formatting": "sharegpt",
            "columns": {"messages": "conversations"},
            "tags": {
                "role_tag": "from", "content_tag": "value",
                "user_tag": "human", "assistant_tag": "gpt", "system_tag": "system",
            },
        }
    with open(args.out_dir / "dataset_info_snippet.json", "w", encoding="utf-8") as f:
        json.dump(dataset_info_snippet, f, ensure_ascii=False, indent=2)
    print(f"  -> {args.out_dir / 'dataset_info_snippet.json'} "
          f"(기존 data/dataset_info.json에 이 키들을 병합해서 넣으면 됨 — file_name은 이 폴더를 "
          f"dataset_dir로 잡거나, 경로를 절대경로로 바꿔서 넣을 것)")


if __name__ == "__main__":
    main()
