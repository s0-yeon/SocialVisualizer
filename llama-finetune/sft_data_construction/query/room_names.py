"""
room_names.py — 메신저 방 해시ID → 표시이름 매핑

로직: 메신저 각 방(예: msg_c2248847)의 GraphRAG 인덱싱 산출물인 entities.parquet에서
type == "CHATROOM"인 행만 골라, 그 방 안에서 가장 많이 언급된(=degree가 가장 큰, 또는
등장 횟수가 가장 많은) ChatRoom 엔티티의 title을 그 방의 "표시 이름"으로 채택한다
(예: msg_c2248847 → "가족방").

## English summary
room_names.py maps messenger room hash IDs to display names.

Logic: for each messenger room (e.g. msg_c2248847), take only the rows with type == "CHATROOM"
from that room's GraphRAG indexing output (entities.parquet), and adopt the title of the
most-mentioned ChatRoom entity (largest degree, or highest occurrence count) in that room as its
display name (e.g. msg_c2248847 -> "가족방"/"Family chat").
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# ⚠ 실제 GraphRAG 출력 경로 규칙은 확인되지 않음 — 프로젝트의 다른 산출물 경로 관례를 보고
# 맞춰서 조정하세요. 아래는 흔히 쓰이는 GraphRAG 기본 레이아웃을 따른 추정 경로입니다.
DEFAULT_ENTITIES_PATTERN = "{room_id}/artifacts/entities.parquet"


# entities.parquet를 읽어 type이 CHATROOM인 행만 추출함
def load_chatroom_entities(entities_parquet_path: Path) -> pd.DataFrame:
    df = pd.read_parquet(entities_parquet_path)
    # GraphRAG entities.parquet의 type 컬럼은 프롬프트에서 정의한 엔티티 타입 그대로 저장됨
    # (messenger.json 기준 ChatRoom/Person/Date/Event/Attachment/Keyword/NamedEntity)
    return df[df["type"].str.upper() == "CHATROOM"].copy()


# CHATROOM 엔티티들 중 가장 빈도 높은 것의 title을 방 표시이름으로 선택함
def pick_display_name(chatroom_df: pd.DataFrame) -> str | None:
    """가장 빈도 높은(=degree가 가장 큰) ChatRoom 엔티티의 title을 표시이름으로 채택."""
    if chatroom_df.empty:
        return None
    # entities.parquet에 degree 컬럼이 있으면 그걸 빈도 프록시로 사용, 없으면 단순 등장 횟수(행 수)로 대체
    if "degree" in chatroom_df.columns:
        best = chatroom_df.sort_values("degree", ascending=False).iloc[0]
    else:
        counts = chatroom_df["title"].value_counts()
        best_title = counts.index[0]
        best = chatroom_df[chatroom_df["title"] == best_title].iloc[0]
    return str(best["title"])


# 방 ID 목록을 순회하며 각 방의 entities.parquet에서 표시이름을 뽑아 매핑 딕셔너리를 만듦
def build_room_name_map(graphrag_output_root: Path, room_ids: list[str]) -> dict[str, str]:
    name_map: dict[str, str] = {}
    for room_id in room_ids:
        entities_path = graphrag_output_root / DEFAULT_ENTITIES_PATTERN.format(room_id=room_id)
        if not entities_path.exists():
            print(f"[WARN] {room_id}: entities.parquet 없음 ({entities_path}) — 스킵")
            continue
        chatroom_df = load_chatroom_entities(entities_path)
        display_name = pick_display_name(chatroom_df)
        if display_name is None:
            print(f"[WARN] {room_id}: ChatRoom 엔티티 없음 — 스킵")
            continue
        name_map[room_id] = display_name
        print(f"{room_id} -> {display_name}")
    return name_map


# CLI 인자를 파싱해 방 이름 매핑을 만들고 JSON으로 저장함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphrag-output-root", type=Path, required=True,
                         help="GraphRAG 메신저 인덱싱 출력 루트 (방별 하위 폴더 포함)")
    parser.add_argument("--room-ids", nargs="+", required=True,
                         help="방 해시 ID 목록 (예: msg_c2248847 msg_27d6848b ...)")
    parser.add_argument("--out", type=Path, default=Path("room_name_map.json"))
    args = parser.parse_args()

    name_map = build_room_name_map(args.graphrag_output_root, args.room_ids)
    args.out.write_text(json.dumps(name_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(name_map)}/{len(args.room_ids)}개 방 매핑 완료 -> {args.out}")


if __name__ == "__main__":
    main()
