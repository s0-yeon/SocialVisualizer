# 대화 블록을 월별/연별로 묶어 LLM으로 요약을 생성하고 JSON과 message_summarize 테이블에 저장한다.

# Groups conversation blocks by month/year, generates summaries via LLM, and saves them to JSON and the message_summarize table.

import os
import json
import datetime
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from util.message_statics import _parse_message_blocks_from_parquet
from util.database.chatroom_db_writer import save_message_summarize_to_db

load_dotenv("src/parquet/.env")


# 프롬프트가 모델의 컨텍스트 길이(대략 32K 토큰)를 넘기지 않도록 입력 텍스트에 거는 안전장치.
_MAX_SUMMARY_INPUT_CHARS = 24000


# 대화 목록을 LLM에 넘겨 해당 기간 요약과 관련 참여자 목록을 JSON으로 받아온다
def _summarize_with_llm(text, period_label, contacts):
    if len(text) > _MAX_SUMMARY_INPUT_CHARS:
        print(f"[message_summary] 입력이 너무 길어서 잘라냄 ({period_label}): {len(text)}자 → {_MAX_SUMMARY_INPUT_CHARS}자")
        text = text[:_MAX_SUMMARY_INPUT_CHARS]

    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,
    )
    last_error = None
    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=os.getenv("SUB_TASK_CHAT_MODEL"),
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "주어진 채팅 대화 목록을 분석하여 아래 JSON 형식으로만 응답하세요.\n"
                            "{\n"
                            '  "summary": "해당 기간의 주요 대화 내용을 3~5문장으로 한국어 요약( ~입니다. 어미로 통일)",\n'
                            '  "contacts": ["요약 내용과 관련된 대화 참여자 이름 목록"]\n'
                            "}\n"
                            "contacts는 아래 제공된 참여자 목록 중에서만 골라주세요."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"[{period_label}] 참여자 목록: {contacts}\n\n대화 목록:\n\n{text}"
                    }
                ],
                max_completion_tokens=1000 
            )
            result = json.loads(response.choices[0].message.content)
            return {
                "summary":  result.get("summary", ""),
                "contacts": result.get("contacts", []),
            }
        except Exception as e:
            last_error = e
            print(f"[message_summary] LLM 오류 ({period_label}, {attempt}/3번째 시도): {e}")

    print(f"[message_summary] {period_label} 요약 {attempt}번 모두 실패, 빈 값으로 대체: {last_error}")
    return {"summary": "", "contacts": []}


# 대화 블록을 월별/연별로 묶어 LLM 요약을 만들고 JSON 저장 및 message_summarize 테이블 저장
def generate_message_summaries(paths):
    blocks = _parse_message_blocks_from_parquet(paths)
    if not blocks:
        print("[message_summary] 요약할 대화 블록 없음")
        return

    entries = []
    for block in blocks:
        if not block["block_date"]:
            continue
        try:
            date = datetime.datetime.strptime(block["block_date"], "%Y-%m-%d")
        except Exception:
            continue

        lines = []
        contacts = set()
        for msg in block["messages"]:
            if msg["is_system"] or not msg["sender"]:
                continue
            lines.append(f"{msg['time']} {msg['sender']}: {msg['text']}")
            contacts.add(msg["sender"])

        if not lines:
            continue

        entries.append({
            "date": date,
            "year": date.strftime("%Y"),
            "month": date.strftime("%Y-%m"),
            "text": "\n".join(lines)[:1500],
            "contacts": contacts,
        })

    if not entries:
        print("[message_summary] 요약할 대화 없음")
        return

    entries.sort(key=lambda x: x["date"])

    monthly_groups = {}
    yearly_groups = {}
    for e in entries:
        monthly_groups.setdefault(e["month"], []).append(e)
        yearly_groups.setdefault(e["year"], []).append(e)

    # 그룹의 대화들을 날짜별로 합쳐 LLM 입력 텍스트로 만든다
    def _build_text(group):
        return "\n\n".join(f"날짜: {e['date'].strftime('%Y-%m-%d')}\n{e['text']}" for e in group)

    # 그룹 내 모든 대화의 참여자 이름을 정렬된 리스트로 모은다
    def _collect_contacts(group):
        names = set()
        for e in group:
            names |= e["contacts"]
        return sorted(names)

    # 기간 그룹 하나를 원본 대화 그대로 LLM 요약해 (kind, period, 요약결과)를 반환한다
    def _summarize_group(kind, period, group):
        print(f"[message_summary] {kind} 요약 중: {period} ({len(group)}개 블록)")
        return kind, period, _summarize_with_llm(_build_text(group), period, _collect_contacts(group))

    # 1단계: 월별 요약을 먼저 만든다. 연도별 요약이 이 결과를 재료로 쓰기 때문에 반드시 먼저 끝나야 한다.
    monthly_summaries = {}
    with ThreadPoolExecutor(max_workers=min(len(monthly_groups), 15)) as executor:
        futures = [executor.submit(_summarize_group, "monthly", month, group) for month, group in monthly_groups.items()]
        for future in as_completed(futures):
            _, period, summary = future.result()
            monthly_summaries[period] = summary
            
    def _build_yearly_text(year):
        months_in_year = sorted(m for m in monthly_summaries if m.startswith(f"{year}-"))
        parts = [
            f"{m}: {monthly_summaries[m].get('summary')}"
            for m in months_in_year
            if monthly_summaries[m].get("summary")
        ]
        return "\n".join(parts)

    def _collect_yearly_contacts(year):
        names = set()
        for m, summary in monthly_summaries.items():
            if m.startswith(f"{year}-"):
                names |= set(summary.get("contacts") or [])
        # 월별 요약에 참여자가 하나도 안 잡혔으면(전부 실패 등) 원본 그룹에서 대신 모은다.
        return sorted(names) if names else _collect_contacts(yearly_groups.get(year, []))

    # 연도 하나를 (월별 요약 기반으로) LLM 요약해 (period, 요약결과)를 반환한다
    def _summarize_year(year):
        text = _build_yearly_text(year)
        if not text:
            # 월별 요약이 전부 비어있으면(전부 실패 등) 마지막 수단으로 원본 대화를 그대로 쓴다.
            text = _build_text(yearly_groups[year])
        print(f"[message_summary] yearly 요약 중: {year} (월별 요약 {len(text.splitlines())}개월 기반)")
        return year, _summarize_with_llm(text, year, _collect_yearly_contacts(year))

    # 2단계: 월별 요약이 다 끝난 뒤, 그걸 재료로 연도별 요약을 만든다.
    yearly_summaries = {}
    with ThreadPoolExecutor(max_workers=min(len(yearly_groups), 15)) as executor:
        futures = [executor.submit(_summarize_year, year) for year in yearly_groups]
        for future in as_completed(futures):
            year, summary = future.result()
            yearly_summaries[year] = summary

    result = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "yearly":  yearly_summaries,
        "monthly": monthly_summaries,
    }

    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(paths.MESSAGE_SUMMARIES_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[message_summary] 저장 완료: {paths.MESSAGE_SUMMARIES_PATH}")

    save_message_summarize_to_db(paths)
