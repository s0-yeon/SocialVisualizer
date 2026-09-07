# src/util/summary_image_generator.py
import os
import json
import base64
import hashlib
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv("src/parquet/.env")

IMAGE_API_BASE = os.getenv("IMAGE_API_BASE", "http://localhost:8005")
SUMMARY_IMAGE_SIZE = 1024
SUMMARY_IMAGE_STEPS = 4
SUMMARY_IMAGE_GUIDANCE_SCALE = 0.0

_file_lock = threading.Lock()


# 기간 키를 md5 해시한 <hash>.png 파일명을 반환한다
def _image_filename(period_key: str) -> str:
    return hashlib.md5(period_key.strip().lower().encode("utf-8")).hexdigest() + ".png"


# 기간 요약 텍스트로 FLUX 이미지 생성 프롬프트 문자열을 만든다
def _build_summary_image_prompt(summary_text: str, period_label: str) -> str:
    return f"""You are the illustration engine for a unified "period recap" image system, in the same flat vector illustration style as the avatar icons used elsewhere in this product (the visual language of Slack/Notion/Linear-style default artwork). Every image in this set must share the same clean, modern, geometric illustration language.

[Subject]
Illustrate a specific scene for the period "{period_label}" that concretely depicts what actually happened, based on the summary below. Read the summary for its concrete content — specific activities, topics, objects, settings, and events — and render those specifics directly (e.g. a summary about a project deadline → people around a table with laptops and documents and a clock/calendar; a summary about travel plans → luggage, a boarding pass, a landmark or vehicle; a summary about a celebration → a cake, gifts, balloons). Avoid falling back to a generic, could-be-anything mood board — the scene should be recognizably specific to THIS summary's content, not to another period's.

Summary of the period (extract concrete activities/objects/settings from this and depict them — never render this text, or any text at all, in the image):
"{summary_text[:600]}"

[Art direction]
- Flat vector illustration: clean geometric shapes, confident outlines of uniform stroke width, a small cohesive color palette. No gradients, no soft shading, no drop shadows, no textures, no glossy highlights, no photorealism, no 3D rendering, no anime style.
- People must stay abstract even as the scene stays specific: simple, faceless or minimally-featured generic silhouettes/characters with no realistic facial features and no identifiable portrait of any real person. Convey who they are and what they're doing through pose, clothing, and surrounding objects instead of facial detail.
- Square canvas, 1:1 aspect ratio, balanced and centered composition.

[Technical constraints]
- No text, no numbers, no letters, no logos, no watermarks, no signatures, no UI chrome, no speech bubbles with writing inside.""".strip()


# GPU FLUX 서버를 호출해 기간 요약 이미지를 생성하고 PNG 바이트를 반환한다
def generate_summary_image_bytes(summary_text: str, period_label: str) -> bytes:
    response = requests.post(
        f"{IMAGE_API_BASE}/generate",
        json={
            "prompt": _build_summary_image_prompt(summary_text, period_label),
            "steps": SUMMARY_IMAGE_STEPS,
            "guidance_scale": SUMMARY_IMAGE_GUIDANCE_SCALE,
            "height": SUMMARY_IMAGE_SIZE,
            "width": SUMMARY_IMAGE_SIZE,
        },
        timeout=240,  # GPU 서버가 동시 요청을 사실상 순차 처리하므로 여유를 둠 (avatar_generator.py와 동일한 이유)
    )
    response.raise_for_status()
    b64 = response.json()["image_base64"]
    return base64.b64decode(b64)


# 요약 JSON의 연/월 항목 중 image_url이 없는 기간만 이미지를 생성해 같은 파일에 기록한다
def _generate_images_for_summaries(summaries_path: str, images_dir: str, url_prefix: str, log_tag: str):
    if not os.path.exists(summaries_path):
        print(f"[{log_tag}] 요약 파일 없음: {summaries_path}")
        return

    with open(summaries_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    targets = []
    for kind in ("yearly", "monthly"):
        for period, info in data.get(kind, {}).items():
            if not info or info.get("image_url") or not info.get("summary"):
                continue
            targets.append((kind, period, info["summary"]))

    if not targets:
        return

    os.makedirs(images_dir, exist_ok=True)

    # 기간 하나의 이미지를 생성해 파일로 저장하고 요약 JSON에 image_url을 병합 기록한다
    def _generate_one(kind, period, summary_text):
        period_key = f"{kind}:{period}"
        try:
            image_bytes = generate_summary_image_bytes(summary_text, period)
            filename = _image_filename(period_key)
            filepath = os.path.join(images_dir, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)

            with _file_lock:
                with open(summaries_path, "r", encoding="utf-8") as f:
                    current = json.load(f)
                current.setdefault(kind, {}).setdefault(period, {})["image_url"] = f"{url_prefix}/{filename}"
                with open(summaries_path, "w", encoding="utf-8") as f:
                    json.dump(current, f, ensure_ascii=False, indent=2)

            print(f"[{log_tag}] 생성 완료: {period_key}")
        except Exception as e:
            print(f"[{log_tag}] 생성 실패 ({period_key}): {e}")

    with ThreadPoolExecutor(max_workers=min(len(targets), 5)) as executor:
        futures = [executor.submit(_generate_one, kind, period, summary_text) for kind, period, summary_text in targets]
        for future in as_completed(futures):
            future.result()


# 메일 기간 요약(mail_summaries.json)의 각 기간에 대한 삽화를 생성한다
def generate_mail_summary_images(paths):
    _generate_images_for_summaries(
        paths.MAIL_SUMMARIES_PATH,
        paths.MAIL_SUMMARY_IMAGES_DIR,
        f"/mail-summary-image/{paths.USER_ID}",
        log_tag="mail_summary_image",
    )


# 메신저 기간 요약(message_summaries.json)의 각 기간에 대한 삽화를 생성한다
def generate_message_summary_images(paths):
    _generate_images_for_summaries(
        paths.MESSAGE_SUMMARIES_PATH,
        paths.MESSAGE_SUMMARY_IMAGES_DIR,
        f"/message-summary-image/{paths.USER_ID}",
        log_tag="message_summary_image",
    )
