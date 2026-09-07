# 메신저 대화방 인덱싱 결과(참여자·대화 블록·관계·키워드·요약·분위기 등)를 chatroom 관련 테이블에 저장한다.

# Utility functions that persist messenger chatroom indexing results (participants, message blocks, relationships, keywords, summaries, mood) into the chatroom-related database tables.

import os
import json
import datetime
from config.db import get_db_connection
from util.database.db_writer import get_or_create_user_id, collect_indexing_stats

# datetime이면 microsecond를 제거해 초 단위로 통일한다 (그 외 값은 그대로 반환)
def _normalize_datetime(value):
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0)
    return value

# participant.participant_name / message_keyword.participant_name 둘 다 VARCHAR(255).
_PARTICIPANT_NAME_MAXLEN = 255

# 참여자 이름이 maxlen(255)을 넘으면 말줄임표를 붙여 잘라낸다 (파싱 오탐으로 긴 이름이 들어오는 경우 대비)
def _clip_participant_name(name: str, maxlen: int = _PARTICIPANT_NAME_MAXLEN) -> str:
    name = (name or "").strip()
    if len(name) <= maxlen:
        return name
    return name[: maxlen - 3].rstrip() + "..."

# chatroom 테이블에서 해당 chatroom_id의 가장 최근 레코드를 dict로 반환한다 (없으면 None)
def get_latest_chatroom(chatroom_id: str):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT chatroom_id, index_date, user_id
            FROM chatroom
            WHERE chatroom_id = %s
            ORDER BY index_date DESC
            LIMIT 1
            """,
            (chatroom_id,),
        )
        return cursor.fetchone()
    except Exception as e:
        print(f"[ERROR] get_latest_chatroom 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# chatroom 레코드의 복합 키 (chatroom_id, index_date, user_id)를 반환한다 (레코드도 update_date도 없으면 None)
def _resolve_chatroom_key(chatroom_id: str, update_date=None):
    update_date = _normalize_datetime(update_date)

    latest = get_latest_chatroom(chatroom_id)
    if update_date is None:
        if not latest:
            return None
        return chatroom_id, latest["index_date"], latest["user_id"]
    user_id = latest["user_id"] if latest else get_or_create_user_id(chatroom_id)
    return chatroom_id, update_date, user_id


# chatroom 테이블에 인덱싱 결과 레코드를 생성하고 user_id를 반환한다 (user_id 없으면 신규 발급)
def create_chatroom(chatroom_id, chatroom_name, ended_at, index_time, message_count, message_platform):
    user_id = get_or_create_user_id(chatroom_id)
    ended_at = _normalize_datetime(ended_at)

    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
    INSERT INTO chatroom (
        chatroom_id, index_date, user_id, chatroom_name, message_platform,
        message_count, index_time, llm_model, embed_model
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    cursor.execute(sql, (
        chatroom_id,
        ended_at,
        user_id,
        chatroom_name,
        message_platform,
        message_count,
        str(index_time),
        "",
        "",
    ))

    conn.commit()
    cursor.close()
    conn.close()
    return user_id


# collect_indexing_stats 결과를 chatroom 테이블의 통계 컬럼들에 업데이트한다
def update_chatroom_indexing_stats(chatroom_id: str, index_date, stats: dict):
    key = _resolve_chatroom_key(chatroom_id, index_date)
    if key is None:
        print(f"[WARN] update_chatroom_indexing_stats: chatroom 없음 {chatroom_id}")
        return
    chatroom_id, index_date, user_id = key

    total_tokens = stats["input_tokens"] + stats["output_tokens"] + stats["embed_tokens"]

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE chatroom SET
                llm_calls     = %s,
                input_tokens  = %s,
                output_tokens = %s,
                llm_model     = %s,
                embed_calls   = %s,
                embed_tokens  = %s,
                embed_model   = %s,
                total_tokens  = %s,
                cost_usd      = %s
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
            """,
            (
                stats["llm_calls"],
                stats["input_tokens"],
                stats["output_tokens"],
                stats["llm_model"],
                stats["embed_calls"],
                stats["embed_tokens"],
                stats["embed_model"],
                total_tokens,
                stats["cost_usd"],
                chatroom_id,
                index_date,
                user_id,
            ),
        )
        conn.commit()
        print(f"[DB] chatroom 인덱싱 통계 저장 완료: {chatroom_id} cost=${stats['cost_usd']:.6f}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] update_chatroom_indexing_stats 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# graph_data.json의 노드/엣지 수를 chatroom 테이블에 저장한다
def save_chatroom_graph_stats_to_db(paths, update_date=None):
    if not os.path.exists(paths.GRAPH_JSON_PATH):
        print(f"[WARN] 그래프 JSON 파일이 없습니다: {paths.GRAPH_JSON_PATH}")
        return

    key = _resolve_chatroom_key(paths.USER_ID, update_date)
    if key is None:
        print(f"[WARN] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, update_date, user_id = key

    with open(paths.GRAPH_JSON_PATH, "r", encoding="utf-8") as f:
        graph_data = json.load(f)

    node_count = len(graph_data.get("nodes", []))
    edge_count = len(graph_data.get("edges", []))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE chatroom SET
                node_count = %s,
                edge_count = %s
            WHERE chatroom_id = %s AND index_date = %s AND user_id = %s
            """,
            (node_count, edge_count, chatroom_id, update_date, user_id),
        )
        conn.commit()
        print(f"[DB] chatroom 그래프 통계 저장 완료: node={node_count} edge={edge_count}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_chatroom_graph_stats_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# 대화 블록을 파싱해 블록별 메시지 수·참여자·어조와 참여자별 발화 수를 message_block/participant 테이블에 저장한다
def save_message_block_to_db(paths, update_date=None):
    from util.message_statics import _parse_message_blocks_from_parquet, _classify_message_tone_with_llm

    key = _resolve_chatroom_key(paths.USER_ID, update_date)
    if key is None:
        print(f"[WARN] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, update_date, user_id = key

    blocks = _parse_message_blocks_from_parquet(paths)
    if not blocks:
        print("[DB] 저장할 메시지 블록 없음")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        block_sql = """
            INSERT INTO message_block (
                block_id, chatroom_id, index_date, user_id, block_date,
                message_count, participant_count, kg_tone, llm_tone, participant
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                block_date = VALUES(block_date),
                message_count = VALUES(message_count),
                participant_count = VALUES(participant_count),
                kg_tone = VALUES(kg_tone),
                llm_tone = VALUES(llm_tone),
                participant = VALUES(participant)
        """
        participant_sql = """
            INSERT INTO participant (
                participant_name, block_id, chatroom_id, index_date, user_id, sent_message
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE sent_message = VALUES(sent_message)
        """

        block_count = 0
        participant_row_count = 0
        for block in blocks:
            real_messages = [m for m in block["messages"] if not m["is_system"] and m["sender"]]

            sent_by: dict[str, int] = {}
            for m in real_messages:
                clipped_sender = _clip_participant_name(m["sender"])
                sent_by[clipped_sender] = sent_by.get(clipped_sender, 0) + 1

            # 참여자 헤더(참여자:)가 비어있으면(예: 파싱 실패) 실제 발신자 집합으로 대체.
            # sent_by 키는 이미 클립돼 있으니 헤더 쪽만 별도로 클립한다.
            participants = [_clip_participant_name(p) for p in block["participants"]] or list(sent_by.keys())

            body_text = "\n".join(f"{m['time']} {m['sender']}: {m['text']}" for m in real_messages)
            llm_tone = _classify_message_tone_with_llm(body_text)

            cursor.execute(block_sql, (
                block["block_id"], chatroom_id, update_date, user_id, block["block_date"],
                len(real_messages), len(participants), None, llm_tone,
                json.dumps(participants, ensure_ascii=False),
            ))
            block_count += 1

            for name, count in sent_by.items():
                cursor.execute(participant_sql, (
                    name, block["block_id"], chatroom_id, update_date, user_id, count,
                ))
                participant_row_count += 1

        conn.commit()
        print(f"[DB] message_block 저장 완료: {block_count}건 / participant {participant_row_count}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_message_block_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# 참여자별 메시지 수와 LLM 프로필(description)을 chatroom_people 테이블에 저장한다
def save_chatroom_people_to_db(paths, update_date=None):
    from util.message_statics import generate_chatroom_people_descriptions, generate_chatroom_people_short_bios

    key = _resolve_chatroom_key(paths.USER_ID, update_date)
    if key is None:
        print(f"[WARN] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, update_date, user_id = key

    if not os.path.exists(paths.CHATROOM_PEOPLE_MESSAGES_PATH):
        raise FileNotFoundError(f"참여자 메시지 이력 파일이 없습니다: {paths.CHATROOM_PEOPLE_MESSAGES_PATH}")

    with open(paths.CHATROOM_PEOPLE_MESSAGES_PATH, "r", encoding="utf-8") as f:
        people = json.load(f).get("people", {})

    try:
        descriptions = generate_chatroom_people_descriptions(paths)
    except Exception as e:
        print(f"[WARN] 참여자 프로필 생성 실패, description 없이 저장: {e}")
        descriptions = {}

    # description을 입력으로 My Time 툴팁용 한줄소개(short_bio) 2차 생성
    try:
        short_bios = generate_chatroom_people_short_bios(descriptions)
    except Exception as e:
        print(f"[WARN] 참여자 한줄소개 생성 실패, short_bio 없이 저장: {e}")
        short_bios = {}

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        insert_sql = """
            INSERT INTO chatroom_people (
                participant_id, chatroom_id, index_date, user_id,
                chatroom_people_name, message_count, description, short_bio
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                chatroom_people_name = VALUES(chatroom_people_name),
                message_count        = VALUES(message_count),
                description          = COALESCE(VALUES(description), description),
                short_bio            = COALESCE(VALUES(short_bio), short_bio)
        """
        count = 0
        for name, messages in people.items():
            clipped_name = _clip_participant_name(name)
            cursor.execute(insert_sql, (
                clipped_name, chatroom_id, update_date, user_id,
                clipped_name, len(messages), descriptions.get(name), short_bios.get(name),
            ))
            count += 1

        conn.commit()
        print(f"[DB] chatroom_people 테이블 저장 완료: {count}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_chatroom_people_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# graph_data.json의 사람-사람 엣지 중 relation_label이 붙은 것만 무방향으로 정리해 chatroom_relationship 테이블에 저장한다
def save_chatroom_relationships_to_db(paths, update_date=None):
    if not os.path.exists(paths.GRAPH_JSON_PATH):
        print(f"[WARN] 그래프 JSON 파일이 없습니다: {paths.GRAPH_JSON_PATH}")
        return

    key = _resolve_chatroom_key(paths.USER_ID, update_date)
    if key is None:
        print(f"[WARN] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, update_date, user_id = key

    with open(paths.GRAPH_JSON_PATH, "r", encoding="utf-8") as f:
        graph_data = json.load(f)

    # message 파싱으로 만들어진 chatroom_people 참여자 명단을 "사람"의 기준으로 한다
    people_cursor_conn = get_db_connection()
    people_cursor = people_cursor_conn.cursor()
    try:
        people_cursor.execute(
            "SELECT participant_id FROM chatroom_people WHERE chatroom_id=%s AND index_date=%s AND user_id=%s",
            (chatroom_id, update_date, user_id),
        )
        person_names = {row[0] for row in people_cursor.fetchall()}
    finally:
        people_cursor.close()
        people_cursor_conn.close()

    merged: dict = {}
    for edge in graph_data.get("edges", []):
        relation_label = edge.get("relation_label")
        source, target = edge.get("source"), edge.get("target")
        if not relation_label or not source or not target or source == target:
            continue
        if source not in person_names or target not in person_names:
            continue

        person_a, person_b = sorted((source, target))
        merged[(person_a, person_b)] = {
            "person_a": person_a,
            "person_b": person_b,
            "relation_label": relation_label,
            "description": edge.get("description"),
        }

    if not merged:
        print("[DB] chatroom_relationship 저장할 관계 없음")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        insert_sql = """
            INSERT INTO chatroom_relationship (
                chatroom_id, index_date, user_id,
                person_a, person_b, relation_label, description
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                relation_label = VALUES(relation_label),
                description    = VALUES(description)
        """
        saved, skipped = 0, 0
        for pair in merged.values():
            try:
                cursor.execute(insert_sql, (
                    chatroom_id, update_date, user_id,
                    pair["person_a"], pair["person_b"],
                    pair["relation_label"], pair["description"],
                ))
                saved += 1
            except Exception as e:
                # person_a/person_b가 chatroom_people에 없는 경우(FK 위반) 그 쌍만 건너뛴다.
                skipped += 1
                print(f"[WARN] chatroom_relationship 저장 실패 ({pair['person_a']}-{pair['person_b']}): {e}")
        conn.commit()
        print(f"[DB] chatroom_relationship 테이블 저장 완료: {saved}건 (건너뜀 {skipped}건)")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_chatroom_relationships_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# message_keyword_stats.json을 읽어 participant에 실제 존재하는 (참여자, 블록) 쌍만 message_keyword 테이블에 저장한다 (2회 미만 키워드 제외)
def save_message_keyword_to_db(paths, update_date=None):
    key = _resolve_chatroom_key(paths.USER_ID, update_date)
    if key is None:
        print(f"[WARN] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, update_date, user_id = key

    if not os.path.exists(paths.MESSAGE_KEYWORDS_PATH):
        raise FileNotFoundError(f"통계 파일이 없습니다: {paths.MESSAGE_KEYWORDS_PATH}")

    with open(paths.MESSAGE_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        stats = json.load(f)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        keywords = stats.get("keywords", {})
        mention_map = stats.get("keyword_participant_block_map", {})

        cursor.execute(
            "SELECT participant_name, block_id FROM participant WHERE chatroom_id = %s AND index_date = %s AND user_id = %s",
            (chatroom_id, update_date, user_id),
        )
        valid_pairs = {(row[0], row[1]) for row in cursor.fetchall()}

        insert_sql = """
            INSERT INTO message_keyword (
                keyword_name, participant_name, block_id, chatroom_id, index_date, user_id, mention_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE mention_count = VALUES(mention_count)
        """
        rows = []
        for keyword_name, participant_map in mention_map.items():
            if keywords.get(keyword_name, 0) < 2:
                continue
            for participant_name, block_map in participant_map.items():
                for block_id, count in block_map.items():
                    if (participant_name, block_id) not in valid_pairs:
                        continue
                    rows.append((keyword_name, participant_name, block_id, chatroom_id, update_date, user_id, count))

        if rows:
            cursor.executemany(insert_sql, rows)
            conn.commit()
            print(f"[DB] message_keyword 테이블 저장 완료: {len(rows)}건")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_message_keyword_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# message_summaries.json의 연/월별 LLM 요약과 참여자 목록을 message_summarize 테이블에 저장한다
def save_message_summarize_to_db(paths, update_date=None):
    key = _resolve_chatroom_key(paths.USER_ID, update_date)
    if key is None:
        print(f"[WARN] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, update_date, user_id = key

    if not os.path.exists(paths.MESSAGE_SUMMARIES_PATH):
        print(f"[WARN] 파일이 없습니다: {paths.MESSAGE_SUMMARIES_PATH}")
        return

    with open(paths.MESSAGE_SUMMARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for period, info in data.get("yearly", {}).items():
        rows.append((
            "yearly", period, chatroom_id, update_date, user_id,
            info.get("summary"),
            json.dumps(info.get("contacts"), ensure_ascii=False) if info.get("contacts") else None,
        ))
    for period, info in data.get("monthly", {}).items():
        rows.append((
            "monthly", period, chatroom_id, update_date, user_id,
            info.get("summary"),
            json.dumps(info.get("contacts"), ensure_ascii=False) if info.get("contacts") else None,
        ))

    if not rows:
        print("[WARN] save_message_summarize_to_db: 저장할 데이터가 없습니다.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        insert_sql = """
            INSERT INTO message_summarize (
                summarize_unit, summary_period, chatroom_id, index_date, user_id,
                summarized_context, contacts
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                summarized_context = VALUES(summarized_context),
                contacts = VALUES(contacts)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print(f"[DB] message_summarize 테이블 저장 완료: {len(rows)}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_message_summarize_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# message_mood.json의 연/월별 분위기 점수·설명을 message_mood 테이블에 저장한다
def save_message_mood_to_db(paths, update_date=None):
    key = _resolve_chatroom_key(paths.USER_ID, update_date)
    if key is None:
        print(f"[WARN] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, update_date, user_id = key

    if not os.path.exists(paths.MESSAGE_MOOD_PATH):
        print(f"[WARN] 파일이 없습니다: {paths.MESSAGE_MOOD_PATH}")
        return

    with open(paths.MESSAGE_MOOD_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for period, info in data.get("yearly", {}).items():
        rows.append((
            period, "yearly", chatroom_id, update_date, user_id,
            info.get("mood_description"),
            info.get("mood_score"),
        ))
    for period, info in data.get("monthly", {}).items():
        rows.append((
            period, "monthly", chatroom_id, update_date, user_id,
            info.get("mood_description"),
            info.get("mood_score"),
        ))

    if not rows:
        print("[WARN] save_message_mood_to_db: 저장할 데이터가 없습니다.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        insert_sql = """
            INSERT INTO message_mood (
                summary_period, summary_unit, chatroom_id, index_date, user_id,
                mood_description, mood_score
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                mood_description = VALUES(mood_description),
                mood_score = VALUES(mood_score)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print(f"[DB] message_mood 테이블 저장 완료: {len(rows)}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_message_mood_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()
