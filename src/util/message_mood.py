# 대화 블록의 말투·응답속도·참여 균형 등을 분석해 채팅방의 월별/연별 분위기 점수와 설명을 계산하고 저장한다.

# Analyzes message tone, response speed, and participation balance in conversation blocks to compute and save each chatroom's monthly/yearly mood scores and descriptions.

import os
import re
import math
import json
import datetime
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from config.db import get_db_connection
from util.message_statics import _parse_message_blocks_from_parquet
from util.database.chatroom_db_writer import save_message_mood_to_db, _resolve_chatroom_key

load_dotenv("src/parquet/.env")

# 가중치
WEIGHT_CONTENT_JUDGE  = 0.35
WEIGHT_TONE           = 0.35
WEIGHT_ACTIVITY       = 0.15
WEIGHT_RESPONSE_SPEED = 0.15

_EMOJI_RE = re.compile(
    r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]'
)
_TEXT_EMOTICON_RE = re.compile(r'\^\^|ㅠ{2,}|ㅜ{2,}|-_-|;;')
_LAUGH_RE = re.compile(r'[ㅋㅎ]{2,}')
_LAUGH_SCORE_CAP = 5  # ㅋㅋㅋㅋㅋ 이상은 더 이상 가점 안 늘림

# 문장 끝 어미 기반 말투 휴리스틱 
# 반말/애교체 어미 → 가점(친밀한 말투), 격식체 어미 → 감점(사무적인 말투)
_CASUAL_ENDING_RE = re.compile(r'(야|다|지|냐|거든|잖아|었어|았어|해|줘|봐|용|염|잉)[\s~.!?]*$')
_FORMAL_ENDING_RE = re.compile(r'(습니다|합니다|입니다|십니다|세요|니다)[\s.!?]*$')


# 메시지 하나의 느낌표·이모티콘·이모지·ㅋㅋㅎㅎ·문장 끝 말투를 합산한 톤 점수를 반환한다
def _tone_marker_score(text: str) -> float:
    score = 0.0
    score += len(re.findall(r'!', text))
    score += len(_TEXT_EMOTICON_RE.findall(text))
    score += len(_EMOJI_RE.findall(text))
    for match in _LAUGH_RE.finditer(text):
        score += min(len(match.group()), _LAUGH_SCORE_CAP)
    if text.strip() == "이모티콘":
        score += 1.0

    tail = text.strip()[-10:]
    if _FORMAL_ENDING_RE.search(tail):
        score -= 1.0
    elif _CASUAL_ENDING_RE.search(tail):
        score += 1.0
    return score


# 대화 블록들을 block_date 기준 월별/연별 그룹으로 나눈다 (실제 발화가 있는 블록만)
def _group_blocks_by_period(blocks):
    monthly, yearly = {}, {}
    for block in blocks:
        if not block["block_date"]:
            continue
        try:
            date = datetime.datetime.strptime(block["block_date"], "%Y-%m-%d")
        except Exception:
            continue

        real_messages = [m for m in block["messages"] if not m["is_system"] and m["sender"]]
        if not real_messages:
            continue

        entry = {"date": date, "real_messages": real_messages}
        monthly.setdefault(date.strftime("%Y-%m"), []).append(entry)
        yearly.setdefault(date.strftime("%Y"), []).append(entry)
    return monthly, yearly


# 기간 그룹의 원본 대화를 날짜별로 이어붙인 텍스트를 만든다 (ContentJudge LLM 입력용)
def _build_raw_text(group):
    lines = []
    for entry in sorted(group, key=lambda e: e["date"]):
        lines.append(f"날짜: {entry['date'].strftime('%Y-%m-%d')}")
        for m in entry["real_messages"]:
            lines.append(f"{m['time']} {m['sender']}: {m['text']}")
    return "\n".join(lines)


# 원본 대화 텍스트를 LLM에 넘겨 사적 대화 비율(%)과 기간 설명을 받아온다
def _judge_mood_with_llm(text, period_label):
    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,
    )
    try:
        response = client.chat.completions.create(
            model=os.getenv("SUB_TASK_CHAT_MODEL"),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "다음은 카카오톡 채팅방의 특정 기간 실제 대화 원문이다. "
                        "이 기간 대화 내용이 사적인 이야기(안부, 감정, 개인적 일상 공유 등)와 "
                        "공적인 이야기(업무, 공지, 스터디, 사무적인 용건 등) 중 어느 쪽에 더 가까운지 "
                        "분석해 아래 JSON 형식으로만 응답하라.\n"
                        "{\n"
                        '  "private_ratio": 0~100 사이 숫자 (전체 대화 중 사적인 내용의 비율, %),\n'
                        '  "description": "이 기간 대화 내용을 1~2문장으로 한국어 설명 (~입니다. 어미로 통일)"\n'
                        "}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"[{period_label}] 대화 내용:\n\n{text[:8000]}",
                },
            ],
            max_completion_tokens=300,  # gpt-5.4-mini(reasoning 모델)는 max_tokens 미지원
        )
        result = json.loads(response.choices[0].message.content)
        private_ratio = float(result.get("private_ratio", 50))
        private_ratio = max(0.0, min(100.0, private_ratio))
        return private_ratio, result.get("description", "")
    except Exception as e:
        print(f"[message_mood] LLM 판단 오류 ({period_label}): {e}")
        return 50.0, ""


# 한 블록(entry) 내 연속 메시지 사이 평균 간격을 분 단위로 계산한다 (메시지 2개 미만이면 None)
def _avg_response_interval_minutes(entry):
    times = []
    for m in entry["real_messages"]:
        try:
            h, mi = m["time"].split(":")
            times.append(int(h) * 60 + int(mi))
        except Exception:
            continue
    if len(times) < 2:
        return None
    diffs = [max(0, times[i + 1] - times[i]) for i in range(len(times) - 1)]
    return sum(diffs) / len(diffs) if diffs else None


# 기간 그룹에서 발화자별 메시지 수를 {발신자: 개수}로 집계한다
def _speaker_message_counts(group):
    sent_by = {}
    for entry in group:
        for m in entry["real_messages"]:
            sent_by[m["sender"]] = sent_by.get(m["sender"], 0) + 1
    return sent_by


# 발화자별 메시지 점유율의 정규화 엔트로피를 반환한다 (0=한 명만 말함, 1=모두 고르게 대화)
def _participation_balance(sent_by: dict) -> float:
    n = len(sent_by)
    if n <= 1:
        return 0.0

    total = sum(sent_by.values())
    shares = [c / total for c in sent_by.values()]
    entropy = -sum(s * math.log(s) for s in shares)
    return entropy / math.log(n)


# dict 값들을 min-max로 0~100 범위에 정규화한다 (모두 같으면 전부 50)
def _minmax_normalize(raw: dict) -> dict:
    if not raw:
        return {}
    vals = list(raw.values())
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return {k: 50.0 for k in raw}
    return {k: (v - lo) / (hi - lo) * 100 for k, v in raw.items()}


# 값 하나를 pool_values의 min-max 범위 기준 0~100 점수로 환산한다 (범위 밖이면 clamp)
def _minmax_score(value, pool_values):
    if not pool_values:
        return 50.0
    lo, hi = min(pool_values), max(pool_values)
    if hi == lo:
        return 50.0
    # pool_values는 DB 스냅샷 기준이라 방금 파싱한 value가 그 범위를 벗어날 수 있음 -> 0~100으로 clamp
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100))


# 같은 계정의 모든 채팅방·기간별 메시지량 목록을 DB에서 조회한다 (Activity 비교 기준 분포)
def _fetch_cross_room_message_counts(user_id, unit):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if unit == "monthly":
            cursor.execute(
                """
                SELECT chatroom_id, DATE_FORMAT(block_date, '%Y-%m') AS period, SUM(message_count) AS cnt
                FROM message_block
                WHERE user_id = %s
                GROUP BY chatroom_id, period
                """,
                (user_id,),
            )
        else:
            cursor.execute(
                """
                SELECT chatroom_id, YEAR(block_date) AS period, SUM(message_count) AS cnt
                FROM message_block
                WHERE user_id = %s
                GROUP BY chatroom_id, period
                """,
                (user_id,),
            )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [float(cnt) for _, _, cnt in rows if cnt is not None]


# 기간별로 메시지량·응답속도·톤 빈도·참여 균형 원값을 계산해 {period: 통계}로 반환한다
def _compute_group_stats(groups: dict) -> dict:
    raw = {}
    for period, group in groups.items():
        sent_by = _speaker_message_counts(group)
        message_count = sum(sent_by.values())

        intervals = [_avg_response_interval_minutes(e) for e in group]
        intervals = [i for i in intervals if i is not None]
        avg_interval = sum(intervals) / len(intervals) if intervals else 1440.0  # 데이터 없으면 하루(느림)로 취급

        tone_hits = 0.0
        for e in group:
            for m in e["real_messages"]:
                tone_hits += _tone_marker_score(m["text"])
        tone_per_message = tone_hits / message_count if message_count else 0.0

        raw[period] = {
            "message_count": message_count,
            "response_speed_raw": 1.0 / (avg_interval + 1.0),  # 간격 역수 (빠를수록 큼)
            "tone_per_message": tone_per_message,
            "participation_balance": _participation_balance(sent_by),
        }
    return raw


# 한 채팅방의 월별/연별 분위기 점수·설명을 계산해 JSON 저장 및 message_mood 테이블 저장까지 수행한다
def generate_message_mood(paths):
    blocks = _parse_message_blocks_from_parquet(paths)
    if not blocks:
        print("[message_mood] 분석할 대화 블록 없음")
        return

    key = _resolve_chatroom_key(paths.USER_ID)
    if key is None:
        print(f"[message_mood] chatroom 테이블에 해당 채팅방이 없습니다: {paths.USER_ID}")
        return
    chatroom_id, index_date, user_id = key

    monthly_groups, yearly_groups = _group_blocks_by_period(blocks)
    if not monthly_groups and not yearly_groups:
        print("[message_mood] 분석할 대화 없음")
        return

    # 월/연 단위 그룹들에 대해 4개 지표를 가중합한 최종 mood_score와 설명을 계산한다
    def _score_unit(groups: dict, unit: str) -> dict:
        raw_stats = _compute_group_stats(groups)
        tone_norm = _minmax_normalize({p: s["tone_per_message"] for p, s in raw_stats.items()})
        speed_norm = _minmax_normalize({p: s["response_speed_raw"] for p, s in raw_stats.items()})

        cross_room_pool = _fetch_cross_room_message_counts(user_id, unit)

        # 기간 하나를 LLM으로 판단해 (period, (사적비율, 설명))을 반환한다
        def _judge(period, group):
            print(f"[message_mood] {unit} 분위기 분석 중: {period} ({len(group)}개 블록)")
            return period, _judge_mood_with_llm(_build_raw_text(group), period)

        # LLM 호출만 병렬로 먼저 끝내고, 점수 계산(로컬 연산)은 메인 스레드에서 순차 처리
        judged = {}
        with ThreadPoolExecutor(max_workers=min(len(groups), 15)) as executor:
            futures = [executor.submit(_judge, period, group) for period, group in groups.items()]
            for future in as_completed(futures):
                period, (private_ratio, content_description) = future.result()
                judged[period] = (private_ratio, content_description)

        result = {}
        for period in groups:
            private_ratio, content_description = judged[period]

            stats = raw_stats[period]
            activity_cross_norm = _minmax_score(stats["message_count"], cross_room_pool)
            activity_score = activity_cross_norm * (0.5 + 0.5 * stats["participation_balance"])

            mood_score = (
                WEIGHT_CONTENT_JUDGE * private_ratio
                + WEIGHT_TONE * tone_norm.get(period, 50.0)
                + WEIGHT_ACTIVITY * activity_score
                + WEIGHT_RESPONSE_SPEED * speed_norm.get(period, 50.0)
            )

            result[period] = {
                "mood_score": round(mood_score, 2),
                "mood_description": content_description,
            }
        return result

    result = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "yearly": _score_unit(yearly_groups, "yearly"),
        "monthly": _score_unit(monthly_groups, "monthly"),
    }

    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(paths.MESSAGE_MOOD_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[message_mood] 저장 완료: {paths.MESSAGE_MOOD_PATH}")

    save_message_mood_to_db(paths)


# 같은 계정의 모든 채팅방 분위기를 다시 계산한다 (Activity 비교 기준 pool을 최신으로 유지)
def recompute_all_message_moods(paths):
    from util.user_path import UserPaths
    from config.settings import BASE_DIR

    key = _resolve_chatroom_key(paths.USER_ID)
    if key is None:
        return
    _, _, user_id = key

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT chatroom_id FROM chatroom WHERE user_id = %s", (user_id,))
        chatroom_ids = [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

    for chatroom_id in chatroom_ids:
        if chatroom_id != paths.USER_ID:
            room_dir = os.path.join(BASE_DIR, "user_data", "messenger", chatroom_id)
            if not os.path.isdir(room_dir):
                continue
        room_paths = paths if chatroom_id == paths.USER_ID else UserPaths(BASE_DIR, chatroom_id, "messenger")
        generate_message_mood(room_paths)
