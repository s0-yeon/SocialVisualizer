# -*- coding: utf-8 -*-
"""
메일 + 메신저 전체 코퍼스의 커뮤니티 크기를 조사해, 프로덕션 community_reports
토큰 예산을 초과해 수작업 gold(compose_oversized.py 참고)가 필요한 커뮤니티를 찾아낸다.

Surveys community sizes across the mail + messenger corpus to identify which
communities exceed the production community_reports token budget and need
hand-written gold (see compose_oversized.py).
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_context import load_domain, build_local_contexts

# 조사 대상 13개 메신저 방 ID 목록
ROOMS = [
    "0827e9a2", "1422f5f2", "4d4d567a", "823e7fcd", "afb96430", "b8378282",
    "c2248847", "c8a7c88a", "ca4130a6", "cb5deed9", "d26b54b6", "d93f9d2f", "f7792b49",
]

MAX_INPUT_TOKENS = 5500  # production community_reports.max_input_length


# mail 도메인과 13개 메신저 방 도메인의 GraphRAG output 경로 목록을 구성함
def build_domains(raw_data_dir: str):
    domains = [("mail", "mail", os.path.join(raw_data_dir, "Llama_mail_output/Llama_mail_output/output"))]
    for r in ROOMS:
        domains.append((
            "messenger", r,
            os.path.join(raw_data_dir, f"Llama_messenger_output/Llama_messenger_output/msg_{r}/graphrag/parquet/output"),
        ))
    return domains


# 전체 도메인의 커뮤니티 컨텍스트를 빌드해 토큰 수를 조사하고, 예산 초과 커뮤니티를 CSV로 저장함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-data-dir", default="./raw_data",
                         help="GraphRAG output root containing Llama_mail_output/ and Llama_messenger_output/")
    parser.add_argument("--out", default="./work/community_survey.csv")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    all_rows = []
    for domain, room, base in build_domains(args.raw_data_dir):
        entities, relationships, communities, reports = load_domain(base)
        full_ctx = build_local_contexts(entities, relationships, communities, max_context_tokens=None)
        for (cid, level), info in full_ctx.items():
            rep_row = reports[(reports["community"] == cid) & (reports["level"] == level)]
            has_gold = len(rep_row) == 1  # 해당 (community, level)에 실제 community_reports gold가 존재하는지
            all_rows.append({
                "domain": domain, "room": room, "community": cid, "level": level,
                "n_entities": info["n_entities"], "full_tokens": info["context_size"],
                "has_gold": has_gold,
            })

    df = pd.DataFrame(all_rows)
    print("total communities:", len(df))
    print("with gold report:", df["has_gold"].sum())
    print()
    print("token distribution:")
    print(df["full_tokens"].describe())
    print()
    over = df[df["full_tokens"] > MAX_INPUT_TOKENS].sort_values("full_tokens", ascending=False)
    print(f"communities exceeding {MAX_INPUT_TOKENS} tokens (full context):", len(over))
    print(over[["domain", "room", "community", "level", "n_entities", "full_tokens", "has_gold"]].to_string(index=False))
    print()
    print("top 15 largest overall:")
    print(df.sort_values("full_tokens", ascending=False).head(15)
          [["domain", "room", "community", "level", "n_entities", "full_tokens", "has_gold"]].to_string(index=False))

    df.to_csv(args.out, index=False)
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
