# 계정(도메인+user_id)별로 원본 데이터·GraphRAG 산출물·이미지 등 모든 파일 경로를 한곳에서 계산하고, 계정 메타 파일과 인덱싱된 계정 목록을 관리한다.

# Centralizes computation of every data/output/image file path for each account (domain + user_id), and manages account metadata files and the list of indexed accounts.

import re,os
import json
import shutil
from config.settings import GRAPHRAG_SETTINGS_DIR, GRAPHRAG_PROMPTS_DIR, RAG_ENGINE

# 계정 폴더에 원본 user_id·room_name을 담아두는 메타 파일명 (sanitize된 폴더명 복원·인덱싱 전 방 이름 폴백용)
ACCOUNT_META_FILENAME = "account.json"

# 해시 부분만 폴더명으로 사용
_MSG_ROOM_ID_RE = re.compile(r"\[msg_([0-9a-f]{8})\]\s*$")

# user_id(이메일 또는 방 이름)를 파일시스템에 안전한 폴더명으로 변환한다
def _mail_to_dir_name(user_id: str) -> str:
    m = _MSG_ROOM_ID_RE.search(user_id)
    if m:
        return f"msg_{m.group(1)}"
    s = user_id.strip().lower()
    s = s.replace("@", "_at_")
    s = s.replace(".", "_")
    s = s.replace("+", "_plus_")
    s = re.sub(r"[^a-z0-9_]", "_", s)
    return s

# 한 계정(도메인+user_id)의 모든 데이터/산출물 파일 경로를 한곳에 모아 계산·보관하는 클래스
class UserPaths:
    # base_dir/도메인/user_id 기준으로 모든 하위 경로 속성을 계산하고 계정 메타 파일을 보장한다
    def __init__(self, base_dir: str, user_id: str, domain: str):
        self.BASE_DIR = base_dir
        self.USER_ID = user_id
        self.DOMAIN = domain

        dir_name = _mail_to_dir_name(user_id)

        # user_data/<domain>/<계정 또는 단톡방>/ 구조 — 도메인(메일/카카오)별로 먼저 나누고 그 밑에 계정 폴더를 둔다.
        self.USER_ROOT = os.path.join(base_dir, "user_data", domain, dir_name)

        # RAG_ENGINE별로 저장 위치를 완전히 분리한다

        # GraphRAG 데이터 저장 위치
        self.DOMAIN_ROOT = os.path.join(self.USER_ROOT, "graphrag")     
        self.GRAPHRAG_ROOT = os.path.join(self.DOMAIN_ROOT, "parquet")

        # LightRAG 데이터 저장 위치
        self.LIGHTRAG_ROOT = os.path.join(self.USER_ROOT, "lightrag")
        # GraphRAG 결과 폴더(cache/input/logs/output)와 구조를 맞추기 위한 하위 폴더.
        self.LIGHTRAG_OUTPUT_DIR = os.path.join(self.LIGHTRAG_ROOT, "output")
        self.LIGHTRAG_INPUT_DIR = os.path.join(self.LIGHTRAG_ROOT, "input")
        self.LIGHTRAG_LOGS_DIR = os.path.join(self.LIGHTRAG_ROOT, "logs")

        # LightRAG용 그래프 시각화 json
        self.LIGHTRAG_GRAPH_JSON_PATH = os.path.join(self.LIGHTRAG_ROOT, "json", "graph_data.json")

        self.USER_GRAPH_SETTINGS_PATH = os.path.join(self.GRAPHRAG_ROOT, "settings.yaml")
        self.USER_GRAPH_PROMPTS_PATH = os.path.join(self.GRAPHRAG_ROOT, "prompts")

        self.GRAPH_JSON_PATH = os.path.join(self.DOMAIN_ROOT, "json", "graph_data.json")
        self.GRAPH_BUILD_SCRIPT = os.path.join(base_dir, "src", "graphrag_parquet2json.py")

        # 원본 메일/첨부파일(latest.txt, latest.csv, attachments/)이 저장되는 위치.
        if RAG_ENGINE == "lightrag":
            self.MAIL_DIR = self.LIGHTRAG_INPUT_DIR
        else:
            self.MAIL_DIR = os.path.join(self.GRAPHRAG_ROOT, "input")

        self.MAIL_LATEST_PATH = os.path.join(self.MAIL_DIR, "latest.txt")
        self.ATTACHMENT_DIR = os.path.join(self.MAIL_DIR, "attachments")

        self.PARQUET_DIR = os.path.join(self.DOMAIN_ROOT, "parquet", "output") # output 폴더: parquet들 저장 (GraphRAG 전용)
        self.ENTITIES_PATH = os.path.join(self.PARQUET_DIR, "entities.parquet") # 노드 데이터: 엔티티 목록
        self.RELATIONSHIPS_PATH = os.path.join(self.PARQUET_DIR, "relationships.parquet") # 엣지 데이터: 엔티티 간 관계
        self.COMMUNITIES_PATH = os.path.join(self.PARQUET_DIR, "communities.parquet") # 커뮤니티 데이터: 군집화한 노드 그룹 정보

        # 연락처/키워드 통계, 요약, 아바타 등을 저장하는 위치
        if RAG_ENGINE == "lightrag":
            self.MAIL_STATICS_PATH = os.path.join(self.LIGHTRAG_ROOT, "statics")
        else:
            self.MAIL_STATICS_PATH = os.path.join(self.PARQUET_DIR, "statics")
        self.MAIL_CONTACTS_PATH = os.path.join(self.MAIL_STATICS_PATH, "mail_contact_stats.json")
        self.MAIL_KEYWORDS_PATH  = os.path.join(self.MAIL_STATICS_PATH, "mail_keyword_stats.json")
        self.MAIL_SUMMARIES_PATH = os.path.join(self.MAIL_STATICS_PATH, "mail_summaries.json")
        self.MAIL_SUMMARY_IMAGES_DIR = os.path.join(self.MAIL_STATICS_PATH, "mail_summary_images")
        self.MAIL_PHOTOS_PATH    = os.path.join(self.MAIL_STATICS_PATH, "contact_photos.json")
        self.MAIL_AVATARS_PATH  = os.path.join(self.MAIL_STATICS_PATH, "person_avatars.json")
        self.AVATAR_IMAGES_DIR  = os.path.join(self.MAIL_STATICS_PATH, "avatars")
        self.MAIL_MESSAGE_CACHE_PATH = os.path.join(self.MAIL_STATICS_PATH, "mail_message_cache.json")
        self.CHATROOM_PEOPLE_MESSAGES_PATH = os.path.join(self.MAIL_STATICS_PATH, "chatroom_people_messages.json")
        self.MESSAGE_KEYWORDS_PATH = os.path.join(self.MAIL_STATICS_PATH, "message_keyword_stats.json")
        self.MESSAGE_SUMMARIES_PATH = os.path.join(self.MAIL_STATICS_PATH, "message_summaries.json")
        self.MESSAGE_SUMMARY_IMAGES_DIR = os.path.join(self.MAIL_STATICS_PATH, "message_summary_images")
        self.MESSAGE_MOOD_PATH = os.path.join(self.MAIL_STATICS_PATH, "message_mood.json")
        self.MESSAGE_AVATARS_PATH = os.path.join(self.MAIL_STATICS_PATH, "chatroom_people_avatars.json")
        self.MESSAGE_AVATAR_IMAGES_DIR = os.path.join(self.MAIL_STATICS_PATH, "chatroom_avatars")
        self.UPDATE_DIR = os.path.join(self.GRAPHRAG_ROOT, "update_output")
        self.ACCOUNT_META_PATH = os.path.join(self.USER_ROOT, ACCOUNT_META_FILENAME)
        _ensure_account_meta(self)

# 계정 폴더에 원본 user_id를 담은 account.json이 없으면 새로 만든다 (sanitize된 폴더명으로부터 복원용)
def _ensure_account_meta(paths: "UserPaths"):
    if os.path.exists(paths.ACCOUNT_META_PATH):
        return
    try:
        os.makedirs(paths.USER_ROOT, exist_ok=True)
        with open(paths.ACCOUNT_META_PATH, "w", encoding="utf-8") as f:
            json.dump({"user_id": paths.USER_ID}, f, ensure_ascii=False)
    except OSError:
        pass

# 업로드 시점에 알고 있는 채팅방 이름을 account.json의 room_name에 저장한다 (인덱싱 전 표시용 폴백)
def set_account_room_name(paths: "UserPaths", room_name: str):
    if not room_name:
        return
    try:
        os.makedirs(paths.USER_ROOT, exist_ok=True)
        meta = {}
        if os.path.exists(paths.ACCOUNT_META_PATH):
            try:
                with open(paths.ACCOUNT_META_PATH, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                meta = {}
        meta["user_id"] = paths.USER_ID
        meta["room_name"] = room_name
        with open(paths.ACCOUNT_META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except OSError:
        pass

# 계정 하나의 인덱싱 완료 여부를 현재 RAG_ENGINE에 맞는 방식으로 판단한다
def _account_indexed(paths) -> bool:
    from config.settings import RAG_ENGINE
    if RAG_ENGINE == "lightrag":
        from util.lightrag_backend.lightrag_engine import is_index_ready
        return is_index_ready(paths.LIGHTRAG_OUTPUT_DIR)
    elif RAG_ENGINE == "graphrag":
        from util.graphrag import _is_index_ready
        return _is_index_ready(paths)
    return False

# path 아래 모든 파일의 가장 최근 수정 시각(mtime)을 재귀적으로 찾는다 (없으면 0.0)
def _dir_max_mtime(path: str) -> float:
    if not os.path.isdir(path):
        return 0.0
    latest = 0.0
    try:
        for root, _dirs, files in os.walk(path):
            for fname in files:
                try:
                    mtime = os.path.getmtime(os.path.join(root, fname))
                    if mtime > latest:
                        latest = mtime
                except OSError:
                    continue
    except OSError:
        pass
    return latest

# 계정 하나의 "가장 최근 인덱싱 시각" 근사치를 인덱싱 산출물 디렉터리의 최신 mtime으로 구한다
def _account_indexed_at(paths) -> float:
    from config.settings import RAG_ENGINE
    if RAG_ENGINE == "lightrag":
        return _dir_max_mtime(paths.LIGHTRAG_OUTPUT_DIR)
    elif RAG_ENGINE == "graphrag":
        return _dir_max_mtime(paths.GRAPHRAG_ROOT)
    return 0.0

# user_data/{domain} 디렉터리를 훑어 각 계정의 user_id·인덱싱 여부·시각·방 이름을 담은 목록을 반환한다 (최근 인덱싱순 정렬)
def list_accounts(base_dir: str, domain: str = "mail") -> list[dict]:
    user_data_dir = os.path.join(base_dir, "user_data", domain)
    accounts = []

    if os.path.isdir(user_data_dir):
        for dir_name in sorted(os.listdir(user_data_dir)):
            dir_path = os.path.join(user_data_dir, dir_name)
            if not os.path.isdir(dir_path):
                continue
            # user_data/{domain}/ 아래를 훑는 것 자체가 이미 도메인 필터링이라 별도 체크 불필요.

            meta_path = os.path.join(dir_path, ACCOUNT_META_FILENAME)
            user_id = None
            room_name = None
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        user_id = (meta.get("user_id") or "").strip()
                        room_name = (meta.get("room_name") or "").strip() or None
                except (OSError, json.JSONDecodeError):
                    user_id = None

            if not user_id:
                user_id = dir_name.replace("_at_", "@", 1).replace("_", ".")

            paths = UserPaths(base_dir, user_id, domain)
            accounts.append({
                "user_id": user_id,
                "indexed": _account_indexed(paths),
                "indexed_at": _account_indexed_at(paths),
                "room_name": room_name,
            })

    # 가장 최근에 인덱싱된 계정이 맨 앞에 오도록 정렬 
    accounts.sort(key=lambda a: a["indexed_at"], reverse=True)

    return accounts

# 인덱싱까지 완료된 계정의 user_id만 리스트로 반환한다 (연합 검색 대상 목록)
def list_indexed_user_ids(base_dir: str, domain: str = "mail") -> list[str]:
    return [a["user_id"] for a in list_accounts(base_dir, domain) if a["indexed"]]

# 도메인별 공용 settings.yaml과 prompts를 사용자 GraphRAG 폴더에 최신본으로 복사한다
def user_graphrag_init(paths):
    domain = paths.DOMAIN

    # 1. parquet 폴더 보장
    os.makedirs(paths.GRAPHRAG_ROOT, exist_ok=True)

    # 2. 도메인별 공용 템플릿 존재 확인
    if not os.path.exists(GRAPHRAG_SETTINGS_DIR(domain)):
        raise FileNotFoundError(
            f"[ERROR] {domain} 공용 settings.yaml 없음: {GRAPHRAG_SETTINGS_DIR(domain)}"
        )
    if not os.path.exists(GRAPHRAG_PROMPTS_DIR(domain)):
        raise FileNotFoundError(
            f"[ERROR] {domain} 공용 prompts 폴더 없음: {GRAPHRAG_PROMPTS_DIR(domain)}"
        )

    # 3. settings.yaml복사(있으면 덮어쓰기), 항상 최신 settings.yaml을 사용하기 위함
    shutil.copy2(GRAPHRAG_SETTINGS_DIR(domain), paths.USER_GRAPH_SETTINGS_PATH)
    print(f"[INIT] settings.yaml 복사/덮어쓰기 완료 → {paths.USER_GRAPH_SETTINGS_PATH}")

    # 4. prompts 폴더 전체 복사(있으면 덮어쓰기), 항상 최신 prompts를 사용하기 위함
    shutil.copytree(
        GRAPHRAG_PROMPTS_DIR(domain),
        paths.USER_GRAPH_PROMPTS_PATH,
        dirs_exist_ok=True  # 기존 프롬프트가 있으면 덮어쓰기
    )