# 메일 본문에서 LLM으로 키워드·어조·관계 프로필을 추출해 연락처별 통계를 계산하고 파이프라인으로 저장한다.

# Extracts keywords, tone, and relationship profiles from mail bodies via LLM, then computes and saves per-contact statistics through a background pipeline.

import os
import re
import json
import time
import threading
import traceback
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
# Job 이용 공통함수 import
from util.jobs.job_store import *

# .env 로드
load_dotenv("src/parquet/.env")

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("SUB_TASK_API_BASE") or None,
)

# 시작 시각과 성능 카운터를 담은 타이머 dict를 만든다
def start_timer():
    return {
        "started_at": datetime.now(),
        "start_perf": time.perf_counter()
    }

# 타이머를 종료해 시작/종료 시각과 경과 초를 담은 dict를 반환한다
def end_timer(timer):
    ended_at = datetime.now().replace(microsecond=0)
    elapsed_sec = time.perf_counter() - timer["start_perf"]

    return {
        "started_at": timer["started_at"],
        "ended_at": ended_at,
        "elapsed_sec": round(elapsed_sec, 2)
    }

# 초 단위 시간을 "HH:MM:SS.ss" 문자열로 변환한다
def format_elapsed_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60  # 소수 포함

    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"

# "이름 <메일>" 형식에서 (이름, 소문자 메일주소) 튜플을 분리해 반환한다
def _parse_contact(raw: str) -> tuple[str, str]:
        m = re.search(r"^(.*?)\s*<([^>]+)>", raw.strip())
        if m:
            name  = m.group(1).strip().strip('"')
            email = m.group(2).strip().lower()
        else:
            name  = ""
            email = raw.strip().lower()
        return name, email

# 메일 블록에서 특정 라벨의 필드 값을 추출한다 (multiline이면 블록 단위로 추출)
def _extract_field(block: str, label: str, multiline: bool = False) -> str:
    if multiline:
        m = re.search(
            rf"\[{re.escape(label)}\]\s*\n(.*?)(?:\n=+|\Z)",
            block,
            re.DOTALL
        )
    else:
        m = re.search(
            rf"^{re.escape(label)}:\s*(.+)$",
            block,
            re.MULTILINE
        )
    return m.group(1).strip() if m else ""

# 메일 본문을 LLM에 넘겨 친밀한 어조인지(True/False) 판별한다
def _is_friendly_tone_with_llm(body: str) -> bool:

    if not body.strip():
        return False
    
    body = body[:1500]

    prompt = f"""
    다음 메일 본문이 '친밀한 어조'인지 판별하라.

    판별 기준:
    - '친밀한 어조'란, 개인적인 친분이나 가까운 관계가 느껴지는 말투를 뜻한다.
    - 사적인 안부, 다정한 표현, 편한 말투, 친한 사이에서 쓰는 표현이 중심이면 friendly다.
    - 단순히 예의 바르거나 친절한 것만으로는 friendly가 아니다.
    - 업무 메일, 학교 메일, 공지, 안내, 광고, 자동 발송, 고객 응대, 형식적인 감사 표현은 not_friendly다.
    - "감사합니다", "좋은 하루 되세요", "잘 부탁드립니다" 같은 일반적인 공손 표현만 있으면 not_friendly다.
    - 메일 전체 분위기가 공식적이거나 정보 전달 중심이면 not_friendly다.

    반드시 아래 둘 중 하나만 정확히 출력하라.
    friendly
    not_friendly

    메일 본문:
    {body}
    """.strip()

    result = client.chat.completions.create(
        model=os.getenv("SUB_TASK_CHAT_MODEL"),
        messages=[
            {
                "role": "system",
                "content": "당신은 메일 본문의 어조를 분류하는 AI입니다. 반드시 friendly 또는 not_friendly 둘 중 하나만 출력하세요."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    answer = result.choices[0].message.content.strip().lower()
    return answer == "friendly"

# 메일/대화 본문에서 LLM으로 핵심 키워드(한국어 명사)를 최대 몇 개 뽑아 리스트로 반환한다
def extract_keywords_with_llm(body: str) -> list[str]:
    body = body.strip()
    if not body:
        return []

    body = body[:2000]

    prompt = f"""
다음 메일 본문에서 핵심 키워드를 최대 3개만 추출하세요.

조건:
- 한국어 명사 위주
- 중복 금지
- 너무 일반적인 단어(예: 내용, 경우, 사람) 제외
- JSON 배열로만 출력
- 내용에서 핵심적인 단어만
- 예시: ["보안", "계정", "액세스"]

메일 본문:
{body}
"""

    try:
        response = client.chat.completions.create(
            model=os.getenv("SUB_TASK_CHAT_MODEL"),
            messages=[
                {"role": "system", "content": "당신은 텍스트에서 핵심 키워드를 추출하는 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        result_text = response.choices[0].message.content.strip()

        if result_text.startswith("```"):
            result_text = re.sub(r"^```(?:json)?\s*", "", result_text)
            result_text = re.sub(r"\s*```$", "", result_text)

        keywords = json.loads(result_text)

        if not isinstance(keywords, list):
            print("[LLM DEBUG] list가 아님")
            return []

        cleaned = []
        for kw in keywords:
            if isinstance(kw, str):
                kw = kw.strip()
                if kw and kw not in cleaned:
                    cleaned.append(kw)

        return cleaned[:5]

    except Exception as e:
        print(f"[LLM ERROR] 키워드 추출 실패: {e}")
        return []


# parquet에서 연락처별 발신/수신/친밀 메일 수와 이름을 집계해 mail_contact_stats.json으로 저장한다 (rewrite/append)
def _save_mail_contact_stats(paths, mode: str = "rewrite"):
    import pandas as pd

    if not os.path.exists(paths.ENTITIES_PATH) or not os.path.exists(paths.RELATIONSHIPS_PATH):
        print(f"[STATS] entities/relationships parquet 없음 → contacts 생성 건너뜀")
        return

    if mode == "append" and os.path.exists(paths.MAIL_CONTACTS_PATH):
        with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
            stats = json.load(f)
    else:
        stats = {}

    entities_df = pd.read_parquet(paths.ENTITIES_PATH)
    rel_df      = pd.read_parquet(paths.RELATIONSHIPS_PATH)

    type_col = 'type' if 'type' in entities_df.columns else 'entity_type'
    emails   = entities_df[entities_df[type_col].str.upper() == 'EMAIL']

    # relationships.parquet 기준: 실제 sent_by/sent_to가 있는 연락처만
    # description은 관계 타입명이 아니라 한국어 문장이므로("이메일의 발신자는 ~이다." 등),
    # 타입은 별도 컬럼이 아니라 문장 안의 "발신자"/"수신자"/"참조" 패턴으로 구분해야 함
    is_cc = rel_df['description'].str.contains('참조', na=False)
    sent_by_count = rel_df[rel_df['description'].str.contains('발신자', na=False) & ~is_cc].groupby('target').size()
    sent_to_count = rel_df[rel_df['description'].str.contains('수신자', na=False) & ~is_cc].groupby('target').size()

    all_contacts = set(sent_by_count.index) | set(sent_to_count.index)
    all_contacts.discard(paths.USER_ID.upper())   # 본인 제외

    # 이름 맵: entities.parquet Person 엔티티에서 파싱 (대문자 키)
    name_map = {}
    for _, row in entities_df[entities_df[type_col].str.upper() == 'PERSON'].iterrows():
        desc = str(row.get('description', ''))
        m = re.search(r'Name:\s*(.+)', desc)
        name = m.group(1).strip() if m else ''
        if name.lower() == 'none':
            name = ''
        elif ',' in name:
            # GraphRAG가 여러 From 이름을 합쳐 저장한 경우 첫 번째 항목만 사용
            name = name.split(',')[0].strip()
        name_map[str(row['title']).upper()] = name

    # Tone: casual인 메일의 연락처별 친밀 카운트
    casual_ids = {
        str(row['title']) for _, row in emails.iterrows()
        if 'Tone: casual' in str(row.get('description', ''))
    }
    friendly_count = rel_df[rel_df['source'].isin(casual_ids)].groupby('target').size()

    for contact in all_contacts:
        email_lower = contact.lower()
        if mode == "append" and email_lower in stats:
            prev = stats[email_lower]
            stats[email_lower] = {
                "name":          name_map.get(contact.upper()) or prev.get("name", ""),
                "sent":          prev.get("sent", 0)          + int(sent_to_count.get(contact, 0)),
                "received":      prev.get("received", 0)      + int(sent_by_count.get(contact, 0)),
                "friendly_mail": prev.get("friendly_mail", 0) + int(friendly_count.get(contact, 0)),
            }
        else:
            stats[email_lower] = {
                "name":          name_map.get(contact.upper(), ""),
                "sent":          int(sent_to_count.get(contact, 0)),
                "received":      int(sent_by_count.get(contact, 0)),
                "friendly_mail": int(friendly_count.get(contact, 0)),
            }

    with open(paths.MAIL_CONTACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"[STATS] ({mode}) 계정 {len(stats)}개 집계 완료 → {paths.MAIL_CONTACTS_PATH}")

# text_units.parquet의 메일마다 LLM 키워드를 뽑아 키워드별 언급 수·사람·날짜 맵을 mail_keyword_stats.json으로 저장한다
def _save_mail_keyword_stats(paths, mode: str = "rewrite"):
    import pandas as pd, re
    # 기존 데이터 로드 (append 모드)
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

    text_units_df = pd.read_parquet(paths.RELATIONSHIPS_PATH.replace("relationships.parquet", "text_units.parquet"))

    for _, row in text_units_df.iterrows():
        text = str(row.get('text', ''))

        id_match = re.search(r'^\[ID\]\s*(.+)$', text, re.MULTILINE)
        mail_id = id_match.group(1).strip() if id_match else None

        if mode == "append" and mail_id in processed_ids:
            continue

        date_match = re.search(r'^\[날짜\]\s*(.+)$', text, re.MULTILINE)
        mail_date = date_match.group(1).strip()[:10] if date_match else None  # YYYY-MM-DD

        # "Name <email>" 형태에서 이메일만 뽑는다
        def parse_email(value):
            m = re.search(r'<(.+?)>', value)
            return m.group(1).strip() if m else value.strip()

        sender_match = re.search(r'^\[발신인\]\s*(.+)$', text, re.MULTILINE)
        sender = parse_email(sender_match.group(1)) if sender_match else None

        receiver_match = re.search(r'^\[수신인\]\s*(.+)$', text, re.MULTILINE)
        receiver = parse_email(receiver_match.group(1)) if receiver_match else None

        person = receiver if sender == paths.USER_ID else sender

        body_match = re.search(r'\[메일 본문\]\s*\n(.*?)(?:\n\[|\n=+|\Z)', text, re.DOTALL)
        body = body_match.group(1).strip() if body_match else ''

        if not body or not mail_date or not person:
            continue

        keywords = extract_keywords_with_llm(body)

        for kw in keywords:
            keyword_stats[kw] = keyword_stats.get(kw, 0) + 1
            if kw not in keyword_person_date_map:
                keyword_person_date_map[kw] = {}
            if person not in keyword_person_date_map[kw]:
                keyword_person_date_map[kw][person] = {}
            keyword_person_date_map[kw][person][mail_date] = \
                keyword_person_date_map[kw][person].get(mail_date, 0) + 1

        if mail_id:
            processed_ids.add(mail_id)

    result = {
        "keywords": keyword_stats,
        "keyword_person_date_map": keyword_person_date_map,
        "processed_mail_ids": list(processed_ids)
    }

    with open(paths.MAIL_KEYWORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[KEYWORD] ({mode}) 키워드 {len(keyword_stats)}개 저장 완료 → {paths.MAIL_KEYWORDS_PATH}")


# parquet에서 사람별 이름·소속·주제·메일 수를 모아 LLM으로 관계 프로필을 생성해 {이메일: {description, relation_label}}로 반환한다
def generate_person_descriptions(paths) -> dict:
    import pandas as pd

    if not os.path.exists(paths.ENTITIES_PATH) or not os.path.exists(paths.RELATIONSHIPS_PATH):
        print("[PROFILES] parquet 없음 → 프로필 생성 건너뜀")
        return {}

    entities_df = pd.read_parquet(paths.ENTITIES_PATH)
    rel_df      = pd.read_parquet(paths.RELATIONSHIPS_PATH)

    type_col = 'type' if 'type' in entities_df.columns else 'entity_type'

    # 주어진 엔티티 타입에 해당하는 title들의 집합을 반환한다
    def titles_of(etype: str) -> set:
        mask = entities_df[type_col].str.lower() == etype.lower()
        return set(entities_df.loc[mask, 'title'].astype(str))

    person_set = titles_of('person')
    topic_set  = titles_of('topic')
    org_set    = titles_of('organization')
    email_set  = titles_of('email')

    person_name_map   = {}
    topic_summary_map = {}
    org_name_map      = {}

    for _, row in entities_df.iterrows():
        etype = str(row.get(type_col, '')).lower()
        title = str(row.get('title', ''))
        desc  = str(row.get('description', ''))
        if etype == 'person':
            m = re.search(r'Name:\s*([^|]+)', desc)
            v = m.group(1).strip() if m else ''
            person_name_map[title] = '' if v.lower() == 'none' else v
        elif etype == 'topic':
            m = re.search(r'Summary:\s*(.+)', desc)
            topic_summary_map[title] = m.group(1).strip() if m else ''
        elif etype == 'organization':
            m = re.search(r'OrgName:\s*([^|]+)', desc)
            org_name_map[title] = m.group(1).strip() if m else title

    # mail_contact_stats.json 기준으로 대상 연락처 한정
    import json as _json
    contact_emails: set = set()
    if os.path.exists(paths.MAIL_CONTACTS_PATH):
        with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as _f:
            contact_emails = set(_json.load(_f).keys())  # lowercase

    email_to_topics:  dict[str, list] = {}
    person_to_emails: dict[str, set]  = {p: set() for p in person_set}
    person_to_orgs:   dict[str, set]  = {p: set() for p in person_set}
    person_counts:    dict[str, dict] = {
        p: {'sent': 0, 'received': 0, 'cc': 0} for p in person_set
    }

    for _, row in rel_df.iterrows():
        src   = str(row.get('source', ''))
        tgt   = str(row.get('target', ''))
        # description 컬럼이 관계 타입 (SENT_BY, SENT_TO, CC_TO, ...)
        rtype = str(row.get('description', '')).upper()

        if src in email_set and tgt in topic_set:
            email_to_topics.setdefault(src, []).append(tgt)

        if src in email_set and tgt in person_set:
            person_to_emails[tgt].add(src)
            if   rtype == 'SENT_BY':  person_counts[tgt]['sent']     += 1
            elif rtype == 'SENT_TO':  person_counts[tgt]['received'] += 1
            elif rtype == 'CC_TO':    person_counts[tgt]['cc']       += 1
            else:                     person_counts[tgt]['received'] += 1

        if src in person_set and tgt in org_set:
            person_to_orgs[src].add(org_name_map.get(tgt, tgt))

    from concurrent.futures import ThreadPoolExecutor, as_completed

    descriptions: dict[str, str] = {}
    my_email = paths.USER_ID.lower()
    my_orgs = person_to_orgs.get(my_email, set())

    # 프롬프트 데이터 수집
    person_prompts = []
    for person_email in person_set:
        if person_email.lower() == my_email:
            continue
        if person_email.lower() not in contact_emails:
            continue

        counts      = person_counts[person_email]
        total_mails = counts['sent'] + counts['received'] + counts['cc']

        name = person_name_map.get(person_email, '')
        person_orgs = person_to_orgs[person_email]
        orgs = list(person_orgs)
        same_org = bool(person_orgs & my_orgs)

        topic_counter: dict[str, int] = {}
        for eid in person_to_emails[person_email]:
            for t in email_to_topics.get(eid, []):
                topic_counter[t] = topic_counter.get(t, 0) + 1

        top_topics  = sorted(topic_counter, key=topic_counter.get, reverse=True)[:5]
        topics_text = '\n'.join(
            f"- {t}: {topic_summary_map.get(t, t)}" for t in top_topics
        ) or '(주제 정보 없음)'

        prompt = f"""다음은 이메일 분석 데이터입니다.

나의 이메일: {my_email}
상대방 이메일: {person_email}
이름: {name if name else '알 수 없음'}
소속 조직: {', '.join(orgs) if orgs else '없음'}
나와 같은 조직 소속 여부: {'예' if same_org else '아니오'}
주고받은 메일 수: {total_mails}건 (보낸 {counts['sent']}건 / 받은 {counts['received']}건)
주요 대화 주제:
{topics_text}

아래 형식으로만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.
한국어(한글)만 사용하고, 영어 단어나 한자(중국어 문자)를 절대 섞지 마세요. 문장은 존댓말로 통일하고 반말을 섞지 마세요.
"관계:" 줄은 반드시 대괄호 태그 [관계: <카테고리>]로 시작해야 합니다. <카테고리>는 가족, 연인, 친구, 동료, 사제, 지인, 기업 중 하나만 사용하세요. 대괄호를 빼먹거나 다른 단어를 쓰면 안 됩니다.

카테고리 판단 기준(위에서부터 순서대로 확인):
1. 상대방이 실제 개인이 아니라 기업/서비스/뉴스레터/알림 등 자동발신 계정으로 보이면(예: 이름이 회사·서비스·팀 명의이거나 no-reply류 발신) 무조건 "기업".
2. "나와 같은 조직 소속 여부"가 "예"이고 다른 뚜렷한 근거가 없으면 "동료".
3. 메일을 몇 건 주고받지 않았거나 업무/공지성 내용뿐이면 "지인".
4. 가족, 연인, 사제는 이름/호칭이나 대화 주제에서 그 관계가 명확히 드러날 때만 사용하세요. 근거가 약하면 절대 추측하지 말고 "지인" 또는 "동료"를 쓰세요.

형식:
관계: [관계: <카테고리>] <이 사람과 나의 관계를 한 문장으로>
자주 주고 받은 내용: <주로 어떤 내용으로 메일을 주고받는지 한 문장으로>

예시 1 (동료 관계인 사람):
관계: [관계: 동료] 같은 팀에서 프로젝트 진행 상황을 자주 공유하는 사이
자주 주고 받은 내용: 주간 업무 보고와 일정 조율

예시 2 (기업/서비스 발신자):
관계: [관계: 기업] Google 계정 관련 알림을 보내는 서비스
자주 주고 받은 내용: 보안 알림 및 계정 안내""".strip()

        person_prompts.append((person_email, name, prompt))

    # 사람 한 명의 프롬프트를 LLM에 넘겨 (이메일, description, relation_label)을 반환한다
    # LLM 출력에서 관계/내용을 파싱해 (relationship, content, relation_label)로 반환한다
    def _parse_relation_output(llm_output):
        rel_m     = re.search(r'관계:\s*(.+)',            llm_output)
        content_m = re.search(r'자주 주고 받은 내용:\s*(.+)', llm_output)
        relationship = rel_m.group(1).strip()     if rel_m     else ''
        content      = content_m.group(1).strip() if content_m else ''

        # [관계: 카테고리] 태그 파싱  person.relation_label 컬럼으로 분리 저장한다
        tag_m = re.match(r'^\[관계:\s*([^\]]+?)\]\s*', relationship)
        relation_label = tag_m.group(1).strip() if tag_m else None
        if tag_m:
            relationship = relationship[tag_m.end():].strip()
        return relationship, content, relation_label

    def _call_llm(person_email, name, prompt):
        last_parsed = None
        feedback = None
        for attempt in range(1, 4):
            try:
                user_content = prompt
                if feedback:
                    user_content += f"\n\n[이전 시도 오류] 방금 답변에 다음 문제가 있었습니다: {feedback}. 반드시 한국어(한글)만 사용해서 다시 작성하세요."
                result = client.chat.completions.create(
                    model=os.getenv("SUB_TASK_CHAT_MODEL"),
                    messages=[
                        {
                            "role": "system",
                            "content": "당신은 이메일 데이터를 분석해 인물 관계를 한국어로 간결하게 요약하는 AI입니다. 반드시 한국어(한글)만 사용하고, 영어 단어나 한자(중국어 문자)를 절대 섞지 않으며, 존댓말로 통일하고 반말을 섞지 않습니다."
                        },
                        {"role": "user", "content": user_content}
                    ],
                    temperature=min(0.3 + 0.2 * (attempt - 1), 0.7)
                )
                llm_output = result.choices[0].message.content.strip()
                relationship, content, relation_label = _parse_relation_output(llm_output)
                last_parsed = (relationship, content, relation_label)

                issue = _has_disallowed_foreign_text(relationship) or _has_disallowed_foreign_text(content)
                if issue is None:
                    description = (
                        f"이름: {name if name else '알 수 없음'}\n"
                        f"관계: {relationship}\n"
                        f"자주 주고 받은 내용: {content}"
                    )
                    return person_email, description, relation_label
                feedback = issue
                print(f"[PROFILES] 형식 검증 실패 ({person_email}, {attempt}/3번째 시도): {llm_output!r} ({issue})")
            except Exception as e:
                print(f"[PROFILES] LLM 호출 실패 ({person_email}, {attempt}/3번째 시도): {e}")

        # 3번 다 검증에 실패해도 완전히 비우는 것보다는 마지막 결과라도 반환한다.
        if last_parsed:
            relationship, content, relation_label = last_parsed
            description = (
                f"이름: {name if name else '알 수 없음'}\n"
                f"관계: {relationship}\n"
                f"자주 주고 받은 내용: {content}"
            )
            return person_email, description, relation_label
        return person_email, None, None

    with ThreadPoolExecutor(max_workers=min(len(person_prompts), 15)) as executor:
        futures = {executor.submit(_call_llm, email, name, prompt): email
                   for email, name, prompt in person_prompts}
        for future in as_completed(futures):
            person_email, desc, relation_label = future.result()
            if desc:
                descriptions[person_email] = {
                    "description": desc,
                    "relation_label": relation_label,
                }
                # print(f"[PROFILES] 완료: {person_email}")

    print(f"[PROFILES] 총 {len(descriptions)}명 프로필 생성 완료")
    return descriptions


# 텍스트에 부적절한 한자/영어가 섞였는지 검사한다. 영어는 이름/도메인/아이디처럼 보이는 것만
# 허용(도메인, 대문자가 하나라도 섞인 단어 — Google, iPhone, eBay 등, 또는 csi10186처럼 숫자가
# 섞인 식별자) 하고 "serta"처럼 순수 소문자로만 된 일반 단어가 섞이면 차단한다. 한자는 무조건 차단.
# 문제없으면 None, 있으면 사유 문자열을 반환한다.
_DOMAIN_RE = re.compile(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.(?:com|net|org|co\.kr|kr|io|ai)', re.IGNORECASE)
_LATIN_WORD_RE = re.compile(r'[A-Za-z][A-Za-z0-9]*')
_HAN_CHAR_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')
# 한국어 존댓말 평서형은 대부분 "~습니다/~입니다/~합니다/~갑니다"처럼 "니다"로 끝난다.
# 어간을 일일이 나열하는 대신 이 공통 어미로 판별한다.
_POLITE_ENDING_RE = re.compile(r'니다\.?\s*$')


def _has_disallowed_foreign_text(text: str):
    if not text:
        return None
    text_wo_domains = _DOMAIN_RE.sub('', text)
    for word in _LATIN_WORD_RE.findall(text_wo_domains):
        if any(ch.isupper() for ch in word) or any(ch.isdigit() for ch in word):
            continue
        return f"허용되지 않는 영어 단어 포함: {word!r}"
    if _HAN_CHAR_RE.search(text):
        return "한자(중국어 문자) 포함"
    return None


def _is_clean_korean_polite_sentence(text: str) -> bool:
    if not text:
        return False
    if _has_disallowed_foreign_text(text) is not None:
        return False
    if not _POLITE_ENDING_RE.search(text):
        return False
    return True


# generate_person_descriptions() 결과({이메일: {description, relation_label}})를 2차 LLM 호출로 한 문장 소개(short_bio)로 압축해 {이메일: 문장}으로 반환한다
def generate_person_short_bios(descriptions: dict) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    targets = [
        (email, info.get("description") or "", info.get("relation_label") or "지인")
        for email, info in descriptions.items()
        if info.get("description")
    ]
    if not targets:
        return {}

    # 완성된 description + relation_label로 한 문장 소개 프롬프트를 만든다
    def _build_prompt(description, relation_label):
        return f"""다음은 이미 생성된 인물 설명입니다.

관계 카테고리: {relation_label}
설명:
{description}

위 내용을 바탕으로, 이 사람을 다른 사람에게 소개하듯 자연스러운 한국어 한 문장으로 요약하세요.
- 문장은 반드시 "~습니다." 또는 "~입니다."로 끝나야 합니다. 반말(~야, ~해, ~지 등)은 절대 쓰지 마세요.
- 한국어(한글)만 사용하세요. 영어 단어나 한자(중국어 문자)를 절대 섞지 마세요.
- 성격이나 관계의 특징이 드러나는 짧은 소개 문장으로 쓰세요.
- 예시: "꼼꼼하고 계획적인 성격의 친구입니다.", "함께 프로젝트를 진행하는 믿음직한 동료입니다."
- 다른 설명, 따옴표, 접두어 없이 문장 하나만 출력하세요.""".strip()

    def _call_llm(email, description, relation_label):
        last_bio = None
        feedback = None
        for attempt in range(1, 4):
            try:
                user_content = _build_prompt(description, relation_label)
                if feedback:
                    user_content += f"\n\n[이전 시도 오류] 방금 답변에 다음 문제가 있었습니다: {feedback}. 반드시 한국어(한글)만 사용하고 \"~습니다.\"/\"~입니다.\"로 끝나도록 다시 작성하세요."
                result = client.chat.completions.create(
                    model=os.getenv("SUB_TASK_CHAT_MODEL"),
                    messages=[
                        {
                            "role": "system",
                            "content": "당신은 인물 설명을 한 문장의 자연스러운 한국어 소개글로 압축하는 AI입니다. 반드시 한국어(한글)만 사용하고, 영어 단어나 한자(중국어 문자)를 절대 섞지 않으며, 존댓말(습니다/입니다체)로 통일하고 반말을 섞지 않습니다."
                        },
                        {"role": "user", "content": user_content}
                    ],
                    temperature=min(0.3 + 0.2 * (attempt - 1), 0.7)
                )
                bio = result.choices[0].message.content.strip()
                last_bio = bio
                issue = _has_disallowed_foreign_text(bio)
                if issue is None and _POLITE_ENDING_RE.search(bio):
                    return email, bio
                feedback = issue or "존댓말(~습니다/~입니다) 종결이 아님"
                print(f"[SHORT_BIO] 형식 검증 실패 ({email}, {attempt}/3번째 시도): {bio!r} ({feedback})")
            except Exception as e:
                print(f"[SHORT_BIO] LLM 호출 실패 ({email}, {attempt}/3번째 시도): {e}")
        # 3번 다 검증에 실패해도 완전히 비우는 것보다는 마지막 결과라도 반환한다.
        return email, last_bio

    short_bios: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(len(targets), 15)) as executor:
        futures = {executor.submit(_call_llm, email, desc, rel): email for email, desc, rel in targets}
        for future in as_completed(futures):
            email, bio = future.result()
            if bio:
                short_bios[email] = bio

    print(f"[SHORT_BIO] 총 {len(short_bios)}명 한줄소개 생성 완료")
    return short_bios


# (함수, 인자) 목록을 각각 스레드로 병렬 실행하고 모두 끝날 때까지 기다린다 (에러가 나면 첫 에러를 재발생)
def _run_and_join(jobs):
    errors = []
    # 함수를 실행하고 예외를 errors 리스트에 모은다
    def _wrap(fn, args):
        try:
            fn(*args)
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=_wrap, args=(fn, args)) for fn, args in jobs]
    for t in threads: t.start()
    for t in threads: t.join()
    if errors:
        raise errors[0]


# 메일 키워드 통계와 연락처 통계 저장을 병렬로 실행하는 메일 통계 파이프라인
def _extract_statics_pipeline(paths, mode: str = "rewrite"):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    # 서로 다른 출력 파일(keywords/contacts)에 쓰고 순서 의존성이 없어 병렬 실행
    _run_and_join([
        (_save_mail_keyword_stats, (paths, mode)),
        (_save_mail_contact_stats, (paths, mode)),
    ])

# 통계 파이프라인을 실행하며 Job 상태(running/done/failed)와 로그를 갱신한다
def run_statics_pipeline(job_id, paths, mode: str = "rewrite"):
    print(f"[JOB][statics] START job_id={job_id}")
    append_job_log(job_id, "[START] statics pipeline")

    try:
        update_job(job_id, status="running", progress=0, message="통계 추출 시작")
        _extract_statics_pipeline(paths, mode)

        update_job(
            job_id,
            status="done",
            progress=100,
            message="통계 추출 완료",
            result={
                "mail_keywords_path": paths.MAIL_KEYWORDS_PATH,
                "mail_contacts_path": paths.MAIL_CONTACTS_PATH,
                "mode": mode,
            },
            finished_at=time.time(),
        )
        append_job_log(job_id, "[FINISH] statics pipeline completed")

    except Exception as e:
        err_text = f"{type(e).__name__}: {e}"
        append_job_log(job_id, f"[ERROR] {err_text}")
        update_job(
            job_id,
            status="failed",
            progress=100,
            message="통계 추출 실패",
            error=err_text,
            finished_at=time.time(),
        )

# 통계 파이프라인을 데몬 스레드로 백그라운드 실행하고 스레드 객체를 반환한다
def start_statics_pipeline_background(job_id, paths, mode: str = "rewrite"):
    print(f"[JOB][statics] BACKGROUND START job_id={job_id}")
    append_job_log(job_id, "[INFO] background thread starting")

    t = threading.Thread(
        target=run_statics_pipeline,
        args=(job_id, paths, mode),
        daemon=True,
    )
    t.start()

    print(f"[JOB][statics] BACKGROUND THREAD STARTED job_id={job_id} thread={t.name}")
    append_job_log(job_id, f"[INFO] background thread started name={t.name}")

    return t