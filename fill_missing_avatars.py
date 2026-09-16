# fill_missing_avatars.py
#
# 시간이 없어서 FLUX로 새로 생성하는 대신, 이미 만들어져 있는 이미지들(avatar_stock,
# avatar_stock1, avatar_stock2, avatar_test_output, avatar_test_output1 전부)을 그러모아서
# 그 계정에 아직 아바타 없는 사람들한테 "누구 얼굴인지 안 따지고" 순서대로 채워 넣는다.
# (급할 때 화면에서 빈 아바타 안 보이게만 하려는 용도 — 나중에 여유 있을 때
# generate_avatar_stock2.py + match_avatar_stock2.py로 제대로 된 아바타로 덮어쓰면 된다.)
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   python fill_missing_avatars.py 03yeeun03@naver.com
#   python fill_missing_avatars.py soyeon@icloud

import sys
import os
import json
import random
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from util.user_path import UserPaths
from util.avatar_generator import _load_avatar_map, _save_avatar_map, _avatar_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_USER_ID = "soyeon@icloud"

POOL_DIRS = [
    "avatar_stock",
    "avatar_stock1",
    "avatar_stock2",
    "avatar_test_output",
    "avatar_test_output1",
]

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def collect_pool():
    files = []
    for d in POOL_DIRS:
        root = os.path.join(BASE_DIR, d)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if fn.lower().endswith(IMG_EXTS):
                    files.append(os.path.join(dirpath, fn))
    return files


def main():
    user_id = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_USER_ID
    paths = UserPaths(BASE_DIR, user_id, "mail")

    print(f"### 대상 계정: {user_id}")

    if not os.path.exists(paths.MAIL_CONTACTS_PATH):
        print(f"[중단] 연락처 통계 파일이 없습니다: {paths.MAIL_CONTACTS_PATH}")
        return

    with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
        contacts = json.load(f)

    avatar_map = _load_avatar_map(paths)
    missing = [email for email in contacts if email not in avatar_map]

    print(f"### 아바타 없는 연락처: {len(missing)}명")

    pool = collect_pool()
    if not pool:
        print("[중단] avatar_stock* / avatar_test_output* 폴더에 쓸 만한 이미지가 하나도 없습니다.")
        return
    print(f"### 재활용 가능한 이미지 풀: {len(pool)}장 (부족하면 순환해서 재사용)")

    if not missing:
        print("이미 전부 아바타가 있습니다. 할 일 없음.")
        return

    random.shuffle(pool)
    os.makedirs(paths.AVATAR_IMAGES_DIR, exist_ok=True)

    filled = 0
    for idx, email in enumerate(missing):
        src = pool[idx % len(pool)]
        dest_filename = _avatar_filename(email)
        dest_path = os.path.join(paths.AVATAR_IMAGES_DIR, dest_filename)
        shutil.copy2(src, dest_path)

        url = f"/person-avatar-image/{paths.USER_ID}/{dest_filename}"
        avatar_map[email] = url
        filled += 1

    _save_avatar_map(paths, avatar_map)

    print(f"\n완료. {filled}명 채워 넣음(사진 내용은 실제 그 사람과 무관하게 재활용된 이미지입니다).")
    print("My People 페이지를 새로고침하면 반영됩니다.")


if __name__ == "__main__":
    main()
