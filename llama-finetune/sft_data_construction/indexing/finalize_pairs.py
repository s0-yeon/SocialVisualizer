# -*- coding: utf-8 -*-
"""
그대로 재사용한 gold 쌍(build_pairs.py)과 예산 초과 커뮤니티용 수작업 gold
(compose_oversized.py)를 합쳐 최종 community_reports SFT 쌍 세트를 만든다.

Merges the directly-reused gold pairs (build_pairs.py) with the hand-written
gold for oversized communities (compose_oversized.py) into the final
community_reports SFT pair set.
"""
import argparse
import json
import os
from collections import Counter
from pathlib import Path

# 렌더링된 프롬프트 템플릿(mail/messenger)이 위치한 기본 경로
DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "parquet_template" / "rendered"

MAX_REPORT_LENGTH = 2000  # 프롬프트에 삽입되는 gold community_reports 최대 길이 값


# mail/messenger 도메인별 community_reports 프롬프트 템플릿 파일을 읽어옴
def load_prompts(prompts_dir: Path):
    return {
        "mail": (prompts_dir / "mail" / "prompts" / "community_reports.txt").read_text(encoding="utf-8"),
        "messenger": (prompts_dir / "messenger" / "prompts" / "community_reports.txt").read_text(encoding="utf-8"),
    }


# 정상 쌍(pairs_normal)과 예산 초과 커뮤니티의 수작업 gold를 합쳐 최종 SFT 쌍 파일을 생성함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts-dir", default=str(DEFAULT_PROMPTS_DIR))
    parser.add_argument("--work-dir", default="./work")
    args = parser.parse_args()

    prompts = load_prompts(Path(args.prompts_dir))

    normal = json.load(open(os.path.join(args.work_dir, "pairs_normal.json"), encoding="utf-8"))
    oversized_cases = json.load(open(os.path.join(args.work_dir, "oversized_cases.json"), encoding="utf-8"))
    oversized_reports = json.load(open(os.path.join(args.work_dir, "oversized_reports.json"), encoding="utf-8"))

    pairs = list(normal)

    for case in oversized_cases:
        cid = case["community"]
        rep = oversized_reports[str(cid)]
        gold_json = json.dumps(rep, ensure_ascii=False, indent=4)  # indent=4로 gold 원본 포맷과 동일하게 직렬화
        prompt = prompts[case["domain"]].format(input_text=case["trimmed_context"], max_report_length=str(MAX_REPORT_LENGTH))
        pairs.append({
            "instruction": prompt,
            "input": "",
            "output": gold_json,
            "_meta": {
                "domain": case["domain"], "room": case["room"], "community": cid, "level": case["level"],
                "n_entities": case["n_entities"], "context_tokens_approx": case["trimmed_tokens"],
                "source": "hand_written_gold_trimmed",
            },
        })

    print("total community_reports SFT pairs:", len(pairs))
    print(Counter(p["_meta"]["domain"] for p in pairs))
    print("source=hand_written_gold_trimmed count:",
          sum(1 for p in pairs if p["_meta"]["source"] == "hand_written_gold_trimmed"))

    out_path = os.path.join(args.work_dir, "community_reports_pairs_v5.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)
    print(f"saved -> {out_path}")


if __name__ == "__main__":
    main()
