# 메일 계정의 통계·친밀도·키워드·연락처 관계 등을 DB에서 조회해 반환한다.

# Utility functions that read and return mail account statistics, affinity (EIS) scores, keywords, and contact relationships from the database.

import calendar
import json
import math
import re
from datetime import date
from config.db import get_db_connection
from util.database.db_writer import get_latest_mail_account

_KG_TONE_SCORE = {
    "casual":        1.0,
    "transactional": 0.5,
    "formal":        0.2,
    "notification":  0.1,
    "alert":         0.1,
}
_LAMBDA = 0.01


# 두 계정이 주고받은 메일로 상호성(R)·반응성(P)·어조(T)를 계산해 관계 친밀도 점수(EIS) dict를 반환한다
def calculate_eis(
    user_mail_account_id: str,
    person_mail_account_id: str,
    update_date: str = None,
    start_date: str = None,
    end_date: str = None,
    apply_volume_correction: bool = True,
    apply_time_decay: bool = True,
) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if update_date is None:
            latest = get_latest_mail_account(user_mail_account_id)
            update_date = latest["index_date"] if latest else None

        date_filter = ""
        params = [user_mail_account_id, update_date, person_mail_account_id, person_mail_account_id]
        if start_date and end_date:
            date_filter = "AND mail_date BETWEEN %s AND %s"
            params += [start_date, end_date]

        sql = f"""
            SELECT direction, kg_tone, llm_tone,
                   is_reply, reply_elapsed_hours, mail_date
            FROM mail
            WHERE user_mail_account_id = %s
              AND index_date = %s
              AND (
                (direction = 'sent'     AND receiver LIKE CONCAT('%<', %s, '>%'))
                OR
                (direction = 'received' AND sender   LIKE CONCAT('%<', %s, '>%'))
              )
              {date_filter}
        """
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    # 1. 상호성 점수 R 
    S_A_to_B = sum(1 for r in rows if r["direction"] == "sent")
    S_B_to_A = sum(1 for r in rows if r["direction"] == "received")
    N = S_A_to_B + S_B_to_A

    R = 0.0 if N == 0 else 1 - abs((S_A_to_B - S_B_to_A) / N)

    # 2. 반응성 점수 P 
    reply_count = sum(1 for r in rows if r["is_reply"] == 1)
    elapsed = [float(r["reply_elapsed_hours"]) for r in rows if r["reply_elapsed_hours"] is not None]

    if N == 0:
        P, t_bar = 0.0, None
    else:
        reply_ratio = reply_count / N
        if elapsed:
            t_bar = sum(elapsed) / len(elapsed)
            P = reply_ratio * math.exp(-_LAMBDA * t_bar)
        else:
            t_bar = None
            P = reply_ratio

    # 3. 어조 점수 T
    if N == 0:
        T = 0.0
    else:
        tone_scores = []
        for r in rows:
            kg_score = _KG_TONE_SCORE.get(r["kg_tone"] or "", 0.0)
            llm = r["llm_tone"]
            if llm is None:
                tone_scores.append(kg_score)
            else:
                llm_score = 1.0 if llm == "friendly" else 0.0
                tone_scores.append((kg_score + llm_score) / 2)
        T = sum(tone_scores) / len(tone_scores)

    # 4. 통합 EIS 
    EIS = 0.3 * R + 0.4 * P + 0.3 * T

    # 5. 볼륨 보정 (apply_volume_correction=False 시 생략)
    EIS_adj = EIS * (1 - math.exp(-0.05 * N)) if apply_volume_correction else EIS

    # 6. 시간 감쇠 보정 (apply_time_decay=False 시 생략) 
    mail_dates = [r["mail_date"] for r in rows if r["mail_date"] is not None]
    if not apply_time_decay:
        delta_t_last = None
        EIS_final = EIS_adj
    elif not mail_dates:
        delta_t_last = None
        EIS_final = 0.0
    else:
        last_mail = max(mail_dates)
        last_date = last_mail.date() if hasattr(last_mail, "date") else last_mail
        delta_t_last = (date.today() - last_date).days
        EIS_final = EIS_adj * math.exp(-0.005 * delta_t_last)

    return {
        "R":            round(R, 6),
        "P":            round(P, 6),
        "T":            round(T, 6),
        "EIS":          round(EIS, 6),
        "EIS_adj":      round(EIS_adj, 6),
        "EIS_final":    round(EIS_final, 6),
        "N":            N,
        "S_A_to_B":     S_A_to_B,
        "S_B_to_A":     S_B_to_A,
        "reply_count":  reply_count,
        "t_bar":        round(t_bar, 4) if t_bar is not None else None,
        "delta_t_last": delta_t_last,
    }

# mail_contact_stats.json(연락처별 송수신 수)을 읽어 반환한다 (파일 없으면 예시 데이터)
def get_mail_stats(paths):
    try:
        with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    except FileNotFoundError:
        return { # 파일이 없으면 가라데이터
        "ae-best-care-market14@deals.aliexpress.com": {
            "name": "AliExpress",
            "sent": 0,
            "received": 3
        },
        "notifications@github.com": {
            "name": "uzichoi",
            "sent": 1,
            "received": 12
        },
        "inews11@seoul.go.kr": {
            "name": "서울시청",
            "sent": 0,
            "received": 2
        },
        "team@company.com": {
            "name": "프로젝트팀",
            "sent": 7,
            "received": 5
        },
        "friend123@gmail.com": {
            "name": "김민수",
            "sent": 4,
            "received": 6
        }
    }
    

# mail_keyword_stats.json의 키워드별 언급 수를 [{word, count}] 리스트로 반환한다 (파일 없으면 예시 데이터)
def get_keyword_stats(paths):
    try:
        with open(paths.MAIL_KEYWORDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        keyword_dict = data.get("keywords", {})

        # dict → 리스트 변환
        keywords_list = [
            {"word": word, "count": count}
            for word, count in keyword_dict.items()
        ]

        return {"keywords": keywords_list}

    except FileNotFoundError:
        return  {
        "keywords": [
            { "word": "회의", "count": 15 },
            { "word": "일정", "count": 2 },
            { "word": "첨부파일", "count": 9 },
            { "word": "프로젝트", "count": 58 },
            { "word": "확인", "count": 22 },
            { "word": "요청", "count": 17 },
            { "word": "보고서", "count": 11 },
            { "word": "마감", "count": 411 },
            { "word": "수정", "count": 13 },
            { "word": "공유", "count": 10 }
        ]
    }

# 이 계정의 모든 연락처에 대해 EIS(볼륨 보정·시간 감쇠 없이)를 계산해 친밀도 내림차순 목록을 반환한다
def get_high_affinity_person_stats(paths):
    latest = get_latest_mail_account(paths.USER_ID)
    if not latest:
        return []
    update_date = latest["index_date"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT person_mail_account_id, person_name FROM person WHERE user_mail_account_id = %s AND index_date = %s",
            (paths.USER_ID, update_date),
        )
        persons = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    result = []
    for person in persons:
        eis = calculate_eis(
            user_mail_account_id=paths.USER_ID,
            person_mail_account_id=person["person_mail_account_id"],
            update_date=update_date,
            apply_volume_correction=False,
            apply_time_decay=False,
        )
        result.append({
            "email": person["person_mail_account_id"],
            "name":  person.get("person_name", ""),
            "affinity": eis["EIS_final"],
        })

    result.sort(key=lambda x: x["affinity"], reverse=True)
    return result


# 특정 상대방과 날짜 범위 내 주고받은 키워드별 총 언급 수와 등장 날짜 목록을 반환한다
def get_keywords_by_person_date(user_id: str, person_user_id: str, start_date: str, end_date: str) -> list:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = """
            SELECT keyword_name, mail_date, SUM(daily_count) AS day_count
            FROM mail_keyword
            WHERE user_mail_account_id   = %s
              AND person_mail_account_id = %s
              AND mail_date BETWEEN %s AND %s
            GROUP BY keyword_name, mail_date
            ORDER BY mail_date
        """
        cursor.execute(sql, (user_id, person_user_id, start_date, end_date))
        rows = cursor.fetchall()

        keyword_map = {}
        for row in rows:
            kw = row["keyword_name"]
            date = str(row["mail_date"])
            if kw not in keyword_map:
                keyword_map[kw] = {"word": kw, "count": 0, "dates": []}
            keyword_map[kw]["count"] += row["day_count"]
            keyword_map[kw]["dates"].append(date)

        return list(keyword_map.values())
    finally:
        cursor.close()
        conn.close()


# 계정 전체(모든 상대방 합산)의 월별 키워드 목록·언급 수를 {월: [{word, count}]}로 반환한다
def get_mail_keyword_monthly_stats(user_id: str, start_date: str = None, end_date: str = None) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = """
            SELECT DATE_FORMAT(mail_date, '%Y-%m') AS month, keyword_name AS word, SUM(daily_count) AS count
            FROM mail_keyword
            WHERE user_mail_account_id = %s
        """
        params = [user_id]
        if start_date and end_date:
            sql += " AND mail_date BETWEEN %s AND %s"
            params += [start_date, end_date + ' 23:59:59']
        sql += " GROUP BY month, keyword_name ORDER BY month, count DESC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    monthly = {}
    for row in rows:
        monthly.setdefault(row["month"], []).append({"word": row["word"], "count": int(row["count"] or 0)})
    return monthly


# 계정 전체가 특정 월에 날짜별로 언급한 키워드 목록·횟수를 {날짜: [{word, count}]}로 반환한다
def get_mail_keyword_daily_stats(user_id: str, month: str) -> dict:
    year, mon = (int(x) for x in month.split("-"))
    month_start = f"{month}-01"
    month_end = f"{month}-{calendar.monthrange(year, mon)[1]:02d}"

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT DATE(mail_date) AS date, keyword_name AS word, SUM(daily_count) AS count
            FROM mail_keyword
            WHERE user_mail_account_id = %s
              AND mail_date BETWEEN %s AND %s
            GROUP BY date, keyword_name
            ORDER BY date, count DESC
            """,
            (user_id, month_start, month_end + ' 23:59:59'),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    daily = {}
    for row in rows:
        date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])
        daily.setdefault(date_str, []).append({"word": row["word"], "count": int(row["count"] or 0)})
    return daily


# 특정 날짜에 특정 키워드를 언급한 상대방별 횟수를 count 내림차순 목록으로 반환한다
def get_mail_keyword_mentioners(user_id: str, date: str, keyword: str) -> list:
    latest = get_latest_mail_account(user_id)
    if not latest:
        return []
    update_date = latest["index_date"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT k.person_mail_account_id AS person_id,
                   p.person_name AS name,
                   SUM(k.daily_count) AS count
            FROM mail_keyword k
            LEFT JOIN person p
              ON p.person_mail_account_id = k.person_mail_account_id
             AND p.user_mail_account_id = k.user_mail_account_id
             AND p.index_date = %s
            WHERE k.user_mail_account_id = %s
              AND k.keyword_name = %s
              AND DATE(k.mail_date) = %s
            GROUP BY k.person_mail_account_id, p.person_name
            ORDER BY count DESC
            """,
            (update_date, user_id, keyword, date),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [{"person_id": r["person_id"], "name": r["name"], "count": int(r["count"] or 0)} for r in rows]


# 전체 유저의 Olive 만족도 통계를 반환한다 (현재는 고정값)
def get_user_rating_stats():
    return {"total_rating" : 99}

# 특정 상대방과 날짜 범위 내 월별 발신/수신 메일 수를 집계해 반환한다 (메일이 오간 연도만, 그 안의 빈 달은 0)
def get_mail_exchange_stats(user_id, person_mail_id, start_date, end_date):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT MAX(index_date) AS ud FROM mail_account WHERE user_mail_account_id = %s", (user_id,))
        update_date = cursor.fetchone()["ud"]

        like_param = f"%{person_mail_id}%"
        sql = """
        SELECT
            DATE_FORMAT(mail_date, '%Y-%m') AS month,
            SUM(CASE WHEN direction = 'sent'     AND receiver LIKE %s THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN direction = 'received' AND sender   LIKE %s THEN 1 ELSE 0 END) AS received
        FROM mail
        WHERE user_mail_account_id = %s
          AND index_date = %s
          AND mail_date BETWEEN %s AND %s
          AND (
            (direction = 'sent'     AND receiver LIKE %s) OR
            (direction = 'received' AND sender   LIKE %s)
          )
        GROUP BY DATE_FORMAT(mail_date, '%Y-%m')
        ORDER BY month ASC
        """
        # 이 사람과 실제로 메일을 주고받은 달만 GROUP BY 대상에 들어오도록 한다
        cursor.execute(sql, (
            like_param, like_param, user_id, update_date, start_date, end_date + ' 23:59:59',
            like_param, like_param,
        ))
        rows = cursor.fetchall()

        by_month = {
            row["month"]: {"sent": int(row["sent"] or 0), "received": int(row["received"] or 0)}
            for row in rows
        }

        # 실제 메일이 오간 "연도"만 남기되, 그 연도 안에서는 달을 건너뛰지 않고 전부 채운다(빈 달은 0건으로) 
        active_years = sorted({month[:4] for month in by_month})
        start_ym, end_ym = start_date[:7], end_date[:7]

        monthly = []
        for year in active_years:
            for m in range(1, 13):
                ym = f"{year}-{m:02d}"
                if ym < start_ym or ym > end_ym:
                    continue
                data = by_month.get(ym, {"sent": 0, "received": 0})
                monthly.append({"month": ym, "sent": data["sent"], "received": data["received"]})

        total_sent     = sum(m["sent"]     for m in monthly)
        total_received = sum(m["received"] for m in monthly)

        return {
            "monthly": monthly,
            "total": {"sent": total_sent, "received": total_received},
        }

    finally:
        cursor.close()
        conn.close()


# 특정 상대방과 특정 월에 날짜별로 주고받은 발신/수신 메일 수를 집계해 반환한다
def get_mail_person_daily_stats(user_id, person_mail_id, month):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT MAX(index_date) AS ud FROM mail_account WHERE user_mail_account_id = %s", (user_id,))
        update_date = cursor.fetchone()["ud"]

        year, mon = (int(x) for x in month.split("-"))
        month_start = f"{month}-01"
        month_end = f"{month}-{calendar.monthrange(year, mon)[1]:02d}"

        like_param = f"%{person_mail_id}%"
        sql = """
        SELECT
            DATE(mail_date) AS date,
            SUM(CASE WHEN direction = 'sent'     AND receiver LIKE %s THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN direction = 'received' AND sender   LIKE %s THEN 1 ELSE 0 END) AS received
        FROM mail
        WHERE user_mail_account_id = %s
          AND index_date = %s
          AND mail_date BETWEEN %s AND %s
          AND (
            (direction = 'sent'     AND receiver LIKE %s) OR
            (direction = 'received' AND sender   LIKE %s)
          )
        GROUP BY DATE(mail_date)
        ORDER BY date ASC
        """
        cursor.execute(sql, (
            like_param, like_param, user_id, update_date, month_start, month_end + ' 23:59:59',
            like_param, like_param,
        ))
        rows = cursor.fetchall()

        days = [
            {
                "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"]),
                "sent": int(row["sent"] or 0),
                "received": int(row["received"] or 0),
                "count": int(row["sent"] or 0) + int(row["received"] or 0),
            }
            for row in rows
        ]
        return {"days": days}
    finally:
        cursor.close()
        conn.close()


# 특정 상대방과 날짜 범위 내 주고받은 메일의 (mail_id, 방향, 날짜) 목록을 반환한다 (제목/본문은 이후 Gmail API로 조회)
def get_person_mail_ids_in_range(user_id, person_mail_id, start_date, end_date) -> list:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT MAX(index_date) AS ud FROM mail_account WHERE user_mail_account_id = %s", (user_id,))
        update_date = cursor.fetchone()["ud"]

        like_param = f"%{person_mail_id}%"
        sql = """
        SELECT mail_id, direction, mail_date
        FROM mail
        WHERE user_mail_account_id = %s
          AND index_date = %s
          AND mail_date BETWEEN %s AND %s
          AND (
            (direction = 'sent'     AND receiver LIKE %s) OR
            (direction = 'received' AND sender   LIKE %s)
          )
        ORDER BY mail_date ASC
        """
        cursor.execute(sql, (user_id, update_date, start_date, end_date + ' 23:59:59', like_param, like_param))
        rows = cursor.fetchall()
        return [
            {"id": row["mail_id"], "direction": row["direction"], "date": str(row["mail_date"])}
            for row in rows
        ]
    finally:
        cursor.close()
        conn.close()


# 날짜 범위 내 발신(sent) 또는 수신(received) 메일을 상대방 이메일별로 집계해 건수 내림차순 목록을 반환한다
def get_date_range_person_stats(user_id, start_date, end_date, sort_by):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT MAX(index_date) AS ud FROM mail_account WHERE user_mail_account_id = %s", (user_id,))
        update_date = cursor.fetchone()["ud"]

        direction_filter = "sent" if sort_by == "sent" else "received"
        sql = """
        SELECT sender, receiver, direction
        FROM mail
        WHERE user_mail_account_id = %s
          AND index_date = %s
          AND mail_date BETWEEN %s AND %s
          AND direction = %s
        """
        cursor.execute(sql, (user_id, update_date, start_date, end_date + ' 23:59:59', direction_filter))
        rows = cursor.fetchall()

        email_pattern = re.compile(r'[\w.+\-]+@[\w.\-]+')
        counts = {}

        for row in rows:
            field = (row["receiver"] if sort_by == "sent" else row["sender"]) or ""
            found = email_pattern.findall(field)
            if found:
                for email in found:
                    email = email.lower()
                    if email == user_id.lower():
                        continue
                    counts[email] = counts.get(email, 0) + 1
            else:
                # 발신/수신 필드가 이메일 형식이 아닌 경우 같은 정규화 과정을 거친다
                ident = field.strip().lower()
                if ident and ident != user_id.lower():
                    counts[ident] = counts.get(ident, 0) + 1

        result = [
            {"email": email, sort_by: count}
            for email, count in counts.items()
        ]
        result.sort(key=lambda x: x[sort_by], reverse=True)
        return result

    finally:
        cursor.close()
        conn.close()


# 최신 인덱싱 기준 이 계정 메일의 가장 이른/늦은 날짜를 반환한다
def get_mail_date_range(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        sql = """
        SELECT MIN(mail_date) AS first_date, MAX(mail_date) AS last_date
        FROM mail
        WHERE user_mail_account_id = %s
          AND index_date = (
              SELECT MAX(index_date) FROM mail_account WHERE user_mail_account_id = %s
          )
        """
        cursor.execute(sql, (user_id, user_id))
        row = cursor.fetchone()

        return {
            "first_date": row["first_date"].strftime("%Y-%m-%d") if row["first_date"] else None,
            "last_date":  row["last_date"].strftime("%Y-%m-%d")  if row["last_date"]  else None,
        }

    finally:
        cursor.close()
        conn.close()

# 가장 최근 인덱싱의 동기화 메일 수·소요 시간·날짜를 반환한다
def get_mail_sync_stats(paths):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        sql = """
        SELECT mail_count, index_time, index_date
        FROM mail_account
        WHERE user_mail_account_id = %s
        ORDER BY index_date DESC
        LIMIT 1
        """
        cursor.execute(sql, (paths.USER_ID,))
        row = cursor.fetchone()

        if not row:
            return {
                "mail_count": 0,
                "sync_time": None,
                "sync_update_date": None
            }

        index_date = row["index_date"]
        if index_date is not None:
            sync_update_date = index_date.strftime("%Y-%m-%d")
        else:
            sync_update_date = None

        return {
            "mail_count": row["mail_count"],
            "sync_time": row["index_time"],
            "sync_update_date": sync_update_date
        }

    finally:
        cursor.close()
        conn.close()


# 최신 인덱싱 기준 이 계정 연락처의 이메일·이름·description·relation_label을 반환한다 (description 있는 것만)
def get_person_descriptions(user_id: str) -> list:
    latest_account = get_latest_mail_account(user_id)
    if not latest_account:
        return []

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # person_account_id로 alias: 프론트/avatar_generator가 기대하는 기존 API 응답 키 유지
        cursor.execute("""
            SELECT person_mail_account_id AS person_account_id, person_name, description, relation_label, short_bio
            FROM person
            WHERE user_mail_account_id = %s AND index_date = %s
              AND description IS NOT NULL AND description != ''
        """, (latest_account["user_mail_account_id"], latest_account["index_date"]))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# 최신 인덱싱 기준 이 계정 연락처 전체를 person 테이블 전 컬럼으로 반환한다 (프론트 연락처 목록용)
def get_mail_people(user_id: str):
    latest_account = get_latest_mail_account(user_id)
    if not latest_account:
        return None

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT person_mail_account_id, person_name, receive_mails, send_mails,
                   friendly_mails, description, relation_label, short_bio
            FROM person
            WHERE user_mail_account_id = %s AND index_date = %s
            ORDER BY (receive_mails + send_mails) DESC
        """, (latest_account["user_mail_account_id"], latest_account["index_date"]))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [
        {
            "person_account_id": row["person_mail_account_id"],
            "person_name": row["person_name"],
            "receive_mails": int(row["receive_mails"] or 0),
            "send_mails": int(row["send_mails"] or 0),
            "friendly_mails": int(row["friendly_mails"] or 0),
            "description": row["description"],
            "relation_label": row["relation_label"],
            "short_bio": row["short_bio"],
        }
        for row in rows
    ]


# 최신 인덱싱 기준 이 계정 연락처 전체(이메일+이름)를 반환한다 (아바타 일괄 생성용 경량 조회)
def get_all_persons(user_id: str) -> list:
    latest_account = get_latest_mail_account(user_id)
    if not latest_account:
        return []

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT person_mail_account_id, person_name
            FROM person
            WHERE user_mail_account_id = %s AND index_date = %s
        """, (latest_account["user_mail_account_id"], latest_account["index_date"]))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# 최신 인덱싱 기준 이 계정 연락처의 이메일·이름·relation_label만 추려서 반환한다 (경량 페이로드)
def get_mail_relationships(user_id: str) -> list:
    latest_account = get_latest_mail_account(user_id)
    if not latest_account:
        return []

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT person_mail_account_id AS person_account_id, person_name, relation_label
            FROM person
            WHERE user_mail_account_id = %s AND index_date = %s
              AND relation_label IS NOT NULL AND relation_label != ''
        """, (latest_account["user_mail_account_id"], latest_account["index_date"]))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# 최신 인덱싱 기준 계정의 연/월별 LLM 요약을 주요 연락처(이메일→description/short_bio 포함)와 함께 반환한다
def get_mail_summaries(user_id: str, summarize_unit: str):
    latest_account = get_latest_mail_account(user_id)
    if not latest_account:
        return None
    user_mail_account_id = latest_account["user_mail_account_id"]
    update_date           = latest_account["index_date"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT summary_period, summarized_context, contacts
            FROM mail_summarize
            WHERE user_mail_account_id = %s AND index_date = %s AND summarize_unit = %s
            ORDER BY summary_period
            """,
            (user_mail_account_id, update_date, summarize_unit),
        )
        rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT person_mail_account_id, person_name, description, short_bio
            FROM person
            WHERE user_mail_account_id = %s AND index_date = %s
            """,
            (user_mail_account_id, update_date),
        )
        people_map = {row["person_mail_account_id"]: row for row in cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()

    result = []
    for row in rows:
        contacts = row["contacts"]
        contacts = json.loads(contacts) if isinstance(contacts, str) else (contacts or [])
        result.append({
            "summary_period": row["summary_period"],
            "summarized_context": row["summarized_context"],
            "contacts": [
                {
                    "person_account_id": email,
                    "person_name": people_map.get(email, {}).get("person_name"),
                    "description": people_map.get(email, {}).get("description"),
                    "short_bio": people_map.get(email, {}).get("short_bio"),
                }
                for email in contacts
            ],
        })
    return result
