# text_units.parquet을 직접 읽어 월별/연별 메일 요약을 LLM으로 생성하고 저장한다 (GraphRAG 전용, LightRAG 버전은 lightrag_backend/lightrag_mail_summary.py).

# Reads text_units.parquet directly to generate and save monthly/yearly mail summaries via LLM — the GraphRAG-specific version (see lightrag_backend/lightrag_mail_summary.py for the LightRAG counterpart).

import os
import re
import json
import datetime
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from util.database.db_writer import save_mail_summarize_to_db

load_dotenv("src/parquet/.env")


# 메일 블록 텍스트에서 "[필드명] 값" 형식의 값을 추출한다 (없으면 None)
def _extract_field(text, field_name):
    m = re.search(rf'^\[{re.escape(field_name)}\]\s*(.+)$', text, re.MULTILINE)
    return m.group(1).strip() if m else None


# 메일 블록 텍스트에서 "[메일 본문]" 이후 내용을 추출한다
def _extract_body(text):
    m = re.search(r'\[메일 본문\]\s*\n(.*?)(?=\n\[|$)', text, re.DOTALL)
    return m.group(1).strip() if m else ""


# "Name <email>" 형태에서 이메일 주소만 뽑는다 (꺾쇠 없으면 원본을 그대로 사용)
def _extract_email(raw):
    m = re.search(r'<([^>]+)>', raw or "")
    return m.group(1).strip() if m else raw.strip() if raw else None


# 메일 목록을 LLM에 넘겨 해당 기간 요약과 관련 이메일 주소 목록을 JSON으로 받아온다
def _summarize_with_llm(text, period_label, contacts):
    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,
    )
    system_prompt = (
        "주어진 이메일 목록을 분석하여 아래 JSON 형식으로만 응답하세요.\n"
        "{\n"
        '  "summary": "해당 기간의 주요 메일 내용을 3~5문장으로 한국어 요약",\n'
        '  "contacts": ["요약 내용과 관련된 메일을 주고받은 이메일 주소 목록"]\n'
        "}\n"
        "contacts는 아래 제공된 이메일 목록 중에서만 골라주세요."
    )
    user_prompt = f"[{period_label}] 이메일 목록: {contacts}\n\n메일 목록:\n\n{text}"

    # response_format=json_object여도 응답이 max_completion_tokens 한도에 걸려 중간에
    # 끊기면 JSON이 안 닫힌 채로 잘려서 json.loads가 실패함(실측 사례: 2023년치가
    # char 3707 지점에서 끊김 — 기존 한도 1000에 거의 다 채운 지점이라 토큰 한도 초과가
    # 원인으로 보임). 한도를 넉넉히 늘리고, 그래도 실패하면 최대 2번 더 재시도함(같은
    # 입력이어도 응답이 매번 조금씩 달라질 수 있어 다음 시도에서 정상적으로 끝날 수 있음).
    last_error = None
    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=os.getenv("SUB_TASK_CHAT_MODEL"),
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=2000
            )
            result = json.loads(response.choices[0].message.content)
            return {
                "summary":  result.get("summary", ""),
                "contacts": result.get("contacts", []),
            }
        except Exception as e:
            last_error = e
            print(f"[mail_summary] LLM 오류 ({period_label}, {attempt}/3번째 시도): {e}")

    print(f"[mail_summary] {period_label} 요약 {attempt}번 모두 실패, 빈 값으로 대체: {last_error}")
    return {"summary": "", "contacts": []}


# text_units.parquet을 파싱해 월별/연별 메일 요약을 만들고 JSON 저장 및 mail_summarize 테이블 저장까지 수행한다
def generate_mail_summaries(paths):
    import pandas as pd

    text_units_path = paths.RELATIONSHIPS_PATH.replace("relationships.parquet", "text_units.parquet")
    if not os.path.exists(text_units_path):
        print(f"[mail_summary] text_units.parquet 없음: {text_units_path}")
        return

    df = pd.read_parquet(text_units_path)

    mails = []
    seen_ids = set()

    for _, row in df.iterrows():
        text = str(row.get('text', ''))

        mail_id = _extract_field(text, 'ID')
        if not mail_id or mail_id in seen_ids:
            continue
        seen_ids.add(mail_id)

        date_str = _extract_field(text, '날짜')
        if not date_str:
            continue

        try:
            date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        sender_raw     = _extract_field(text, '발신인') or ""
        receiver_raw   = _extract_field(text, '수신인') or ""
        sender_email   = _extract_email(sender_raw)
        receiver_email = _extract_email(receiver_raw)

        mails.append({
            "date":           date,
            "year":           date.strftime("%Y"),
            "month":          date.strftime("%Y-%m"),
            "subject":        _extract_field(text, '제목') or "",
            "sender":         sender_raw,
            "sender_email":   sender_email,
            "receiver_email": receiver_email,
            "body":           _extract_body(text)[:500],
        })

    if not mails:
        print("[mail_summary] 요약할 메일 없음")
        return

    mails.sort(key=lambda x: x["date"])

    monthly_groups = {}
    yearly_groups  = {}
    for mail in mails:
        monthly_groups.setdefault(mail["month"], []).append(mail)
        yearly_groups.setdefault(mail["year"],  []).append(mail)

    # 그룹의 메일들을 제목/발신인/내용 형식으로 합쳐 LLM 입력 텍스트로 만든다
    def _build_text(group):
        return "\n\n".join(
            f"제목: {m['subject']}\n발신인: {m['sender']}\n내용: {m['body']}"
            for m in group
        )

    # 그룹 내 모든 메일의 발신/수신 이메일 주소를 정렬된 리스트로 모은다 (본인 제외)
    my_email = (paths.USER_ID or "").lower()

    def _collect_contacts(group):
        emails = set()
        for m in group:
            if m.get("sender_email") and m["sender_email"].lower() != my_email:
                emails.add(m["sender_email"])
            if m.get("receiver_email") and m["receiver_email"].lower() != my_email:
                emails.add(m["receiver_email"])
        return sorted(emails)

    # 기간 그룹 하나를 LLM 요약해 (kind, period, 요약결과)를 반환한다
    def _summarize_group(kind, period, group):
        print(f"[mail_summary] {kind} 요약 중: {period} ({len(group)}건)")
        return kind, period, _summarize_with_llm(_build_text(group), period, _collect_contacts(group))

    jobs = [("monthly", month, group) for month, group in monthly_groups.items()] + \
           [("yearly", year, group) for year, group in yearly_groups.items()]

    monthly_summaries = {}
    yearly_summaries = {}
    with ThreadPoolExecutor(max_workers=min(len(jobs), 15)) as executor:
        futures = [executor.submit(_summarize_group, kind, period, group) for kind, period, group in jobs]
        for future in as_completed(futures):
            kind, period, summary = future.result()
            (monthly_summaries if kind == "monthly" else yearly_summaries)[period] = summary

    result = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "yearly":  yearly_summaries,
        "monthly": monthly_summaries,
    }

    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(paths.MAIL_SUMMARIES_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[mail_summary] 저장 완료: {paths.MAIL_SUMMARIES_PATH}")

    save_mail_summarize_to_db(paths)
