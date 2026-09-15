# scripts/backfill_chatroom_db.py

# 이미 GraphRAG 인덱싱까지는 끝났지만 DB에는 아직 저장되지 않은 메신저(messenger) 계정을
# 대상으로, 인덱싱을 다시 돌리지 않고 DB 저장 단계만 골라서 실행하는 백필 스크립트.
# job_run_graphrag.py의 run_graph_pipeline() 중 messenger 분기(DB 저장 부분)만 그대로 재사용한다.

# Backfills the database for messenger accounts that were already indexed by GraphRAG but
# never had their DB rows written, without re-running indexing itself. Reuses the exact
# messenger branch (DB-saving steps only) from run_graph_pipeline() in job_run_graphrag.py.

import os
import sys
import argparse
import datetime
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

from util.user_path import UserPaths, list_accounts, _account_indexed, _account_indexed_at, ACCOUNT_META_FILENAME
from util.database.db_writer import collect_indexing_stats
from util.message_statics import _extract_message_statics_pipeline, _parse_message_blocks_from_parquet, count_total_messages
from util.database.chatroom_db_writer import (
    create_chatroom, update_chatroom_indexing_stats, save_chatroom_graph_stats_to_db,
    save_message_block_to_db, save_chatroom_people_to_db, save_message_keyword_to_db,
    save_chatroom_relationships_to_db,
)
from util.message_summary import generate_message_summaries
from util.message_mood import recompute_all_message_moods
from util.avatar_generator import generate_chatroom_people_avatars_batch


# user_data/messenger 밑 폴더명(해시)을 account.json에 적힌 원본 user_id로 되돌린다.
# UserPaths가 내부에서 user_id를 다시 해싱해 폴더명을 만들기 때문에, 폴더명 문자열을
# user_id로 그대로 넘기면 다른 경로를 가리킬 수 있어 반드시 이 매핑을 거쳐야 한다.
def _resolve_user_id_by_dir(dir_name: str) -> str | None:
    dir_path = os.path.join(BASE_DIR, "user_data", "messenger", dir_name)
    meta_path = os.path.join(dir_path, ACCOUNT_META_FILENAME)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
            return (meta.get("user_id") or "").strip() or None
    except (OSError, json.JSONDecodeError):
        return None


# 인덱싱된 계정 하나를 대상으로 DB 저장 단계만 실행한다 (run_graph_pipeline의 messenger 분기와 동일한 순서)
def backfill_one(user_id: str, mail_platform: str):
    paths = UserPaths(BASE_DIR, user_id, "messenger")

    if not _account_indexed(paths):
        print(f"[SKIP] 인덱싱 결과 없음: {user_id}")
        return

    indexed_at = _account_indexed_at(paths)
    target_update_date = datetime.datetime.fromtimestamp(indexed_at) if indexed_at else datetime.datetime.now()

    print(f"[START] {user_id} (index_date={target_update_date})")

    _extract_message_statics_pipeline(paths, mode="rewrite")

    blocks = _parse_message_blocks_from_parquet(paths)
    chatroom_name = blocks[0]["chatroom_name"] if blocks else user_id

    create_chatroom(
        chatroom_id=user_id,
        chatroom_name=chatroom_name,
        ended_at=target_update_date,
        index_time="backfill",
        message_count=count_total_messages(paths),
        message_platform=mail_platform,
    )

    indexing_stats = collect_indexing_stats(paths)
    update_chatroom_indexing_stats(user_id, target_update_date, indexing_stats)
    save_chatroom_graph_stats_to_db(paths, target_update_date)

    save_message_block_to_db(paths, target_update_date)
    save_chatroom_people_to_db(paths, target_update_date)
    save_message_keyword_to_db(paths, target_update_date)
    generate_message_summaries(paths)

    save_chatroom_relationships_to_db(paths, target_update_date)
    recompute_all_message_moods(paths)

    try:
        generate_chatroom_people_avatars_batch(paths)
    except Exception as e:
        print(f"[WARN] 아바타 생성 실패 (무시): {e}")

    print(f"[DONE] {user_id}")


def main():
    parser = argparse.ArgumentParser(description="인덱싱된 메신저 계정 DB 백필")
    parser.add_argument("dirs", nargs="*", help="user_data/messenger 밑 대상 폴더명(해시) 목록. 생략하면 --all 필요")
    parser.add_argument("--all", action="store_true", help="user_data/messenger 밑 인덱싱된 계정 전부 대상")
    parser.add_argument("--list", action="store_true", help="대상 후보 폴더명과 room_name만 출력하고 종료")
    parser.add_argument("--platform", default="kakao", help="message_platform 값 (기본: kakao)")
    args = parser.parse_args()

    if args.list:
        messenger_dir = os.path.join(BASE_DIR, "user_data", "messenger")
        for dir_name in sorted(os.listdir(messenger_dir)):
            user_id = _resolve_user_id_by_dir(dir_name)
            print(f"{dir_name}  ->  {user_id!r}")
        return

    if args.all:
        targets = [a["user_id"] for a in list_accounts(BASE_DIR, "messenger") if a["indexed"]]
    elif args.dirs:
        targets = []
        for dir_name in args.dirs:
            user_id = _resolve_user_id_by_dir(dir_name)
            if not user_id:
                print(f"[SKIP] account.json 없음/매핑 실패: {dir_name}")
                continue
            targets.append(user_id)
    else:
        parser.error("폴더명을 하나 이상 넘기거나 --all을 쓰세요 (후보 확인: --list)")
        return

    print(f"[TARGETS] {len(targets)}개: {targets}")
    for user_id in targets:
        try:
            backfill_one(user_id, args.platform)
        except Exception as e:
            print(f"[ERROR] {user_id} 실패: {e}")


if __name__ == "__main__":
    main()
