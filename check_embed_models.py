import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from config.db import get_db_connection


def main():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT user_mail_account_id, index_date, embed_model
            FROM mail_account
            ORDER BY user_mail_account_id, index_date DESC
            """
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    seen = set()
    print("### 계정별 최신 index_date의 embed_model\n")
    for r in rows:
        uid = r["user_mail_account_id"]
        if uid in seen:
            continue
        seen.add(uid)
        embed = r["embed_model"] or "(비어있음)"
        note = ""
        if "bge" in embed.lower():
            note = "  <- 로컬(bge-m3)로 인덱싱됨. OpenAI 전환 시 재임베딩 필요"
        elif "text-embedding" in embed.lower():
            note = "  <- 이미 OpenAI 임베딩"
        print(f"  {uid} | index_date={r['index_date']} | embed_model={embed}{note}")


if __name__ == "__main__":
    main()
