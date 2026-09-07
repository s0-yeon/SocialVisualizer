import os

# 프로젝트 루트
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 해당 도메인의 GraphRAG settings.yaml 경로를 만들어 반환한다
def GRAPHRAG_SETTINGS_DIR(domain):
    return os.path.join(BASE_DIR, "parquet_template", "rendered", domain, "settings.yaml")

# 해당 도메인의 GraphRAG 프롬프트 디렉터리 경로를 만들어 반환한다
def GRAPHRAG_PROMPTS_DIR(domain):
    return os.path.join(BASE_DIR, "parquet_template", "rendered", domain, "prompts")

# 메일 블록 구분자
MAIL_BLOCK_SEP = "============================================================"

# 질의 및 인덱싱 시 RAG 엔진 결정
RAG_ENGINE = "graphrag"

# 지원 가능한 RAG 엔진
SUPPORTED_RAG_ENGINES = ("graphrag", "lightrag")
if RAG_ENGINE not in SUPPORTED_RAG_ENGINES:
    raise ValueError(f"지원하지 않는 RAG_ENGINE 값: {RAG_ENGINE!r} (가능한 값: {SUPPORTED_RAG_ENGINES})")


