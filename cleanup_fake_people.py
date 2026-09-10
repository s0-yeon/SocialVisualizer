# cleanup_fake_people.py
#
# seed_fake_people.py(2026-08 재작성판 v2)가 넣은 시연용 가라데이터를 전부 지운다.
# 화면에 "[DEMO]" 같은 표식을 아예 남기지 않기로 했기 때문에, 텍스트 매칭 대신
# seed_fake_people.py가 가진 "정확히 어떤 데이터를 넣었는지"의 소스 오브 트루스
# (ROSTER_RAW의 이메일 목록, DEMO-MAIL-/DEMO-BLK- 내부 PK 접두어, 5개 채팅방 id +
# 우리가 넣은 summary_period 목록)를 그대로 가져와서 정확히 그 행들만 지운다.
# 실제 인덱싱된 데이터는 전혀 건드리지 않는다(채팅방 이름은 원래대로 되돌아가지
# 않으니 필요하면 직접 다시 바꿔야 함).
#
# 실행: python cleanup_fake_people.py

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv

load_dotenv("src/parquet/.env")

import mysql.connector

from seed_fake_people import (
    MAIL_USER_ID,
    DEMO_MAIL_PREFIX,
    DEMO_BLOCK_PREFIX,
    CHATROOMS,
    build_roster,
    demo_summary_periods,
)

OLD_TEST_EMAILS = [
    "minjun.kim@example.com",
    "seoyeon.lee@example.com",
    "jihoon.park@example.com",
]


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def main():
    roster = build_roster()
    emails = [p["email"] for p in roster]

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        placeholders = ",".join(["%s"] * len(emails))

        cur.execute(
            f"DELETE FROM mail_keyword WHERE user_mail_account_id=%s "
            f"AND person_mail_account_id IN ({placeholders})",
            (MAIL_USER_ID, *emails),
        )
        print(f"[OK] mail_keyword {cur.rowcount}건 삭제")

        cur.execute("DELETE FROM mail WHERE user_mail_account_id=%s AND mail_id LIKE %s",
                    (MAIL_USER_ID, DEMO_MAIL_PREFIX + "%"))
        print(f"[OK] mail {cur.rowcount}건 삭제")

        cur.execute(
            f"DELETE FROM person WHERE user_mail_account_id=%s "
            f"AND person_mail_account_id IN ({placeholders})",
            (MAIL_USER_ID, *emails),
        )
        print(f"[OK] person {cur.rowcount}건 삭제")

        cur.execute(
            "DELETE FROM person WHERE person_mail_account_id IN (%s,%s,%s)",
            tuple(OLD_TEST_EMAILS),
        )
        print(f"[OK] 예전 테스트 person {cur.rowcount}건 삭제")

        periods = demo_summary_periods()
        for chatroom in CHATROOMS:
            chatroom_id = chatroom["chatroom_id"]
            cur.execute(
                "DELETE FROM message_keyword WHERE chatroom_id=%s AND block_id LIKE %s",
                (chatroom_id, DEMO_BLOCK_PREFIX + "%"),
            )
            cur.execute(
                "DELETE FROM participant WHERE chatroom_id=%s AND block_id LIKE %s",
                (chatroom_id, DEMO_BLOCK_PREFIX + "%"),
            )
            cur.execute(
                "DELETE FROM message_block WHERE chatroom_id=%s AND block_id LIKE %s",
                (chatroom_id, DEMO_BLOCK_PREFIX + "%"),
            )
            for unit, period in periods:
                cur.execute(
                    "DELETE FROM message_summarize WHERE chatroom_id=%s AND summarize_unit=%s AND summary_period=%s",
                    (chatroom_id, unit, period),
                )
        print("[OK] 메신저 5개 방 시연용 message_block/participant/message_keyword/message_summarize 삭제")

        conn.commit()
        print("완료! 시연용 데이터가 모두 정리됐습니다(채팅방 이름은 자동으로 되돌아가지 않습니다).")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] cleanup 실패: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
