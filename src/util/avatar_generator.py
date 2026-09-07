# 인물 이름·관계 힌트·회사 도메인 등을 바탕으로 FLUX 이미지 서버(또는 회사 로고)를 호출해 인물/본인/채팅방 참여자 아바타를 생성하고 person_avatars.json 캐시에 저장한다.

# Generates avatars for people, the user, and chatroom participants by calling the FLUX image server (or fetching company logos) based on names, relationship hints, and company domains, caching the results in person_avatars.json.

import os
import io
import re
import json
import base64
import hashlib
import threading
import requests
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageChops
from util.database.db_reader import get_person_descriptions, get_all_persons
from util.database.chatroom_reader import get_chatroom_people

load_dotenv("src/parquet/.env")

# text_client: 성별/기업 판별, 관계 힌트 번역 등 텍스트 판단(SUB_TASK_CHAT_MODEL, 로컬 Qwen)
text_client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("SUB_TASK_API_BASE") or None,
)
client = text_client  # 하위 호환용 별칭(아래 텍스트 판별 호출부에서 계속 사용)

# GPU 서버에 직접 띄운 FLUX.1-schnell 서버(flux_server.py) 호출.
IMAGE_API_BASE = os.getenv("IMAGE_API_BASE", "http://localhost:8005")
AVATAR_SIZE = 512
AVATAR_STEPS = 4
AVATAR_GUIDANCE_SCALE = 0.0

_map_lock = threading.Lock()

# (email, user_id) 단위로 "지금 생성 중"임을 표시해서, 이미 진행 중인 요청이
# 있으면 새 요청은 그 결과를 기다리지 않고 그냥 건너뛴다 
_in_progress_lock = threading.Lock()
_in_progress = set()  # {(user_id, email)}

# 본인 아바타(generate_self_avatar)는 호출자가 URL을 바로 반환받아야 하므로, 
# 이미 진행 중인 요청이 끝날 때까지 기다렸다가 그 결과를 같이 반환한다 
_self_avatar_events = {}  # (user_id, key) -> threading.Event
_self_avatar_events_lock = threading.Lock()


# 이메일을 md5 해시한 <hash>.png 파일명을 반환한다
def _avatar_filename(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest() + ".png"


# person_avatars.json(이메일→아바타 URL 맵)을 읽어 dict로 반환한다 (없으면 빈 dict)
def _load_avatar_map(paths) -> dict:
    if not os.path.exists(paths.MAIL_AVATARS_PATH):
        return {}
    with open(paths.MAIL_AVATARS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# 아바타 URL이 가리키는 실제 png 파일이 존재하는지 확인한다 (유실된 캐시 항목 걸러내기용)
def _avatar_url_file_exists(paths, url: str) -> bool:
    if not url:
        return False
    filename = url.rstrip("/").rsplit("/", 1)[-1]
    if not filename:
        return False
    return os.path.exists(os.path.join(paths.AVATAR_IMAGES_DIR, filename))


# 이메일→아바타 URL 맵을 person_avatars.json에 저장한다
def _save_avatar_map(paths, avatar_map: dict):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(paths.MAIL_AVATARS_PATH, "w", encoding="utf-8") as f:
        json.dump(avatar_map, f, ensure_ascii=False, indent=2)


# 참여자 ID를 md5 해시한 <hash>.png 파일명을 반환한다
def _chatroom_avatar_filename(participant_id: str) -> str:
    return hashlib.md5(participant_id.strip().encode("utf-8")).hexdigest() + ".png"


# 채팅방 참여자→아바타 URL 맵(chatroom_people_avatars.json)을 읽어 dict로 반환한다
def _load_chatroom_avatar_map(paths) -> dict:
    if not os.path.exists(paths.MESSAGE_AVATARS_PATH):
        return {}
    with open(paths.MESSAGE_AVATARS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# 채팅방 참여자→아바타 URL 맵을 chatroom_people_avatars.json에 저장한다
def _save_chatroom_avatar_map(paths, avatar_map: dict):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(paths.MESSAGE_AVATARS_PATH, "w", encoding="utf-8") as f:
        json.dump(avatar_map, f, ensure_ascii=False, indent=2)


# person.description에서 '관계' 줄만 추출해 아바타 스타일 힌트로 쓴다
def _extract_relationship_hint(description: str) -> str:
    if not description:
        return ""
    m = re.search(r"관계:\s*(.+)", description)
    return m.group(1).strip() if m else ""


# chatroom_people.description에서 '말투' 줄만 추출해 아바타 스타일 힌트로 쓴다
def _extract_tone_hint(description: str) -> str:
    if not description:
        return ""
    m = re.search(r"말투:\s*(.+)", description)
    return m.group(1).strip() if m else ""


# 사람마다 시각적으로 뚜렷이 구분되도록, 이메일 해시로 결정적으로 고르는 속성 풀.
# (같은 이메일 → 항상 같은 조합, 다른 이메일 → 대부분 다른 조합)
_BG_COLORS = [
    ("warm coral pink", "#F4B8B8"), ("sky blue", "#AEDFF7"), ("sage green", "#BFE3C8"),
    ("soft lavender", "#D8C6F0"), ("warm sand", "#F4D9A6"), ("seafoam teal", "#A8E0D8"),
    ("dusty rose", "#F0C4D6"), ("pale sunflower yellow", "#F6E2A0"), ("powder blue", "#C7D9F0"),
    ("muted mint", "#BEEBD9"), ("warm peach", "#F6CBA6"), ("soft periwinkle", "#C9CCF4"),
]
_HAIR_STYLES = [
    "short and neatly combed", "medium-length with a side part", "long and straight reaching the shoulders",
    "long and gently wavy", "tied back in a low ponytail", "a short bob cut",
    "tousled and slightly messy", "tied back in a neat bun", "shoulder-length with bangs",
]
_HAIR_COLORS = ["jet black", "dark brown", "warm chestnut brown", "soft ash brown"]
_ACCESSORIES = ["no accessories", "simple round glasses", "small stud earrings", "a thin headband", "rectangular glasses"]
_CLOTHING_COLORS = [
    "coral red", "navy blue", "olive green", "mustard yellow", "plum purple",
    "burnt orange", "deep teal", "rose pink", "charcoal gray", "warm brown",
]


# "#RRGGBB" hex 색상을 (r, g, b) 정수 튜플로 변환한다
def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# seed 문자열 해시로 배경색·머리·액세서리·옷 색을 결정적으로 골라 dict로 반환한다
def _pick_style_attributes(seed_key: str) -> dict:
    n = int(hashlib.md5((seed_key or "").strip().lower().encode("utf-8")).hexdigest(), 16)
    bg_name, bg_hex = _BG_COLORS[n % len(_BG_COLORS)]
    return {
        "bg_name": bg_name,
        "bg_hex": bg_hex,
        "bg_rgb": _hex_to_rgb(bg_hex),
        "hair_style": _HAIR_STYLES[(n // 7) % len(_HAIR_STYLES)],
        "hair_color": _HAIR_COLORS[(n // 13) % len(_HAIR_COLORS)],
        "accessory": _ACCESSORIES[(n // 29) % len(_ACCESSORIES)],
        "clothing_color": _CLOTHING_COLORS[(n // 41) % len(_CLOTHING_COLORS)],
    }


# 이름을 LLM에 넘겨 통상적으로 인지되는 성별을 'female'/'male'/'unknown'으로 판별한다
def _infer_gender_presentation(name: str) -> str:
    try:
        result = client.chat.completions.create(
            model=os.getenv("SUB_TASK_CHAT_MODEL"),
            messages=[
                {
                    "role": "system",
                    "content": "주어진 사람 이름만 보고 일반적으로 인지되는 성별을 판단하는 AI입니다. "
                                "이름은 한국어, 영어 등 다양한 언어/문화권에서 올 수 있으니 이름의 언어/문화권에 맞는 "
                                "통상적인 성별 인식 관습을 적용하세요. "
                                "반드시 female, male, unknown 중 하나만 정확히 출력하세요. 판단이 애매하면 unknown.",
                },
                {"role": "user", "content": f"이름: {name}"},
            ],
            temperature=0,
        )
        answer = result.choices[0].message.content.strip().lower()
        if "female" in answer:
            return "female"
        if "male" in answer:
            return "male"
    except Exception as e:
        print(f"[AVATAR] 성별 추론 실패 ({name}): {e}")
    return "unknown"


# 초대형 브랜드는 LLM 판별이 흔들릴 수 있어(도메인이 발송대행사인 경우 등) 확정 매핑을 우선 사용한다.
_KNOWN_BRAND_DOMAINS = {
    "instagram": "instagram.com", "pinterest": "pinterest.com", "google": "google.com",
    "google play": "google.com", "mcafee": "mcafee.com", "twitter": "x.com", "x": "x.com",
    "discord": "discord.com", "microsoft": "microsoft.com", "xbox": "xbox.com",
    "neo4j": "neo4j.com", "the neo4j team": "neo4j.com", "facebook": "facebook.com",
    "linkedin": "linkedin.com", "naver": "naver.com", "kakao": "kakaocorp.com",
    "amazon": "amazon.com", "apple": "apple.com", "netflix": "netflix.com",
    "youtube": "youtube.com", "spotify": "spotify.com", "slack": "slack.com",
    "zoom": "zoom.us", "adobe": "adobe.com", "dropbox": "dropbox.com",
    "paypal": "paypal.com", "ebay": "ebay.com", "samsung": "samsung.com",
    "lg": "lg.com", "steam": "steampowered.com", "playstation": "playstation.com",
    "nintendo": "nintendo.com", "airbnb": "airbnb.com", "uber": "uber.com",
    "github": "github.com", "figma": "figma.com", "notion": "notion.so",
}


# 표시 이름/도메인으로 발신자가 기업/서비스 자동발송 계정인지 판별해 공식 도메인을 반환한다 (개인/불확실이면 None)
def _classify_sender(name: str, domain: str) -> str | None:
    known = _KNOWN_BRAND_DOMAINS.get((name or "").strip().lower())
    if known:
        return known
    try:
        result = client.chat.completions.create(
            model=os.getenv("SUB_TASK_CHAT_MODEL"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "이메일 발신자 정보를 보고 이것이 실제로 존재하는 기업/서비스가 보낸 "
                        "자동 발송 계정(알림, 뉴스레터, 영수증, 마케팅 메일 등)인지 판단하는 AI입니다. "
                        "표시 이름이 유명 기업/서비스 이름과 일치하면, 이메일 도메인이 발송대행사 "
                        "도메인(예: sendgrid.net, mailgun.org, amazonses.com 등)이라서 그 기업의 "
                        "공식 도메인과 달라 보여도 표시 이름을 우선 신뢰해 그 기업으로 판단하세요. "
                        "실제로 존재하는 기업/서비스라면 그 기업의 공식 웹사이트 도메인만 "
                        "(예: google.com) 정확히 출력하세요. 실제 사람 개인 계정이거나 "
                        "어느 기업인지 확실하지 않으면 정확히 'PERSON'이라고만 출력하세요."
                    ),
                },
                {"role": "user", "content": f"표시 이름: {name}\n이메일 도메인: {domain}"},
            ],
            temperature=0,
        )
        answer = (result.choices[0].message.content or "").strip()
        if not answer or answer.upper() == "PERSON":
            return None
        m = re.search(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", answer)
        return m.group(0).lower() if m else None
    except Exception as e:
        print(f"[AVATAR] 기업 판별 실패 ({name}): {e}")
        return None


# 로고에서 실제로 눈에 보이는 도형 픽셀만 흰색으로 표시하는 "L" 모드 마스크를 만든다 (옅은 알파/안티에일리어싱 제외)
def _logo_content_mask(logo: Image.Image) -> Image.Image:
    alpha = logo.split()[-1]
    if alpha.getextrema()[0] < 250:  # 투명 배경이 있는 이미지 → 알파 기준
        return alpha.point(lambda a: 255 if a >= 32 else 0)
    # 불투명(흰 배경) 이미지 → 흰색과 뚜렷이 다른 영역 기준
    rgb = logo.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))).convert("L")
    return diff.point(lambda d: 255 if d >= 24 else 0)


# 로고를 실제 도형 경계까지 크롭하고 (크롭된 로고, 내용 마스크)를 반환한다
def _trim_logo_padding(logo: Image.Image) -> tuple[Image.Image, Image.Image] | tuple[None, None]:
    w, h = logo.size
    mask = _logo_content_mask(logo)
    bbox = mask.getbbox()
    if not bbox:
        return logo, mask
    # 과도한 크롭으로 로고 윤곽이 뭉개지는 것을 방지한다
    pad = max(1, round(max(w, h) * 0.01))
    left, top, right, bottom = bbox
    bbox = (max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad))
    return logo.crop(bbox), mask.crop(bbox)


# 로고가 배경 없는 얇은 단색 마크면 그 마크 색을 배지 배경색으로 뽑아 반환한다 (이미 배지형/다색이면 None)
def _logo_badge_color(logo: Image.Image, mask: Image.Image) -> tuple[int, int, int] | None:
    rgb = logo.convert("RGB")
    pixels = list(rgb.getdata())
    mask_data = list(mask.getdata())
    content = [px for px, m in zip(pixels, mask_data) if m]
    if not content:
        return None

    fill_ratio = len(content) / (logo.width * logo.height)
    if fill_ratio >= 0.68:
        # 이미 도형 자체가 원/사각형을 꽉 채운 배지 형태 → 그대로 사용
        return None

    # 색 다양성 검사: 양자화한 색상 버킷 중 하나가 압도적 비중이면 "단색 마크"로 본다.
    buckets = Counter((r // 32, g // 32, b // 32) for r, g, b in content)
    top_bucket, top_count = buckets.most_common(1)[0]
    if top_count / len(content) < 0.75:
        # Instagram/Google처럼 여러 색이 섞인 다색 로고 → 재색칠하지 않고 그대로 사용
        return None

    top_pixels = [
        px for px, m in zip(pixels, mask_data)
        if m and (px[0] // 32, px[1] // 32, px[2] // 32) == top_bucket
    ]
    r = sum(p[0] for p in top_pixels) // len(top_pixels)
    g = sum(p[1] for p in top_pixels) // len(top_pixels)
    b = sum(p[2] for p in top_pixels) // len(top_pixels)
    return (r, g, b)


# 로고를 정사각형 캔버스에 여백 없이 꽉 채운 PNG 바이트를 반환한다 (얇은 단색 마크는 배지 스타일로 재색칠)
def _pad_logo_square(image_bytes: bytes, canvas_size: int = 512) -> bytes:
    logo = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    logo, mask = _trim_logo_padding(logo)
    badge_color = _logo_badge_color(logo, mask)

    if badge_color is not None:
        white_glyph = Image.new("RGBA", logo.size, (255, 255, 255, 255))
        white_glyph.putalpha(mask)
        logo = white_glyph
        bg_rgba = badge_color + (255,)
    else:
        bg_rgba = (255, 255, 255, 255)

    # cover(꽉 채우기): 짧은 변을 캔버스 크기에 맞춰 확대해 여백 없이 채운다.
    # 파비콘처럼 아주 작은 원본을 큰 배율로 늘리면 뭉개져 보이므로 배율 자체에 상한을 둔다.
    scale = min(max(canvas_size / logo.width, canvas_size / logo.height), 6.0)
    new_size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    logo = logo.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), bg_rgba)
    x, y = (canvas_size - logo.width) // 2, (canvas_size - logo.height) // 2
    canvas.paste(logo, (x, y), logo)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()


_BRAND_LOGOS_DIR = os.path.join(os.path.dirname(__file__), "brand_logos")

# Clearbit/파비콘이 화질이 낮거나 배지 형태가 아닌 로고를 주는 브랜드는
# 직접 준비한 원본 이미지를 우선 사용한다.
_HARDCODED_LOGO_FILES = {
    "pinterest.com": "pinterest.png",
    "mcafee.com": "mcafee.png",
    "neo4j.com": "neo4j.png",
}


# 직접 준비한 로고 이미지를 재색칠·cover 크롭 없이 여백만 다듬어 캔버스 안에 contain 배치한 PNG 바이트를 반환한다
def _place_hardcoded_logo(image_bytes: bytes, canvas_size: int = 512) -> bytes:
    logo = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    logo, _ = _trim_logo_padding(logo)
    target = int(canvas_size * 0.68)
    scale = min(target / max(logo.width, logo.height), 6.0)
    new_size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    logo = logo.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
    x, y = (canvas_size - logo.width) // 2, (canvas_size - logo.height) // 2
    canvas.paste(logo, (x, y), logo)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()


# 하드코딩 파일 또는 공개 로고 서비스(Clearbit/파비콘)에서 기업 로고를 가져와 정사각형 PNG로 반환한다 (실패 시 None)
def _fetch_company_logo(domain: str) -> bytes | None:
    hardcoded = _HARDCODED_LOGO_FILES.get(domain)
    if hardcoded:
        filepath = os.path.join(_BRAND_LOGOS_DIR, hardcoded)
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                return _place_hardcoded_logo(f.read())

    for url in (
        f"https://logo.clearbit.com/{domain}?size=256",
        f"https://www.google.com/s2/favicons?sz=256&domain={domain}",
    ):
        try:
            res = requests.get(url, timeout=8)
            if res.status_code == 200 and res.content and len(res.content) > 200:
                return _pad_logo_square(res.content)
        except Exception as e:
            print(f"[AVATAR] 로고 요청 실패 ({url}): {e}")
    return None


# 한국어 관계 힌트를 짧은 영어 한 문장으로 LLM 번역한다 (FLUX 프롬프트용, 실패 시 빈 문자열)
def _translate_hint_to_english(hint: str) -> str:
    try:
        result = text_client.chat.completions.create(
            model=os.getenv("SUB_TASK_CHAT_MODEL"),
            messages=[
                {
                    "role": "system",
                    "content": "다음 한 줄짜리 관계 설명을 이미지 생성 프롬프트에 넣을 수 있도록 "
                                "간결한 영어 한 문장으로 번역하세요. 번역 결과 외의 다른 말은 절대 하지 마세요.",
                },
                {"role": "user", "content": hint},
            ],
            temperature=0,
        )
        return (result.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[AVATAR] 관계 힌트 번역 실패: {e}")
        return ""


# 이름·관계 힌트·seed로 통일된 스타일의 아바타 이미지 생성 프롬프트 문자열을 만든다
def _build_avatar_prompt(name: str, relationship_hint: str = "", seed_key: str = "") -> str:
    context_block = ""
    if relationship_hint:
        translated_hint = _translate_hint_to_english(relationship_hint[:200])
        if translated_hint:
            context_block = f"""

[Persona context — style inspiration only, never literal]
A short note about this person's relationship to the user: "{translated_hint}"
Use this ONLY as soft inspiration for clothing style and mood (e.g. business-casual for a colleague, relaxed casual for a friend/family member). Never depict any text, objects, logos, or literal scenes from this note."""

    attrs = _pick_style_attributes(seed_key or name)
    gender = _infer_gender_presentation(name)
    gender_line = {
        "female": "Depict this person with a clearly feminine gender presentation.",
        "male": "Depict this person with a clearly masculine gender presentation.",
        "unknown": "This person's gender is ambiguous from their name — depict them with a gender-neutral, androgynous presentation.",
    }[gender]

    return f"""You are the illustration engine for a unified corporate contact-avatar system, in the visual language of products like Slack, Notion, or Linear's default member avatars. Every avatar you generate must look like it belongs to the exact same icon set — consistent style, consistent rules, every time. Each person in this set must look like a clearly distinct individual, not a reused default template.

[Hard rule — read first, applies to the whole image]
The ENTIRE image outside the person's head/hair/shoulders must be a single pure flat solid color ({attrs['bg_name']}, hex {attrs['bg_hex']}) — perfectly flat, uniform, edge-to-edge, corner-to-corner, with zero variation. Do NOT draw a picture frame, border, mat/matting, vignette, spotlight, or a circular/oval disc of any other color or shade behind the person. Nothing decorative behind or around the subject, ever — just the one flat color.

[Subject]
A single friendly portrait of one person whose given name is "{name}". {gender_line}{context_block}

[Individual appearance — follow exactly, these make this avatar visually distinct from everyone else in the set]
- Hair: {attrs['hair_color']}, styled {attrs['hair_style']}.
- Accessory: {attrs['accessory']}.
- Clothing: a flat, solid {attrs['clothing_color']} top.
- Background: pure flat {attrs['bg_name']} (hex {attrs['bg_hex']}) filling the entire canvas edge-to-edge behind the person. Completely uniform, no gradient, no vignette, no texture, no shape, no glow, no spotlight. Absolutely NO circular disc, badge, frame, or any shape of a different shade behind the person — the background must be one single flat rectangle of this color, corner to corner.

[Art direction]
- Flat vector illustration, modern corporate-avatar style: clean geometric shapes, confident outlines of uniform stroke width. No gradients, no soft shading, no drop shadows, no textures, no glossy highlights anywhere in the image.
- The face must read clearly even at very small sizes (this renders as a ~40px circular icon): simple but expressive eyes, nose, and a warm closed-mouth smile. Never leave the face blank or featureless.

[Framing & composition]
- The face must look directly at the viewer: a straight-on, frontal head-on pose with both eyes looking straight ahead into the camera. Do NOT draw a 3/4 turned angle, side profile, or head tilted/turned away — the nose must point straight forward at the center of the image, perfectly symmetrical left-to-right.
- Close-up, centered, symmetrical portrait, zoomed in so the face is the clear focal point — tighter than a standard shoulders-up photo, more like a close-up headshot. Still keep a small margin of empty space above the hair and on both sides so the hairstyle silhouette isn't cropped.
- The entire head, the full hairstyle silhouette, and both ears must be completely visible. The head should occupy roughly 70-80% of the image height — the face should read as large and prominent, not small within a wide shot.
- The shoulders and clothing should extend all the way down and bleed off the bottom edge of the canvas, with NO background visible below the body — only the head/hair area needs top and side margin, the torso should fill edge-to-edge at the bottom like a standard cropped profile-picture avatar.

[Technical constraints]
- Square canvas, 1:1 aspect ratio.
- No text, no logos, no watermarks, no signatures, no UI chrome, no photorealism, no 3D rendering, no anime style.
- No border, no frame, no outline, no card edge of any kind around the outer edge of the canvas — the background color must reach all four edges directly.""".strip()




_rembg_session = None
_rembg_session_lock = threading.Lock()


# 인물 세그멘테이션(rembg) 세션을 프로세스당 한 번만 로드해 재사용한다
def _get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        with _rembg_session_lock:
            if _rembg_session is None:
                from rembg import new_session
                _rembg_session = new_session("u2net")
    return _rembg_session


# rembg 세그멘테이션으로 인물 영역만 추출해 완전히 새 단색 배경 위에 확대 배치한 PNG 바이트를 반환한다
def _normalize_composition(image_bytes: bytes, bg_rgb: tuple, min_top: float = 0.02, min_side: float = 0.03) -> bytes:
    from rembg import remove

    subject = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = subject.size

    session = _get_rembg_session()
    cutout_bytes = remove(image_bytes, session=session)
    alpha = Image.open(io.BytesIO(cutout_bytes)).convert("RGBA").split()[-1]

    # 사진이 아니라 윤곽선이 뚜렷한 평면 일러스트라서 부드러운 반투명 경계가 필요 없다 —
    # 오히려 옷/어깨 같은 큰 단색 영역이 애매한 알파로 남으면 배경색과 섞여 흐릿한
    # "유령" 자국이 생긴다. 그래서 이진화해서 사람 영역은 완전 불투명, 나머지는 완전
    # 투명으로 딱 잘라낸다 — 가장자리에 원본 배경색이 섞인 반투명 픽셀도 이 과정에서
    # 함께 제거되므로 색 스필(색 번짐) 문제가 생기지 않는다.
    alpha = alpha.point(lambda p: 255 if p > 80 else 0)

    r, g, b = subject.split()
    cutout = Image.merge("RGBA", (r, g, b, alpha))

    bbox = alpha.getbbox()
    canvas = Image.new("RGBA", (orig_w, orig_h), bg_rgb + (255,))

    if not bbox:
        # 세그멘테이션이 완전히 실패하면(알파가 전부 비어있음) 원본을 그대로 반환한다
        # (사람 영역을 못 찾았으므로 억지로 자르지 않는다).
        return image_bytes

    left, top, right, bottom = bbox
    content_w, content_h = right - left, bottom - top
    if content_w <= 0 or content_h <= 0:
        return image_bytes

    cropped = cutout.crop(bbox)

    scale = (orig_h * (1 - min_top)) / content_h
    max_w = orig_w * (1 - 2 * min_side)
    if content_w * scale > max_w:
        scale = max_w / content_w

    new_w, new_h = max(1, round(content_w * scale)), max(1, round(content_h * scale))
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    canvas.alpha_composite(resized, ((orig_w - new_w) // 2, orig_h - new_h))

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()


# GPU FLUX 서버를 호출해 아바타를 생성하고 rembg로 배경을 순수 단색으로 재구성한 PNG 바이트를 반환한다
def generate_avatar_image_bytes(name: str, relationship_hint: str = "", seed_key: str = "") -> bytes:
    attrs = _pick_style_attributes(seed_key or name)
    prompt = _build_avatar_prompt(name, relationship_hint, seed_key)
    response = requests.post(
        f"{IMAGE_API_BASE}/generate",
        json={
            "prompt": prompt,
            "steps": AVATAR_STEPS,
            "guidance_scale": AVATAR_GUIDANCE_SCALE,
            "height": AVATAR_SIZE,
            "width": AVATAR_SIZE,
        },
        timeout=240,  # GPU 서버가 동시 요청을 사실상 순차 처리해서, 여러 명을 한꺼번에
        # 생성할 때 뒤에 밀린 요청은 120초를 넘기기 쉬웠다 — 여유를 더 줌
    )
    response.raise_for_status()
    b64 = response.json()["image_base64"]
    raw_bytes = base64.b64decode(b64)
    return _normalize_composition(raw_bytes, attrs["bg_rgb"])


# person.description에서 이메일별 '관계' 한 줄을 뽑아 {이메일: 힌트} dict로 반환한다
def _load_relationship_hints(user_id: str) -> dict:
    hints = {}
    try:
        for row in get_person_descriptions(user_id):
            email = (row.get("person_account_id") or "").strip().lower()
            hint = _extract_relationship_hint(row.get("description") or "")
            if email and hint:
                hints[email] = hint
    except Exception as e:
        print(f"[AVATAR] 관계 설명 조회 실패 (스타일 힌트 없이 진행): {e}")
    return hints


# 캐시된 아바타 맵에서 실제 png 파일이 있는 항목만 반환한다 (유실된 항목은 캐시에서도 제거)
def get_cached_person_avatars(paths) -> dict:
    avatar_map = _load_avatar_map(paths)
    valid = {k: v for k, v in avatar_map.items() if _avatar_url_file_exists(paths, v)}
    if len(valid) != len(avatar_map):
        with _map_lock:
            _save_avatar_map(paths, valid)  # 유실된 항목은 캐시에서도 지워서 재생성 대상이 되게 함
    return valid


_SELF_AVATAR_KEY = "__self__"


# 로그인한 사용자 본인 아바타의 캐시 URL을 반환한다 (없거나 파일 유실 시 None)
def get_cached_self_avatar(paths):
    url = _load_avatar_map(paths).get(_SELF_AVATAR_KEY)
    return url if _avatar_url_file_exists(paths, url) else None


# 로그인한 사용자 본인 아바타를 없으면 한 번 생성·캐시하고 URL을 반환한다 (고정 키 __self__로 캐시, 동시 요청은 대기)
def generate_self_avatar(paths, name: str) -> str:
    avatar_map = _load_avatar_map(paths)
    cached = avatar_map.get(_SELF_AVATAR_KEY)
    if cached and _avatar_url_file_exists(paths, cached):
        return cached

    lock_key = (paths.USER_ID, _SELF_AVATAR_KEY)
    with _self_avatar_events_lock:
        event = _self_avatar_events.get(lock_key)
        is_owner = event is None
        if is_owner:
            event = threading.Event()
            _self_avatar_events[lock_key] = event

    if not is_owner:
        # 다른 요청이 이미 생성 중 — 새로 FLUX를 호출하지 않고 그 결과가 끝나길 기다린다.
        event.wait(timeout=240)
        return _load_avatar_map(paths).get(_SELF_AVATAR_KEY) or cached

    try:
        os.makedirs(paths.AVATAR_IMAGES_DIR, exist_ok=True)
        image_bytes = generate_avatar_image_bytes(name or "나", "", paths.USER_ID + ":self")
        filename = _avatar_filename(_SELF_AVATAR_KEY + ":" + paths.USER_ID)
        filepath = os.path.join(paths.AVATAR_IMAGES_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        url = f"/person-avatar-image/{paths.USER_ID}/{filename}"
        with _map_lock:
            latest = _load_avatar_map(paths)
            latest[_SELF_AVATAR_KEY] = url
            _save_avatar_map(paths, latest)
        return url
    finally:
        with _self_avatar_events_lock:
            _self_avatar_events.pop(lock_key, None)
        event.set()


# 아직 캐시 없는 연락처만 아바타(기업은 로고, 개인은 일러스트)를 생성하고 {이메일: URL} 매핑을 반환한다
def generate_person_avatars_batch(paths, people: list) -> dict:
    os.makedirs(paths.AVATAR_IMAGES_DIR, exist_ok=True)
    avatar_map = _load_avatar_map(paths)

    targets = []
    seen = set()
    for p in people:
        email = (p.get("email") or "").strip().lower()
        name = (p.get("name") or "").strip()
        if not email or not name or email in seen:
            continue
        seen.add(email)
        if not _avatar_url_file_exists(paths, avatar_map.get(email)):
            key = (paths.USER_ID, email)
            with _in_progress_lock:
                if key in _in_progress:
                    # 다른 요청이 이 이메일을 이미 생성 중 — 중복으로 또 시작하지 않는다.
                    # (그 요청이 끝나면 캐시가 채워지므로 다음 새로고침/배치에서 히트된다.)
                    continue
                _in_progress.add(key)
            domain = email.split("@", 1)[1] if "@" in email else ""
            targets.append((email, name, domain))

    relationship_hints = _load_relationship_hints(paths.USER_ID) if targets else {}

    # 연락처 한 명의 아바타(로고 또는 일러스트)를 생성해 파일 저장하고 캐시에 병합한다
    def _generate_one(email, name, domain):
        try:
            brand_domain = _classify_sender(name, domain)
            image_bytes = _fetch_company_logo(brand_domain) if brand_domain else None
            is_logo = image_bytes is not None
            if image_bytes is None:
                image_bytes = generate_avatar_image_bytes(name, relationship_hints.get(email, ""), email)

            filename = _avatar_filename(email)
            filepath = os.path.join(paths.AVATAR_IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            url = f"/person-avatar-image/{paths.USER_ID}/{filename}"
            with _map_lock:
                # 저장 직전에 파일을 다시 읽어 병합한다. 요청 시작 시점 스냅샷(avatar_map)을
                # 그대로 덮어쓰면, 동시에 들어온 다른 /generate-person-avatars 요청이 그 사이
                # 새로 추가한 항목을 지워버려 "생성 완료" 로그는 찍히는데 person_avatars.json엔
                # 안 남는(→ 화면에 안 뜨고 다음 로드 때 또 재생성되는) 문제가 생긴다.
                latest = _load_avatar_map(paths)
                latest[email] = url
                _save_avatar_map(paths, latest)
                avatar_map[email] = url
            print(f"[AVATAR] 생성 완료: {email} ({name}){' [기업 로고]' if is_logo else ''}")
            return email, url
        except Exception as e:
            print(f"[AVATAR] 생성 실패 ({email}): {e}")
            return email, None
        finally:
            with _in_progress_lock:
                _in_progress.discard((paths.USER_ID, email))

    if targets:
        # GPU 서버가 하나라 동시 요청을 어차피 순차 처리한다 — 여러 개를 동시에 던지면
        # 뒤에 밀린 요청만 대기 시간이 늘어나 타임아웃 위험만 커지고 실제로는 더 빨라지지
        # 않는다. 게다가 자기 자신(/generate-self-avatar)도 같은 GPU 서버를 같이 쓰므로
        # 부담을 더 줄이려 동시 실행 수를 1로 낮춘다.
        with ThreadPoolExecutor(max_workers=1) as executor:
            futures = [executor.submit(_generate_one, email, name, domain) for email, name, domain in targets]
            for future in as_completed(futures):
                future.result()

    return {email: avatar_map[email] for email in seen if email in avatar_map}


# 이 계정의 연락처 전체를 조회해 일괄 아바타를 생성한다 (인덱싱 완료 직후 서버 사이드 트리거용)
def generate_all_person_avatars(paths) -> dict:
    persons = get_all_persons(paths.USER_ID)
    people = [
        {"email": p["person_mail_account_id"], "name": p.get("person_name") or ""}
        for p in persons
        if p.get("person_mail_account_id")
    ]
    return generate_person_avatars_batch(paths, people)


# 채팅방 참여자 아바타 캐시 맵을 그대로 반환한다
def get_cached_chatroom_people_avatars(paths) -> dict:
    return _load_chatroom_avatar_map(paths)


# 이 채팅방 참여자 중 아바타가 없는 사람만 일러스트 아바타를 생성하고 {participant_id: URL} 매핑을 반환한다
def generate_chatroom_people_avatars_batch(paths) -> dict:
    people = get_chatroom_people(paths.USER_ID)
    if not people:
        return {}

    os.makedirs(paths.MESSAGE_AVATAR_IMAGES_DIR, exist_ok=True)
    avatar_map = _load_chatroom_avatar_map(paths)

    targets = []
    seen = set()
    for p in people:
        participant_id = (p.get("participant_id") or "").strip()
        name = (p.get("name") or "").strip()
        if not participant_id or not name or participant_id in seen:
            continue
        seen.add(participant_id)
        if participant_id not in avatar_map:
            tone_hint = _extract_tone_hint(p.get("description") or "")
            targets.append((participant_id, name, tone_hint))

    # 참여자 한 명의 일러스트 아바타를 생성해 파일 저장하고 캐시에 병합한다
    def _generate_one(participant_id, name, tone_hint):
        try:
            image_bytes = generate_avatar_image_bytes(name, tone_hint, participant_id)

            filename = _chatroom_avatar_filename(participant_id)
            filepath = os.path.join(paths.MESSAGE_AVATAR_IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            url = f"/chatroom-person-avatar-image/{paths.USER_ID}/{filename}"
            with _map_lock:
                avatar_map[participant_id] = url
                _save_chatroom_avatar_map(paths, avatar_map)
            print(f"[AVATAR] 참여자 아바타 생성 완료: {participant_id} ({name})")
            return participant_id, url
        except Exception as e:
            print(f"[AVATAR] 참여자 아바타 생성 실패 ({participant_id}): {e}")
            return participant_id, None

    if targets:
        with ThreadPoolExecutor(max_workers=min(len(targets), 3)) as executor:
            futures = [executor.submit(_generate_one, pid, name, hint) for pid, name, hint in targets]
            for future in as_completed(futures):
                future.result()

    return {pid: avatar_map[pid] for pid in seen if pid in avatar_map}
