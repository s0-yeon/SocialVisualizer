# 메일 인덱싱 결과(계정·연락처·메일·키워드·요약·폴더·비용 통계 등)를 user DB에 저장한다.

# Utility functions that persist mail indexing results — accounts, contacts, mail, keywords, summaries, folders, and cost stats — into the user database.

import os
import re
import json
import uuid
import datetime
from config.db import get_db_connection

# mail_account 테이블에서 해당 계정의 가장 최근 레코드를 dict로 반환한다 (없으면 None)
def get_latest_mail_account(user_mail_account_id: str):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        sql = """
            SELECT user_mail_account_id, index_date, user_id
            FROM mail_account
            WHERE user_mail_account_id = %s
            ORDER BY index_date DESC
            LIMIT 1
        """
        cursor.execute(sql, (user_mail_account_id,))
        result = cursor.fetchone()
        return result

    except Exception as e:
        print(f"[ERROR] get_latest_mail_account 실패: {e}")
        raise

    finally:
        cursor.close()
        conn.close()

# user 테이블의 user_id를 조회하고, 없으면 새 UUID를 발급해 저장한 뒤 반환한다
def get_or_create_user_id(user_mail_account_id: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM user LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row[0]

        new_user_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO user (user_id) VALUES (%s)", (new_user_id,))
        conn.commit()
        return new_user_id
    finally:
        cursor.close()
        conn.close()


# mail_account 테이블에 인덱싱 결과 레코드를 생성하고 user_id를 반환한다 (user_id 없으면 신규 발급)
def create_mail_account(user_mail_account_id, ended_at, index_time, mail_count, mail_platform):
    user_id = get_or_create_user_id(user_mail_account_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
    INSERT INTO mail_account (
        user_mail_account_id, index_date, user_id, mail_platform,
        mail_count, index_time, llm_model, embed_model
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """

    cursor.execute(sql, (
        user_mail_account_id,
        ended_at,
        user_id,
        mail_platform,
        mail_count,
        str(index_time),
        "",
        "",
    ))

    conn.commit()
    cursor.close()
    conn.close()
    return user_id

# mail_contact_stats.json과 LLM 프로필을 합쳐 person 테이블에 저장한다 (255자 초과 이메일은 건너뜀)
def save_person_stats_to_db(paths, update_date=None):
    if not os.path.exists(paths.MAIL_CONTACTS_PATH):
        raise FileNotFoundError(f"통계 파일이 없습니다: {paths.MAIL_CONTACTS_PATH}")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if update_date is None:
            latest_account = get_latest_mail_account(paths.USER_ID)
            if not latest_account:
                print(f"[WARN] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
                return
            user_mail_account_id = latest_account["user_mail_account_id"]
            update_date          = latest_account["index_date"]
        else:
            user_mail_account_id = paths.USER_ID

        with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
            stats = json.load(f)

        # parquet → LLM 프로필 생성 (실패해도 기본 통계 저장은 계속)
        from util.extract_statics import generate_person_descriptions, generate_person_short_bios
        try:
            descriptions_raw = generate_person_descriptions(paths)
            descriptions = {k.lower(): v for k, v in descriptions_raw.items()}
        except Exception as e:
            print(f"[WARN] 프로필 생성 실패, description 없이 저장: {e}")
            descriptions = {}

        # description(+relation_label)을 입력으로 My Time 툴팁용 한줄소개(short_bio) 2차 생성
        try:
            short_bios = generate_person_short_bios(descriptions)
        except Exception as e:
            print(f"[WARN] 한줄소개 생성 실패, short_bio 없이 저장: {e}")
            short_bios = {}

        insert_sql = """
            INSERT INTO person (
                person_mail_account_id,
                user_mail_account_id,
                index_date,
                person_name,
                receive_mails,
                send_mails,
                friendly_mails,
                description,
                relation_label,
                short_bio
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                person_name    = VALUES(person_name),
                receive_mails  = VALUES(receive_mails),
                send_mails     = VALUES(send_mails),
                friendly_mails = VALUES(friendly_mails),
                description    = COALESCE(VALUES(description), description),
                relation_label = COALESCE(VALUES(relation_label), relation_label),
                short_bio      = COALESCE(VALUES(short_bio), short_bio)
        """

        inserted_count = 0
        skipped_count = 0
        for email, info in stats.items():
            # 발신자 파싱이 실패한 값은 DB에 넣지 않고 건너뛴다
            if len(email) > 255:
                skipped_count += 1
                continue
            profile = descriptions.get(email) or {}
            cursor.execute(
                insert_sql,
                (
                    email,
                    user_mail_account_id,
                    update_date,
                    info.get("name", ""),
                    int(info.get("received", 0)),
                    int(info.get("sent", 0)),
                    int(info.get("friendly_mail", 0)),
                    profile.get("description"),
                    profile.get("relation_label"),
                    short_bios.get(email),
                )
            )
            inserted_count += 1

        conn.commit()
        print(f"[DB] person 테이블 저장 완료: {inserted_count}건 (255자 초과로 건너뜀: {skipped_count}건)")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_person_stats_to_db 실패: {e}")
        raise

    finally:
        cursor.close()
        conn.close()

_MODEL_COST_PER_1M = {
    "gpt-4o-mini": {"input": 0.150, "output": 0.600},
    "gpt-4o": {"input": 2.50,  "output": 10.00},
    "gpt-5.4-mini": {"input": 0.75,  "output": 4.50},
}

_EMBED_COST_PER_1M = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}

# 채팅 모델의 입출력 토큰 수로 USD 비용을 계산한다
def _calc_cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    costs = _MODEL_COST_PER_1M.get(model_name, {"input": 0.0, "output": 0.0})
    return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

# 임베딩 모델의 토큰 수로 USD 비용을 계산한다
def _calc_embed_cost_usd(model_name: str, total_tokens: int) -> float:
    cost = _EMBED_COST_PER_1M.get(model_name, 0.0)
    return (total_tokens * cost) / 1_000_000


# GraphRAG 캐시 폴더를 읽어 인덱싱에 쓴 LLM/임베딩 호출 수·토큰·비용을 집계한 dict를 반환한다
def collect_indexing_stats(paths) -> dict:
    LLM_FOLDERS = ["community_reporting", "extract_graph", "summarize_descriptions"]
    EMBED_FOLDER = "text_embedding"

    cache_dir = os.path.join(paths.GRAPHRAG_ROOT, "cache")

    llm_calls = 0
    input_tokens = 0
    output_tokens = 0
    # 인덱싱 온오프 스위치(INDEXING_COMPLETION_MODEL_ID)가 실제로 가리키는 모델을 그대로 라벨링.
    # "indexing_chat_model"이면 로컬(INDEXING_CHAT_MODEL), 아니면("default_chat_model") OpenAI(RAG_CHAT_MODEL).
    if os.getenv("INDEXING_COMPLETION_MODEL_ID") == "indexing_chat_model":
        llm_model = os.getenv("INDEXING_CHAT_MODEL", "")
    else:
        llm_model = os.getenv("RAG_CHAT_MODEL", "")

    embed_calls = 0
    embed_tokens = 0
    if os.getenv("INDEXING_EMBEDDING_MODEL_ID") == "indexing_embedding_model":
        embed_model = os.getenv("INDEXING_EMBEDDING_MODEL", "")
    else:
        embed_model = os.getenv("RAG_EMBEDDING_MODEL", "")

    for folder in LLM_FOLDERS:
        folder_path = os.path.join(cache_dir, folder)
        if not os.path.exists(folder_path):
            continue
        for fname in os.listdir(folder_path):
            fpath = os.path.join(folder_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                response = data.get("result", {}).get("response", {})  # v3 캐시 구조: result.response 아래에에 usage/model
                usage = response.get("usage", {})
                llm_calls += 1
                input_tokens += usage.get("prompt_tokens", 0)
                output_tokens += usage.get("completion_tokens", 0)
            except Exception as e:
                print(f"[WARN] LLM 캐시 읽기 실패 {fpath}: {e}")

    embed_path = os.path.join(cache_dir, EMBED_FOLDER)
    if os.path.exists(embed_path):
        for fname in os.listdir(embed_path):
            fpath = os.path.join(embed_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                response = data.get("result", {}).get("response", {})  # v3 캐시 구조: result.response 아래에 usage/model
                usage = response.get("usage", {})
                embed_calls += 1
                embed_tokens += usage.get("total_tokens", 0)
            except Exception as e:
                print(f"[WARN] 임베딩 캐시 읽기 실패 {fpath}: {e}")

    cost_usd = (
        _calc_cost_usd(llm_model, input_tokens, output_tokens)
        + _calc_embed_cost_usd(embed_model, embed_tokens)
    )

    print(
        f"[STATS] llm={llm_calls}calls in={input_tokens} out={output_tokens} model={llm_model} | "
        f"embed={embed_calls}calls tokens={embed_tokens} model={embed_model} | cost=${cost_usd:.6f}"
    )
    return {
        "llm_calls": llm_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_model": llm_model,
        "embed_calls": embed_calls,
        "embed_tokens": embed_tokens,
        "embed_model": embed_model,
        "cost_usd": cost_usd,
    }


# collect_indexing_stats 결과를 mail_account 테이블의 통계 컬럼들에 업데이트한다
def update_mail_account_indexing_stats(user_mail_account_id: str, index_date, stats: dict):
    if index_date is None:
        latest = get_latest_mail_account(user_mail_account_id)
        if not latest:
            print(f"[WARN] update_mail_account_indexing_stats: mail_account 없음 {user_mail_account_id}")
            return
        index_date = latest["index_date"]

    total_tokens = stats["input_tokens"] + stats["output_tokens"] + stats["embed_tokens"]

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE mail_account SET
                llm_calls     = %s,
                input_tokens  = %s,
                output_tokens = %s,
                llm_model     = %s,
                embed_calls   = %s,
                embed_tokens  = %s,
                embed_model   = %s,
                total_tokens  = %s,
                cost_usd      = %s
            WHERE user_mail_account_id = %s AND index_date = %s
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
                user_mail_account_id,
                index_date,
            ),
        )
        conn.commit()
        print(f"[DB] mail_account 인덱싱 통계 저장 완료: {user_mail_account_id} cost=${stats['cost_usd']:.6f}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] update_mail_account_indexing_stats 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# graph_data.json의 노드/엣지 수를 mail_account 테이블에 저장한다
def save_graph_stats_to_db(paths, update_date=None):
    if not os.path.exists(paths.GRAPH_JSON_PATH):
        print(f"[WARN] 그래프 JSON 파일이 없습니다: {paths.GRAPH_JSON_PATH}")
        return

    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)
        if not latest_account:
            print(f"[WARN] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
            return
        user_mail_account_id = latest_account["user_mail_account_id"]
        update_date = latest_account["index_date"]
    else:
        user_mail_account_id = paths.USER_ID

    with open(paths.GRAPH_JSON_PATH, "r", encoding="utf-8") as f:
        graph_data = json.load(f)

    node_count = len(graph_data.get("nodes", []))
    edge_count = len(graph_data.get("edges", []))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE mail_account SET
                node_count = %s,
                edge_count = %s
            WHERE user_mail_account_id = %s AND index_date = %s
            """,
            (node_count, edge_count, user_mail_account_id, update_date),
        )
        conn.commit()
        print(f"[DB] mail_account 그래프 통계 저장 완료: node={node_count} edge={edge_count}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_graph_stats_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# 질의 1건(질문·응답 시간·스코프·토큰·비용·답변·근거)을 query 테이블에 저장한다
def save_query_to_db(
    user_mail_account_id: str,
    context: str,
    response_time: float,
    scope: str = "",
    model_name: str = None,
    input_tokens: int = None,
    output_tokens: int = None,
    answer: str = None,
    refer_kg: str = None,
):
    user_id = get_or_create_user_id(user_mail_account_id)

    cost_usd = None
    if model_name and input_tokens is not None and output_tokens is not None:
        cost_usd = _calc_cost_usd(model_name, input_tokens, output_tokens)

    normalized_scope = scope if scope in ("local", "global") else "other"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO query
                (query_id, user_id, context, response_time, scope, response_date,
                 model_name, input_tokens, output_tokens, cost_usd, answer, refer_kg)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                context,
                round(response_time, 5),
                normalized_scope,
                datetime.datetime.now(),
                model_name,
                input_tokens,
                output_tokens,
                cost_usd,
                answer,
                refer_kg,
            )
        )
        conn.commit()
        print(f"[DB] query 저장 완료: {user_mail_account_id} / {response_time:.2f}s / {normalized_scope} / {model_name} / in={input_tokens} out={output_tokens} cost=${cost_usd} / refer_kg={refer_kg}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_query_to_db 실패: {e}")
    finally:
        cursor.close()
        conn.close()


# mail_keyword_stats.json을 읽어 키워드·사람·날짜별 일간 언급 수를 mail_keyword 테이블에 저장한다 (2회 미만 키워드/미등록 person 제외)
def save_keyword_stats_to_db(paths,update_date=None):
    if not os.path.exists(paths.MAIL_KEYWORDS_PATH):
        raise FileNotFoundError(f"통계 파일이 없습니다: {paths.MAIL_KEYWORDS_PATH}")

    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)

        if not latest_account:
            print(f"[WARN] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
            return

        user_mail_account_id = latest_account["user_mail_account_id"]
        update_date = latest_account["index_date"]
    else:
        user_mail_account_id = paths.USER_ID

    with open(paths.MAIL_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        stats = json.load(f)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        keywords = stats.get("keywords", {})
        keyword_person_date_map = stats.get("keyword_person_date_map", {})

        cursor.execute(
            "SELECT person_mail_account_id FROM person WHERE user_mail_account_id = %s AND index_date = %s",
            (user_mail_account_id, update_date)
        )
        valid_persons = {row[0] for row in cursor.fetchall()}

        km_insert_sql = """
            INSERT INTO mail_keyword (keyword_name, user_mail_account_id, index_date, person_mail_account_id, mail_date, daily_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE daily_count = VALUES(daily_count)
        """
        km_rows = []
        for keyword_name, person_map in keyword_person_date_map.items():
            if keywords.get(keyword_name, 0) < 2:
                continue
            for person_id, date_map in person_map.items():
                if person_id not in valid_persons:
                    continue
                for mail_date, count in date_map.items():
                    km_rows.append((keyword_name, user_mail_account_id, update_date, person_id, mail_date, count))

        if km_rows:
            cursor.executemany(km_insert_sql, km_rows)
            conn.commit()
            print(f"[DB] mail_keyword 테이블 저장 완료: {len(km_rows)}건")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_keyword_stats_to_db 실패: {e}")
        raise

    finally:
        cursor.close()
        conn.close()

# 기존 키워드 목록과 text_units parquet으로 LLM 없이 문자열 매칭해 keyword_person_date_map을 재구성하고 mail_keyword를 채운다
def rebuild_keyword_mail(paths, update_date=None):
    import pandas as pd, re, os

    if not os.path.exists(paths.MAIL_KEYWORDS_PATH):
        raise FileNotFoundError(f"keyword 파일이 없습니다: {paths.MAIL_KEYWORDS_PATH}")

    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)
        if not latest_account:
            print(f"[WARN] mail_account 없음: {paths.USER_ID}")
            return
        update_date = latest_account["index_date"]

    with open(paths.MAIL_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        kw_data = json.load(f)

    known_keywords = [kw for kw, cnt in kw_data.get("keywords", {}).items() if cnt >= 2]
    if not known_keywords:
        print("[WARN] 유효한 키워드 없음 (count < 2)")
        return

    text_units_path = paths.RELATIONSHIPS_PATH.replace("relationships.parquet", "text_units.parquet")
    if not os.path.exists(text_units_path):
        print(f"[WARN] text_units parquet 없음: {text_units_path}")
        return

    df = pd.read_parquet(text_units_path)

    # "Name <email>" 형태에서 이메일만 소문자로 뽑는다
    def parse_email(value):
        m = re.search(r'<(.+?)>', value)
        return m.group(1).strip().lower() if m else value.strip().lower()

    keyword_person_date_map = {}
    user_lower = paths.USER_ID.lower()

    for _, row in df.iterrows():
        text = str(row.get('text', ''))

        date_match   = re.search(r'^\[날짜\]\s*(.+)$', text, re.MULTILINE)
        sender_match = re.search(r'^\[발신인\]\s*(.+)$', text, re.MULTILINE)
        receiver_match = re.search(r'^\[수신인\]\s*(.+)$', text, re.MULTILINE)
        body_match   = re.search(r'\[메일 본문\]\s*\n(.*?)(?:\n\[|\n=+|\Z)', text, re.DOTALL)

        mail_date = date_match.group(1).strip()[:10] if date_match else None
        sender    = parse_email(sender_match.group(1)) if sender_match else None
        receiver  = parse_email(receiver_match.group(1)) if receiver_match else None
        body      = body_match.group(1).strip() if body_match else ''

        person = receiver if sender == user_lower else sender

        if not body or not mail_date or not person:
            continue

        for kw in known_keywords:
            if kw in body:
                keyword_person_date_map.setdefault(kw, {}).setdefault(person, {})
                keyword_person_date_map[kw][person][mail_date] = \
                    keyword_person_date_map[kw][person].get(mail_date, 0) + 1

    kw_data["keyword_person_date_map"] = keyword_person_date_map
    with open(paths.MAIL_KEYWORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(kw_data, f, ensure_ascii=False, indent=2)

    total_pairs = sum(len(pm) for pm in keyword_person_date_map.values())
    print(f"[KEYWORD] keyword_person_date_map 재구성 완료: 키워드 {len(keyword_person_date_map)}개, person-date 쌍 {total_pairs}개")

    # DB에 저장
    save_keyword_stats_to_db(paths, update_date)


# processed_attachments 테이블과 대조해 아직 처리되지 않은 첨부파일만 걸러 반환한다
def filter_unprocessed_attachments(user_id: str, attachments: list) -> list:
    if not attachments:
        return []

    latest_account = get_latest_mail_account(user_id)
    if not latest_account:
        print(f"[WARN] filter_unprocessed_attachments: mail_account 테이블에 {user_id} 없음, 전체 처리")
        return attachments

    user_mail_account_id = latest_account["user_mail_account_id"]
    index_date = latest_account["index_date"]

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT mail_id, filename
            FROM processed_attachments
            WHERE user_mail_account_id = %s
              AND index_date = %s
              AND (mail_id, filename) IN ({",".join(["(%s,%s)"] * len(attachments))})
        """, [user_mail_account_id, index_date] + [
            v for a in attachments
            for v in (a.get("mail_id", ""), a.get("name", ""))
        ])

        already_done = set((row[0], row[1]) for row in cursor.fetchall())
        cursor.close()
        conn.close()

        unprocessed = [
            a for a in attachments
            if (a.get("mail_id", ""), a.get("name", "")) not in already_done
        ]

        skipped = len(attachments) - len(unprocessed)
        if skipped > 0:
            print(f"[AttachmentFilter] 중복 제외: {skipped}개 / 처리 대상: {len(unprocessed)}개")

        return unprocessed

    except Exception as e:
        print(f"[AttachmentFilter] DB 조회 실패, 전체 처리: {e}")
        return attachments


# 처리 완료된 첨부파일을 processed_attachments 테이블에 기록한다 (중복은 INSERT IGNORE)
def mark_attachments_as_processed(user_id: str, attachments: list):
    if not attachments:
        return

    latest_account = get_latest_mail_account(user_id)
    if not latest_account:
        print(f"[WARN] mark_attachments_as_processed: mail_account 테이블에 {user_id} 없음, 기록 생략")
        return

    user_mail_account_id = latest_account["user_mail_account_id"]
    index_date = latest_account["index_date"]

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.datetime.now()
        rows = [
            (user_mail_account_id, index_date, a.get("mail_id", ""), a.get("name", ""), now)
            for a in attachments
        ]
        cursor.executemany("""
            INSERT IGNORE INTO processed_attachments
                (user_mail_account_id, index_date, mail_id, filename, processed_at)
            VALUES (%s, %s, %s, %s, %s)
        """, rows)
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[AttachmentFilter] {len(rows)}개 처리 완료 기록")
    except Exception as e:
        print(f"[AttachmentFilter] 처리 완료 기록 실패 (무시): {e}")

# mail_summaries.json의 연/월별 요약과 참여자 목록을 mail_summarize 테이블에 저장한다
def save_mail_summarize_to_db(paths, update_date=None):
    if not os.path.exists(paths.MAIL_SUMMARIES_PATH):
        print(f"[WARN] 파일이 없습니다: {paths.MAIL_SUMMARIES_PATH}")
        return

    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)
        if not latest_account:
            print(f"[WARN] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
            return
        user_mail_account_id = latest_account["user_mail_account_id"]
        update_date = latest_account["index_date"]
    else:
        user_mail_account_id = paths.USER_ID

    with open(paths.MAIL_SUMMARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for period, info in data.get("yearly", {}).items():
        rows.append((
            user_mail_account_id,
            update_date,
            "yearly",
            period,
            info.get("summary"),
            json.dumps(info.get("contacts"), ensure_ascii=False) if info.get("contacts") else None,
        ))
    for period, info in data.get("monthly", {}).items():
        rows.append((
            user_mail_account_id,
            update_date,
            "monthly",
            period,
            info.get("summary"),
            json.dumps(info.get("contacts"), ensure_ascii=False) if info.get("contacts") else None,
        ))

    if not rows:
        print("[WARN] save_mail_summarize_to_db: 저장할 데이터가 없습니다.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        insert_sql = """
            INSERT INTO mail_summarize (
                user_mail_account_id, index_date, summarize_unit, summary_period,
                summarized_context, contacts
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                summarized_context = VALUES(summarized_context),
                contacts = VALUES(contacts)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print(f"[DB] mail_summarize 테이블 저장 완료: {len(rows)}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_mail_summarize_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# text_units parquet을 메일(document) 단위로 묶어 폴더별 메일 수를 집계해 mail_folder 테이블에 저장한다
def save_mail_folder_to_db(paths, update_date=None):
    import pandas as pd, re, os

    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)
        if not latest_account:
            print(f"[WARN] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
            return
        user_mail_account_id = latest_account["user_mail_account_id"]
        update_date = latest_account["index_date"]
    else:
        user_mail_account_id = paths.USER_ID

    text_units_path = paths.RELATIONSHIPS_PATH.replace("relationships.parquet", "text_units.parquet")
    df = pd.read_parquet(text_units_path)

    # document_id(=메일) 단위로 묶어서 그중 하나라도 메일 폴더 정보를 찾으면 그 값을 메일의 폴더로 쓴다.
    folder_by_doc = {}
    for _, row in df.iterrows():
        doc_key = row.get('document_id')

        if folder_by_doc.get(doc_key):
            continue

        text = str(row.get('text', ''))
        folder_match = re.search(r'\[폴더 정보\]\s*(.+)', text)
        folder_raw = folder_match.group(1).strip() if folder_match else None
        if folder_raw and folder_raw != '없음':
            folder_by_doc[doc_key] = folder_raw
        else:
            folder_by_doc.setdefault(doc_key, None)

    folder_counts = {}
    for folder_raw in folder_by_doc.values():
        # save_mail_to_db와 동일한 폴백('UNKNOWN')을 쓴다
        mail_folder_name = folder_raw or 'UNKNOWN'
        folder_counts[mail_folder_name] = folder_counts.get(mail_folder_name, 0) + 1

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        insert_sql = """
            INSERT INTO mail_folder (mail_folder_name, user_mail_account_id, index_date, mail_count)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE mail_count = VALUES(mail_count)
        """
        for mail_folder_name, mail_count in folder_counts.items():
            cursor.execute(insert_sql, (mail_folder_name, user_mail_account_id, update_date, mail_count))
        conn.commit()
        print(f"[DB] mail_folder 테이블 저장 완료: {len(folder_counts)}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_mail_folder_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# text_units parquet을 파싱해 메일별 방향·어조·답장 관계를 계산해 mail 테이블에 저장한다
def save_mail_to_db(paths, update_date=None):
    import pandas as pd, re, os, datetime

    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)
        if not latest_account:
            print(f"[WARN] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
            return
        user_mail_account_id = latest_account["user_mail_account_id"]
        update_date = latest_account["index_date"]
    else:
        user_mail_account_id = paths.USER_ID

    text_units_path = paths.RELATIONSHIPS_PATH.replace("relationships.parquet", "text_units.parquet")
    df = pd.read_parquet(text_units_path)

    # entities.parquet에서 mail_id -> kg_tone 매핑 빌드
    tone_map = {}
    if os.path.exists(paths.ENTITIES_PATH):
        entities_df = pd.read_parquet(paths.ENTITIES_PATH)
        type_col = 'type' if 'type' in entities_df.columns else 'entity_type'
        for _, row in entities_df[entities_df[type_col].str.upper() == 'EMAIL'].iterrows():
            tone_m = re.search(r'Tone:\s*(\w+)', str(row.get('description', '')))
            if tone_m:
                val = tone_m.group(1).lower()
                if val in {'formal', 'casual', 'transactional', 'notification', 'alert'}:
                    tone_map[str(row['title']).upper()] = val

    # "Name <email>" 형태에서 이메일만 소문자로 뽑는다
    def _extract_sender_email(raw):
        m = re.search(r'<([^>]+)>', raw)
        return m.group(1).lower() if m else raw.strip().lower()

    # "2024년 1월 1일 (월) 오후 3:20" 형식의 한글 날짜를 "YYYY-MM-DD HH:MM" 문자열로 변환한다
    def _parse_korean_datetime(text):
        m = re.search(r'(\d{4})년 (\d{1,2})월 (\d{1,2})일[^(]*\([^)]+\)\s*(오전|오후)\s*(\d{1,2}):(\d{2})', text)
        if not m:
            return None
        year, month, day, ampm, hour, minute = m.groups()
        hour = int(hour)
        if ampm == '오후' and hour != 12:
            hour += 12
        elif ampm == '오전' and hour == 12:
            hour = 0
        return f"{year}-{int(month):02d}-{int(day):02d} {hour:02d}:{minute}"

    from util.extract_statics import _is_friendly_tone_with_llm

    # 1pass: 전체 메일 파싱 + 발신자/날짜 기준 lookup 딕셔너리 빌드
    mail_data = []
    mail_lookup = {}  # (sender_email, 'YYYY-MM-DD HH:MM') -> (mail_id, mail_date)
    seen_ids = set()

    for _, row in df.iterrows():
        text = str(row.get('text', ''))

        id_match = re.search(r'^\[ID\]\s*(.+)$', text, re.MULTILINE)
        mail_id = id_match.group(1).strip() if id_match else None
        if not mail_id or mail_id in seen_ids:
            continue
        seen_ids.add(mail_id)

        date_match = re.search(r'^\[날짜\]\s*(.+)$', text, re.MULTILINE)
        mail_date = date_match.group(1).strip() if date_match else None

        # mail.mail_folder_name은 NOT NULL이며 mail_folder에 대한 FK이므로, 파싱 실패 시에도 'UNKNOWN'으로 대체
        folder_match = re.search(r'\[폴더 정보\]\s*(.+)', text)
        folder_raw = folder_match.group(1).strip() if folder_match else None
        mail_folder_name = folder_raw if (folder_raw and folder_raw != '없음') else 'UNKNOWN'

        sender_match = re.search(r'^\[발신인\]\s*(.+)$', text, re.MULTILINE)
        sender = sender_match.group(1).strip() if sender_match else None

        receiver_match = re.search(r'^\[수신인\]\s*(.+)$', text, re.MULTILINE)
        receiver = receiver_match.group(1).strip() if receiver_match else None

        direction_match = re.search(r'^\[구분\]\s*(.+)$', text, re.MULTILINE)
        direction_raw = direction_match.group(1).strip() if direction_match else None
        direction = 'sent' if direction_raw == '발신' else ('received' if direction_raw == '수신' else None)

        subject_match = re.search(r'^\[제목\]\s*(.+)$', text, re.MULTILINE)
        subject = subject_match.group(1).strip() if subject_match else ''

        body_match = re.search(r'\[메일 본문\]\s*\n(.*?)(?:\n\[|\n=+|\Z)', text, re.DOTALL)
        body = body_match.group(1).strip() if body_match else ''

        is_reply = bool(re.match(r'Re:\s*', subject, re.IGNORECASE))
        kg_tone = tone_map.get(mail_id.upper())
        llm_tone = 'friendly' if _is_friendly_tone_with_llm(body) else 'not_friendly'

        if sender and mail_date:
            key = (_extract_sender_email(sender), mail_date[:16])
            mail_lookup[key] = (mail_id, mail_date)

        mail_data.append({
            'mail_id': mail_id,
            'mail_folder_name': mail_folder_name,
            'mail_date': mail_date,
            'sender': sender,
            'receiver': receiver,
            'direction': direction,
            'is_reply': is_reply,
            'kg_tone': kg_tone,
            'llm_tone': llm_tone,
            'body': body,
        })

    # 2pass: 답장 메일의 reply_to_mail_id, reply_elapsed_hours 계산 후 DB INSERT
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        insert_sql = """
            INSERT INTO mail (
                mail_id, user_mail_account_id, index_date, mail_folder_name, mail_date,
                sender, receiver, direction, kg_tone, llm_tone,
                is_reply, reply_to_mail_id, reply_elapsed_hours
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                mail_folder_name = VALUES(mail_folder_name), mail_date = VALUES(mail_date),
                sender = VALUES(sender), receiver = VALUES(receiver), direction = VALUES(direction),
                kg_tone = VALUES(kg_tone), llm_tone = VALUES(llm_tone),
                is_reply = VALUES(is_reply),
                reply_to_mail_id = VALUES(reply_to_mail_id), reply_elapsed_hours = VALUES(reply_elapsed_hours)
        """
        count = 0
        for mail in mail_data:
            reply_to_mail_id = None
            reply_elapsed_hours = None

            if mail['is_reply'] and mail['body']:
                quoted_m = re.search(
                    r'(\d{4}년 \d{1,2}월 \d{1,2}일[^,]+),\s*(.+?)님이 작성:',
                    mail['body']
                )
                if quoted_m:
                    orig_dt_str = _parse_korean_datetime(quoted_m.group(1))
                    orig_sender_email = _extract_sender_email(quoted_m.group(2).strip())

                    if orig_dt_str:
                        match = mail_lookup.get((orig_sender_email, orig_dt_str))
                        if match:
                            reply_to_mail_id = match[0]
                            try:
                                orig_dt = datetime.datetime.strptime(match[1][:16], '%Y-%m-%d %H:%M')
                                reply_dt = datetime.datetime.strptime(mail['mail_date'][:16], '%Y-%m-%d %H:%M')
                                reply_elapsed_hours = round((reply_dt - orig_dt).total_seconds() / 3600, 2)
                            except Exception:
                                pass

            # print(f"[DEBUG] receiver (len={len(mail['receiver'] or '')}) = {mail['receiver']}")
            cursor.execute(insert_sql, (
                mail['mail_id'], user_mail_account_id, update_date, mail['mail_folder_name'],
                mail['mail_date'], mail['sender'], mail['receiver'], mail['direction'],
                mail['kg_tone'], mail['llm_tone'], mail['is_reply'], reply_to_mail_id, reply_elapsed_hours
            ))
            count += 1

        conn.commit()
        print(f"[DB] mail 테이블 저장 완료: {count}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_mail_to_db 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()
    