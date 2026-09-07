# IMAP 서버에 로그인해 선택한 폴더의 메일을 가져오고, 폴더명 인코딩/디코딩과 플랫폼 판별 등 수집에 필요한 기능을 처리한다.

# Logs into the IMAP server to fetch mail from the selected folders, handling folder-name encoding/decoding and platform detection needed for collection.

import base64
import re
import imaplib
import email
import traceback

from util.imap_message import _imap_build_block

IMAP_FETCH_BATCH_SIZE = 50 # 한 번의 FETCH 요청으로 가져올 메일 개수

# IMAP 호스트 → 실제 메일 플랫폼 이름 매핑 (mail_account.mail_platform에 저장)
_IMAP_HOST_PLATFORM_MAP = {
    "imap.gmail.com": "gmail",
    "imap.naver.com": "naver",
    "imap.daum.net": "daum",
    "imap.mail.me.com": "icloud",
    "imap.kakao.com": "kakao",
    "imap.mail.yahoo.com": "yahoo",
}

# IMAP 호스트명으로 메일 플랫폼 이름을 판별한다 (매핑에 없으면 도메인에서 추정)
def _detect_imap_platform(host: str) -> str:
    host_lower = (host or "").strip().lower()
    if host_lower in _IMAP_HOST_PLATFORM_MAP:
        return _IMAP_HOST_PLATFORM_MAP[host_lower]
    # 매핑에 없는 커스텀 호스트는 도메인에서 서비스명을 추정 (예: imap.foo.co.kr -> foo)
    labels = [p for p in host_lower.split(".") if p not in ("imap", "mail", "www")]
    if len(labels) >= 2:
        return labels[-2]
    return host_lower or "imap"

# 폴더명을 IMAP Modified UTF-7(RFC 3501)로 인코딩한다
def _imap_utf7_encode_folder(folder: str) -> str:
    result = bytearray()
    i, n = 0, len(folder)
    while i < n:
        ch = folder[i]
        if ch == "&":
            result.extend(b"&-")
            i += 1
            continue
        if 0x20 <= ord(ch) <= 0x7e:
            result.append(ord(ch))
            i += 1
            continue
        j = i
        while j < n and not (0x20 <= ord(folder[j]) <= 0x7e):
            j += 1
        chunk = folder[i:j]
        b64 = base64.b64encode(chunk.encode("utf-16-be")).decode("ascii")
        b64 = b64.rstrip("=").replace("/", ",")
        result.extend(b"&" + b64.encode("ascii") + b"-")
        i = j
    return result.decode("ascii")

# IMAP Modified UTF-7(RFC 3501) 폴더명을 일반 문자열로 디코딩한다
def _imap_utf7_decode_folder(name: str) -> str:
    result = []
    i, n = 0, len(name)
    while i < n:
        ch = name[i]
        if ch != "&":
            result.append(ch)
            i += 1
            continue
        j = name.find("-", i)
        if j == -1:
            j = n
        b64 = name[i + 1:j]
        if b64 == "":
            result.append("&")
        else:
            b64 = b64.replace(",", "/")
            b64 += "=" * ((-len(b64)) % 4)
            try:
                result.append(base64.b64decode(b64).decode("utf-16-be"))
            except Exception:
                result.append(name[i:j + 1])
        i = j + 1
    return "".join(result)

# 이미 만든 메일 블록의 '[폴더 정보]' 줄에 새 폴더 이름을 콤마로 덧붙인다 (중복 메일 재생성 방지)
def _add_folder_label(block_text: str, new_folder: str) -> str:
    m = re.search(r'(\[폴더 정보\]\s*)(.*)', block_text)
    if not m:
        return block_text
    existing = [f.strip() for f in m.group(2).split(',') if f.strip()]
    if new_folder in existing:
        return block_text
    existing.append(new_folder)
    return block_text[:m.start(2)] + ", ".join(existing) + block_text[m.end(2):]

# IMAP LIST 응답 한 줄을 파싱해 선택 가능한 폴더명을 반환한다 (Noselect/파싱 실패 시 None)
def _imap_parse_list_line(line: bytes):
    try:
        text = line.decode("utf-8", errors="replace").strip()
    except Exception:
        return None

    m = re.match(r'^\(([^)]*)\)\s+(?:"([^"]*)"|NIL)\s+(.+)$', text)
    if not m:
        return None

    flags = m.group(1)
    if "\\Noselect" in flags:
        return None  # 선택 불가능한 폴더는 제외

    raw_name = m.group(3).strip()
    if raw_name.startswith('"') and raw_name.endswith('"'):
        raw_name = raw_name[1:-1]

    return _imap_utf7_decode_folder(raw_name)

# IMAP 서버에 로그인해 선택한 폴더들의 메일을 가져와 (블록 텍스트, 첨부 payload 리스트)로 반환한다
def _imap_fetch_content(host: str, port: int, use_ssl: bool, user: str, password: str,
                         folders: list[str], limit: int, my_email: str, on_batch=None) -> tuple[str, list[dict]]:
    conn = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)

    try:
        conn.login(user, password)

        all_blocks: list[str] = []
        all_attachments: list[dict] = []
        mail_index = 0
        block_index_by_id: dict[str, int] = {}  # 이미 만든 블록을 폴더별로 다시 찾아 라벨만 덧붙이기 위한 인덱스

        for folder in folders:
            encoded_folder = _imap_utf7_encode_folder(folder)
            status, _resp = conn.select(f'"{encoded_folder}"', readonly=True)
            if status != "OK":
                status, _resp = conn.select(encoded_folder, readonly=True)
            if status != "OK":
                print(f"[IMAP] 폴더 선택 실패, 스킵: {folder}")
                continue

            status, data = conn.uid("search", None, "ALL")
            if status != "OK" or not data or not data[0]:
                continue

            uids = data[0].split()
            uids.reverse()  # 최신 메일부터
            if limit and limit > 0:
                uids = uids[:limit]

            total_batches = (len(uids) + IMAP_FETCH_BATCH_SIZE - 1) // IMAP_FETCH_BATCH_SIZE
            for batch_num, batch_start in enumerate(range(0, len(uids), IMAP_FETCH_BATCH_SIZE), start=1):
                batch = uids[batch_start:batch_start + IMAP_FETCH_BATCH_SIZE]
                batch_arg = b",".join(batch)

                try:
                    status, msg_data = conn.uid("fetch", batch_arg, "(BODY.PEEK[])")
                except Exception as e:
                    print(f"[IMAP] 배치 FETCH 오류, 스킵: uids={batch} / {e}")
                    traceback.print_exc()
                    continue

                if status != "OK" or not msg_data:
                    continue

                # 응답 순서가 요청 순서와 다를 수 있어 UID로 매칭해서 원래 순서(최신순)를 유지한다
                raw_by_uid: dict[str, bytes] = {}
                ordered_raw: list[bytes] = []
                for part in msg_data:
                    if not (isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray))):
                        continue
                    header = part[0]
                    header_str = header.decode(errors="ignore") if isinstance(header, (bytes, bytearray)) else str(header)
                    ordered_raw.append(part[1])
                    m = re.search(r"UID (\d+)", header_str)
                    if m:
                        raw_by_uid[m.group(1)] = part[1]

                # 일부 서버(네이버 등)는 배치 UID FETCH 응답 헤더에 UID를 안 돌려줘서 위 정규식 매칭이 전부 실패할 수 있다.
                # 이 경우 응답 순서 = 요청 순서라고 가정하고 위치 기반으로 매칭
                if not raw_by_uid and ordered_raw:
                    if len(ordered_raw) != len(batch):
                        print(f"[IMAP] 위치 기반 폴백 매칭 개수 불일치: 응답 {len(ordered_raw)}개 vs 요청 {len(batch)}개")
                    raw_by_uid = {
                        (uid.decode(errors="ignore") if isinstance(uid, bytes) else str(uid)): raw
                        for uid, raw in zip(batch, ordered_raw)
                    }

                for uid in batch:
                    uid_str = uid.decode(errors="ignore") if isinstance(uid, bytes) else str(uid)
                    raw_email = raw_by_uid.get(uid_str)
                    if raw_email is None:
                        print(f"[IMAP] RFC822 본문 없음, 스킵: uid={uid_str}")
                        continue

                    try:
                        msg = email.message_from_bytes(raw_email)
                    except Exception as e:
                        print(f"[IMAP] 메일 파싱 오류, 스킵: uid={uid_str} / {e}")
                        traceback.print_exc()
                        continue

                    message_id = (msg.get("Message-ID") or "").strip().strip("<>")
                    if not message_id:
                        message_id = f"{folder}-{uid_str}"

                    # 이전 폴더에서 이미 수집된 메일이면 블록을 새로 안 만들고 라벨 정보만 이 폴더로 덧붙인다
                    if message_id in block_index_by_id:
                        idx = block_index_by_id[message_id]
                        all_blocks[idx] = _add_folder_label(all_blocks[idx], folder)
                        continue

                    mail_index += 1
                    block_text, attachments_payload = _imap_build_block(mail_index, message_id, msg, folder, my_email)
                    all_blocks.append(block_text)
                    block_index_by_id[message_id] = len(all_blocks) - 1
                    all_attachments.extend(attachments_payload)

                if on_batch:
                    try:
                        on_batch(folder, batch_num, total_batches, len(batch))
                    except Exception:
                        pass  # 진행상황 알림 실패는 수집 자체를 막으면 안 되므로 무시

        content = "\n\n".join(all_blocks).strip()
        if content:
            content += "\n"
        return content, all_attachments

    finally:
        try:
            conn.logout()
        except Exception:
            pass