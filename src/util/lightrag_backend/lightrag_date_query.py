# src/util/lightrag_backend/lightrag_date_query.py

# LightRAG용 날짜 범위 질의 처리 모듈. 
# 질문 문장에서 정규식으로 날짜/기간 표현을 뽑아내고 (오늘/어제/이번 주/N일 전 등 20여 가지 패턴), 그 범위에 드는 메일만 mail_latest.txt에서 직접 필터링해 LLM에 근거로 넘겨 답변을 생성한다. 
# LightRAG 그래프 검색을 거치지 않고 날짜 조건이 명확한 질문에 한해 빠르게 답하는 전용 경로다.

# Handles date-range mail queries for LightRAG. 
# Extracts date/period expressions from the question via regex (today, yesterday, this week, N
# days ago, and ~20 more patterns), filters mail_latest.txt directly for mails within that range, and feeds them to an LLM as grounding context.
# A fast path for date-scoped questions that bypasses LightRAG's graph search.

import os
import re
import time
import datetime
import calendar
import openai

from config.settings import MAIL_BLOCK_SEP

# 질의문에서 날짜/기간 표현을 정규식으로 파싱해 (시작일, 종료일) 문자열을 반환한다 (없으면 None)
def _extract_date_range(message: str):
    today = datetime.datetime.now()
    year = today.year

    # 패턴1: 3월 22일 ~ 3월 25일
    m = re.search(r'(\d+)월\s*(\d+)일\s*[~～\-]\s*(\d+)월\s*(\d+)일', message)
    if m:
        start = f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        end = f"{year}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"
        return start, end

    # 패턴2: 3월 22일 ~ 25일
    m = re.search(r'(\d+)월\s*(\d+)일\s*[~～\-]\s*(\d+)일', message)
    if m:
        month = int(m.group(1))
        start = f"{year}-{month:02d}-{int(m.group(2)):02d}"
        end = f"{year}-{month:02d}-{int(m.group(3)):02d}"
        return start, end

    # 패턴3: 2026-03-22 ~ 2026-03-25
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})\s*[~～\-]\s*(\d{4})-(\d{2})-(\d{2})', message)
    if m:
        start = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        end = f"{m.group(4)}-{m.group(5)}-{m.group(6)}"
        return start, end

    # 패턴4: 2026-03-22 ~ 03-25
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})\s*[~～\-]\s*(\d{2})-(\d{2})', message)
    if m:
        start = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        end = f"{m.group(1)}-{m.group(4)}-{m.group(5)}"
        return start, end

    # 패턴5: 이번 주
    if '이번 주' in message or '이번주' in message:
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)
        return start_of_week.strftime('%Y-%m-%d'), end_of_week.strftime('%Y-%m-%d')

    # 패턴6: 지난 주 / 저번 주 / 저저번 주 (N주 전)
    m = re.search(r'(저저번|저번|지난)\s*주', message)
    if m:
        weeks_ago = 2 if m.group(1) == '저저번' else 1
        start_of_week = today - datetime.timedelta(days=today.weekday() + 7 * weeks_ago)
        end_of_week = start_of_week + datetime.timedelta(days=6)
        return start_of_week.strftime('%Y-%m-%d'), end_of_week.strftime('%Y-%m-%d')

    # 패턴7: 오늘
    if '오늘' in message:
        date = today.strftime('%Y-%m-%d')
        return date, date

    # 패턴8: 어제
    if '어제' in message:
        date = (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        return date, date

    # 패턴9: 며칠 전 (3일 전, 5일 전 등)
    m = re.search(r'(\d+)\s*일\s*전', message)
    if m:
        date = (today - datetime.timedelta(days=int(m.group(1)))).strftime('%Y-%m-%d')
        return date, date

    # 패턴10: 최근 N일
    m = re.search(r'최근\s*(\d+)\s*일', message)
    if m:
        start = (today - datetime.timedelta(days=int(m.group(1)) - 1)).strftime('%Y-%m-%d')
        end = today.strftime('%Y-%m-%d')
        return start, end

    # 패턴11: 이번 달
    if '이번 달' in message or '이번달' in message:
        start = today.replace(day=1).strftime('%Y-%m-%d')
        end = today.strftime('%Y-%m-%d')
        return start, end

    # 패턴12: 지난 달 / 저번 달 / 저저번 달 (N달 전)
    m = re.search(r'(저저번|저번|지난)\s*달', message)
    if m:
        months_ago = 2 if m.group(1) == '저저번' else 1
        month = today.month - months_ago
        y = today.year
        while month <= 0:
            month += 12
            y -= 1
        last_day = calendar.monthrange(y, month)[1]
        return f"{y}-{month:02d}-01", f"{y}-{month:02d}-{last_day:02d}"

    # 패턴13: 올해
    if '올해' in message:
        start = f"{year}-01-01"
        end = today.strftime('%Y-%m-%d')
        return start, end

    # 패턴14: 작년
    if '작년' in message:
        last_year = year - 1
        return f"{last_year}-01-01", f"{last_year}-12-31"

    # 패턴15: N년 전
    m = re.search(r'(\d+)\s*년\s*전', message)
    if m:
        target_year = year - int(m.group(1))
        return f"{target_year}-01-01", f"{target_year}-12-31"

    # 패턴16: N달 전 (해당 월 전체)
    m = re.search(r'(\d+)\s*달\s*전', message)
    if m:
        months_ago = int(m.group(1))
        month = today.month - months_ago
        y = today.year
        while month <= 0:
            month += 12
            y -= 1
        last_day = calendar.monthrange(y, month)[1]
        return f"{y}-{month:02d}-01", f"{y}-{month:02d}-{last_day:02d}"

    # 패턴17: N개월 전 (해당 월 전체)
    m = re.search(r'(\d+)\s*개월\s*전', message)
    if m:
        months_ago = int(m.group(1))
        month = today.month - months_ago
        y = today.year
        while month <= 0:
            month += 12
            y -= 1
        last_day = calendar.monthrange(y, month)[1]
        return f"{y}-{month:02d}-01", f"{y}-{month:02d}-{last_day:02d}"

    # 패턴18: 2026년 3월 22일
    m = re.search(r'(\d{4})\s*년\s*(\d+)\s*월\s*(\d+)\s*일', message)
    if m:
        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return date, date

    # 패턴19: 2026년 3월 (연월 전체)
    m = re.search(r'(\d{4})\s*년\s*(\d+)\s*월', message)
    if m and not re.search(r'\d+일', message):
        y, month = int(m.group(1)), int(m.group(2))
        last_day = calendar.monthrange(y, month)[1]
        return f"{y}-{month:02d}-01", f"{y}-{month:02d}-{last_day:02d}"

    # 패턴20: 2026년 전체
    m = re.search(r'(\d{4})\s*년', message)
    if m and not re.search(r'\d+월', message):
        y = int(m.group(1))
        return f"{y}-01-01", f"{y}-12-31"

    # 패턴21: 3월 전체 (연도 없이 월만)
    m = re.search(r'(\d+)월', message)
    if m and not re.search(r'\d+일', message):
        month = int(m.group(1))
        last_day = calendar.monthrange(year, month)[1]
        return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"

    # 패턴22: 3월 22일 (단일 날짜)
    m = re.search(r'(\d+)월\s*(\d+)일', message)
    if m:
        date = f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        return date, date

    # 패턴23: 2026-03-22 (단일 날짜 숫자형)
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', message)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # 패턴24: 26-03-22 또는 2026-3-22 (zero-padding 없는 경우)
    m = re.search(r'(\d{2,4})-(\d{1,2})-(\d{1,2})', message)
    if m:
        y = int(m.group(1))
        if y < 100:
            y += 2000
        date = f"{y}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return date, date

    return None


# mail_latest.txt에서 날짜 범위에 드는 메일 블록을 골라 제목/ID/날짜/본문 스니펫 dict 리스트로 반환한다
def _filter_emails_by_date(paths, start_date: str, end_date: str) -> list:
    if not os.path.exists(paths.MAIL_LATEST_PATH):
        return []

    with open(paths.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)

    results = []
    for block in text.split(MAIL_BLOCK_SEP):
        block = block.strip()
        if not block:
            continue

        # 대괄호/콜론 둘 다 가능
        date_m = re.search(r'^\s*(?:\[날짜\]|날짜:)\s*(.+?)\s*$', block, re.MULTILINE)
        if not date_m:
            continue  # 날짜 필드 없으면 걍 넘어감

        try:
            mail_dt = datetime.datetime.strptime(date_m.group(1).strip(), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue  # 날짜 파싱 실패하면 걍 넘어감

        if not (start_dt <= mail_dt <= end_dt):
            continue  # 날짜 범위 밖이면 걍 넘어감

        id_m = re.search(r'^\s*(?:\[ID\]|ID:)\s*(.+?)\s*$', block, re.MULTILINE)
        title_m = re.search(r'^\s*(?:\[제목\]|제목:)\s*(.+?)\s*$', block, re.MULTILINE)

        # 원본 본문 앞부분을 그대로 잘라 쓴다(컨텍스트 길이 제한용).
        body_m = re.search(r'\[메일 본문\]\s*\n(.*)', block, re.DOTALL)
        body = body_m.group(1).strip() if body_m else ''
        snippet = body[:300]

        results.append({
            'title': title_m.group(1).strip() if title_m else '(제목 없음)',
            'id': id_m.group(1).strip() if id_m else '알 수 없음',
            'date': date_m.group(1).strip(),
            'summary': snippet,
        })

    # 날짜 오름차순 정렬
    results.sort(key=lambda x: x['date'])
    return results


# 질의의 날짜 범위로 mail_latest.txt를 필터링해 LLM 답변을 생성한다 (날짜 질의가 아니면 None 반환)
def run_date_range_query(message: str, paths) -> str:
    date_range = _extract_date_range(message)  # 질의에서 날짜 범위 추출, 날짜 패턴 없으면 None 반환
    if not date_range:
        return None  # 날짜 쿼리 아니면 LightRAG로 넘긴다

    start_date, end_date = date_range
    start_time = time.time()
    emails = _filter_emails_by_date(paths, start_date, end_date)
    print(f"[DEBUG][lightrag] filtered emails count: {len(emails)}")

    if not emails:  # 해당 기간 이메일 없으면 바로 없다고 메시지 반환
        print(f'date_query(lightrag) execution_time : {time.time() - start_time}')
        return f"{start_date} ~ {end_date} 사이에 수신된 이메일이 없습니다."

    # 필터링된 이메일 목록 LLM에 넘길 텍스트로 변환
    lines = []
    for i, e in enumerate(emails, 1):
        lines.append(
            f"{i}. 제목: {e['title']}\n"
            f"   ID: {e['id']}\n"
            f"   날짜: {e['date']}\n"
            f"   내용: {e['summary']}"
        )
    context = "\n\n".join(lines)

    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("RAG_CHAT_API_BASE") or None,  # 지정 시 로컬 vLLM(라마)으로 라우팅
    )

    # 필터링된 이메일 목록을 근거로 최종 답변을 생성한다
    response = client.chat.completions.create(
        model=os.environ.get("RAG_CHAT_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 이메일 데이터를 분석하는 어시스턴트입니다. "
                    "아래 제공된 이메일 목록을 기반으로 사용자 질문에 한국어로 답변하세요. "
                    "제공된 데이터 외의 내용은 추측하지 마세요."
                    "날짜 필터링은 이미 완료되었습니다. "
                    "제공된 이메일 목록이 곧 사용자가 요청한 기간의 전체 결과입니다. "
                    "날짜 범위를 임의로 재해석하거나 변경하지 마세요. "
                    "목록이 비어있지 않다면 반드시 모든 이메일을 답변에 포함하세요."
                    "이메일 목록의 첫 번째부터 마지막까지 순서대로 전부 나열하세요."
                )
            },
            {
                "role": "user",
                "content": f"[이메일 목록]\n{context}\n\n[질문]\n{message}"
            }
        ],
        temperature=0.0  # 날짜 기반 질문은 창의성 필요 없음
    )
    print(f'date_query(lightrag) execution_time : {time.time() - start_time}')
    print(f'date_query(lightrag) answer : {response.choices[0].message.content.strip()}')
    return response.choices[0].message.content.strip()
