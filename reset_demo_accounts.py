# reset_demo_accounts.py
#
# 시연을 반복할 때마다 쓰는 데모용 계정 2개를 "완전 초기화"한다:
#   - 메일: suntest225@gmail.com
#   - 메신저: f44255c7db2e52a33006974c4fdc9d934e990c9d (방금 새로 만든 시연용 방)
#
# 여기 명시된 이 두 대상 외에는 절대 건드리지 않는다. 특히 김도현 HS 채팅방
# (64c6eaa5a654c2e3c7948bec2be03b3dbe63fb43)은 하드코딩으로 접근조차 안 하도록
# 방지해뒀다.
#
# 하는 일:
#   1. user_data/mail/suntest225_at_gmail_com, user_data/messenger/f44255...9d 폴더 삭제
#      -> 이게 지워져야 "데이터 선택" 목록에서 사라진다(list_accounts가 폴더를 스캔하므로).
#   2. DB에서 각각의 user_mail_account_id / chatroom_id로 걸린 모든 행 삭제
#      -> 이게 안 지워지면 다음 시연 인덱싱 때 index_date가 계속 쌓여서
#         My Time 같은 곳에서 index_date 불일치 문제가 또 생길 수 있다.
#
# 실행 전 계획을 모두 출력하고, y를 입력해야만 실제로 삭제한다.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   python reset_demo_accounts.py

import sys
import os
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from config.db import get_db_connection

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAIL_USER_ID = "suntest225@gmail.com"
MAIL_DIR = os.path.join(BASE_DIR, "user_data", "mail", "suntest225_at_gmail_com")
MAIL_TABLES = [
    "mail_account", "person", "mail", "mail_folder",
    "mail_keyword", "mail_summarize", "processed_attachments",
]

CHATROOM_ID = "f44255c7db2e52a33006974c4fdc9d934e990c9d"
CHATROOM_DIR = os.path.join(BASE_DIR, "user_data", "messenger", CHATROOM_ID)
CHATROOM_TABLES = [
    "chatroom", "message_block", "participant", "chatroom_people",
    "chatroom_relationship", "message_keyword", "message_summarize", "message_mood",
]

# 안전장치 — 이 스크립트가 절대 건드려선 안 되는 ID (실수로 위 값이 바뀌어도 여기서 막는다)
PROTECTED_IDS = {"64c6eaa5a654c2e3c7948bec2be03b3dbe63fb43"}


def main():
    assert CHATROOM_ID not in PROTECTED_IDS, "보호된 채팅방 ID는 초기화할 수 없습니다."
    assert MAIL_USER_ID not in PROTECTED_IDS

    print("### 초기화 계획")
    print(f"[메일] {MAIL_USER_ID}")
    print(f"  폴더: {MAIL_DIR} (존재: {os.path.isdir(MAIL_DIR)})")
    print(f"  DB 테이블: {', '.join(MAIL_TABLES)}")
    print(f"\n[메신저] {CHATROOM_ID}")
    print(f"  폴더: {CHATROOM_DIR} (존재: {os.path.isdir(CHATROOM_DIR)})")
    print(f"  DB 테이블: {', '.join(CHATROOM_TABLES)}")

    print("\n" + "=" * 50)
    answer = input("위 두 대상만 정확히 지웁니다. 실행할까요? (y 입력 시 실행): ").strip().lower()
    if answer != "y":
        print("실행하지 않고 종료합니다. 아무것도 바뀌지 않았습니다.")
        return

    # 1. DB 삭제
    # 테이블 간 FK(예: mail_folder -> mail_account, message_keyword -> message_block)가
    # 여러 겹으로 얽혀 있어 삭제 순서를 다 맞추기보다, 이 트랜잭션 동안만 FK 검사를 잠깐
    # 꺼서 두 대상(위에서 하드코딩된 이 계정/이 채팅방)의 관련 행만 순서 상관없이 지운다.
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        for table in MAIL_TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE user_mail_account_id = %s", (MAIL_USER_ID,))
            print(f"  [DB] {table}: {cursor.rowcount}행 삭제 (mail)")
        for table in CHATROOM_TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE chatroom_id = %s", (CHATROOM_ID,))
            print(f"  [DB] {table}: {cursor.rowcount}행 삭제 (messenger)")
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[오류] DB 삭제 중 문제 발생, 롤백했습니다: {e}")
        try:
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        except Exception:
            pass
        cursor.close()
        conn.close()
        return
    finally:
        cursor.close()
        conn.close()

    # 2. 폴더 삭제 (DB가 먼저 성공적으로 지워진 뒤에만 진행)
    if os.path.isdir(MAIL_DIR):
        shutil.rmtree(MAIL_DIR)
        print(f"  [폴더] 삭제 완료: {MAIL_DIR}")
    if os.path.isdir(CHATROOM_DIR):
        shutil.rmtree(CHATROOM_DIR)
        print(f"  [폴더] 삭제 완료: {CHATROOM_DIR}")

    print("\n완료. 서버 재시작 후 '데이터 선택'에서 두 계정이 사라진 걸 확인하세요.")


if __name__ == "__main__":
    main()
