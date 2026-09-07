# 메일 메시지의 헤더·본문·첨부파일을 파싱해 인덱싱용 텍스트 블록으로 변환한다.

# Parses a mail message's headers, body, and attachments and converts it into a text block for indexing.

import re
import os
import base64
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime

from config.settings import MAIL_BLOCK_SEP

IMAP_SUPPORTED_ATT_EXTS = {".pdf", ".docx", ".hwp", ".pptx", ".xlsx", ".csv", ".txt"}
IMAP_MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB

# 마케팅 메일이 프리헤더(받은편지함 미리보기 줄)를 채우는 데 쓰는 폭 0 문자들.
# ZWSP/ZWNJ/ZWJ/LRM/RLM, 방향 제어 문자(202A-202E), 워드조이너, BOM/ZWNBSP.
_INVISIBLE_CHARS = "".join(chr(c) for c in (
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2060, 0xFEFF,
))

# MIME 인코딩된 메일 헤더 값(Subject 등)을 디코딩해 문자열로 반환한다
def _imap_decode_header_str(raw) -> str:
    if not raw:
        return ""
    decoded = ""
    for text, enc in decode_header(raw):
        if isinstance(text, bytes):
            try:
                decoded += text.decode(enc or "utf-8", errors="replace")
            except (LookupError, UnicodeDecodeError):
                decoded += text.decode("utf-8", errors="replace")
        else:
            decoded += text
    return decoded.strip()

# 이름/주소를 "이름 <계정>" 형식 문자열로 만든다 (이름 없으면 계정 로컬파트를 사용)
def _imap_format_person(name: str, addr: str) -> str:
    name = (name or "").strip()
    addr = (addr or "").strip().lower()
    if not addr:
        return "없음"
    if not name:
        name = addr.split("@")[0]
    if name.lower() != addr:
        return f"{name} <{addr}>"
    return f"<{addr}>"

# To/Cc 같은 주소 헤더를 파싱해 (이름, 주소) 튜플 리스트로 반환한다
def _imap_parse_person_list(raw_header) -> list[tuple[str, str]]:
    if not raw_header:
        return []
    people = []
    for name, addr in getaddresses([raw_header]):
        addr = (addr or "").strip()
        if addr:
            people.append((_imap_decode_header_str(name), addr))
    return people

# 메일 본문을 추출한다 (text/plain 우선, 없으면 text/html에서 태그·링크·불가시문자 제거)
def _imap_extract_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition") or "")
            if part.get_content_type() == "text/plain" and "attachment" not in disp.lower():
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True) or b""
                try:
                    body = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    body = payload.decode("utf-8", errors="replace")
                break
        if not body:
            for part in msg.walk():
                disp = str(part.get("Content-Disposition") or "")
                if part.get_content_type() == "text/html" and "attachment" not in disp.lower():
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True) or b""
                    try:
                        body = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        body = payload.decode("utf-8", errors="replace")
                    break
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                body = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                body = payload.decode("utf-8", errors="replace")

    # 최종 본문에 남은 태그/주석은 방어적으로 한 번 더 제거한다.
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.DOTALL)  # HTML 주석(조건부 주석 포함) 제거
    # <style>/<script> 블록 내용째로 제거
    body = re.sub(r"<style[^>]*>.*?</style>", " ", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<script[^>]*>.*?</script>", " ", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<[^>]+>", " ", body)

    # 본문에 남는 링크(구독 해지/추적 URL 등) 제거
    body = re.sub(r"https?://\S+", " ", body)

    # 폭 0 문자(ZWNJ/ZWJ/LRM/RLM/BOM 등) 제거 
    # display:none 처리된 프리헤더 속 내용 제거
    body = re.sub(f"[{_INVISIBLE_CHARS}]", "", body)

    body = body.replace("\r\n", "\n")
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()

# 메일의 첨부파일을 훑어 (전체 메타 정보 리스트, 지원 형식·용량 내 실제 데이터 payload 리스트)를 반환한다
def _imap_collect_attachments(msg) -> tuple[list[dict], list[dict]]:
    infos, payloads = [], []
    if not msg.is_multipart():
        return infos, payloads

    idx = 0
    for part in msg.walk():
        disp = str(part.get("Content-Disposition") or "")
        if "attachment" not in disp.lower():
            continue
        idx += 1
        filename = _imap_decode_header_str(part.get_filename()) or f"attachment_{idx}"
        mime = part.get_content_type() or "application/octet-stream"
        data = part.get_payload(decode=True) or b""
        size = len(data)
        ext = os.path.splitext(filename)[-1].lower()
        supported = ext in IMAP_SUPPORTED_ATT_EXTS

        if not supported:
            status = "제외: 형식 미지원"
        elif size > IMAP_MAX_ATTACHMENT_SIZE:
            status = "제외: 용량 초과"
        else:
            status = "포함"

        infos.append({"name": filename, "mime": mime, "size": size, "status": status})
        if supported and size <= IMAP_MAX_ATTACHMENT_SIZE:
            payloads.append({"name": filename, "mime": mime, "data": data})

    return infos, payloads

# 메일 하나를 인덱싱용 텍스트 블록으로 변환하고 첨부 payload 리스트와 함께 반환한다
def _imap_build_block(mail_index: int, mail_id: str, msg, folder: str, my_email: str) -> tuple[str, list[dict]]:
    subject = _imap_decode_header_str(msg.get("Subject")) or "(제목 없음)"

    from_list = _imap_parse_person_list(msg.get("From"))
    from_name, from_addr = from_list[0] if from_list else ("", "")
    direction = "발신" if from_addr.lower() == my_email.strip().lower() else "수신"

    to_list = _imap_parse_person_list(msg.get("To"))
    cc_list = _imap_parse_person_list(msg.get("Cc"))

    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        date_str = ""

    att_infos, att_payloads = _imap_collect_attachments(msg)
    if att_infos:
        attachment_info = "\n".join(
            f"- {a['name']} ({a['size']/1024:.1f} KB) ({a['status']})" for a in att_infos
        )
    else:
        attachment_info = "없음"

    body = _imap_extract_body(msg)

    block_text = "\n".join([
        MAIL_BLOCK_SEP,
        f"[메일 {mail_index}]",
        "",
        f"[ID] {mail_id}",
        f"[제목] {subject}",
        f"[구분] {direction}",
        f"[날짜] {date_str}",
        f"[발신인] {_imap_format_person(from_name, from_addr)}",
        "[수신인] " + (", ".join(_imap_format_person(n, a) for n, a in to_list) if to_list else "없음"),
        "[참조(CC)] " + (", ".join(_imap_format_person(n, a) for n, a in cc_list) if cc_list else "없음"),
        f"[폴더 정보] {folder}",
        "",
        "[메일 본문]",
        body if body.strip() else "(none)",
        "",
        "[첨부파일 정보]",
        attachment_info,
        MAIL_BLOCK_SEP,
    ])

    attachments_payload = [
        {
            "mail_id": mail_id,
            "name": a["name"],
            "mime": a["mime"],
            "data_base64": base64.b64encode(a["data"]).decode("ascii"),
        }
        for a in att_payloads
    ]

    return block_text, attachments_payload
