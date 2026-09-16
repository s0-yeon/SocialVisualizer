# check_account.py
# 여러 계정의 mail_account/person/mail 테이블 상태를 한 번에 점검하는 진단 스크립트.
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   가상환경 켜고 -> python check_account.py

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from config.db import get_db_connection

USER_IDS = ["03yeah03@gmail.com", "soyeon@icloud.com", "03yeeun03@naver.com"]


def check(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    print("=" * 70)
    print(f"### {user_id}")
    print("=" * 70)

    print(f"[1] mail_account 최신 5건")
    cursor.execute(
        "SELECT index_date, mail_count, node_count, edge_count, llm_model FROM mail_account "
        "WHERE user_mail_account_id = %s ORDER BY index_date DESC LIMIT 5",
        (user_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        print("  -> 결과 없음! mail_account 테이블에 이 계정이 아예 없습니다.")
    else:
        for r in rows:
            print(" ", r)
    latest_index_date = rows[0]["index_date"] if rows else None

    print()
    print(f"[2] person 테이블 (최신 index_date={latest_index_date} 기준)")
    if latest_index_date:
        cursor.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN person_name IS NOT NULL AND person_name != '' THEN 1 ELSE 0 END) AS named "
            "FROM person WHERE user_mail_account_id = %s AND index_date = %s",
            (user_id, latest_index_date),
        )
        print(" ", cursor.fetchone())
    else:
        print("  -> mail_account가 없어서 건너뜀")

    print()
    print(f"[3] mail 테이블 index_date별 카운트")
    cursor.execute(
        "SELECT index_date, COUNT(*) AS cnt FROM mail WHERE user_mail_account_id = %s "
        "GROUP BY index_date ORDER BY index_date DESC LIMIT 5",
        (user_id,),
    )
    rows2 = cursor.fetchall()
    if not rows2:
        print("  -> mail 테이블에 이 계정 데이터가 아예 없음")
    else:
        for r in rows2:
            print(" ", r)

    print()
    print(f"[4] mail_keyword / mail_folder 등 부가 테이블 카운트 (최신 index_date 기준)")
    for table in ("mail_keyword", "mail_folder"):
        try:
            cursor.execute(
                f"SELECT COUNT(*) AS cnt FROM {table} WHERE user_mail_account_id = %s AND index_date = %s",
                (user_id, latest_index_date),
            )
            print(f"  {table}:", cursor.fetchone())
        except Exception as e:
            print(f"  {table}: 조회 실패 ({e})")

    print()
    cursor.close()
    conn.close()


for uid in USER_IDS:
    check(uid)
    print()
