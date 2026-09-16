# fetch_logos_naver.py
#
# 03yeeun03@naver.com 계정의 My People 연락처를 전부 돌면서, 아직 아바타(로고)가
# 없는 연락처에 대해 LLM(_classify_sender)으로 "사람"인지 "기업/브랜드"인지
# 판별하고, 브랜드로 판별된 연락처는 실제 회사 로고(Clearbit/구글 파비콘)를
# 찾아서 아바타로 채워넣는다. FLUX(GPU) 서버는 쓰지 않는다 — generate_logos_only.py와
# 동일한 방식이며, 대상 계정을 03yeeun03@naver.com 하나로 좁히고 결과를
# brand_classification_result.json에도 남겨서(로고 성공/실패, 브랜드 판별 여부를
# 나중에 다시 확인할 수 있게) 한 번에 정리한다.
#
# - 사람으로 판별된 연락처는 건너뛴다(일러스트 아바타는 이 스크립트가 다루지 않음).
# - 이미 아바타가 있는 연락처도 건너뛴다.
# - 중간에 멈췄다 다시 실행해도 이미 처리된 연락처는 건너뛰므로 재시작 안전하다.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고, 가상환경 켜고 실행하세요:
#   python fetch_logos_naver.py

import sys
import os
import json

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
USER_ID = "03yeeun03@naver.com"
DOMAIN = "mail"
RESULT_PATH = os.path.join(BASE_DIR, "brand_classification_result.json")


def main():
    print(f"### {USER_ID} 처리 시작")
    paths = UserPaths(BASE_DIR, USER_ID, DOMAIN)
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
            continue
        domain_part = email.split("@", 1)[1] if "@" in email else ""
        targets.append((email, name, domain_part))

    print(f"아바타 없는 연락처 {len(targets)}명 확인, LLM으로 사람/브랜드 판별 시작\n")

    logo_ok = []
    logo_fail = []
    persons_skipped = []

    for idx, (email, name, domain_part) in enumerate(targets, start=1):
        try:
            brand_domain = _classify_sender(name, domain_part)
            if not brand_domain:
                persons_skipped.append({"email": email, "name": name})
                continue

            image_bytes = _fetch_company_logo(brand_domain)
            if image_bytes is None:
                print(f"[{idx}/{len(targets)}] 로고 못 찾음(브랜드 판별은 됨): {email} ({name}, {brand_domain})")
                logo_fail.append({"email": email, "name": name, "domain": brand_domain})
                continue

            filename = _avatar_filename(email)
            filepath = os.path.join(paths.AVATAR_IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            url = f"/person-avatar-image/{paths.USER_ID}/{filename}"

            latest = _load_avatar_map(paths)
            latest[email] = url
            _save_avatar_map(paths, latest)

            logo_ok.append({"email": email, "name": name, "domain": brand_domain})
            print(f"[{idx}/{len(targets)}] 로고 완료: {email} ({name}) -> {brand_domain}")
        except Exception as e:
            logo_fail.append({"email": email, "name": name, "domain": None, "error": str(e)})
            print(f"[{idx}/{len(targets)}] 실패: {email} ({name}) - {e}")

    print(f"\n=== 결과 요약 ===")
    print(f"로고 생성 성공: {len(logo_ok)}건")
    print(f"사람으로 판별되어 건너뜀: {len(persons_skipped)}건")
    print(f"브랜드인데 로고를 못 찾은 목록 ({len(logo_fail)}건):")
    for f in logo_fail:
        extra = f" - {f['error']}" if f.get("error") else ""
        print(f"  - {f['email']} ({f['name']}){extra}")

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"logo_ok": logo_ok, "logo_fail": logo_fail, "persons_skipped": persons_skipped},
            f, ensure_ascii=False, indent=2,
        )
    print(f"\n상세 결과를 {RESULT_PATH}에 저장했습니다.")
    print("My People 페이지를 새로고침하면 로고가 반영됩니다.")


if __name__ == "__main__":
    main()
