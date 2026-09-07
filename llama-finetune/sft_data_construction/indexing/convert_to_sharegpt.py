# -*- coding: utf-8 -*-
"""
최종 community_reports SFT 쌍(finalize_pairs.py 결과물)을 train/val로 분할한 뒤,
각각을 LLaMA-Factory용 ShareGPT 3-turn(system/human/gpt) JSONL로 변환한다.

Splits the final community_reports SFT pairs (finalize_pairs.py output) into
train/val, then converts each to ShareGPT 3-turn (system/human/gpt) JSONL for
LLaMA-Factory.
"""
import argparse
import json
import os
import random

MARKER = "Do not make anything up in your answer.\n"
VAL_RATIO = 0.08  # ~950 train / ~81 val, matching the split used for v5 training
SEED = 42


# instruction 텍스트를 MARKER 문구 기준으로 앞부분(system)과 뒷부분(human)으로 분리함
def split_system_human(instruction):
    idx = instruction.find(MARKER)
    if idx == -1:
        raise ValueError("split marker not found")
    split_at = idx + len(MARKER)  # MARKER 문구 자체는 system 쪽에 포함시킴
    return instruction[:split_at], instruction[split_at:]


# 하나의 instruction/output 쌍을 ShareGPT 3-turn(system/human/gpt) 대화 레코드로 변환함
def to_sharegpt_record(pair):
    system, human = split_system_human(pair["instruction"])
    return {
        "conversations": [
            {"from": "system", "value": system},
            {"from": "human", "value": human},
            {"from": "gpt", "value": pair["output"]},
        ]
    }


# 레코드 목록을 JSONL 파일로 저장하고, 메일/메신저 도메인별 건수를 집계해 출력함
def write_jsonl(records, out_path):
    n_mail, n_msg = 0, 0
    with open(out_path, "w", encoding="utf-8") as f:
        for rec, meta in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if meta["domain"] == "mail":
                n_mail += 1
            else:
                n_msg += 1
    print(f"{out_path} -> mail: {n_mail}  messenger: {n_msg}  total: {n_mail + n_msg}")


# 최종 SFT 쌍을 고정 시드로 셔플/분할한 뒤 train/val ShareGPT JSONL로 각각 저장하는 진입점
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default="./work")
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args()

    pairs = json.load(open(os.path.join(args.work_dir, "community_reports_pairs_v5.json"), encoding="utf-8"))

    rng = random.Random(SEED)
    shuffled = pairs[:]
    rng.shuffle(shuffled)
    n_val = max(1, round(len(shuffled) * VAL_RATIO))
    val_pairs, train_pairs = shuffled[:n_val], shuffled[n_val:]  # 셔플된 앞부분을 val, 나머지를 train으로 사용

    train_records = [(to_sharegpt_record(p), p["_meta"]) for p in train_pairs]
    val_records = [(to_sharegpt_record(p), p["_meta"]) for p in val_pairs]

    os.makedirs(args.out_dir, exist_ok=True)
    train_path = os.path.join(args.out_dir, "mailgrapher_v5_community_reports_train.jsonl")
    val_path = os.path.join(args.out_dir, "mailgrapher_v5_community_reports_val.jsonl")
    write_jsonl(train_records, train_path)
    write_jsonl(val_records, val_path)

    # 레코드 1개 정상 여부 확인
    with open(train_path, encoding="utf-8") as f:
        rec = json.loads(f.readline())
    print()
    print("=== sample check ===")
    for c in rec["conversations"]:
        print("FROM:", c["from"], "LEN:", len(c["value"]))


if __name__ == "__main__":
    main()
