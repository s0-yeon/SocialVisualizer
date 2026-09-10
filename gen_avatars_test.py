# gen_avatars_test.py
#
# 인덱싱(메일 크롤링/DB 저장) 없이 FLUX 아바타 생성만 단독으로 테스트하는 스크립트.
# avatar_generator.py의 generate_avatar_image_bytes()를 그대로 재사용한다 —
# 실제 My People 인덱싱 때 호출되는 것과 완전히 동일한 프롬프트/후처리(rembg 배경 정리)를 거친다.
#
# 실행 방법 (MailGrapher 폴더에서):
#   python gen_avatars_test.py
# (venv가 활성화돼 있지 않다면 socialvisualizer-venv/Scripts/python.exe gen_avatars_test.py)
#
# IMAGE_API_BASE(src/parquet/.env)가 가리키는 FLUX 서버가 떠 있어야 한다.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from util.avatar_generator import generate_avatar_image_bytes

OUT_DIR = os.path.join(os.path.dirname(__file__), "avatar_test_output")

# (파일명, 이름, 관계 힌트) — 관계 힌트는 없으면 ""로 둬도 됨
SAMPLES = [
    ("sample_01.png", "김동한", "친구"),
    ("sample_02.png", "이서진", "친구"),
    ("sample_03.png", "장소미", "친구"),
]

if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    for filename, name, hint in SAMPLES:
        print(f"생성 중: {name} ({hint or '힌트 없음'})")
        image_bytes = generate_avatar_image_bytes(name, hint, seed_key=filename)
        filepath = os.path.join(OUT_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        print(f"  -> 저장됨: {filepath}")
