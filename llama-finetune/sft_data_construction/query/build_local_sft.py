"""
build_local_sft.py — local_search 최종 SFT 페어 조립

입력: 기존 QA 엑셀 (Llama_mail_QA.xlsx, Llama_messenger_QA.xlsx — "질문", "실제 답변",
"정답 답변" 컬럼 가정)
출력: mailgrapher_v5_local_search_{train,val}.jsonl (ShareGPT 3-turn 포맷)

gold 답변 소스: "실제 답변"(프로덕션이 실제로 낸 응답)을 우선 쓰고
비어 있으면 "정답 답변"(사람이 미리 써둔 기준 답안)으로 폴백. 실측 결과 143행 전부
"실제 답변"이 채워져 있어 폴백은 한 건도 발생하지 않았음.

train/val 분할: 메일 73 + 메신저 70 = 143문항, 도메인별 9:1 비율로 분할 후 병합·셔플
(seed=42) → 129/14.

## English summary
build_local_sft.py assembles the final local_search SFT pairs.

Input: existing QA spreadsheets (Llama_mail_QA.xlsx, Llama_messenger_QA.xlsx — assumes
"질문"(question), "실제 답변"(actual answer), "정답 답변"(reference answer) columns).
Output: mailgrapher_v5_local_search_{train,val}.jsonl (ShareGPT 3-turn format).

Gold answer source: prefers "실제 답변" (the response production actually gave), falling back to
"정답 답변" (a human-written reference answer) when empty. In practice all 143 rows had
"실제 답변" filled in, so the fallback never triggered.

train/val split: mail 73 + messenger 70 = 143 questions, split 9:1 per domain, then merged and
shuffled (seed=42) -> 129/14.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

from local_build_context import (
    StubTextEmbedder,
    build_mail_context,
    build_federated_messenger_context,
    render_system_prompt,
)

SEED = 42
VAL_RATIO = 0.1  # 9:1


# 행에서 gold 답변을 뽑음: "실제 답변" 우선, 비어 있으면 "정답 답변"으로 폴백
def pick_gold_answer(row: pd.Series) -> str:
    """"실제 답변" 우선, 비어 있으면 "정답 답변"으로 폴백."""
    actual = str(row.get("실제 답변", "") or "").strip()
    if actual:
        return actual
    fallback = str(row.get("정답 답변", "") or "").strip()
    if not fallback:
        raise ValueError(f"실제 답변/정답 답변 둘 다 비어있는 행: {row.to_dict()}")
    return fallback


# system/human/gpt 3-turn 딕셔너리를 만들어 ShareGPT 포맷 학습 예제 하나로 조립함
def build_sharegpt_example(system_prompt: str, question: str, gold_answer: str) -> dict:
    return {
        "conversations": [
            {"from": "system", "value": system_prompt},
            {"from": "human", "value": question},
            {"from": "gpt", "value": gold_answer},
        ]
    }


# 예제 리스트를 셔플한 뒤 val_ratio 비율로 train/val 두 리스트로 나눔
def domain_split(examples: list[dict], val_ratio: float, rng: random.Random) -> tuple[list[dict], list[dict]]:
    shuffled = examples[:]
    rng.shuffle(shuffled)
    n_val = max(1, round(len(shuffled) * val_ratio))
    return shuffled[n_val:], shuffled[:n_val]


# CLI 엔트리포인트: QA 엑셀을 읽어 local_search SFT train/val jsonl을 만들어 저장함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mail-qa-xlsx", type=Path, required=True)
    parser.add_argument("--messenger-qa-xlsx", type=Path, required=True)
    parser.add_argument("--local-search-prompt", type=Path, required=True,
                         help="local_search.txt 프롬프트 템플릿 경로")
    parser.add_argument("--query-embeddings", type=Path, required=True,
                         help="rebuild_lancedb.py로 사전 계산한 질문 임베딩 json")
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    args = parser.parse_args()

    prompt_template = args.local_search_prompt.read_text(encoding="utf-8")
    embedder = StubTextEmbedder(args.query_embeddings)  # noqa: F841 — 실제 엔진 초기화에 주입

    examples: list[dict] = []
    rng = random.Random(SEED)

    # --- 메일 (단일계정) ---
    mail_df = pd.read_excel(args.mail_qa_xlsx)
    mail_examples = []
    for _, row in mail_df.iterrows():
        question = str(row["질문"]).strip()
        gold = pick_gold_answer(row)
        # context_data는 실제로는 build_mail_context(mail_search_engine, question)로 생성됨 —
        # 엔진 초기화(lancedb 연결 등)는 프로젝트 환경에 맞춰 별도 조립 필요.
        context_data = row.get("_precomputed_context", "")  # placeholder — 실제 파이프라인 연결 필요
        system_prompt = render_system_prompt(prompt_template, context_data, is_federated=False)
        mail_examples.append(build_sharegpt_example(system_prompt, question, gold))

    # --- 메신저 (federated, 13개 방) ---
    msg_df = pd.read_excel(args.messenger_qa_xlsx)
    msg_examples = []
    for _, row in msg_df.iterrows():
        question = str(row["질문"]).strip()
        gold = pick_gold_answer(row)
        context_data = row.get("_precomputed_context", "")  # placeholder — 실제로는
        # build_federated_messenger_context(room_search_engines, room_display_names, question)
        system_prompt = render_system_prompt(prompt_template, context_data, is_federated=True)
        msg_examples.append(build_sharegpt_example(system_prompt, question, gold))

    print(f"메일 {len(mail_examples)}개, 메신저 {len(msg_examples)}개 (합계 {len(mail_examples) + len(msg_examples)}개)")

    mail_train, mail_val = domain_split(mail_examples, VAL_RATIO, rng)
    msg_train, msg_val = domain_split(msg_examples, VAL_RATIO, rng)

    train = mail_train + msg_train
    val = mail_val + msg_val
    rng.shuffle(train)
    rng.shuffle(val)

    train_path = args.out_dir / "mailgrapher_v5_local_search_train.jsonl"
    val_path = args.out_dir / "mailgrapher_v5_local_search_val.jsonl"
    with train_path.open("w", encoding="utf-8") as f:
        for ex in train:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    with val_path.open("w", encoding="utf-8") as f:
        for ex in val:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"train {len(train)}개 -> {train_path}")
    print(f"val {len(val)}개 -> {val_path}")


if __name__ == "__main__":
    main()
