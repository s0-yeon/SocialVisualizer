# src/util/lightrag_backend/lightrag_mail_parser.py

# LightRAG용 메일 원문 파서. 
# mail_latest.txt에 쌓인 메일 블록 텍스트를 읽어 메일 한 통당 dict(id/date/subject/sender/receiver/direction/folder/body)로 분해하고, "이름 <이메일>" 형식 문자열에서 이메일 주소만 뽑아내는 기능을 제공한다. 
# 통계 생성, DB 저장, 요약 등 LightRAG 하위 모듈들이 메일 텍스트를 다룰 때 공통으로 거치는 진입점이다.

# Parses raw mail block text accumulated in mail_latest.txt for LightRAG into per-mail dicts (id/date/subject/sender/receiver/direction/folder/body), and extracts a bare email address out of "Name <email>" style strings. 
# Shared entry point used by statics generation, DB writing, and summarization modules.

import os
import re

from config.settings import MAIL_BLOCK_SEP


# mail_latest.txt를 블록 구분자로 잘라 메일별 dict 리스트로 반환. id가 없거나 중복인 블록은 건너뛴다
def parse_mail_blocks(paths) -> list[dict]:
    if not os.path.exists(paths.MAIL_LATEST_PATH):
        return []

    with open(paths.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    records = []
    seen_ids = set()

    for block in text.split(MAIL_BLOCK_SEP):
        block = block.strip()
        if not block:
            continue

        # 대괄호/콜론 둘 다 가능
        id_m = re.search(r"^\s*(?:\[ID\]|ID:)\s*(.+?)\s*$", block, re.MULTILINE)
        mail_id = id_m.group(1).strip() if id_m else None
        if not mail_id or mail_id in seen_ids:
            continue
        seen_ids.add(mail_id)

        date_m = re.search(r"^\s*(?:\[날짜\]|날짜:)\s*(.+?)\s*$", block, re.MULTILINE)
        subject_m = re.search(r"^\s*(?:\[제목\]|제목:)\s*(.+?)\s*$", block, re.MULTILINE)
        sender_m = re.search(r"^\s*(?:\[발신인\]|발신인:)\s*(.+?)\s*$", block, re.MULTILINE)
        receiver_m = re.search(r"^\s*(?:\[수신인\]|수신인:)\s*(.+?)\s*$", block, re.MULTILINE)
        direction_m = re.search(r"^\s*(?:\[구분\]|구분:)\s*(.+?)\s*$", block, re.MULTILINE)
        folder_m = re.search(r"\[라벨 정보\]\s*\n(.+)", block)
        body_m = re.search(r"\[메일 본문\]\s*\n(.*?)(?:\n=+|\Z)", block, re.DOTALL)

        folder_raw = folder_m.group(1).strip() if folder_m else None
        if folder_raw == "없음":
            folder_raw = None

        records.append({
            "id": mail_id,
            "date": date_m.group(1).strip() if date_m else None,
            "subject": subject_m.group(1).strip() if subject_m else "",
            "sender": sender_m.group(1).strip() if sender_m else "",
            "receiver": receiver_m.group(1).strip() if receiver_m else "",
            "direction_raw": direction_m.group(1).strip() if direction_m else None,
            "folder": folder_raw,
            "body": body_m.group(1).strip() if body_m else "",
        })

    return records


# "Name <email>" 형태 문자열에서 꺾쇠 안 이메일 주소만 소문자로 추출. 꺾쇠가 없으면 원문 전체를 소문자로 반환
def extract_email(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return m.group(1).strip().lower() if m else raw.strip().lower()
