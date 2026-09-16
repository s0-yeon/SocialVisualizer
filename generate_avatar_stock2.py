# generate_avatar_stock2.py
# 지정한 계정에서 person_avatars.json에 아직 매칭되지 않은 연락처들의 아바타를,
# 켜둔 FLUX 서버(로컬 8005 포트로 SSH 터널링된 GPU 서버)를 이용해 새로 생성하고,
# MailGrapher 루트의 avatar_stock2/<계정폴더명>/ 에 저장한다.
#
# - 이 계정의 person_avatars.json에 이미 들어있는 이메일(이미 매칭 완료)은 건너뛴다.
# - avatar_stock2/<계정폴더명>/에 이미 만들어둔 파일(파일명에 이메일 해시가 들어있음)이
#   있으면 건너뛰므로, 중간에 멈췄다가 다시 실행해도 이어서 생성한다(재시작 안전).
# - FLUX 서버가 사실상 순차 처리라 한 번에 하나씩만 요청한다. 인원이 많으면 상당히
#   오래 걸릴 수 있으니(이미지 1장당 수십 초 단위), 오래 켜둘 수 있는 터미널에서
#   실행하는 걸 권장한다. 계정마다 따로(동시에 X) 실행하세요 — 같은 FLUX 서버를
#   나눠 쓰면 서로 느려질 뿐 병렬로 빨라지지 않습니다.
# - 이 스크립트가 만드는 이미지는 계정에 바로 매칭(person_avatars.json에 반영)하지
#   않고 avatar_stock2/<계정폴더명>/에만 쌓아둔다.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고, 가상환경 켜고 실행하세요:
#   python generate_avatar_stock2.py soyeon@icloud
#   python generate_avatar_stock2.py 03yeeun03@naver.com
# 인자를 안 주면 기본값으로 soyeon@icloud를 처리합니다.

import sys
import os
import json
import hashlib
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from util.avatar_generator import generate_avatar_image_bytes, _classify_sender
from util.user_path import UserPaths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_USER_ID = "soyeon@icloud"


def safe_name_for_filename(name: str) -> str:
    name = (name or "").strip()
    cleaned = "".join(c for c in name if c not in '\\/:*?"<>|').strip()
    return cleaned or "무명"


def email_hash8(email: str) -> str:
    digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    return str(int(digest[:12], 16))[-8:].zfill(8)


def main():
    user_id = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_USER_ID
    paths = UserPaths(BASE_DIR, user_id, "mail")

    # soyeon@icloud는 기존에 이미 avatar_stock2/ 바로 밑에 결과물이 쌓여있으므로(하위 폴더 없이),
    # 그 계정만 기존 위치를 그대로 쓰고, 새로 추가하는 다른 계정은 서로 안 섞이게
    # avatar_stock2/<계정폴더명>/ 하위 폴더를 쓴다.
    if user_id == DEFAULT_USER_ID:
        stock2_dir = os.path.join(BASE_DIR, "avatar_stock2")
    else:
        stock2_dir = os.path.join(BASE_DIR, "avatar_stock2", os.path.basename(paths.USER_ROOT))
    os.makedirs(stock2_dir, exist_ok=True)

    print(f"### 대상 계정: {user_id}")
    print(f"### 저장 위치: {stock2_dir}")

    if not os.path.exists(paths.MAIL_CONTACTS_PATH):
        print(f"[중단] 연락처 통계 파일이 없습니다: {paths.MAIL_CONTACTS_PATH}")
        return

    with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
        contacts = json.load(f)

    already_matched = set()
    if os.path.exists(paths.MAIL_AVATARS_PATH):
        with open(paths.MAIL_AVATARS_PATH, "r", encoding="utf-8") as f:
            already_matched = set(json.load(f).keys())

    candidates = []
    for email, info in contacts.items():
        if email in already_matched:
            continue
        total = int(info.get("sent", 0)) + int(info.get("received", 0))
        candidates.append((email, info.get("name", ""), total))
    candidates.sort(key=lambda x: x[2], reverse=True)

    print(f"### 아바타 없는 연락처 {len(candidates)}명 — 이 중 '사람'으로 판별되는 연락처만 일러스트 대상으로 삼는다(브랜드/기업은 로고 전용 스크립트가 처리)")

    items = []
    brand_skipped = 0
    for email, name, total in candidates:
        domain_part = email.split("@", 1)[1] if "@" in email else ""
        try:
            brand_domain = _classify_sender(name, domain_part)
        except Exception as e:
            print(f"  [분류 실패, 사람으로 취급] {email} ({name}) - {e}")
            brand_domain = None
        if brand_domain:
            brand_skipped += 1
            continue
        items.append((email, name, total))

    print(f"### 최종 대상: {len(items)}명 (이미 매칭된 {len(already_matched)}명 제외, 브랜드로 판별되어 제외 {brand_skipped}명)")

    existing_files = set(os.listdir(stock2_dir))

    ok_count = 0
    fail_count = 0
    skip_count = 0

    for idx, (email, name, total) in enumerate(items, start=1):
        h8 = email_hash8(email)
        already_done = any(h8 in fn for fn in existing_files)
        if already_done:
            skip_count += 1
            continue

        display_name = safe_name_for_filename(name)
        filename = f"{idx:03d}_{display_name}_{h8}.png"
        filepath = os.path.join(stock2_dir, filename)

        try:
            t0 = time.time()
            image_bytes = generate_avatar_image_bytes(name or email, "", email)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            elapsed = time.time() - t0
            ok_count += 1
            print(f"[{idx}/{len(items)}] 생성 완료: {email} ({name}) -> {filename} ({elapsed:.1f}s)")
        except Exception as e:
            fail_count += 1
            print(f"[{idx}/{len(items)}] 생성 실패: {email} ({name}) - {e}")

    print()
    print(f"완료. 성공 {ok_count}건 / 실패 {fail_count}건 / 이미 있어서 건너뜀 {skip_count}건")
    print(f"저장 위치: {stock2_dir}")


if __name__ == "__main__":
    main()
