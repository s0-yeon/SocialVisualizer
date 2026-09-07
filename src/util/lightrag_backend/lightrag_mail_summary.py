# src/util/lightrag_backend/lightrag_mail_summary.py

# LightRAG용 메일 월별/연별 요약 생성 모듈. 
# mail_latest.txt를 파싱해 메일을 월/연 단위로 묶고, 그룹별로 LLM에 넘겨 요약문과 관련 연락처를 받아 mail_summaries.json에 저장한 뒤 mail_summarize 테이블 저장과 요약 삽화 생성까지 이어서 처리한다.

# Generates monthly/yearly mail summaries for LightRAG. 
# Parses mail_latest.txt, groups mails by month and year, sends each group to an LLM for a summary and related contacts,saves the result to mail_summaries.json, then persists it to the mail_summarize table and generates summary illustrations.

import os
import json
import datetime
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed

from util.database.db_writer import save_mail_summarize_to_db
from util.lightrag_backend.lightrag_mail_parser import parse_mail_blocks, extract_email
from util.summary_image_generator import generate_mail_summary_images


# 메일 목록을 LLM에 넘겨 해당 기간 요약과 관련 이메일 주소 목록을 JSON으로 받아온다
def _summarize_with_llm(text, period_label, contacts):
    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,  # 지정 시 로컬 Qwen으로 라우팅
    )
    try:
        response = client.chat.completions.create(
            model=os.environ.get("SUB_TASK_CHAT_MODEL", "gpt-4o-mini"),  # 요약 대상 목록 압축 = 보조 작업
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "주어진 이메일 목록을 분석하여 아래 JSON 형식으로만 응답하세요.\n"
                        "{\n"
                        '  "summary": "해당 기간의 주요 메일 내용을 3~5문장으로 한국어 요약",\n'
                        '  "contacts": ["요약 내용과 관련된 메일을 주고받은 이메일 주소 목록"]\n'
                        "}\n"
                        "contacts는 아래 제공된 이메일 목록 중에서만 골라주세요."
                    )
                },
                {
                    "role": "user",
                    "content": f"[{period_label}] 이메일 목록: {contacts}\n\n메일 목록:\n\n{text}"
                }
            ],
            max_completion_tokens=1000  # SUB_TASK_CHAT_MODEL이 gpt-5 계열이면 max_tokens 대신 이 파라미터를 받는다
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "summary":  result.get("summary", ""),
            "contacts": result.get("contacts", []),
        }
    except Exception as e:
        print(f"[mail_summary][lightrag] LLM 오류 ({period_label}): {e}")
        return {"summary": "", "contacts": []}


# mail_latest.txt를 파싱해 월별/연별 메일 요약을 만들고 JSON 저장 및 mail_summarize 테이블 저장, 삽화 생성까지 수행한다
def generate_mail_summaries_lightrag(paths):
    records = parse_mail_blocks(paths)
    if not records:
        print(f"[mail_summary][lightrag] mail_latest.txt 없음/비어있음 → 요약 건너뜀")
        return

    mails = []
    for r in records:
        date_str = r["date"]
        if not date_str:
            continue
        try:
            date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        mails.append({
            "date":           date,
            "year":           date.strftime("%Y"),
            "month":          date.strftime("%Y-%m"),
            "subject":        r["subject"],
            "sender":         r["sender"],
            "sender_email":   extract_email(r["sender"]),
            "receiver_email": extract_email(r["receiver"]),
            "body":           r["body"][:500],
        })

    if not mails:
        print("[mail_summary][lightrag] 요약할 메일 없음")
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
        print(f"[mail_summary][lightrag] {kind} 요약 중: {period} ({len(group)}건)")
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

    print(f"[mail_summary][lightrag] 저장 완료: {paths.MAIL_SUMMARIES_PATH}")

    save_mail_summarize_to_db(paths)
    generate_mail_summary_images(paths)
