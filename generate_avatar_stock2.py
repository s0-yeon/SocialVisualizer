# generate_avatar_stock2.py
# soyeon@icloud 계정에서 avatar_stock/avatar_stock1/avatar_test_output/avatar_test_output1
# 이미지로 매칭되지 않고 남은 연락처들의 아바타를, 켜둔 FLUX 서버(로컬 8005 포트로 SSH 터널링된
# GPU 서버)를 이용해 새로 생성하고, MailGrapher 루트의 avatar_stock2/ 폴더에 저장한다.
#
# - 이 계정(soyeon@icloud)의 person_avatars.json에 이미 들어있는 이메일(=이미 매칭 완료된
#   179명)은 건너뛴다.
# - avatar_stock2/에 이미 만들어둔 파일(파일명에 이메일 해시가 들어있음)이 있으면 건너뛰므로,
#   중간에 멈췄다가 다시 실행해도 이어서 생성한다(재시작 안전).
# - FLUX 서버가 사실상 순차 처리라 한 번에 하나씩만 요청한다. 713명이면 상당히 오래 걸릴 수
#   있으니(이미지 1장당 수십 초 단위), 오래 켜둘 수 있는 터미널에서 실행하는 걸 권장한다.
# - 이 스크립트가 만드는 이미지는 이 계정에 바로 매칭(person_avatars.json에 반영)하지 않고
#   avatar_stock2/에만 쌓아둔다 — "생성한 이미지는 avatar_stock2 만들어서 저장해줘"라는 요청대로.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   가상환경 켜고 -> python generate_avatar_stock2.py

import sys
import os
import json
import hashlib
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from util.avatar_generator import generate_avatar_image_bytes

USER_ID = "soyeon@icloud"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONTACTS_PATH = os.path.join(
    BASE_DIR, "user_data", "mail", "soyeon_at_icloud", "graphrag", "parquet",
    "output", "statics", "mail_contact_stats.json",
)
PERSON_AVATARS_PATH = os.path.join(
    BASE_DIR, "user_data", "mail", "soyeon_at_icloud", "graphrag", "parquet",
    "output", "statics", "person_avatars.json",
)
STOCK2_DIR = os.path.join(BASE_DIR, "avatar_stock2")


def safe_name_for_filename(name: str) -> str:
    name = (name or "").strip()
    # 파일명에 못 쓰는 문자만 제거하고, 이름이 아예 없으면 익명 처리
    cleaned = "".join(c for c in name if c not in '\\/:*?"<>|').strip()
    return cleaned or "무명"


def email_hash8(email: str) -> str:
    digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    # 앞의 avatar_stock 파일들과 비슷하게 숫자 8자리로 보이도록 변환
    return str(int(digest[:12], 16))[-8:].zfill(8)


def main():
    os.makedirs(STOCK2_DIR, exist_ok=True)

    with open(CONTACTS_PATH, "r", encoding="utf-8") as f:
        contacts = json.load(f)

    with open(PERSON_AVATARS_PATH, "r", encoding="utf-8") as f:
        already_matched = set(json.load(f).keys())

    # 이미 avatar_stock/1, test_output/1 으로 매칭된 179명은 person_avatars.json에 이미
    # 들어있으므로 자동으로 제외된다. 나머지(활동량 많은 순)를 대상으로 한다.
    items = []
    for email, info in contacts.items():
        if email in already_matched:
            continue
        total = int(info.get("sent", 0)) + int(info.get("received", 0))
        items.append((email, info.get("name", ""), total))
    items.sort(key=lambda x: x[2], reverse=True)

    print(f"### 남은 대상: {len(items)}명 (이미 매칭된 {len(already_matched)}명 제외)")

    existing_files = set(os.listdir(STOCK2_DIR))

    ok_count = 0
    fail_count = 0
    skip_count = 0

    for idx, (email, name, total) in enumerate(items, start=1):
        h8 = email_hash8(email)
        # 이미 이 이메일로 생성해둔 파일이 있으면 건너뛴다(파일명에 해시가 들어있어 재시작해도 중복 생성 안 함)
        already_done = any(h8 in fn for fn in existing_files)
        if already_done:
            skip_count += 1
            continue

        display_name = safe_name_for_filename(name)
        filename = f"{idx:03d}_{display_name}_{h8}.png"
        filepath = os.path.join(STOCK2_DIR, filename)

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
    print(f"저장 위치: {STOCK2_DIR}")


if __name__ == "__main__":
    main()
