# generate_avatar_stock.py
#
# 요청 — 내일 GPU를 못 쓰는 상황을 대비해, FLUX 일러스트 아바타를 오늘 미리
# 넉넉히(기본 100장) 생성해서 파일로만 모아둔다. DB/person_avatars.json 등
# 기존 캐시 구조는 전혀 건드리지 않고, 그냥 별도 폴더에 랜덤 이름 아바타
# png 100장을 저장할 뿐이다 (앱에는 아직 연결되지 않음 — 나중에 필요할 때
# 골라서 쓰기 위한 재고용).
#
# 실행 방법 (MailGrapher 폴더에서, GPU FLUX 서버가 켜져 있는 지금 실행):
#   python generate_avatar_stock.py
#   python generate_avatar_stock.py --count 150 --out my_avatars
#
# 결과물은 avatar_stock/ 폴더(기본값)에
#   NNN_<이름>_<8자리 랜덤키>.png
# 형식으로 저장된다.

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv

load_dotenv("src/parquet/.env")

from util.avatar_generator import generate_avatar_image_bytes

# 시연 데이터와 겹치지 않는, 이 스크립트 전용 랜덤 이름 풀.
_SURNAMES = [
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
    "한", "오", "서", "신", "권", "황", "안", "송", "류", "전",
]
_GIVEN_SYLLABLES = [
    "민", "서", "지", "현", "준", "우", "하", "은", "도", "윤",
    "재", "율", "아", "연", "규", "성", "호", "경", "수", "진",
    "찬", "영", "빈", "태", "원", "훈", "환", "유",
]


def _random_name(rng: random.Random) -> str:
    surname = rng.choice(_SURNAMES)
    given_len = rng.choice([1, 2])
    given = "".join(rng.choice(_GIVEN_SYLLABLES) for _ in range(given_len))
    return surname + given


def main():
    parser = argparse.ArgumentParser(description="FLUX 아바타 미리 생성해서 파일로 저장")
    parser.add_argument("--count", type=int, default=100, help="생성할 이미지 수 (기본 100)")
    parser.add_argument("--out", type=str, default="avatar_stock", help="저장 폴더 (기본 avatar_stock)")
    parser.add_argument("--seed", type=int, default=None, help="랜덤 시드 (재현하고 싶을 때만 지정)")
    args = parser.parse_args()

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.out)
    os.makedirs(out_dir, exist_ok=True)

    rng = random.Random(args.seed)

    ok, fail = 0, 0
    for i in range(1, args.count + 1):
        name = _random_name(rng)
        seed_key = f"stock-{i}-{rng.randrange(10**8):08d}"
        try:
            image_bytes = generate_avatar_image_bytes(name, "", seed_key)
            filename = f"{i:03d}_{name}_{seed_key[-8:]}.png"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            ok += 1
            print(f"[{i}/{args.count}] 생성 완료: {filename}")
        except Exception as e:
            fail += 1
            print(f"[{i}/{args.count}] 생성 실패 ({name}): {e}")

    print(f"\n완료 — 성공 {ok}장, 실패 {fail}장 → {out_dir}")


if __name__ == "__main__":
    main()
