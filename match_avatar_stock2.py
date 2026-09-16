# match_avatar_stock2.py
#
# avatar_stock2/(또는 avatar_stock2/<계정폴더명>/)에 미리 생성해둔 아바타 이미지들을,
# 실제 계정의 avatars 폴더로 복사하고 person_avatars.json에 반영(매칭)한다.
# generate_avatar_stock2.py는 검토용 스테이징 폴더에만 쌓아두고 자동 매칭은 안 하도록
# 설계돼 있었는데, 이제 자동 매칭으로 바로 반영해달라는 요청에 따라 이 스크립트를 만든다.
#
# - 파일명 안의 8자리 해시(email_hash8, generate_avatar_stock2.py와 동일 로직)로
#   그 이미지가 어느 이메일용인지 역산이 아니라 "이 계정 전체 연락처의 해시를 미리
#   계산해두고 파일명과 대조"하는 방식으로 찾는다(해시 자체는 원래 이메일로 복원 불가한
#   손실 변환이라 파일명만 보고는 못 찾고, 후보와 대조해야 한다).
# - 이미 person_avatars.json에 있는 이메일(이미 매칭됨)은 건드리지 않는다.
# - 매칭 성공한 이미지는 앱이 쓰는 형식 그대로(avatars 폴더에 md5(email).png로 복사 +
#   person_avatars.json에 URL 추가) 반영되므로, 반영 후 새로고침하면 바로 보인다.
# - 매칭 못 한(대응하는 이메일을 못 찾은) 파일은 건드리지 않고 목록만 출력한다.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   python match_avatar_stock2.py soyeon@icloud
#   python match_avatar_stock2.py 03yeeun03@naver.com
# 인자를 안 주면 기본값으로 soyeon@icloud를 처리합니다.

import sys
import os
import json
import hashlib
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from util.user_path import UserPaths
from util.avatar_generator import _load_avatar_map, _save_avatar_map, _avatar_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_USER_ID = "soyeon@icloud"


def email_hash8(email: str) -> str:
    digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    return str(int(digest[:12], 16))[-8:].zfill(8)


def main():
    user_id = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_USER_ID
    paths = UserPaths(BASE_DIR, user_id, "mail")

    if user_id == DEFAULT_USER_ID:
        stock2_dir = os.path.join(BASE_DIR, "avatar_stock2")
    else:
        stock2_dir = os.path.join(BASE_DIR, "avatar_stock2", os.path.basename(paths.USER_ROOT))

    print(f"### 대상 계정: {user_id}")
    print(f"### 스테이징 폴더: {stock2_dir}")

    if not os.path.isdir(stock2_dir):
        print(f"[중단] 폴더가 없습니다: {stock2_dir}")
        return
    if not os.path.exists(paths.MAIL_CONTACTS_PATH):
        print(f"[중단] 연락처 통계 파일이 없습니다: {paths.MAIL_CONTACTS_PATH}")
        return

    with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
        contacts = json.load(f)

    avatar_map = _load_avatar_map(paths)
    already_matched = set(avatar_map.keys())

    # 이 계정의 아직 안 매칭된 연락처들의 해시 -> 이메일 대조표
    hash_to_email = {}
    for email in contacts:
        if email in already_matched:
            continue
        hash_to_email[email_hash8(email)] = email

    files = sorted(os.listdir(stock2_dir))
    print(f"### 스테이징 파일 {len(files)}개, 대조 대상 연락처 {len(hash_to_email)}명\n")

    os.makedirs(paths.AVATAR_IMAGES_DIR, exist_ok=True)

    matched = 0
    unmatched = []

    for fname in files:
        fpath = os.path.join(stock2_dir, fname)
        if not os.path.isfile(fpath):
            continue

        found_email = None
        for h8, email in hash_to_email.items():
            if h8 in fname:
                found_email = email
                break

        if not found_email:
            unmatched.append(fname)
            continue

        dest_filename = _avatar_filename(found_email)
        dest_path = os.path.join(paths.AVATAR_IMAGES_DIR, dest_filename)
        shutil.copy2(fpath, dest_path)

        url = f"/person-avatar-image/{paths.USER_ID}/{dest_filename}"
        latest = _load_avatar_map(paths)
        latest[found_email] = url
        _save_avatar_map(paths, latest)

        # 한 이메일에 파일이 여러 개 걸리는 걸 막기 위해 매칭되고 나면 대조표에서 제거
        del hash_to_email[email_hash8(found_email)]

        matched += 1
        print(f"[매칭] {fname} -> {found_email}")

    print(f"\n=== 결과 ===")
    print(f"매칭 완료: {matched}건")
    print(f"매칭 못 함 ({len(unmatched)}건):")
    for fn in unmatched:
        print(f"  - {fn}")
    print("\nMy People 페이지를 새로고침하면 반영됩니다.")


if __name__ == "__main__":
    main()
