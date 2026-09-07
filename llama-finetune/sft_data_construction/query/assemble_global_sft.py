"""
assemble_global_sft.py — global_search 최종 SFT 페어 조립

MAP + REDUCE를 합쳐 ShareGPT 포맷 SFT 페어로 조립한다.

- MAP (310쌍): system = global_search_map.txt.format(context_data=배치, max_length=1000),
  user = 질문, gpt = 실제 응답 JSON {"points": [...]}  그대로 (프로덕션이 저장하는 키 이름
  "description" 그대로 사용 — _parse_search_response()가 REDUCE 처리를 위해 내부적으로만
  "answer"로 이름을 바꿔 쓸 뿐, SFT gold는 프로덕션 원본 그대로 "description" 키로 저장)
- REDUCE (20쌍): system = global_search_reduce.txt.format(report_data=...,
  response_type, max_length=2000), user = 질문, gpt = 최종 답변 텍스트

train/val 분할: [mail_map, msg_map, mail_reduce, msg_reduce] 4개 그룹별 층화 9:1 분할 후
병합·셔플(seed=43), REDUCE 그룹은 표본이 적어 각 그룹 최소 val 2개를 보장 → 295/35.

## English summary
assemble_global_sft.py assembles the final global_search SFT pairs, combining MAP + REDUCE into
ShareGPT-format SFT pairs.

- MAP (310 pairs): system = global_search_map.txt.format(context_data=batch, max_length=1000),
  user = question, gpt = the actual response JSON {"points": [...]} verbatim (kept under the key
  name production actually stores, "description" — _parse_search_response() only renames it to
  "answer" internally for REDUCE processing; SFT gold keeps production's original "description"
  key).
- REDUCE (20 pairs): system = global_search_reduce.txt.format(report_data=..., response_type,
  max_length=2000), user = question, gpt = final answer text.

train/val split: stratified 9:1 split within each of the 4 groups
[mail_map, msg_map, mail_reduce, msg_reduce], then merged and shuffled (seed=43). The REDUCE
groups are small, so each is guaranteed at least 2 val examples -> 295/35 overall.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SEED = 43
VAL_RATIO = 0.1
REDUCE_MIN_VAL = 2  # REDUCE 그룹은 표본이 적어 각 그룹 최소 val 2개 보장


# 4개 그룹(mail_map/msg_map/mail_reduce/msg_reduce)별로 층화된 train/val 분할을 수행함
def stratified_split(groups: dict[str, list[dict]], val_ratio: float, min_val: dict[str, int], rng: random.Random):
    train, val = [], []
    for group_name, examples in groups.items():
        shuffled = examples[:]
        rng.shuffle(shuffled)
        n_val = max(min_val.get(group_name, 1), round(len(shuffled) * val_ratio))  # 비율(9:1) 기반 개수와 그룹별 최소 val 개수 중 큰 값 사용
        n_val = min(n_val, len(shuffled))  # 그룹 크기를 넘지 않도록 가드
        val.extend(shuffled[:n_val])
        train.extend(shuffled[n_val:])
        print(f"  {group_name}: {len(shuffled)}개 -> train {len(shuffled) - n_val} / val {n_val}")
    return train, val


# MAP 태스크와 실제 모델 응답을 합쳐 ShareGPT 포맷 예제로 만들고 mail_map/msg_map 그룹으로 나눔
def build_map_examples(map_results_dir: Path, map_tasks_jsonl: Path) -> dict[str, list[dict]]:
    """extract_global_batches.py가 만든 태스크(system_prompt 포함) + 실제 모델 응답을 합쳐
    ShareGPT 예제로 변환. 도메인별로 mail_map / msg_map 그룹에 나눠 담는다."""
    tasks = [json.loads(line) for line in map_tasks_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]

    groups: dict[str, list[dict]] = {"mail_map": [], "msg_map": []}
    for task in tasks:
        result_file = map_results_dir / f"{task['domain']}_{task.get('room_id') or ''}_{task['question_id']}_{task['batch_id']}.json"
        if not result_file.exists():
            print(f"[WARN] MAP 결과 없음, 스킵: {result_file}")
            continue
        gold_json = result_file.read_text(encoding="utf-8")
        example = {
            "conversations": [
                {"from": "system", "value": task["system_prompt"]},
                {"from": "human", "value": task["question"]},
                {"from": "gpt", "value": gold_json},
            ]
        }
        group = "mail_map" if task["domain"] == "mail" else "msg_map"
        groups[group].append(example)
    return groups


# REDUCE 입력과 실제 답변을 합쳐 ShareGPT 포맷 예제로 만들고 mail_reduce/msg_reduce 그룹으로 나눔
def build_reduce_examples(reduce_inputs_jsonl: Path, reduce_results_dir: Path, reduce_prompt_template: str) -> dict[str, list[dict]]:
    reduce_inputs = [json.loads(line) for line in reduce_inputs_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]

    groups: dict[str, list[dict]] = {"mail_reduce": [], "msg_reduce": []}
    for item in reduce_inputs:
        result_file = reduce_results_dir / f"{item['domain']}_{item.get('room_id') or ''}_{item['question_id']}.txt"
        if not result_file.exists():
            print(f"[WARN] REDUCE 결과 없음, 스킵: {result_file}")
            continue
        gold_answer = result_file.read_text(encoding="utf-8")
        system_prompt = reduce_prompt_template.format(
            report_data=item["report_data"],
            response_type="multiple paragraphs",
            max_length=2000,
        )
        example = {
            "conversations": [
                {"from": "system", "value": system_prompt},
                {"from": "human", "value": item["question"]},
                {"from": "gpt", "value": gold_answer},
            ]
        }
        group = "mail_reduce" if item["domain"] == "mail" else "msg_reduce"
        groups[group].append(example)
    return groups


# CLI 진입점: MAP/REDUCE 예제를 조립하고 4개 그룹별 층화 분할 후 train/val jsonl로 저장함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-tasks", type=Path, required=True)
    parser.add_argument("--map-results-dir", type=Path, required=True)
    parser.add_argument("--reduce-inputs", type=Path, required=True)
    parser.add_argument("--reduce-results-dir", type=Path, required=True)
    parser.add_argument("--global-search-reduce-prompt", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    args = parser.parse_args()

    reduce_prompt_template = args.global_search_reduce_prompt.read_text(encoding="utf-8")

    map_groups = build_map_examples(args.map_results_dir, args.map_tasks)
    reduce_groups = build_reduce_examples(args.reduce_inputs, args.reduce_results_dir, reduce_prompt_template)

    all_groups = {**map_groups, **reduce_groups}
    total = sum(len(v) for v in all_groups.values())
    print(f"조립된 예제: {[f'{k}={len(v)}' for k, v in all_groups.items()]} (합계 {total})")

    min_val = {"mail_reduce": REDUCE_MIN_VAL, "msg_reduce": REDUCE_MIN_VAL}
    rng = random.Random(SEED)
    train, val = stratified_split(all_groups, VAL_RATIO, min_val, rng)
    rng.shuffle(train)
    rng.shuffle(val)

    train_path = args.out_dir / "mailgrapher_v5_global_search_train.jsonl"
    val_path = args.out_dir / "mailgrapher_v5_global_search_val.jsonl"
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
