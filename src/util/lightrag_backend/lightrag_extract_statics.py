# src/util/lightrag_backend/lightrag_extract_statics.py

# LightRAG용 메일 통계 집계 모듈. 
# mail_latest.txt를 파싱해 연락처별 발신/수신/친밀 메일 수와 메일별 LLM 키워드를 뽑아 각각 mail_contact_stats.json, mail_keyword_stats.json으로 저장한다.
# 어조(friendly) 판정과 처리된 메일 id는 캐시/기록해두고 append 모드에서 재사용해 중복 계산을 막는다.

# Aggregates mail statistics for LightRAG. 
# Parses mail_latest.txt to compute per-contact sent/received/friendly-tone counts and per-mail LLM keywords, saving them to mail_contact_stats.json and mail_keyword_stats.json. 
# Tone judgments and processed mail ids are cached so append mode skips rework.

import os
import json
import re

from util.jobs.job_store import *  # extract_statics.py와 동일하게 job 로그 헬퍼 사용 가능하도록
from util.lightrag_backend.lightrag_mail_parser import parse_mail_blocks, extract_email
from util.extract_statics import extract_keywords_with_llm, _is_friendly_tone_with_llm

# mail_id별 "friendly"/"not_friendly" 판정을 캐시하는 파일
_TONE_CACHE_FILENAME = "lightrag_tone_cache.json"


# 어조 판정 캐시 파일의 전체 경로를 반환한다
def _tone_cache_path(paths) -> str:
    return os.path.join(paths.MAIL_STATICS_PATH, _TONE_CACHE_FILENAME)


# mail_id별 어조 판정 캐시(JSON)를 읽어 dict로 반환한다 (없으면 빈 dict)
def load_tone_cache(paths) -> dict:
    path = _tone_cache_path(paths)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 어조 판정 캐시 dict를 JSON 파일로 저장한다
def _save_tone_cache(paths, cache: dict):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(_tone_cache_path(paths), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# mail_latest.txt를 파싱해 연락처별 발신/수신/친밀 메일 수를 집계해 mail_contact_stats.json으로 저장한다 (rewrite/append)
def _save_mail_contact_stats_lightrag(paths, mode: str = "rewrite"):
    if mode == "append" and os.path.exists(paths.MAIL_CONTACTS_PATH):
        with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
            stats = json.load(f)
    else:
        stats = {}

    records = parse_mail_blocks(paths)
    if not records:
        print(f"[STATS][lightrag] mail_latest.txt 없음/비어있음 → contacts 생성 건너뜀")
        return

    my_email = (paths.USER_ID or "").lower()
    tone_cache = load_tone_cache(paths)

    deltas: dict[str, dict] = {}

    for r in records:
        sender_email = extract_email(r["sender"])
        receiver_email = extract_email(r["receiver"])

        # "구분" 필드(발신/수신, imap 수집 시점에 계정 주인 기준으로 이미 붙어있음)를 우선
        # 쓰고, 없으면 발신인 이메일이 본인 계정인지로 판별한다.
        if r["direction_raw"] == "발신":
            is_sent = True
        elif r["direction_raw"] == "수신":
            is_sent = False
        else:
            is_sent = (sender_email == my_email)

        if is_sent:
            contact_email, contact_raw, stat_key = receiver_email, r["receiver"], "sent"
        else:
            contact_email, contact_raw, stat_key = sender_email, r["sender"], "received"

        if not contact_email or contact_email == my_email:
            continue

        name_m = re.match(r'^(.*?)\s*<', contact_raw.strip()) if contact_raw else None
        name = name_m.group(1).strip().strip('"') if name_m else ""

        entry = deltas.setdefault(contact_email, {"name": "", "sent": 0, "received": 0, "friendly_mail": 0})
        if name and not entry["name"]:
            entry["name"] = name
        entry[stat_key] += 1

        mail_id = r["id"]
        cached = tone_cache.get(mail_id)
        if cached is None:
            is_friendly = _is_friendly_tone_with_llm(r["body"])
            tone_cache[mail_id] = "friendly" if is_friendly else "not_friendly"
        else:
            is_friendly = (cached == "friendly")

        if is_friendly:
            entry["friendly_mail"] += 1

    for email, delta in deltas.items():
        if mode == "append" and email in stats:
            prev = stats[email]
            stats[email] = {
                "name":          prev.get("name", "") or delta["name"],
                "sent":          prev.get("sent", 0)          + delta["sent"],
                "received":      prev.get("received", 0)      + delta["received"],
                "friendly_mail": prev.get("friendly_mail", 0) + delta["friendly_mail"],
            }
        else:
            stats[email] = delta

    with open(paths.MAIL_CONTACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    _save_tone_cache(paths, tone_cache)

    print(f"[STATS][lightrag] ({mode}) 계정 {len(stats)}개 집계 완료 → {paths.MAIL_CONTACTS_PATH}")


# mail_latest.txt의 메일마다 LLM 키워드를 뽑아 키워드별 언급 수·사람·날짜 맵을 mail_keyword_stats.json으로 저장한다
def _save_mail_keyword_stats_lightrag(paths, mode: str = "rewrite"):
    if mode == "append" and os.path.exists(paths.MAIL_KEYWORDS_PATH):
        with open(paths.MAIL_KEYWORDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            keyword_stats = data.get("keywords", {})
            keyword_person_date_map = data.get("keyword_person_date_map", {})
            processed_ids = set(data.get("processed_mail_ids", []))
    else:
        keyword_stats = {}
        keyword_person_date_map = {}
        processed_ids = set()

    records = parse_mail_blocks(paths)
    if not records:
        print(f"[KEYWORD][lightrag] mail_latest.txt 없음/비어있음 → 키워드 추출 건너뜀")
        return

    my_email = (paths.USER_ID or "").lower()

    for r in records:
        mail_id = r["id"]
        if mode == "append" and mail_id in processed_ids:
            continue

        mail_date = (r["date"] or "")[:10]  # YYYY-MM-DD
        sender_email = extract_email(r["sender"])
        receiver_email = extract_email(r["receiver"])
        person = receiver_email if sender_email == my_email else sender_email

        body = r["body"]
        if not body or not mail_date or not person:
            continue

        keywords = extract_keywords_with_llm(body)

        for kw in keywords:
            keyword_stats[kw] = keyword_stats.get(kw, 0) + 1
            keyword_person_date_map.setdefault(kw, {}).setdefault(person, {})
            keyword_person_date_map[kw][person][mail_date] = \
                keyword_person_date_map[kw][person].get(mail_date, 0) + 1

        if mail_id:
            processed_ids.add(mail_id)

    result = {
        "keywords": keyword_stats,
        "keyword_person_date_map": keyword_person_date_map,
        "processed_mail_ids": list(processed_ids),
    }

    with open(paths.MAIL_KEYWORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[KEYWORD][lightrag] ({mode}) 키워드 {len(keyword_stats)}개 저장 완료 → {paths.MAIL_KEYWORDS_PATH}")


# 키워드 통계 → 연락처 통계 순으로 실행하는 LightRAG용 메일 통계 파이프라인
def _extract_statics_pipeline_lightrag(paths, mode: str = "rewrite"):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    _save_mail_keyword_stats_lightrag(paths, mode)
    _save_mail_contact_stats_lightrag(paths, mode)
