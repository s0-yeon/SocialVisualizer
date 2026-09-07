"""
build_reduce_data.py — global_search REDUCE 집계 로직 재현

로직: 모든 MAP 결과의 point를 score 내림차순 정렬(0점 제외) 후
f"----Analyst {n}----\nImportance Score: {score}\n{answer}" 형태로 포맷,
max_data_tokens=12000(cl100k_base) 예산 내에서 이어붙이고 초과분은 드롭.

검증 사실: 메일 q0가 실제로 토큰 상한에 걸려 134개 포인트 중 18개가
드롭되는 것까지 확인 — 프로덕션 트렁케이션 동작과 일치함이 재현으로 검증됨. 이 스크립트도
동일하게 정렬 → 필터 → 토큰 예산 적용 순서를 따른다.

REDUCE는 항상 정확히 1번만 실행됨 (federated인 메신저도 동일 — 각 방 MAP 결과를 모아 1회.
local_search federated와 달리 REDUCE 쪽에는 별도 하드코딩 지침 블록이 붙지 않음).

## English summary
build_reduce_data.py reproduces the global_search REDUCE aggregation logic.

Logic: sort all MAP-result points by score descending (excluding zero-score points), format each
as f"----Analyst {n}----\nImportance Score: {score}\n{answer}", then concatenate within a
max_data_tokens=12000 (cl100k_base) budget and drop whatever overflows.

Verified: mail question q0 actually hits the token cap, with 18 of its 134 points dropped —
confirming this reproduction matches production's truncation behavior exactly. This script
follows the same sort -> filter -> apply-token-budget order.

REDUCE always runs exactly once (same for federated messenger — one pass pooling every room's MAP
results. Unlike federated local_search, REDUCE has no separate hardcoded instruction block
appended).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import tiktoken

MAX_DATA_TOKENS = 12000
REDUCE_MAX_LENGTH = 2000  # global_search_reduce.txt에 넘기는 파라미터
CL100K_ENCODING = "cl100k_base"


# 특정 질문/도메인/방에 해당하는 MAP 결과 JSON 파일들을 모두 찾아 point 리스트로 합침
def load_map_results(map_results_dir: Path, question_id: str, domain: str, room_id: str | None) -> list[dict]:
    """map_results/{domain}_{room_id or ''}_{question_id}_{batch_id}.json 파일들을 모두 읽어
    {"points": [{"description", "score"}, ...]} JSON을 파싱한다."""
    pattern_prefix = f"{domain}_{room_id or ''}_{question_id}_"
    all_points = []
    for f in sorted(map_results_dir.glob(f"{pattern_prefix}*.json")):
        try:
            parsed = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[WARN] JSON 파싱 실패, 스킵: {f}")
            continue
        for point in parsed.get("points", []):
            all_points.append(point)
    return all_points


# REDUCE의 report_data 문자열을 조립함: score 정렬 후 포맷팅하여 토큰 예산 내에서만 이어붙임
def build_report_data(points: list[dict], max_data_tokens: int = MAX_DATA_TOKENS) -> tuple[str, int, int]:
    """score 내림차순 정렬(0점 제외) → 포맷 → 토큰 예산 내에서 이어붙임.

    Returns: (report_data 문자열, 포함된 point 수, 드롭된 point 수)
    """
    scored = [p for p in points if p.get("score", 0) > 0]
    scored.sort(key=lambda p: p["score"], reverse=True)

    enc = tiktoken.get_encoding(CL100K_ENCODING)
    chunks: list[str] = []
    used_tokens = 0
    included = 0

    for i, point in enumerate(scored, start=1):
        chunk = f"----Analyst {i}----\nImportance Score: {point['score']}\n{point['description']}\n"
        chunk_tokens = len(enc.encode(chunk))
        if used_tokens + chunk_tokens > max_data_tokens:
            break  # 예산 초과 시 이후 낮은 점수 포인트는 전부 드롭 (정렬돼 있으므로 여기서 중단해도 됨)
        chunks.append(chunk)
        used_tokens += chunk_tokens
        included += 1

    dropped = len(scored) - included
    return "".join(chunks), included, dropped


# CLI 진입점: 질문 목록을 읽어 질문별로 MAP 결과를 로드하고 REDUCE 입력을 jsonl로 저장함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-results-dir", type=Path, required=True)
    parser.add_argument("--questions-json", type=Path, required=True,
                         help="{'id', 'question', 'domain', 'room_id'?} 리스트")
    parser.add_argument("--out", type=Path, default=Path("reduce_inputs.jsonl"))
    args = parser.parse_args()

    questions = json.loads(args.questions_json.read_text(encoding="utf-8"))

    with args.out.open("w", encoding="utf-8") as out_f:
        for q in questions:
            points = load_map_results(args.map_results_dir, q["id"], q["domain"], q.get("room_id"))
            report_data, included, dropped = build_report_data(points)
            if dropped:
                print(f"[{q['domain']}:{q['id']}] {len(points)}개 포인트 중 {dropped}개 드롭 "
                      f"(토큰 예산 {MAX_DATA_TOKENS} 초과)")
            out_f.write(json.dumps({
                "question_id": q["id"],
                "domain": q["domain"],
                "room_id": q.get("room_id"),
                "question": q["question"],
                "report_data": report_data,
                "n_points_total": len(points),
                "n_points_included": included,
            }, ensure_ascii=False) + "\n")

    print(f"REDUCE 입력 {len(questions)}건 -> {args.out}")


if __name__ == "__main__":
    main()
