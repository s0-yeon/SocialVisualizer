# resync_db_only.py
# GraphRAG 인덱싱 결과(parquet)는 이미 디스크에 있는 걸 그대로 쓰고 재인덱싱은 하지 않는다.
# 다만 키워드 등 통계는 이전 실행에서 LLM 호출(API 크레딧 소진 등)이 실패해 비어있는 채로
# 저장됐을 수 있으므로, 통계 재추출(_extract_statics_pipeline, mode="rewrite")부터 다시 돌린
# 뒤 DB 저장 단계(create_mail_account ~ save_mail_to_db 등)를 실행한다.
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   가상환경 켜고 -> python resync_db_only.py [user_id] [mail_platform]
#   인자를 안 주면 아래 기본값(USER_ID/MAIL_PLATFORM)을 사용
# 필요하면 먼저 reset_account.py로 기존 DB 행을 지우고 실행하세요.

import sys
import os
import re
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from config.settings import BASE_DIR
from util.user_path import UserPaths
from util.extract_statics import _extract_statics_pipeline
from util.database.db_writer import (
    create_mail_account,
    collect_indexing_stats,
    update_mail_account_indexing_stats,
    save_graph_stats_to_db,
    save_mail_folder_to_db,
    save_person_stats_to_db,
    save_mail_to_db,
    save_keyword_stats_to_db,
)

USER_ID = sys.argv[1] if len(sys.argv) > 1 else "soyeon@icloud"
MAIL_PLATFORM = sys.argv[2] if len(sys.argv) > 2 else "icloud"

paths = UserPaths(BASE_DIR, USER_ID, "mail")

# mail_latest.txt의 [ID] 라인 개수로 메일 총 건수를 구함 (참고용 메타데이터일 뿐, 동작에 영향 없음)
def _count_total_mails(p):
    if not os.path.exists(p.MAIL_LATEST_PATH):
        return 0
    with open(p.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    return len(re.findall(r'^\[ID\][ \t]*.+$', text, re.MULTILINE))

MAIL_COUNT = _count_total_mails(paths)
target_update_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

print(f"### {USER_ID} DB 재저장 시작 (index_date={target_update_date})")

print("[0] 통계/키워드 재추출 (인덱싱 결과 parquet는 그대로 재사용, LLM 키워드 추출만 처음부터 다시)")
_extract_statics_pipeline(paths, mode="rewrite")

print("[1] mail_account 생성")
create_mail_account(
    user_mail_account_id=USER_ID,
    ended_at=target_update_date,
    index_time="0:00:00",
    mail_count=MAIL_COUNT,
    mail_platform=MAIL_PLATFORM,
)

print("[2] 인덱싱 통계(캐시) 반영")
stats = collect_indexing_stats(paths)
update_mail_account_indexing_stats(USER_ID, target_update_date, stats)

print("[3] 그래프 통계 저장")
save_graph_stats_to_db(paths, target_update_date)

print("[4] mail_folder 저장")
save_mail_folder_to_db(paths, target_update_date)

print("[5] person 저장 (LLM 프로필 생성 포함 — 시간이 좀 걸릴 수 있음)")
save_person_stats_to_db(paths, target_update_date)

print("[6] mail 저장 (메일별 LLM 어조 판별 포함)")
save_mail_to_db(paths, target_update_date)

print("[7] mail_keyword 저장")
save_keyword_stats_to_db(paths, target_update_date)

print("완료. check_account.py로 mail_account/mail 최신 index_date가 같은지 확인해보세요.")