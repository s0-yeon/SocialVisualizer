# parquet의 대화 블록을 파싱해 어조를 판별하고, 참여자별 메시지 이력·LLM 프로필·키워드 통계를 병렬로 생성해 저장한다.

# Parses conversation blocks from parquet to classify tone, then generates and saves per-participant message history, LLM profiles, and keyword statistics in parallel.

import os
import re
import json
from dotenv import load_dotenv
from openai import OpenAI

from util.extract_statics import _run_and_join, _is_clean_korean_polite_sentence, _has_disallowed_foreign_text, _POLITE_ENDING_RE

load_dotenv("src/parquet/.env")

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("SUB_TASK_API_BASE") or None,
)

# build_message_blocks()가 쓰는 대화 내용 줄 포맷과 대응:
#   "HH:MM 발신자: 메시지"          -> sender/text
#   "HH:MM [알림] 메시지"           -> sys_text (입장/퇴장 등 시스템 메시지)
_MSG_LINE_RE = re.compile(
    r'^(?P<time>\d{2}:\d{2})\s+(?:\[알림\]\s?(?P<sys_text>.*)|(?P<sender>[^:\n]+?):\s(?P<text>.*))$'
)


# documents.parquet을 훑어 대화 블록 하나당 dict(block_id/방이름/날짜/참여자/messages)로 파싱한 리스트를 반환한다
def _parse_message_blocks_from_parquet(paths) -> list[dict]:
    import pandas as pd

    documents_path = os.path.join(paths.PARQUET_DIR, "documents.parquet")
    if not os.path.exists(documents_path):
        print(f"[MSG_STATS] documents.parquet 없음: {documents_path}")
        return []

    df = pd.read_parquet(documents_path)

    blocks = []
    seen_ids = set()

    for _, row in df.iterrows():
        text = str(row.get('text', ''))

        id_match = re.search(r'^ID:\s*(.+)$', text, re.MULTILINE)
        block_id = id_match.group(1).strip() if id_match else None
        if not block_id or block_id in seen_ids:
            continue
        seen_ids.add(block_id)

        room_match = re.search(r'^채팅방:\s*(.+)$', text, re.MULTILINE)
        chatroom_name = room_match.group(1).strip() if room_match else ""

        date_match = re.search(r'^날짜:\s*(.+)$', text, re.MULTILINE)
        block_date = date_match.group(1).strip() if date_match else None

        participants_match = re.search(r'^참여자:\s*(.+)$', text, re.MULTILINE)
        participants_raw = participants_match.group(1).strip() if participants_match else ""
        participants = [
            p.strip() for p in participants_raw.split(",")
            if p.strip() and p.strip() != "알 수 없음"
        ]

        body_match = re.search(r'\[대화 내용\]\s*\n(.*?)(?:\n=+|\Z)', text, re.DOTALL)
        body = body_match.group(1) if body_match else ""

        #  새 "HH:MM ...:" 줄이 나올 때까지는 직전 메시지의 연속으로 본다
        messages = []
        for line in body.splitlines():
            m = _MSG_LINE_RE.match(line)
            if m:
                if m.group('sys_text') is not None:
                    messages.append({
                        "time": m.group('time'), "sender": None,
                        "text": m.group('sys_text'), "is_system": True,
                    })
                else:
                    messages.append({
                        "time": m.group('time'), "sender": m.group('sender').strip(),
                        "text": m.group('text'), "is_system": False,
                    })
            elif messages:
                messages[-1]["text"] += "\n" + line

        blocks.append({
            "block_id": block_id,
            "chatroom_name": chatroom_name,
            "block_date": block_date,
            "participants": participants,
            "messages": messages,
        })

    return blocks


# 하루치 대화 텍스트를 LLM에 넘겨 어조를 friendly / not_friendly로 판별한다
def _classify_message_tone_with_llm(text: str) -> str:
    if not text.strip():
        return "not_friendly"

    text = text[:1500]

    prompt = f"""
    다음은 카카오톡 채팅방의 하루치 대화 내용이다. 이 대화가 '친밀한 어조'인지 판별하라.

    판별 기준:
    - '친밀한 어조'란, 개인적인 친분이나 가까운 관계가 느껴지는 말투를 뜻한다.
    - 반말, 이모티콘/농담, 사적인 안부, 편한 말투가 중심이면 friendly다.
    - 공지/알림 위주, 업무·스터디 관련 형식적인 대화, 존댓말 중심의 사무적인 대화는 not_friendly다.

    반드시 아래 둘 중 하나만 정확히 출력하라.
    friendly
    not_friendly

    대화 내용:
    {text}
    """.strip()

    result = client.chat.completions.create(
        model=os.getenv("SUB_TASK_CHAT_MODEL"),
        messages=[
            {
                "role": "system",
                "content": "당신은 채팅 대화의 어조를 분류하는 AI입니다. 반드시 friendly 또는 not_friendly 둘 중 하나만 출력하세요."
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    answer = result.choices[0].message.content.strip().lower()
    return "friendly" if answer == "friendly" else "not_friendly"


# 참여자별 메시지 이력(시간·내용)을 JSON으로 저장한다 (프로필 생성용 원본 데이터, rewrite/append)
def _save_chatroom_people_messages(paths, mode: str = "rewrite"):
    blocks = _parse_message_blocks_from_parquet(paths)

    if mode == "append" and os.path.exists(paths.CHATROOM_PEOPLE_MESSAGES_PATH):
        with open(paths.CHATROOM_PEOPLE_MESSAGES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        people = data.get("people", {})
        processed_block_ids = set(data.get("processed_block_ids", []))
    else:
        people = {}
        processed_block_ids = set()

    for block in blocks:
        if block["block_id"] in processed_block_ids:
            continue

        block_date = block["block_date"]
        for msg in block["messages"]:
            if msg["is_system"] or not msg["sender"]:
                continue
            datetime_str = f"{block_date} {msg['time']}" if block_date else msg["time"]
            people.setdefault(msg["sender"], []).append({
                "datetime": datetime_str,
                "text": msg["text"],
            })

        processed_block_ids.add(block["block_id"])

    result = {
        "processed_block_ids": sorted(processed_block_ids),
        "people": people,
    }

    with open(paths.CHATROOM_PEOPLE_MESSAGES_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[MSG_STATS] ({mode}) 참여자 {len(people)}명 메시지 이력 저장 완료 → {paths.CHATROOM_PEOPLE_MESSAGES_PATH}")


# chatroom_people_messages.json의 전체 메시지 수를 합산해 반환한다 (시스템 메시지 제외)
def count_total_messages(paths) -> int:
    if not os.path.exists(paths.CHATROOM_PEOPLE_MESSAGES_PATH):
        return 0
    with open(paths.CHATROOM_PEOPLE_MESSAGES_PATH, "r", encoding="utf-8") as f:
        people = json.load(f).get("people", {})
    return sum(len(messages) for messages in people.values())


# 참여자별 메시지 이력을 LLM에 넘겨 {이름: 프로필 문장} dict를 생성한다 (DB 저장은 호출자 담당)
def generate_chatroom_people_descriptions(paths) -> dict:
    if not os.path.exists(paths.CHATROOM_PEOPLE_MESSAGES_PATH):
        print("[MSG_PROFILES] 참여자 메시지 이력 없음 → 프로필 생성 건너뜀")
        return {}

    with open(paths.CHATROOM_PEOPLE_MESSAGES_PATH, "r", encoding="utf-8") as f:
        people = json.load(f).get("people", {})

    from concurrent.futures import ThreadPoolExecutor, as_completed

    MAX_MESSAGES_FOR_PROMPT = 80

    # 참여자 한 명의 최근 메시지 이력으로 프로필 생성 프롬프트를 만든다
    def _build_prompt(name, messages):
        ordered = sorted(messages, key=lambda m: m["datetime"])
        sample = ordered[-MAX_MESSAGES_FOR_PROMPT:]
        history_text = "\n".join(f"[{m['datetime']}] {m['text']}" for m in sample)
        return f"""다음은 '{name}'님이 채팅방에서 실제로 보낸 메시지 이력입니다 (최근 {len(sample)}건 / 총 {len(messages)}건 중).

{history_text}

위 메시지들만 근거로 아래 형식으로만 출력하세요. 다른 텍스트는 절대 포함하지 마세요. "~입니다." 체로 통일하세요.
한국어(한글)만 사용하고, 영어 단어나 한자(중국어 문자)를 절대 섞지 마세요.
참여 패턴: <대화에 얼마나 자주/활발히 참여하는지 한 문장으로>
자주 하는 이야기: <주로 어떤 주제/내용의 메시지를 보내는지 한 문장으로>
말투: <반말/존댓말, 이모티콘 사용 등 말투 특징을 한 문장으로>""".strip()

    # 참여자 한 명의 프로필을 LLM으로 생성해 (이름, 설명)을 반환한다
    def _call_llm(name, messages):
        prompt = _build_prompt(name, messages)
        last_desc = None
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
                            "content": "당신은 채팅 메시지 이력을 분석해 참여자 프로필을 한국어로 간결하게 요약하는 AI입니다. 반드시 한국어(한글)만 사용하고, 영어 단어나 한자(중국어 문자)를 절대 섞지 않으며, 존댓말로 통일하고 반말을 섞지 않습니다."
                        },
                        {"role": "user", "content": user_content},
                    ],
                    temperature=min(0.3 + 0.2 * (attempt - 1), 0.7),
                )
                desc = result.choices[0].message.content.strip()
                last_desc = desc
                issue = _has_disallowed_foreign_text(desc)
                if issue is None:
                    return name, desc
                feedback = issue
                print(f"[MSG_PROFILES] 형식 검증 실패 ({name}, {attempt}/3번째 시도): {desc!r} ({issue})")
            except Exception as e:
                print(f"[MSG_PROFILES] LLM 호출 실패 ({name}, {attempt}/3번째 시도): {e}")
        # 3번 다 검증에 실패해도 완전히 비우는 것보다는 마지막 결과라도 반환한다.
        return name, last_desc

    targets = [(name, msgs) for name, msgs in people.items() if msgs]

    descriptions: dict[str, str] = {}
    if targets:
        with ThreadPoolExecutor(max_workers=min(len(targets), 15)) as executor:
            futures = {executor.submit(_call_llm, name, msgs): name for name, msgs in targets}
            for future in as_completed(futures):
                name, desc = future.result()
                if desc:
                    descriptions[name] = desc

    print(f"[MSG_PROFILES] 총 {len(descriptions)}명 프로필 생성 완료")
    return descriptions


# generate_chatroom_people_descriptions() 결과({이름: description})를 2차 LLM 호출로 한 문장 소개(short_bio)로 압축해 {이름: 문장}으로 반환한다
def generate_chatroom_people_short_bios(descriptions: dict) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    targets = [(name, desc) for name, desc in descriptions.items() if desc]
    if not targets:
        return {}

    # 완성된 참여자 description으로 한 문장 소개 프롬프트를 만든다
    def _build_prompt(name, description):
        return f"""다음은 '{name}'님에 대해 이미 생성된 채팅 프로필입니다.

{description}

위 내용을 바탕으로, 이 사람을 다른 사람에게 소개하듯 자연스러운 한국어 한 문장으로 요약하세요.
- 문장은 반드시 "~습니다." 또는 "~입니다."로 끝나야 합니다. 반말(~야, ~해, ~지 등)은 절대 쓰지 마세요.
- 한국어(한글)만 사용하세요. 영어 단어나 한자(중국어 문자)를 절대 섞지 마세요.
- 성격이나 대화 스타일의 특징이 드러나는 짧은 소개 문장으로 쓰세요.
- 예시: "꼼꼼하고 계획적인 성격의 친구입니다.", "이모티콘을 자주 쓰는 유쾌한 성격입니다."
- 다른 설명, 따옴표, 접두어 없이 문장 하나만 출력하세요.""".strip()

    def _call_llm(name, description):
        last_bio = None
        feedback = None
        for attempt in range(1, 4):
            try:
                user_content = _build_prompt(name, description)
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
                    temperature=min(0.3 + 0.2 * (attempt - 1), 0.7),
                )
                bio = result.choices[0].message.content.strip()
                last_bio = bio
                issue = _has_disallowed_foreign_text(bio)
                if issue is None and _POLITE_ENDING_RE.search(bio):
                    return name, bio
                feedback = issue or "존댓말(~습니다/~입니다) 종결이 아님"
                print(f"[MSG_SHORT_BIO] 형식 검증 실패 ({name}, {attempt}/3번째 시도): {bio!r} ({feedback})")
            except Exception as e:
                print(f"[MSG_SHORT_BIO] LLM 호출 실패 ({name}, {attempt}/3번째 시도): {e}")
        # 3번 다 검증에 실패해도 완전히 비우는 것보다는 마지막 결과라도 반환한다.
        return name, last_bio

    short_bios: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(len(targets), 15)) as executor:
        futures = {executor.submit(_call_llm, name, desc): name for name, desc in targets}
        for future in as_completed(futures):
            name, bio = future.result()
            if bio:
                short_bios[name] = bio

    print(f"[MSG_SHORT_BIO] 총 {len(short_bios)}명 한줄소개 생성 완료")
    return short_bios


# 블록마다 참여자별 메시지에서 LLM 키워드를 뽑아 언급 횟수를 집계해 JSON으로 저장한다 (rewrite/append)
def _save_message_keyword_stats(paths, mode: str = "rewrite"):
    from util.extract_statics import extract_keywords_with_llm

    blocks = _parse_message_blocks_from_parquet(paths)

    if mode == "append" and os.path.exists(paths.MESSAGE_KEYWORDS_PATH):
        with open(paths.MESSAGE_KEYWORDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        keyword_stats = data.get("keywords", {})
        mention_map = data.get("keyword_participant_block_map", {})
        processed_ids = set(data.get("processed_block_ids", []))
    else:
        keyword_stats = {}
        mention_map = {}
        processed_ids = set()

    for block in blocks:
        if block["block_id"] in processed_ids:
            continue

        per_sender_text: dict[str, list[str]] = {}
        for msg in block["messages"]:
            if msg["is_system"] or not msg["sender"]:
                continue
            per_sender_text.setdefault(msg["sender"], []).append(msg["text"])

        for sender, texts in per_sender_text.items():
            body = "\n".join(texts).strip()
            if not body:
                continue

            # 실제 키워드 언급 횟수는 이 사람이 이 블록에서 보낸 메시지 원문에서 직접 센다
            keywords = extract_keywords_with_llm(body)
            for kw in keywords:
                occurrence = sum(text.count(kw) for text in texts)
                if occurrence <= 0:
                    continue
                keyword_stats[kw] = keyword_stats.get(kw, 0) + occurrence
                mention_map.setdefault(kw, {}).setdefault(sender, {})
                mention_map[kw][sender][block["block_id"]] = \
                    mention_map[kw][sender].get(block["block_id"], 0) + occurrence

        processed_ids.add(block["block_id"])

    result = {
        "keywords": keyword_stats,
        "keyword_participant_block_map": mention_map,
        "processed_block_ids": list(processed_ids),
    }

    with open(paths.MESSAGE_KEYWORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[MSG_KEYWORD] ({mode}) 키워드 {len(keyword_stats)}개 저장 완료 → {paths.MESSAGE_KEYWORDS_PATH}")


# 참여자 메시지 이력 저장과 키워드 통계 저장을 병렬로 실행하는 메신저 통계 파이프라인
def _extract_message_statics_pipeline(paths, mode: str = "rewrite"):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    _run_and_join([
        (_save_chatroom_people_messages, (paths, mode)),
        (_save_message_keyword_stats, (paths, mode)),
    ])
