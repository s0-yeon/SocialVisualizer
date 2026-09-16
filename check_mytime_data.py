# check_mytime_data.py
# My Time이 필요로 하는 DB 데이터(mail_account의 최신 index_date, 그 index_date 기준
# mail_summarize 행)가 실제로 있는지, 여러 계정에 대해 한 번에 확인만 하는 스크립트.
# 수정/삭제 없음.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   python check_mytime_data.py

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from config.db import get_db_connection

USER_IDS = ["soyeon@icloud", "03yeeun03@naver.com", "03yeah03@gmail.com"]


def check_account(cursor, user_id: str):
    print(f"\n### {user_id}")

    cursor.execute(
        """
        SELECT user_mail_account_id, index_date, mail_count
        FROM mail_account
        WHERE user_mail_account_id = %s
        ORDER BY index_date DESC
        """,
        (user_id,),
    )
    accounts = cursor.fetchall()
    print(f"mail_account 행: {len(accounts)}건")
    for a in accounts:
        print(f"  index_date={a['index_date']} mail_count={a['mail_count']}")

    if not accounts:
        print("[결론] mail_account 자체가 없어서 get_latest_mail_account()가 None을 반환 -> My Time이 아예 404를 받습니다.")
        return

    latest_index_date = accounts[0]["index_date"]
    print(f"최신 index_date: {latest_index_date} 기준으로 mail_summarize 확인")

    for unit in ("monthly", "yearly"):
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM mail_summarize
            WHERE user_mail_account_id = %s AND index_date = %s AND summarize_unit = %s
            """,
            (user_id, latest_index_date, unit),
        )
        cnt = cursor.fetchone()["cnt"]
        print(f"  mail_summarize({unit}, 최신 index_date 기준): {cnt}건")

    # index_date 무관하게 이 계정에 mail_summarize가 아예 있는지(있다면 몇 번 index_date로 있는지)
    cursor.execute(
        "SELECT index_date, summarize_unit, COUNT(*) AS cnt FROM mail_summarize WHERE user_mail_account_id = %s GROUP BY index_date, summarize_unit ORDER BY index_date DESC",
        (user_id,),
    )
    all_rows = cursor.fetchall()
    print(f"(참고) mail_summarize 전체(index_date 무관): {len(all_rows)}개 그룹")
    for r in all_rows:
        matched = "  <- 최신 index_date와 일치" if r["index_date"] == latest_index_date else "  <- 최신 index_date와 불일치(옛날 것)"
        print(f"  index_date={r['index_date']} unit={r['summarize_unit']} count={r['cnt']}{matched}")


def main():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        for user_id in USER_IDS:
            check_account(cursor, user_id)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
