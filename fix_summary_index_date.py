# fix_summary_index_date.py
#
# My Time이 "요약이 없다"고 뜨는 문제 수정용.
# 원인: mail_summarize에는 실제 요약 데이터가 있는데, 그 index_date가
#       mail_account의 "현재 최신 index_date"와 달라서(옛날 인덱싱 시점 값) My Time의
#       WHERE index_date = %s (완전일치) 조회가 못 찾는 것.
#
# 이 스크립트가 하는 일 (계정별):
#   1. mail_account에서 최신 index_date를 찾는다. (=target_index_date)
#   2. mail_summarize를 index_date별로 그룹화해서, target_index_date와 이미 일치하는
#      데이터가 있으면 건드리지 않고 건너뛴다.
#   3. 일치하는 게 없으면, monthly+yearly 총 건수가 가장 많은 "옛날" index_date 그룹을
#      골라서 그 그룹의 index_date를 target_index_date로 UPDATE한다.
#      (내용은 그대로, 날짜 태그만 최신 mail_account.index_date에 맞춤)
#   4. 실제 UPDATE 전에 계획을 모두 출력하고, 콘솔에서 y 입력해야만 실행한다.
#      (DRY RUN 기본 — 아무것도 안 바꾸고 계획만 보고 싶으면 y 대신 다른 키 입력)
#
# 대상 계정: soyeon@icloud, 03yeeun03@naver.com
# (03yeah03@gmail.com은 이미 정상이라 건드리지 않음)
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   python fix_summary_index_date.py

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from config.db import get_db_connection

USER_IDS = ["soyeon@icloud", "03yeeun03@naver.com"]


def plan_for_account(cursor, user_id: str):
    cursor.execute(
        """
        SELECT index_date FROM mail_account
        WHERE user_mail_account_id = %s
        ORDER BY index_date DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        print(f"\n### {user_id}: mail_account 행이 없어서 건너뜁니다.")
        return None

    target_index_date = row["index_date"]

    cursor.execute(
        """
        SELECT index_date, summarize_unit, COUNT(*) AS cnt
        FROM mail_summarize
        WHERE user_mail_account_id = %s
        GROUP BY index_date, summarize_unit
        ORDER BY index_date DESC
        """,
        (user_id,),
    )
    groups = cursor.fetchall()

    print(f"\n### {user_id}")
    print(f"  최신 mail_account.index_date: {target_index_date}")

    if not groups:
        print("  mail_summarize 자체가 없습니다. (이 스크립트로는 해결 불가 — 요약을 새로 생성해야 함)")
        return None

    # 이미 최신 index_date와 일치하는 데이터가 있으면 건드릴 필요 없음
    if any(g["index_date"] == target_index_date for g in groups):
        print("  이미 최신 index_date와 일치하는 mail_summarize가 있습니다. 수정 불필요 — 건너뜁니다.")
        return None

    # index_date별 총 건수(monthly+yearly) 집계해서 가장 데이터가 많은 index_date 하나 선택
    totals = {}
    for g in groups:
        totals[g["index_date"]] = totals.get(g["index_date"], 0) + g["cnt"]

    best_index_date = max(totals, key=lambda d: (totals[d], d))
    best_total = totals[best_index_date]

    print("  기존 그룹 목록:")
    for d, total in sorted(totals.items(), key=lambda x: x[0], reverse=True):
        marker = "  <- 이걸로 옮길 예정" if d == best_index_date else ""
        print(f"    index_date={d} 총 {total}건{marker}")

    print(f"  => index_date={best_index_date} ({best_total}건)을 {target_index_date}로 UPDATE 예정")

    return {
        "user_id": user_id,
        "old_index_date": best_index_date,
        "new_index_date": target_index_date,
        "total": best_total,
    }


def apply_plan(cursor, plan):
    cursor.execute(
        """
        UPDATE mail_summarize
        SET index_date = %s
        WHERE user_mail_account_id = %s AND index_date = %s
        """,
        (plan["new_index_date"], plan["user_id"], plan["old_index_date"]),
    )
    print(f"  [완료] {plan['user_id']}: index_date {plan['old_index_date']} -> {plan['new_index_date']} ({cursor.rowcount}건 갱신)")


def main():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        plans = []
        for user_id in USER_IDS:
            p = plan_for_account(cursor, user_id)
            if p:
                plans.append(p)

        if not plans:
            print("\n수정할 항목이 없습니다. 종료합니다.")
            return

        print("\n" + "=" * 50)
        answer = input("위 계획대로 UPDATE를 실행할까요? (y 입력 시 실행): ").strip().lower()
        if answer != "y":
            print("실행하지 않고 종료합니다. (DB에는 아무 변경도 없습니다)")
            return

        cursor2 = conn.cursor(dictionary=True)
        try:
            for p in plans:
                apply_plan(cursor2, p)
            conn.commit()
            print("\n모든 변경 사항을 커밋했습니다. 이제 My Time을 새로고침해서 확인해보세요.")
        except Exception as e:
            conn.rollback()
            print(f"\n[오류] 실행 중 문제가 발생해 롤백했습니다: {e}")
        finally:
            cursor2.close()
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
