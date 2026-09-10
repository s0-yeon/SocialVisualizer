# generate_hs_male_avatars.py
#
# "3학년 4반 고등학교 단톡방"(HS_CHATROOM_ID) 멤버 15명 중 남성 이름인 5명은
# avatar_test_output1 폴더에 여성 일러스트밖에 없어서 못 채웠던 것을, FLUX 아바타
# 생성 파이프라인(avatar_generator.generate_avatar_image_bytes — gen_avatars_test.py와
# 완전히 동일한 함수)으로 직접 생성해서 채운다.
#
# gen_avatars_test.py와 다른 점: 그쪽은 이미지를 avatar_test_output/ 폴더에만 저장하고
# 끝나지만, 이 스크립트는 생성한 이미지를 실제 서비스가 읽는 위치
# (user_data/messenger/<HS_CHATROOM_ID>/.../statics/chatroom_avatars/)에 바로 저장하고
# chatroom_people_avatars.json에도 바로 매핑해 넣는다 — 실행 한 번으로 My People 화면에
# 바로 반영됨(기존에 채워둔 다른 10명 여성 아바타는 그대로 두고 5명만 추가/갱신).
#
# 실행 방법 (MailGrapher 폴더에서):
#   python generate_hs_male_avatars.py
# (venv가 활성화돼 있지 않다면 socialvisualizer-venv/Scripts/python.exe generate_hs_male_avatars.py)
#
# IMAGE_API_BASE(src/parquet/.env)가 가리키는 FLUX 서버와 SUB_TASK_API_BASE(성별 추론용
# vLLM)가 떠 있어야 한다 — 이름만으로 성별을 추론해 프롬프트에 반영하므로(가) 이 5명은
# 전부 통상적인 남성 이름이라 male로 추론될 것이다.

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import util.avatar_generator as avatar_generator
from util.avatar_generator import generate_avatar_image_bytes
from util.user_path import UserPaths

# _build_avatar_prompt()는 이름만 보고 LLM(_infer_gender_presentation)으로 성별을
# 추론하는데, 한국 이름 기준으로도 꽤 자주 틀린다(1차 실행에서 박재현/오승민/임찬우/
# 강태오 4명이 전부 여성으로 나옴 — avatar_generator.py 주석에도 "최지유 → 남성으로
# 잘못 생성" 같은 반대 사례가 이미 언급돼 있다). 이 스크립트는 "무조건 남성"이 목적이라
# 이름 기반 추론에 기대지 않고, 이 모듈이 쓰는 함수 자체를 항상 "male"만 반환하도록
# 바꿔치기한다(이 스크립트 프로세스 안에서만 유효 — 실제 서비스가 쓰는
# avatar_generator.py 파일은 건드리지 않음).
avatar_generator._infer_gender_presentation = lambda name: "male"

# gender_line만 "masculine"으로 바꿔도 2차 실행에서 여전히 여성으로 나왔다 — 원인은
# _pick_style_attributes()가 이름 해시로 hair_style/accessory를 고르는데, 그 풀에
# "a thin headband"/"small stud earrings"/"tied back in a neat bun" 같은 여성 코드화된
# 조합이 섞여 있어서(성별과 무관하게 뽑힘) FLUX가 그 구체적인 묘사(헤어밴드, 귀걸이)를
# "masculine" 지시보다 더 강하게 따라간 것으로 보인다. 그래서 hair_style/accessory도
# 남성으로 통상 읽히는 조합만 나오도록 같은 방식(seed_key 해시)으로 바꿔치기한다 —
# 배경색/옷 색은 원래 로직 그대로 이름마다 달라짐.
_MALE_HAIR_STYLES = ["short and neatly combed", "medium-length with a side part", "tousled and slightly messy"]
_MALE_ACCESSORIES = ["no accessories", "simple round glasses", "rectangular glasses"]
_orig_pick_style_attributes = avatar_generator._pick_style_attributes


def _male_pick_style_attributes(seed_key: str) -> dict:
    attrs = _orig_pick_style_attributes(seed_key)
    n = int(hashlib.md5((seed_key or "").strip().lower().encode("utf-8")).hexdigest(), 16)
    attrs["hair_style"] = _MALE_HAIR_STYLES[n % len(_MALE_HAIR_STYLES)]
    attrs["accessory"] = _MALE_ACCESSORIES[(n // 3) % len(_MALE_ACCESSORIES)]
    return attrs


avatar_generator._pick_style_attributes = _male_pick_style_attributes

BASE_DIR = os.path.dirname(__file__)
HS_CHATROOM_ID = "64c6eaa5a654c2e3c7948bec2be03b3dbe63fb43"

# (이름, 관계 힌트) — 이미 avatar_test_output1 이미지로 채운 여성 10명 + 남성 1명(김도현)은
# 건드리지 않는다. 윤도경은 1차 실행에서 이미 남성으로 잘 나와서 재생성 대상에서 뺐고,
# 여성으로 잘못 나왔던 4명만 다시 생성한다.
TARGETS = [
    ("박재현", "고등학교 동창"),
    ("오승민", "고등학교 동창"),
    ("임찬우", "고등학교 동창"),
    ("강태오", "고등학교 동창"),
]


def chatroom_avatar_filename(participant_id: str) -> str:
    return hashlib.md5(participant_id.strip().encode("utf-8")).hexdigest() + ".png"


def main():
    paths = UserPaths(BASE_DIR, HS_CHATROOM_ID, "messenger")
    os.makedirs(paths.MESSAGE_AVATAR_IMAGES_DIR, exist_ok=True)

    avatar_map = {}
    if os.path.exists(paths.MESSAGE_AVATARS_PATH):
        with open(paths.MESSAGE_AVATARS_PATH, "r", encoding="utf-8") as f:
            avatar_map = json.load(f)

    for name, hint in TARGETS:
        print(f"생성 중: {name} ({hint})")
        image_bytes = generate_avatar_image_bytes(name, hint, seed_key=name)

        filename = chatroom_avatar_filename(name)
        filepath = os.path.join(paths.MESSAGE_AVATAR_IMAGES_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)

        avatar_map[name] = f"/chatroom-person-avatar-image/{HS_CHATROOM_ID}/{filename}"
        print(f"  -> 저장됨: {filepath}")

    with open(paths.MESSAGE_AVATARS_PATH, "w", encoding="utf-8") as f:
        json.dump(avatar_map, f, ensure_ascii=False, indent=2)

    print(f"\n매핑 갱신 완료: {paths.MESSAGE_AVATARS_PATH}")


if __name__ == "__main__":
    main()
