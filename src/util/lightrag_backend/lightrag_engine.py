# src/util/lightrag_backend/lightrag_engine.py

# 계정별 LightRAG 인스턴스를 만들고 캐싱하는 모듈. 
# LLM/임베딩 함수를 로컬 vLLM 엔드포인트에 연결한 LightRAG 객체를 유저 단위로 캐시해 재사용하고, 인덱스 파일(graphml)이 갱신되거나 이벤트 루프가 바뀌면 자동으로 새로 빌드한다. 
# 인덱싱 완료 여부 판단, 유저별 토큰 사용량 조회도 함께 제공한다.

# Builds and caches per-account LightRAG instances. 
# Wires the LLM/embedding functions to local vLLM endpoints and reuses a cached instance per user, rebuilding automatically when the index file (graphml) changes or the calling event loop differs. 
# Also exposes index-ready checks and per-user token usage lookups.

import os
import sys
import asyncio
import threading
from functools import partial

from config.settings import BASE_DIR

sys.path.insert(0, os.path.join(BASE_DIR, "LightRAG"))
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc, TokenTracker
from lightrag.llm.openai import openai_complete_if_cache, openai_embed

_RAG_CHAT_MODEL = os.environ.get("RAG_CHAT_MODEL", "gpt-4o-mini")
_RAG_EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "text-embedding-3-small")

# job_run_lightrag.py에 있는 것과 같은 표. 임베딩 모델별 벡터 차원 수
# (LightRAG는 embedding_dim을 미리 알아야 해서 자동 감지가 안 됨).
_EMBEDDING_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "BAAI/bge-m3": 1024,
}

_cache_lock = threading.Lock()
# 유저별 캐시: { user_id: { "rag": LightRAG 인스턴스, "token_tracker": TokenTracker, "mtime": float } }
_instance_cache: dict = {}


# LightRAG 그래프 파일(graphml)의 수정 시각을 반환한다 (없으면 0.0) — 인덱스 최신 여부 판단 기준
def _get_storage_mtime(working_dir: str) -> float:
    graph_path = os.path.join(working_dir, "graph_chunk_entity_relation.graphml")
    return os.path.getmtime(graph_path) if os.path.exists(graph_path) else 0.0


# graphml 파일 존재 여부로 LightRAG 인덱싱 완료 여부를 반환한다
def is_index_ready(working_dir: str) -> bool:
    return _get_storage_mtime(working_dir) > 0.0


# LLM/임베딩 함수에 TokenTracker를 물린 LightRAG 인스턴스를 새로 만들어 스토리지까지 초기화해 반환한다
async def _build_lightrag_instance(working_dir: str, token_tracker: TokenTracker) -> LightRAG:
    api_key = os.environ.get("LLM_API_KEY")

    llm_model_func = partial(
        openai_complete_if_cache,
        _RAG_CHAT_MODEL,
        api_key=api_key,
        base_url=os.environ.get("RAG_CHAT_API_BASE") or None,  # 지정 시 로컬 vLLM(라마)으로 라우팅
        token_tracker=token_tracker,
    )
    embedding_func = EmbeddingFunc(
        embedding_dim=_EMBEDDING_DIMS.get(_RAG_EMBEDDING_MODEL, 1536),
        func=partial(
            openai_embed.func,
            model=_RAG_EMBEDDING_MODEL,
            api_key=api_key,
            base_url=os.environ.get("INDEXING_EMBEDDING_API_BASE") or None,  # 로컬 bge-m3로 라우팅
            token_tracker=token_tracker,
        ),
    )

    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )
    await rag.initialize_storages()
    return rag


# 유저별로 캐시된 LightRAG 인스턴스를 반환한다 (캐시 미스·인덱스 갱신·이벤트 루프 불일치 시 새로 빌드)
async def get_lightrag_instance(user_id: str, working_dir: str) -> LightRAG:
    mtime = _get_storage_mtime(working_dir)
    if mtime == 0.0:
        raise RuntimeError(f"인덱스가 아직 생성되지 않았습니다: {working_dir}")

    current_loop = asyncio.get_running_loop()

    with _cache_lock:
        cached = _instance_cache.get(user_id)
        if cached and cached["mtime"] == mtime and cached["loop"] is current_loop:
            return cached["rag"]

    # 캐시 미스, 인덱스 갱신, 또는 이전과 다른 이벤트 루프에서 호출되므로 새로 빌드한다
    print(f"[ENGINE][lightrag] 인스턴스 빌드 시작: {user_id}")
    token_tracker = TokenTracker()
    rag = await _build_lightrag_instance(working_dir, token_tracker)

    with _cache_lock:
        _instance_cache[user_id] = {
            "rag": rag, "token_tracker": token_tracker, "mtime": mtime, "loop": current_loop,
        }

    print(f"[ENGINE][lightrag] 인스턴스 빌드 완료: {user_id}")
    return rag


# 유저의 누적 토큰 사용량을 조회해 dict로 반환하고 트래커를 리셋한다
def get_and_reset_usage(user_id: str) -> dict:
    with _cache_lock:
        cached = _instance_cache.get(user_id)
        if not cached:
            return {"model_name": _RAG_CHAT_MODEL, "input_tokens": 0, "output_tokens": 0}

        tracker: TokenTracker = cached["token_tracker"]
        usage = {
            "model_name": _RAG_CHAT_MODEL,
            "input_tokens": tracker.prompt_tokens,
            "output_tokens": tracker.completion_tokens,
        }
        tracker.reset()
        return usage
