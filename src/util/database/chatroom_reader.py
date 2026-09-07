# 메신저 대화방의 목록·참여자·관계·키워드·분위기·메시지·요약 등을 DB에서 조회해 반환한다.

# Utility functions that read and return messenger chatroom data — room lists, participants, relationships, keywords, mood, messages, and summaries — from the database.

import calendar
import json
import os
from config.db import get_db_connection
from util.database.chatroom_db_writer import get_latest_chatroom
from util.user_path import list_accounts, UserPaths


# 모든 단톡방의 이름·메시지 수·참여자 수·참여자 목록을 모아 반환한다 (인덱싱 중인 방도 indexed:False로 포함, 기간 지정 시 그 기간 집계)
def list_indexed_chatrooms(base_dir: str, start_date: str = None, end_date: str = None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        rooms = []
        for acc in list_accounts(base_dir, "messenger"):
            chatroom_id = acc["user_id"]

            # 인덱싱 중인 채팅방도 목록에 넣고 "생성 중" 배지로 보여준다
            if not acc["indexed"]:
                if start_date and end_date:
                    continue
                rooms.append({
                    "chatroom_id": chatroom_id,
                    "chatroom_name": acc.get("room_name"),
                    "message_count": 0,
                    "participant_count": 0,
                    "top_participants": [],
                    "indexed": False,
                })
                continue

            latest = get_latest_chatroom(chatroom_id)
            if not latest:
                continue
            index_date, user_id = latest["index_date"], latest["user_id"]

            cursor.execute(
                """
                SELECT chatroom_name FROM chatroom
                WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
                """,
                (chatroom_id, index_date, user_id),
            )
            meta = cursor.fetchone()
            if not meta:
                continue

            if start_date and end_date:
                cursor.execute(
                    """
                    SELECT SUM(message_count) AS message_count
                    FROM message_block
                    WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
                      AND block_date BETWEEN %s AND %s
                    """,
                    (chatroom_id, index_date, user_id, start_date, end_date),
                )
                message_count = int((cursor.fetchone() or {}).get("message_count") or 0)
                if message_count == 0:
                    continue

                cursor.execute(
                    """
                    SELECT p.participant_name AS name, SUM(p.sent_message) AS cnt
                    FROM participant p
                    JOIN message_block b
                      ON p.block_id = b.block_id AND p.chatroom_id = b.chatroom_id
                     AND p.index_date = b.index_date AND p.user_id = b.user_id
                    WHERE p.chatroom_id = %s AND p.index_date = %s AND p.user_id = %s
                      AND b.block_date BETWEEN %s AND %s
                    GROUP BY p.participant_name
                    HAVING SUM(p.sent_message) > 0
                    ORDER BY cnt DESC
                    """,
                    (chatroom_id, index_date, user_id, start_date, end_date),
                )
                active_rows = cursor.fetchall()
                participant_count = len(active_rows)
                top_participants = [row["name"] for row in active_rows]
            else:
                cursor.execute(
                    """
                    SELECT message_count FROM chatroom
                    WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
                    """,
                    (chatroom_id, index_date, user_id),
                )
                message_count = int((cursor.fetchone() or {}).get("message_count") or 0)

                cursor.execute(
                    """
                    SELECT COUNT(*) AS participant_count
                    FROM chatroom_people
                    WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
                    """,
                    (chatroom_id, index_date, user_id),
                )
                participant_count = cursor.fetchone()["participant_count"]

                cursor.execute(
                    """
                    SELECT chatroom_people_name AS name
                    FROM chatroom_people
                    WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
                    ORDER BY message_count DESC
                    """,
                    (chatroom_id, index_date, user_id),
                )
                top_participants = [row["name"] for row in cursor.fetchall()]

            rooms.append({
                "chatroom_id": chatroom_id,
                "chatroom_name": meta["chatroom_name"],
                "message_count": message_count,
                "participant_count": int(participant_count or 0),
                "top_participants": top_participants,
                "indexed": True,
            })
        return rooms
    finally:
        cursor.close()
        conn.close()


# 인덱싱된 모든 단톡방을 통틀어 가장 이른/늦은 메시지 날짜를 반환한다 (인덱싱된 방 없으면 둘 다 None)
def get_messenger_date_range(base_dir: str):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        first_date, last_date = None, None
        for acc in list_accounts(base_dir, "messenger"):
            if not acc["indexed"]:
                continue
            chatroom_id = acc["user_id"]
            latest = get_latest_chatroom(chatroom_id)
            if not latest:
                continue

            cursor.execute(
                """
                SELECT MIN(block_date) AS first_date, MAX(block_date) AS last_date
                FROM message_block
                WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
                """,
                (chatroom_id, latest["index_date"], latest["user_id"]),
            )
            row = cursor.fetchone()
            if row["first_date"] and (first_date is None or row["first_date"] < first_date):
                first_date = row["first_date"]
            if row["last_date"] and (last_date is None or row["last_date"] > last_date):
                last_date = row["last_date"]

        return {
            "first_date": first_date.strftime("%Y-%m-%d") if first_date else None,
            "last_date":  last_date.strftime("%Y-%m-%d")  if last_date  else None,
        }
    finally:
        cursor.close()
        conn.close()


# 가장 최근 인덱싱의 메시지 수·소요 시간·날짜를 반환한다 (인덱싱 기록 없으면 0/None)
def get_chatroom_sync_stats(chatroom_id: str):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT message_count, index_time, index_date
            FROM chatroom
            WHERE chatroom_id = %s
            ORDER BY index_date DESC
            LIMIT 1
            """,
            (chatroom_id,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not row:
        return {
            "message_count": 0,
            "sync_time": None,
            "sync_update_date": None,
        }

    index_date = row["index_date"]
    return {
        "message_count": row["message_count"],
        "sync_time": row["index_time"],
        "sync_update_date": index_date.strftime("%Y-%m-%d") if index_date is not None else None,
    }


# 인덱싱 전 방을 위해 account.json에 저장된 room_name을 읽어 반환한다 (실패 시 None)
def _room_name_from_account_meta(chatroom_id: str):
    try:
        from config.settings import BASE_DIR
        from util.user_path import UserPaths
        paths = UserPaths(BASE_DIR, chatroom_id, "messenger")
        if not os.path.exists(paths.ACCOUNT_META_PATH):
            return None
        with open(paths.ACCOUNT_META_PATH, "r", encoding="utf-8") as f:
            return (json.load(f).get("room_name") or "").strip() or None
    except Exception:
        return None


# chatroom_id로 방 이름만 조회한다 (DB에 없으면 account.json의 이름으로 폴백)
def get_chatroom_name(chatroom_id: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return _room_name_from_account_meta(chatroom_id)
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT chatroom_name
            FROM chatroom
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
            """,
            (chatroom_id, index_date, user_id),
        )
        row = cursor.fetchone()
        return row["chatroom_name"] if row else _room_name_from_account_meta(chatroom_id)
    finally:
        cursor.close()
        conn.close()


# 채팅방의 참여자 전체 목록(id/이름/누적 메시지 수/설명)을 기간과 무관하게 반환한다 (미인덱싱 방이면 None)
def get_chatroom_people(chatroom_id: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT participant_id, chatroom_people_name AS name, message_count, description, short_bio
            FROM chatroom_people
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
            ORDER BY message_count DESC
            """,
            (chatroom_id, index_date, user_id),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [
        {
            "participant_id": row["participant_id"],
            "name": row["name"],
            "message_count": int(row["message_count"] or 0),
            "description": row["description"],
            "short_bio": row["short_bio"],
        }
        for row in rows
    ]


# 채팅방 참여자별로 지정 기간에 보낸 메시지 수와 프로필 설명을 반환한다 (미인덱싱 방이면 None)
def get_chatroom_people_stats(chatroom_id: str, start_date: str, end_date: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT p.participant_name AS name,
                   SUM(p.sent_message) AS message_count,
                   MAX(cp.description) AS description
            FROM participant p
            JOIN message_block b
              ON p.block_id = b.block_id AND p.chatroom_id = b.chatroom_id
             AND p.index_date = b.index_date AND p.user_id = b.user_id
            LEFT JOIN chatroom_people cp
              ON cp.participant_id = p.participant_name AND cp.chatroom_id = p.chatroom_id
             AND cp.index_date = p.index_date AND cp.user_id = p.user_id
            WHERE p.chatroom_id = %s AND p.index_date = %s AND p.user_id = %s
              AND b.block_date BETWEEN %s AND %s
            GROUP BY p.participant_name
            ORDER BY message_count DESC
            """,
            (chatroom_id, index_date, user_id, start_date, end_date),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [
        {
            "participant_id": row["name"],
            "name": row["name"],
            "message_count": int(row["message_count"] or 0),
            "description": row["description"],
        }
        for row in rows
    ]


# chatroom_relationship 테이블의 실제 저장된 관계만 relation_label별로 집계해 count 내림차순으로 반환한다
def get_chatroom_relationship_stats(chatroom_id: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT relation_label, COUNT(*) AS count
            FROM chatroom_relationship
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
            GROUP BY relation_label
            ORDER BY count DESC
            """,
            (chatroom_id, index_date, user_id),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    relationships = [{"relation_label": row["relation_label"], "count": int(row["count"] or 0)} for row in rows]
    return {
        "total": sum(r["count"] for r in relationships),
        "relationships": relationships,
    }


# chatroom_relationship 테이블에서 이 채팅방의 사람-사람 관계 중 양쪽 다 active_names에 속한 것만 반환한다
def get_chatroom_relationships(paths, active_names: set) -> list:
    latest = get_latest_chatroom(paths.USER_ID)
    if not latest:
        return []
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT person_a AS source, person_b AS target,
                   relation_label, description
            FROM chatroom_relationship
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
        """, (paths.USER_ID, index_date, user_id))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    existing = {
        (row["source"], row["target"]): row
        for row in rows
        if row["source"] in active_names and row["target"] in active_names
    }

    names = sorted(active_names)
    result = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            result.append(existing.get((a, b)) or {
                "source": a,
                "target": b,
                "relation_label": "채팅방 참여자",
                "description": None,
            })
    return result


# 채팅방 참여자 명단(participant_id 지정 시 그 한 명)의 프로필 설명과 기간 내 메시지 수를 반환한다 (기간 0건도 포함)
def get_chatroom_person_detail(chatroom_id: str, start_date: str, end_date: str, participant_id: str = None):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = """
            SELECT participant_id, chatroom_people_name AS name, description
            FROM chatroom_people
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
        """
        params = [chatroom_id, index_date, user_id]
        if participant_id:
            sql += " AND participant_id = %s"
            params.append(participant_id)
        cursor.execute(sql, params)
        roster = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    if not roster:
        return None

    # 기간 내 메시지 수
    period_counts = {
        row["name"]: row["message_count"]
        for row in (get_chatroom_people_stats(chatroom_id, start_date, end_date) or [])
    }

    return [
        {
            "participant_id": row["participant_id"],
            "name": row["name"],
            "message_count": period_counts.get(row["name"], 0),
            "description": row["description"],
        }
        for row in roster
    ]


# 채팅방의 지정 기간에 걸치는 월별/연별 분위기 점수·설명을 message_mood 테이블에서 읽어 반환한다 (미인덱싱 방이면 None)
def get_chatroom_mood(chatroom_id: str, start_date: str, end_date: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]
    month_start, month_end = start_date[:7], end_date[:7]
    year_start, year_end = start_date[:4], end_date[:4]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT summary_period, summary_unit, mood_score, mood_description
            FROM message_mood
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
                AND (
                    (summary_unit = 'monthly' AND summary_period BETWEEN %s AND %s)
                OR (summary_unit = 'yearly'  AND summary_period BETWEEN %s AND %s)
                )
            ORDER BY summary_unit, summary_period
            """,
            (chatroom_id, index_date, user_id, month_start, month_end, year_start, year_end),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    monthly, yearly = [], []
    for row in rows:
        entry = {
            "period": row["summary_period"],
            "mood_score": float(row["mood_score"]) if row["mood_score"] is not None else None,
            "mood_description": row["mood_description"],
        }
        (monthly if row["summary_unit"] == "monthly" else yearly).append(entry)

    return {"monthly": monthly, "yearly": yearly}


# 특정 참여자가 지정 기간에 사용한 키워드별 언급 횟수를 반환한다 (미인덱싱 방이면 None, 명단에 없으면 False)
def get_chatroom_keywords_by_person(chatroom_id: str, start_date: str, end_date: str, participant_id: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT 1 FROM chatroom_people
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s AND participant_id = %s
            """,
            (chatroom_id, index_date, user_id, participant_id),
        )
        if cursor.fetchone() is None:
            return False

        cursor.execute(
            """
            SELECT k.keyword_name AS word, SUM(k.mention_count) AS count
            FROM message_keyword k
            JOIN message_block b
              ON k.block_id = b.block_id AND k.chatroom_id = b.chatroom_id
             AND k.index_date = b.index_date AND k.user_id = b.user_id
            WHERE k.chatroom_id = %s AND k.index_date = %s AND k.user_id = %s
              AND k.participant_name = %s
              AND b.block_date BETWEEN %s AND %s
            GROUP BY k.keyword_name
            ORDER BY count DESC
            """,
            (chatroom_id, index_date, user_id, participant_id, start_date, end_date),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [{"word": row["word"], "count": int(row["count"] or 0)} for row in rows]


# 채팅방 전체(모든 참여자·전체 기간 합산)의 키워드별 총 언급 수를 count 내림차순으로 반환한다
def get_chatroom_keyword_stats(chatroom_id: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT keyword_name AS word, SUM(mention_count) AS count
            FROM message_keyword
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
            GROUP BY keyword_name
            ORDER BY count DESC
            """,
            (chatroom_id, index_date, user_id),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return {"keywords": [{"word": row["word"], "count": int(row["count"] or 0)} for row in rows]}


# 채팅방 전체(모든 참여자 합산)의 월별 메시지 수를 [{month, count}]로 반환한다 (미인덱싱 방이면 None)
# 단톡방은 발신/수신 구분이 없는 그룹 대화라 "송수신 횟수" = 그 달에 오간 전체 메시지 수로 집계한다.
def get_chatroom_monthly_message_stats(chatroom_id: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT DATE_FORMAT(block_date, '%Y-%m') AS month, SUM(message_count) AS count
            FROM message_block
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
            GROUP BY month
            ORDER BY month
            """,
            (chatroom_id, index_date, user_id),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [{"month": row["month"], "count": int(row["count"] or 0)} for row in rows]


# 채팅방 전체(모든 참여자 합산)의 월별 키워드 목록·언급 수를 {월: [{word, count}]}로 반환한다 (미인덱싱 방이면 None)
def get_chatroom_keyword_monthly_stats(chatroom_id: str, start_date: str = None, end_date: str = None):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = """
            SELECT DATE_FORMAT(b.block_date, '%Y-%m') AS month, k.keyword_name AS word, SUM(k.mention_count) AS count
            FROM message_keyword k
            JOIN message_block b
              ON k.block_id = b.block_id AND k.chatroom_id = b.chatroom_id
             AND k.index_date = b.index_date AND k.user_id = b.user_id
            WHERE k.chatroom_id = %s AND k.index_date = %s AND k.user_id = %s
        """
        params = [chatroom_id, index_date, user_id]
        if start_date and end_date:
            sql += " AND b.block_date BETWEEN %s AND %s"
            params += [start_date, end_date]
        sql += " GROUP BY month, k.keyword_name ORDER BY month, count DESC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    monthly = {}
    for row in rows:
        monthly.setdefault(row["month"], []).append({"word": row["word"], "count": int(row["count"] or 0)})
    return monthly


# 채팅방 전체가 특정 월에 날짜별로 언급한 키워드 목록·횟수를 {날짜: [{word, count}]}로 반환한다 (미인덱싱 방이면 None)
def get_chatroom_keyword_daily_stats(chatroom_id: str, month: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    year, mon = (int(x) for x in month.split("-"))
    month_start = f"{month}-01"
    month_end = f"{month}-{calendar.monthrange(year, mon)[1]:02d}"

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT b.block_date AS date, k.keyword_name AS word, SUM(k.mention_count) AS count
            FROM message_keyword k
            JOIN message_block b
              ON k.block_id = b.block_id AND k.chatroom_id = b.chatroom_id
             AND k.index_date = b.index_date AND k.user_id = b.user_id
            WHERE k.chatroom_id = %s AND k.index_date = %s AND k.user_id = %s
              AND b.block_date BETWEEN %s AND %s
            GROUP BY b.block_date, k.keyword_name
            ORDER BY b.block_date, count DESC
            """,
            (chatroom_id, index_date, user_id, month_start, month_end),
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


# 특정 날짜에 특정 키워드를 언급한 참여자별 횟수를 count 내림차순 목록으로 반환한다 (미인덱싱 방이면 None)
def get_chatroom_keyword_mentioners(chatroom_id: str, date: str, keyword: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT k.participant_name AS participant_id, SUM(k.mention_count) AS count
            FROM message_keyword k
            JOIN message_block b
              ON k.block_id = b.block_id AND k.chatroom_id = b.chatroom_id
             AND k.index_date = b.index_date AND k.user_id = b.user_id
            WHERE k.chatroom_id = %s AND k.index_date = %s AND k.user_id = %s
              AND k.keyword_name = %s
              AND b.block_date = %s
            GROUP BY k.participant_name
            ORDER BY count DESC
            """,
            (chatroom_id, index_date, user_id, keyword, date),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [{"participant_id": r["participant_id"], "name": r["participant_id"], "count": int(r["count"] or 0)} for r in rows]


# 특정 참여자가 월별로 보낸 메시지 수와 총합을 집계해 반환한다 (미인덱싱 방이면 None, 명단에 없으면 False)
def get_chatroom_person_monthly_stats(chatroom_id: str, participant_id: str, start_date: str = None, end_date: str = None):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT 1 FROM chatroom_people
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s AND participant_id = %s
            """,
            (chatroom_id, index_date, user_id, participant_id),
        )
        if cursor.fetchone() is None:
            return False

        sql = """
            SELECT DATE_FORMAT(b.block_date, '%Y-%m') AS month, SUM(p.sent_message) AS count
            FROM participant p
            JOIN message_block b
              ON p.block_id = b.block_id AND p.chatroom_id = b.chatroom_id
             AND p.index_date = b.index_date AND p.user_id = b.user_id
            WHERE p.chatroom_id = %s AND p.index_date = %s AND p.user_id = %s
              AND p.participant_name = %s
        """
        params = [chatroom_id, index_date, user_id, participant_id]
        if start_date and end_date:
            sql += " AND b.block_date BETWEEN %s AND %s"
            params += [start_date, end_date]
        sql += " GROUP BY month ORDER BY month"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    monthly = [{"month": row["month"], "count": int(row["count"] or 0)} for row in rows]
    total = sum(m["count"] for m in monthly)
    return {"monthly": monthly, "total": total}


# 특정 참여자가 특정 월에 날짜별로 보낸 메시지 수를 집계해 반환한다 (미인덱싱 방이면 None, 명단에 없으면 False)
def get_chatroom_person_daily_stats(chatroom_id: str, participant_id: str, month: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    year, mon = (int(x) for x in month.split("-"))
    month_start = f"{month}-01"
    month_end = f"{month}-{calendar.monthrange(year, mon)[1]:02d}"

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT 1 FROM chatroom_people
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s AND participant_id = %s
            """,
            (chatroom_id, index_date, user_id, participant_id),
        )
        if cursor.fetchone() is None:
            return False

        cursor.execute(
            """
            SELECT b.block_date AS date, SUM(p.sent_message) AS count
            FROM participant p
            JOIN message_block b
              ON p.block_id = b.block_id AND p.chatroom_id = b.chatroom_id
             AND p.index_date = b.index_date AND p.user_id = b.user_id
            WHERE p.chatroom_id = %s AND p.index_date = %s AND p.user_id = %s
              AND p.participant_name = %s
              AND b.block_date BETWEEN %s AND %s
            GROUP BY b.block_date
            ORDER BY b.block_date
            """,
            (chatroom_id, index_date, user_id, participant_id, month_start, month_end),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    days = [
        {
            "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"]),
            "count": int(row["count"] or 0),
        }
        for row in rows
    ]
    return {"days": days}


# 채팅방의 특정 날짜 하루치 대화 원문 메시지를 parquet에서 파싱해 시간순으로 반환한다 (미인덱싱 방이면 None)
def get_chatroom_day_messages(base_dir: str, chatroom_id: str, date: str):
    from util.message_statics import _parse_message_blocks_from_parquet

    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None

    paths = UserPaths(base_dir, chatroom_id, "messenger")
    blocks = _parse_message_blocks_from_parquet(paths)

    messages = []
    for block in blocks:
        if block.get("block_date") != date:
            continue
        messages.extend(block.get("messages") or [])

    messages.sort(key=lambda m: m.get("time") or "")
    return messages


# 채팅방의 월별/연별 LLM 요약을 기간 오름차순으로 반환한다 (미인덱싱 방이면 None)
def get_chatroom_summaries(chatroom_id: str, summarize_unit: str):
    latest = get_latest_chatroom(chatroom_id)
    if not latest:
        return None
    index_date, user_id = latest["index_date"], latest["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT summary_period, summarized_context, contacts
            FROM message_summarize
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
              AND summarize_unit = %s
            ORDER BY summary_period
            """,
            (chatroom_id, index_date, user_id, summarize_unit),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    result = []
    for row in rows:
        contacts = row["contacts"]
        if contacts:
            contacts = json.loads(contacts) if isinstance(contacts, str) else contacts
        else:
            contacts = []
        result.append({
            "summary_period": row["summary_period"],
            "summarized_context": row["summarized_context"],
            "contacts": contacts,
        })
    return result
