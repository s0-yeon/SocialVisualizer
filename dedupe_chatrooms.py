# dedupe_chatrooms.py
#
# 요청 — "메신저 데이터 선택" 목록에 "IT 공과대학 공지방"이랑 "헬스장 운동 메이트"가
# 두 개씩(서로 다른 chatroom_id) 중복으로 떠서, 각각 하나씩 — 더 오래전에 만들어진
# 쪽만 남기고 나중에 생긴 쪽을 완전히 지우는 스크립트.
#
#  1) "IT 공과대학"(chatroom_id 1c51f4c...)은 seed_fake_people.py가 이번 하드코딩
#     작업 중에 직접 새로 만든 가짜 방(원래 인덱싱된 적 없음)이라 chatroom_id를
#     정확히 알고 있어서 바로 지운다. (진짜 방인 "IT공과대학 공지방", chatroom_id
#     a8c50ec...는 그대로 둠.) seed_fake_people.py의 CHATROOMS 목록에서도 이미
#     빼놨으니 재실행해도 다시 안 생김.
#  2) "헬스장 운동 메이트"는 두 개 다 seed_fake_people.py가 만든 게 아니라(둘 다
#     실제로 인덱싱된 방으로 추정) 어느 chatroom_id가 나중 건지 코드만 보고는 알 수
#     없어서, DB에서 이름이 "헬스장"을 포함하는 chatroom_id를 전부 찾아 각각
#     "처음 인덱싱된 시각"(MIN(index_date))을 비교 — 가장 오래된 것만 남기고
#     나머지는 지운다.
#
# 주의 — 이 스크립트는 DELETE + commit을 실제로 실행합니다(되돌릴 수 없음).
# 실행 전에 한 번 더 확인하고 싶으면 아래 DRY_RUN = True로 바꿔서 먼저 뭐가
# 지워질지만 출력해보세요.
#
# 실행: python dedupe_chatrooms.py
# (venv가 활성화 안 돼 있으면 socialvisualizer-venv/Scripts/python.exe dedupe_chatrooms.py)

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv

load_dotenv("src/parquet/.env")

import mysql.connector

# 요청 시 여기를 True로 바꾸면 아무것도 지우지 않고 "뭘 지울지"만 출력합니다.
DRY_RUN = False

# 1) 우리가 이번에 직접 만든 가짜 방들 — chatroom_id로 확정된 것들.
KNOWN_FAKE_DUPLICATE_IDS = [
    ("1c51f4c1edcc77077a28f1065c45e259e295e85d", "IT 공과대학"),
    # 요청 — "대학교 전공 동기 모임"도 실제로 요청한 적 없는 가짜 방이라 제거.
    # seed_fake_people.py의 CHATROOMS 목록에서도 이미 빼놨으니 재실행해도 다시 안 생김.
    ("8b94336a96491260786638bce7ed92d63185c35a", "대학교 전공 동기 모임"),
]

# 2) chatroom_name에 이 문자열이 들어간 방들을 서로 비교해서 중복을 찾음.
NAME_PATTERNS_TO_DEDUPE = ["헬스장"]


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def purge_chatroom(cur, chatroom_id, label):
    """chatroom_id 하나에 딸린 메신저 데이터를 전부 지운다(FK 자식 → 부모 순서)."""
    steps = [
        ("message_keyword", "DELETE FROM message_keyword WHERE chatroom_id=%s"),
        ("chatroom_relationship", "DELETE FROM chatroom_relationship WHERE chatroom_id=%s"),
        ("participant", "DELETE FROM participant WHERE chatroom_id=%s"),
        ("message_block", "DELETE FROM message_block WHERE chatroom_id=%s"),
        ("chatroom_people", "DELETE FROM chatroom_people WHERE chatroom_id=%s"),
        ("message_summarize", "DELETE FROM message_summarize WHERE chatroom_id=%s"),
        ("message_mood", "DELETE FROM message_mood WHERE chatroom_id=%s"),
        ("chatroom", "DELETE FROM chatroom WHERE chatroom_id=%s"),
    ]
    for table, sql in steps:
        if DRY_RUN:
            print(f"    [DRY-RUN] {table}에서 chatroom_id={chatroom_id[:8]}... 삭제 예정")
            continue
        try:
            cur.execute(sql, (chatroom_id,))
            print(f"    [OK] {table} {cur.rowcount}건 삭제")
        except mysql.connector.Error as e:
            # message_mood처럼 일부 환경엔 아예 없는 레거시 테이블일 수 있어서
            # "테이블 없음" 에러만 조용히 넘어가고 나머지는 그대로 진행한다.
            if e.errno == 1146:  # ER_NO_SUCH_TABLE
                print(f"    [SKIP] {table} 테이블이 없어서 건너뜀")
            else:
                raise
    print(f"  → '{label}' (chatroom_id={chatroom_id[:8]}...) 삭제 완료\n")


def dedupe_known_fake(cur):
    for known_id, label in KNOWN_FAKE_DUPLICATE_IDS:
        print(f"[1] 우리가 새로 만든 가짜 '{label}' 방 정리 (chatroom_id={known_id[:8]}...)")
        cur.execute(
            "SELECT chatroom_id, chatroom_name FROM chatroom WHERE chatroom_id=%s LIMIT 1",
            (known_id,),
        )
        row = cur.fetchone()
        if not row:
            print("  → 이미 없음(전에 지웠거나 애초에 안 만들어짐). 건너뜀.\n")
            continue
        print(f"  찾음: '{row[1]}' — 삭제 진행")
        purge_chatroom(cur, known_id, row[1])


def dedupe_by_name(cur, pattern):
    print(f"[2] chatroom_name에 '{pattern}' 포함된 방들 비교")
    cur.execute(
        """
        SELECT chatroom_id, MIN(index_date) AS first_seen, MAX(chatroom_name) AS latest_name
        FROM chatroom
        WHERE chatroom_name LIKE %s
        GROUP BY chatroom_id
        ORDER BY first_seen ASC
        """,
        (f"%{pattern}%",),
    )
    rows = cur.fetchall()
    if len(rows) < 2:
        print(f"  → chatroom_id가 {len(rows)}개만 발견돼서(중복 아님) 아무것도 안 지움: {rows}\n")
        return
    keep = rows[0]
    losers = rows[1:]
    print(f"  발견된 방 {len(rows)}개(오래된 순):")
    for r in rows:
        print(f"    - {r[0][:8]}...  최초 인덱싱: {r[1]}  이름: '{r[2]}'")
    print(f"  → 유지: {keep[0][:8]}... (가장 오래됨, '{keep[2]}')")
    for loser in losers:
        print(f"  → 삭제: {loser[0][:8]}... ('{loser[2]}')")
        purge_chatroom(cur, loser[0], loser[2])


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        dedupe_known_fake(cur)
        for pattern in NAME_PATTERNS_TO_DEDUPE:
            dedupe_by_name(cur, pattern)

        if DRY_RUN:
            print("DRY_RUN=True라서 실제로는 아무것도 지우지 않았습니다. 결과가 맞으면 "
                  "DRY_RUN = False로 바꾸고 다시 실행하세요.")
        else:
            conn.commit()
            print("완료! 중복 방 정리가 끝났습니다. My People을 새로고침하면 반영됩니다.")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] 실패 — 롤백함: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
