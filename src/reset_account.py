# reset_account.py
# 특정 계정의 mail_account/person/mail/mail_keyword/mail_folder 행을 전부 삭제한다.
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   가상환경 켜고 -> python reset_account.py

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from config.db import get_db_connection

USER_ID = "soyeon@icloud"

TABLES = ["mail_keyword", "mail_folder", "mail", "person", "mail_account"]

conn = get_db_connection()
cursor = conn.cursor()

print(f"### {USER_ID} 관련 행 삭제 시작")
cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
try:
    for table in TABLES:
        cursor.execute(f"DELETE FROM {table} WHERE user_mail_account_id = %s", (USER_ID,))
        print(f"  {table}: {cursor.rowcount}건 삭제")
    conn.commit()
    print("완료. 이제 이 계정을 --syncmode rewrite로 다시 인덱싱하면 됩니다.")
except Exception:
    conn.rollback()
    raise
finally:
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    cursor.close()
    conn.close()