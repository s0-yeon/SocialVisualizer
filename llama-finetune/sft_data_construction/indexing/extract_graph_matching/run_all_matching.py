#!/usr/bin/env python3
"""
run_all_matching.py (v2) — build_sft_pairs.py(v2)를 이메일 도메인 + 메신저 13개 방 전체에
대해 한 번에 돌린다. (완전일치 + 쪼개진 문서용 최근접 매칭 2-pass 반영)

실행 위치 가정: 원본 합성 데이터 + GraphRAG 인덱싱 산출물이 모여있는 폴더를 --root로 지정.
    <root>/
      ├─ synthetic_mail_latest.csv                                (참고용, v2부터 미사용)
      ├─ haeun_synthetic_owner_at_gmail_com/graphrag/parquet       (이메일 graphrag 결과)
      ├─ user_data/messenger/msg_XXXXXXXX/parquet/cache/input/latest.csv   (참고용, v2부터 미사용)
      └─ 라마학습_메신저_인덱싱/msg_XXXXXXXX/graphrag/parquet      (메신저 graphrag 결과, 방별)

v2부터는 input 텍스트를 CSV가 아니라 text_units.parquet의 실제 청크 원문에서 바로 가져오므로
CSV 경로들은 더 이상 필수가 아니다(있어도 되고 없어도 됨 — 존재 여부만 확인에 사용).

사용법 (socialvisualizer-venv 활성화 후, 프로젝트 루트 무관하게 실행 가능):
    python run_all_matching.py --root ./raw_data --out-dir sft_pairs_v2

출력:
    sft_pairs_v2/email.jsonl
    sft_pairs_v2/messenger_<room>.jsonl   (방마다 하나)
    sft_pairs_v2/_unmatched/*.jsonl       (검수용)
    콘솔에 도메인별/방별 매칭률(완전일치/최근접 구분) 요약 출력

## English summary
run_all_matching.py (v2) runs build_sft_pairs.py (v2) across the full email domain plus all 13
messenger rooms in one pass, applying the exact-match + relaxed-nearest-match 2-pass strategy for
split documents.

Assumed layout: --root points at the folder holding both the raw synthetic data and the GraphRAG
indexing output (see the directory tree above). From v2 on, input text comes directly from
text_units.parquet's actual chunk text rather than the CSV, so the CSV paths are no longer
required (used only to check existence, if present). Usage and output paths are the same
regardless of language — see above.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sft_pairs import match_room  # noqa: E402


# CLI 엔트리포인트: 이메일 도메인 + 메신저 13개 방 전체를 순회하며 match_room을 돌리고 요약을 출력함
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--out-dir", default="sft_pairs_v2", type=Path)
    ap.add_argument("--relaxed-threshold", type=float, default=0.75)
    args = ap.parse_args()

    root: Path = args.root
    out_dir: Path = args.out_dir
    unmatched_dir = out_dir / "_unmatched"
    out_dir.mkdir(parents=True, exist_ok=True)
    unmatched_dir.mkdir(parents=True, exist_ok=True)

    import json

    summary = []  # (domain, room, matched, total, n_exact, n_relaxed)

    # 도메인/방 하나에 대해 match_room을 실행하고 matched/unmatched 결과를 파일로 쓴 뒤 summary에 누적함
    def run_one(graphrag_dir, domain, room_label, out_name):
        matched, unmatched, ambiguous, unused_docs, (n_exact, n_relaxed) = match_room(
            graphrag_dir, None, domain, room_label, args.relaxed_threshold
        )
        with open(out_dir / out_name, "w", encoding="utf-8") as f:
            for row in matched:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        with open(unmatched_dir / out_name, "w", encoding="utf-8") as f:
            for row in unmatched + ambiguous:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        total = len(matched) + len(unused_docs)
        print(
            f"[{domain}/{room_label}] 매칭 {len(matched)}/{total} "
            f"(완전일치 {n_exact}, 최근접 {n_relaxed}) "
            f"(미매칭 {len(unmatched)}, 모호 {len(ambiguous)})"
        )
        summary.append((domain, room_label, len(matched), total, n_exact, n_relaxed))

    # --- 이메일 도메인 ---
    email_graphrag = root / "haeun_synthetic_owner_at_gmail_com" / "graphrag" / "parquet"
    if email_graphrag.exists():
        run_one(email_graphrag, "email", "haeun_synthetic", "email.jsonl")
    else:
        print(f"[email] 건너뜀 — 경로 없음: {email_graphrag}")

    # --- 메신저 도메인 (13개 방) ---
    msg_graphrag_root = root / "라마학습_메신저_인덱싱"
    if msg_graphrag_root.exists():
        rooms = sorted(p.name for p in msg_graphrag_root.iterdir() if p.is_dir())
        for room in rooms:
            graphrag_dir = msg_graphrag_root / room / "graphrag" / "parquet"
            if not graphrag_dir.exists():
                print(f"[messenger/{room}] 건너뜀 — 경로 없음")
                continue
            run_one(graphrag_dir, "messenger", room, f"messenger_{room}.jsonl")
    else:
        print(f"[messenger] 건너뜀 — 경로 없음: {msg_graphrag_root}")

    print("\n=== 요약 ===")
    total_matched = sum(s[2] for s in summary)
    total_all = sum(s[3] for s in summary)
    total_exact = sum(s[4] for s in summary)
    total_relaxed = sum(s[5] for s in summary)
    email_matched = sum(s[2] for s in summary if s[0] == "email")
    msg_matched = sum(s[2] for s in summary if s[0] == "messenger")
    print(f"이메일: {email_matched}건")
    print(f"메신저: {msg_matched}건 ({len([s for s in summary if s[0]=='messenger'])}개 방)")
    print(f"합계: {total_matched}/{total_all}건 매칭 ({total_matched/total_all*100:.1f}%)" if total_all else "합계: 0건")
    print(f"  └ 완전일치 {total_exact}건 + 최근접(쪼개진 문서) {total_relaxed}건")
    if total_matched:
        print(f"이메일:메신저 비율 = {email_matched/total_matched*100:.0f}:{msg_matched/total_matched*100:.0f}")


if __name__ == "__main__":
    main()
