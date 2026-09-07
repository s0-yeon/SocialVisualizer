# src/util/lightrag_backend/lightrag_db_writer.py

# LightRAG 인덱싱 결과를 MySQL에 반영하는 모듈. mail_latest.txt를 파싱해 폴더별 메일 수를
# mail_folder 테이블에, 메일 개별 레코드(방향/어조/답장 관계 포함)를 mail 테이블에 저장한다.
# GraphRAG는 knowledge graph에서 뽑은 kg_tone을 쓰지만 LightRAG 경로엔 그 값이 없어 항상 None으로 둔다.

# Persists LightRAG indexing results into MySQL. Parses mail_latest.txt to save
# per-folder mail counts into mail_folder, and per-mail records (direction, tone,
# reply relationship) into the mail table. kg_tone is always None here since
# LightRAG has no equivalent to GraphRAG's knowledge-graph-derived tone.

import os
import re
import datetime

from config.db import get_db_connection
from util.database.db_writer import get_latest_mail_account
from util.lightrag_backend.lightrag_mail_parser import parse_mail_blocks, extract_email
from util.lightrag_backend.lightrag_extract_statics import load_tone_cache
from util.extract_statics import _is_friendly_tone_with_llm


# mail_latest.txt를 파싱해 폴더별 메일 수를 집계해 mail_folder 테이블에 저장한다
def save_mail_folder_to_db_lightrag(paths, update_date=None):
    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)
        if not latest_account:
            print(f"[WARN][lightrag] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
            return
        user_mail_account_id = latest_account["user_mail_account_id"]
        update_date = latest_account["index_date"]
    else:
        user_mail_account_id = paths.USER_ID

    records = parse_mail_blocks(paths)
    if not records:
        print(f"[WARN][lightrag] mail_latest.txt 없음/비어있음 → mail_folder 저장 건너뜀")
        return

    folder_counts: dict[str, int] = {}
    for r in records:
        # save_mail_to_db_lightrag와 동일한 폴백('UNKNOWN')을 써야 mail.mail_folder_name FK가 항상 만족됨
        mail_folder_name = r["folder"] or "UNKNOWN"
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
        print(f"[DB][lightrag] mail_folder 테이블 저장 완료: {len(folder_counts)}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR][lightrag] save_mail_folder_to_db_lightrag 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


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


# mail_latest.txt를 파싱해 메일별 방향·어조·답장 관계를 계산해 mail 테이블에 저장한다 (kg_tone은 LightRAG에 없어 None)
def save_mail_to_db_lightrag(paths, update_date=None):
    if update_date is None:
        latest_account = get_latest_mail_account(paths.USER_ID)
        if not latest_account:
            print(f"[WARN][lightrag] mail_account 테이블에 해당 유저가 없습니다: {paths.USER_ID}")
            return
        user_mail_account_id = latest_account["user_mail_account_id"]
        update_date = latest_account["index_date"]
    else:
        user_mail_account_id = paths.USER_ID

    records = parse_mail_blocks(paths)
    if not records:
        print(f"[WARN][lightrag] mail_latest.txt 없음/비어있음 → mail 저장 건너뜀")
        return

    # _save_mail_contact_stats_lightrag가 이미 채워둔 어조 판정 캐시를 재사용해서 같은
    # 본문에 LLM을 두 번 호출하지 않는다 (캐시에 없으면 그 자리에서 계산해 폴백).
    tone_cache = load_tone_cache(paths)

    # 1pass: 전체 메일 파싱 + 발신자/날짜 기준 lookup 딕셔너리 빌드
    mail_data = []
    mail_lookup = {}  # (sender_email, 'YYYY-MM-DD HH:MM') -> (mail_id, mail_date)

    for r in records:
        mail_id = r["id"]
        mail_date = r["date"]
        sender = r["sender"]
        receiver = r["receiver"]
        mail_folder_name = r["folder"] or "UNKNOWN"
        subject = r["subject"]
        body = r["body"]

        direction = 'sent' if r["direction_raw"] == '발신' else ('received' if r["direction_raw"] == '수신' else None)
        is_reply = bool(re.match(r'Re:\s*', subject, re.IGNORECASE))

        cached = tone_cache.get(mail_id)
        if cached is None:
            llm_tone = 'friendly' if _is_friendly_tone_with_llm(body) else 'not_friendly'
        else:
            llm_tone = cached

        sender_email = extract_email(sender)
        if sender_email and mail_date:
            key = (sender_email, mail_date[:16])
            mail_lookup[key] = (mail_id, mail_date)

        mail_data.append({
            'mail_id': mail_id,
            'mail_folder_name': mail_folder_name,
            'mail_date': mail_date,
            'sender': sender,
            'receiver': receiver,
            'direction': direction,
            'is_reply': is_reply,
            'kg_tone': None,
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
                    orig_sender_email = extract_email(quoted_m.group(2).strip())

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

            cursor.execute(insert_sql, (
                mail['mail_id'], user_mail_account_id, update_date, mail['mail_folder_name'],
                mail['mail_date'], mail['sender'], mail['receiver'], mail['direction'],
                mail['kg_tone'], mail['llm_tone'], mail['is_reply'], reply_to_mail_id, reply_elapsed_hours
            ))
            count += 1

        conn.commit()
        print(f"[DB][lightrag] mail 테이블 저장 완료: {count}건")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR][lightrag] save_mail_to_db_lightrag 실패: {e}")
        raise
    finally:
        cursor.close()
        conn.close()
