# generate_logos_only.py
#
# 03yeeun03@naver.com, soyeon@icloud 두 계정에서 "사람"이 아니라 "기업/브랜드/발신전용"으로
# 판별되는 연락처만 골라 실제 회사 로고(Clearbit/구글 파비콘, 또는 하드코딩된 로고)를
# 아바타로 채워넣는다. FLUX 이미지 서버(GPU, localhost:8005)는 전혀 쓰지 않는다 —
# 지금 avatar_stock2 생성 스크립트가 그 서버를 계속 붙잡고 있어서, 그거 끝날 때까지
# 기다리지 않고 로고만이라도 먼저 채우기 위한 스크립트다.
#
# - 앱이 실제로 쓰는 _classify_sender()(사람/기업 LLM 판별) + _fetch_company_logo()
#   (Clearbit/구글 파비콘/하드코딩 로고)를 그대로 재사용한다. 둘 다 FLUX가 아니라
#   텍스트 LLM(SUB_TASK_API_BASE)과 일반 인터넷 요청만 쓰므로 GPU 서버 상태와 무관하다.
# - 사람으로 판별된 연락처는 건너뛴다 — 이 스크립트는 로고만 다루고, FLUX로 그리는
#   일러스트 아바타는 절대 만들지 않는다(그건 기존 앱 로직/avatar_stock류가 담당).
# - 이미 아바타(로고든 일러스트든)가 있는 연락처도 건너뛴다.
# - person_avatars.json/avatars 폴더에 앱과 완전히 같은 형식으로 저장하므로, 실행 후
#   새로고침만 하면 바로 My People 화면에 반영된다.
# - "광고 제거" 토글(mypeopleEngine.js의 isGenericLocalPart/isBrandDisplayName)은
#   이메일 로컬파트·표시이름만 보는 별개의 프론트엔드 로직이라 이 스크립트가 따로
#   손댈 부분은 없다 — 다만 여기서 로고를 채워준 연락처는 실제로도 발신전용/기업
#   계정일 확률이 높아서, 그 토글로 걸러질 때 "로고 없이 이니셜만 뜨는" 어색함 없이
#   자연스럽게 같이 맞아떨어진다.
# - 중간에 멈췄다가 다시 실행해도 이미 로고가 붙은 연락처는 건너뛰므로 재시작 안전하다.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고, 가상환경 켜고 실행하세요:
#   python generate_logos_only.py

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from util.user_path import UserPaths
from util.avatar_generator import (
    _load_avatar_map,
    _save_avatar_map,
    _avatar_url_file_exists,
    _avatar_filename,
    _classify_sender,
    _fetch_company_logo,
)
from util.database.db_reader import get_all_persons

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# (user_id, domain) — 필요하면 여기에 계정을 더 추가하면 된다.
TARGET_ACCOUNTS = [
    ("03yeeun03@naver.com", "mail"),
    ("soyeon@icloud", "mail"),
]


def process_account(user_id: str, domain: str):
    print(f"\n### {user_id} 처리 시작")
    paths = UserPaths(BASE_DIR, user_id, domain)
    os.makedirs(paths.AVATAR_IMAGES_DIR, exist_ok=True)

    persons = get_all_persons(paths.USER_ID)
    avatar_map = _load_avatar_map(paths)

    targets = []
    seen = set()
    for p in persons:
        email = (p.get("person_mail_account_id") or "").strip().lower()
        name = (p.get("person_name") or "").strip()
        if not email or email in seen:
            continue
        seen.add(email)
        if _avatar_url_file_exists(paths, avatar_map.get(email)):
            continue  # 이미 아바타(로고든 일러스트든) 있음 — 건너뜀
        domain_part = email.split("@", 1)[1] if "@" in email else ""
        targets.append((email, name, domain_part))

    print(f"아바타 없는 연락처 {len(targets)}명 — 이 중 '기업/브랜드'로 판별되는 사람만 로고를 붙인다")

    logo_count = 0
    person_count = 0
    fail_count = 0

    for idx, (email, name, domain_part) in enumerate(targets, start=1):
        try:
            brand_domain = _classify_sender(name, domain_part)
            if not brand_domain:
                # 실제 사람으로 판별됨 — 이 스크립트는 로고만 다루므로 건너뛴다
                # (일러스트 아바타는 FLUX 서버가 한가해지면 앱이 알아서 채워준다).
                person_count += 1
                continue

            image_bytes = _fetch_company_logo(brand_domain)
            if image_bytes is None:
                # 브랜드로는 판별됐는데 Clearbit/파비콘에서 실제 로고를 못 받아온 경우 —
                # 여기서도 FLUX로 대체 생성하지 않고 그냥 건너뛴다(로고 전용 스크립트이므로).
                print(f"[{idx}/{len(targets)}] 로고 못 찾음(브랜드 판별은 됨): {email} ({name}, {brand_domain})")
                fail_count += 1
                continue

            filename = _avatar_filename(email)
            filepath = os.path.join(paths.AVATAR_IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            url = f"/person-avatar-image/{paths.USER_ID}/{filename}"

            # 저장 직전에 다시 읽어서 병합 — 그 사이 다른 요청(앱 자체 배치 등)이
            # 채워놓은 항목을 덮어쓰지 않기 위함(avatar_generator.py의 기존 패턴과 동일).
            latest = _load_avatar_map(paths)
            latest[email] = url
            _save_avatar_map(paths, latest)

            logo_count += 1
            print(f"[{idx}/{len(targets)}] 로고 완료: {email} ({name}) -> {brand_domain}")
        except Exception as e:
            fail_count += 1
            print(f"[{idx}/{len(targets)}] 실패: {email} ({name}) - {e}")

    print(
        f"\n{user_id} 완료 — 로고 생성 {logo_count}건 / 사람이라 건너뜀 {person_count}건 / "
        f"실패(브랜드인데 로고 못 찾음 등) {fail_count}건"
    )


def main():
    for user_id, domain in TARGET_ACCOUNTS:
        process_account(user_id, domain)
    print("\n### 전체 완료. My People 페이지를 새로고침하면 바로 반영됩니다.")


if __name__ == "__main__":
    main()
