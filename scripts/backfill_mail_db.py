# scripts/backfill_mail_db.py

# 이미 GraphRAG 인덱싱이 끝난 메일 계정에 대해, 인덱싱(build_graphrag_index/build_graph_json)은
# 다시 돌리지 않고 통계 추출(_extract_statics_pipeline, 키워드 LLM 호출 포함)과 DB 저장 단계만
# 처음부터 다시 실행한다. 인덱싱 도중 LLM API 크레딧 소진 등으로 키워드 추출이 비어있는 채로
# 저장됐을 때, 비싼 재인덱싱 없이 통계/DB만 바로잡기 위한 스크립트.

# For a mail account whose GraphRAG indexing already finished, re-run only the stats
# extraction (_extract_statics_pipeline, which includes LLM keyword extraction) and the
# DB-save steps from scratch, without re-running build_graphrag_index/build_graph_json.
# Useful when keyword extraction previously failed (e.g. LLM API credit exhaustion) and
# got saved as empty, so you can fix the stats/DB without paying for a full re-index.

import os
import sys
import argparse
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

from util.user_path import UserPaths, _account_indexed, _account_indexed_at
from util.extract_statics import _extract_statics_pipeline
from util.database.db_writer import (
    create_mail_account,
    save_person_stats_to_db,
    save_keyword_stats_to_db,
    save_mail_folder_to_db,
    save_mail_to_db,
    collect_indexing_stats,
    update_mail_account_indexing_stats,
    save_graph_stats_to_db,
)
from util.graphrag_mail_summary import generate_mail_summaries
from util.avatar_generator import generate_all_person_avatars


# mail_latest.txt에서 [ID] 라인 개수를 세어 메일 총 개수를 구한다 (재인덱싱 없이 개수만 필요할 때)
def _count_total_mails(paths) -> int:
    if not os.path.exists(paths.MAIL_LATEST_PATH):
        return 0
    with open(paths.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    import re
    return len(re.findall(r'^\[ID\][ \t]*.+$', text, re.MULTILINE))


def backfill_mail(user_id: str, mail_platform: str = "gmail", skip_avatar: bool = False):
    paths = UserPaths(BASE_DIR, user_id, "mail")

    if not _account_indexed(paths):
        print(f"[SKIP] 인덱싱 결과 없음: {user_id}")
        return

    indexed_at = _account_indexed_at(paths)
    target_update_date = (
        datetime.datetime.fromtimestamp(indexed_at) if indexed_at else datetime.datetime.now()
    )

    print(f"[START] {user_id} (index_date={target_update_date})")

    # 1) 통계/키워드 재추출 (rewrite: 이전 processed_mail_ids/키워드 통계를 버리고 처음부터)
    _extract_statics_pipeline(paths, mode="rewrite")

    mail_count = _count_total_mails(paths)

    # 2) DB 저장 (create_mail_account부터 순서대로, run_graph_pipeline의 mail 분기와 동일)
    create_mail_account(
        user_mail_account_id=paths.USER_ID,
        ended_at=target_update_date,
        index_time="backfill",
        mail_count=mail_count,
        mail_platform=mail_platform,
    )

    indexing_stats = collect_indexing_stats(paths)
    update_mail_account_indexing_stats(paths.USER_ID, None, indexing_stats)
    save_graph_stats_to_db(paths, target_update_date)

    save_mail_folder_to_db(paths, target_update_date)
    save_person_stats_to_db(paths, target_update_date)

    save_mail_to_db(paths, target_update_date)
    save_keyword_stats_to_db(paths, target_update_date)
    generate_mail_summaries(paths)

    if not skip_avatar:
        try:
            generate_all_person_avatars(paths)
        except Exception as e:
            print(f"[WARN] 아바타 생성 실패 (무시): {e}")

    print(f"[DONE] {user_id}")


def main():
    parser = argparse.ArgumentParser(description="인덱싱 재실행 없이 메일 계정 통계/DB만 재추출")
    parser.add_argument("user_id", help="계정 이메일 (예: yeeun@gmail.com)")
    parser.add_argument("--platform", default="gmail", help="mail_platform 값")
    parser.add_argument("--skip-avatar", action="store_true", help="아바타 생성 단계 건너뛰기")
    args = parser.parse_args()

    backfill_mail(args.user_id, args.platform, skip_avatar=args.skip_avatar)


if __name__ == "__main__":
    main()
