# GraphRAG의 LocalSearch/GlobalSearch 엔진을 유저별로 메모리에 캐싱해두고, 인덱스가 갱신되면 새로 빌드해 재사용한다.

# Caches GraphRAG's LocalSearch/GlobalSearch engines in memory per user and rebuilds them when the index is updated, for reuse across queries.

import os
from pathlib import Path # 파일 경로를 객체로 다루기 위한 표준 라이브러리
import openai # OpenAI API 호출용
import threading
_cache_lock = threading.Lock() # 멀티스레드 환경에서 캐시 동시 접근하는 것을 방지하기 위한 락
from graphrag.config.load_config import load_config # settings.yaml 설정 로더
from graphrag.query.context_builder.entity_extraction import EntityVectorStoreKey
from graphrag.query.indexer_adapters import (
    read_indexer_entities,       # parquet → Entity 객체 리스트로 변환
    read_indexer_relationships,  # parquet → Relationship 객체 리스트로 변환
    read_indexer_reports,        # parquet → CommunityReport 객체 리스트로 변환
    read_indexer_text_units,     # parquet → TextUnit 객체 리스트로 변환
    read_indexer_communities,    # parquet → Community 객체 리스트로 변환
)
from graphrag.query.structured_search.local_search.mixed_context import LocalSearchMixedContext  # 로컬 서치 컨텍스트 빌더
from graphrag.query.structured_search.local_search.search import LocalSearch   # 실제 로컬 서치 엔진
from graphrag_vectors.lancedb import LanceDBVectorStore                        # 임베딩 저장용 로컬 벡터 DB
from collections.abc import AsyncGenerator # 비동기 제너레이터 타입 힌트용
from graphrag.query.structured_search.global_search.community_context import GlobalCommunityContext
from graphrag.query.structured_search.global_search.search import GlobalSearch # 실제 글로벌 서치 엔진
from graphrag_llm.tokenizer import create_tokenizer # v3: Tokenizer 객체 생성 팩토리
from graphrag_llm.config import TokenizerConfig

# GraphRAG 검색 엔진이 쓰는 채팅 모델 어댑터 — OpenAI(호환) API를 직접 호출하며 토큰 사용량을 누적한다
class DirectOpenAIChatModel:
    # 비동기 OpenAI 클라이언트를 만들고 모델명·토큰 카운터를 초기화한다 (api_base 지정 시 로컬 vLLM으로 라우팅)
    def __init__(self, api_key: str, model: str, api_base: str | None = None):
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base) if api_base else openai.AsyncOpenAI(api_key=api_key) # 비동기 OpenAI(호환) 클라이언트
        self._model = model # 사용할 모델명
        self._input_tokens = 0
        self._output_tokens = 0

    # 누적된 토큰 사용량을 반환하고 카운터를 0으로 초기화한다
    def consume_usage(self) -> dict:
        result = {
            "model_name": self._model,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
        }
        self._input_tokens = 0
        self._output_tokens = 0
        return result

    # LocalSearch/GlobalSearch가 호출하는 채팅 완성 진입점 — 응답의 토큰 사용량을 누적한다
    async def completion_async(self, *, messages, stream: bool = False, **kwargs):
        params = dict(kwargs)
        # graphrag_llm 전용 키워드(OpenAI API에는 없음) → OpenAI JSON mode로 변환
        if params.pop("response_format_json_object", False):
            params["response_format"] = {"type": "json_object"}

        if stream:
            return self._stream_completion(messages, params)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=False,
            **params,
        )
        if response.usage:
            self._input_tokens += response.usage.prompt_tokens
            self._output_tokens += response.usage.completion_tokens
        return response

    # 스트리밍 채팅 완성을 청크 단위로 yield하며 토큰 사용량을 누적한다
    async def _stream_completion(self, messages, params: dict) -> AsyncGenerator:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            **params,
        )
        async for chunk in stream:
            if chunk.usage:
                self._input_tokens += chunk.usage.prompt_tokens
                self._output_tokens += chunk.usage.completion_tokens
            if chunk.choices:
                yield chunk

# GraphRAG 컨텍스트 빌더가 쓰는 임베딩 어댑터 — OpenAI(호환) 임베딩 API를 직접 호출한다
class DirectOpenAIEmbedder:
    # 동기 OpenAI 클라이언트와 임베딩 모델명을 초기화한다 (api_base 지정 시 로컬 vLLM으로 라우팅)
    def __init__(self, api_key: str, model: str, api_base: str | None = None):
        self._client = openai.OpenAI(api_key=api_key, base_url=api_base) if api_base else openai.OpenAI(api_key=api_key) # 동기 OpenAI(호환) 클라이언트
        self._model = model # 사용할 임베딩 모델명

    # 입력 문자열 리스트를 임베딩해 _EmbeddingResponse로 감싸 반환한다
    def embedding(self, *, input: list[str], **kwargs) -> "_EmbeddingResponse":
        response = self._client.embeddings.create(
            input=input,
            model=self._model
        )
        return _EmbeddingResponse([d.embedding for d in response.data])


# graphrag_llm의 LLMEmbeddingResponse를 흉내 내는 래퍼 (.embeddings / .first_embedding 속성만 제공)
class _EmbeddingResponse:
    # 임베딩 벡터 리스트를 보관한다
    def __init__(self, embeddings: list[list[float]]):
        self._embeddings = embeddings

    # 전체 임베딩 벡터 리스트를 반환한다
    @property
    def embeddings(self) -> list[list[float]]:
        return self._embeddings

    # 첫 번째 임베딩 벡터를 반환한다 (없으면 빈 리스트)
    @property
    def first_embedding(self) -> list[float]:
        return self._embeddings[0] if self._embeddings else []

# 유저별 엔진 캐시
_engine_cache: dict = {}

# entities.parquet의 마지막 수정 시각을 반환한다 (없으면 0.0) — 인덱스 갱신 감지용
def _get_output_mtime(output_dir: str) -> float:
    p = os.path.join(output_dir, "entities.parquet")
    return os.path.getmtime(p) if os.path.exists(p) else 0.0

# parquet과 lancedb를 읽어 LocalSearch 엔진과 채팅 모델을 새로 조립해 반환한다
def _build_local_engine(output_dir: str, graphrag_root: str) -> tuple[LocalSearch, "DirectOpenAIChatModel"]:
    import pandas as pd
    lancedb_uri = os.path.join(output_dir, "lancedb")
    #setting.yaml에서 설정 가져옴
    config = load_config(Path(graphrag_root))

    # v3: models → completion_models/embedding_models로 분리됨
    # settings.yaml의 local_search
    ls_config = config.local_search
    llm_config = config.completion_models["default_chat_model"]
    emb_config = config.embedding_models[ls_config.embedding_model_id]

    # LLM: 최종 답변 생성용
    model = DirectOpenAIChatModel(
        api_key=os.environ["LLM_API_KEY"],
        model=llm_config.model,  # gpt-4o-mini
        api_base=getattr(llm_config, "api_base", None),
    )
    text_embedder = DirectOpenAIEmbedder(
        api_key=emb_config.api_key,
        model=emb_config.model,
        api_base=getattr(emb_config, "api_base", None),
    )

    # v3: token_encoder(raw tiktoken 객체) 대신 tokenizer(Tokenizer 객체)를 사용
    tokenizer = create_tokenizer(TokenizerConfig(type="tiktoken", encoding_name=config.chunking.encoding_model))

    # graphrag가 인덱싱 완료 후 output/ 폴더에 생성한 parquet 파일들을 DataFrame으로 로드
    entity_df    = pd.read_parquet(os.path.join(output_dir, "entities.parquet"))
    community_df = pd.read_parquet(os.path.join(output_dir, "communities.parquet"))
    relation_df  = pd.read_parquet(os.path.join(output_dir, "relationships.parquet"))
    report_df    = pd.read_parquet(os.path.join(output_dir, "community_reports.parquet"))
    text_unit_df = pd.read_parquet(os.path.join(output_dir, "text_units.parquet"))
    
    best_level = int(community_df['level'].value_counts().idxmax())
    # DataFrame → graphrag 내부 객체로 변환. read_indexer_* 함수들이 DataFrame을 graphrag가 이해하는 데이터 클래스로 변환해줌
    entities      = read_indexer_entities(entity_df, community_df, community_level=best_level)
    relationships = read_indexer_relationships(relation_df)
    reports       = read_indexer_reports(report_df, community_df, community_level=best_level)
    text_units    = read_indexer_text_units(text_unit_df)

    # 벡터스토어 연결 및 엔티티 임베딩 로드 (graphrag 인덱싱 시 생성된 lancedb에 저장된 엔티티 임베딩을 불러옴)
    description_embedding_store = LanceDBVectorStore(
        db_uri=lancedb_uri,
        index_name="entity_description",
        vector_size=config.vector_store.vector_size,
    )
    description_embedding_store.connect()

    # 컨텍스트 빌더 생성 (LLM에 넘길 컨텍스트를 조립하는 역할)
    context_builder = LocalSearchMixedContext(
        entities=entities,
        entity_text_embeddings=description_embedding_store,
        text_embedder=text_embedder,
        text_units=text_units,
        community_reports=reports,
        relationships=relationships,
        covariates=None,
        tokenizer=tokenizer,
        embedding_vectorstore_key=EntityVectorStoreKey.ID,
    )

    prompt_path = os.path.join(graphrag_root, "prompts", "local_search.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # LocalSearch 엔진 생성 (이 객체가 실제로 search(query)를 받아서 LLM 응답을 생성하는 핵심 객체) 재사용 가능
    engine = LocalSearch(
        model=model,
        context_builder=context_builder,
        tokenizer=tokenizer,
        system_prompt=system_prompt,
        model_params=dict(llm_config.call_args),
        context_builder_params={
            "text_unit_prop": ls_config.text_unit_prop,           # 0.5
            "community_prop": ls_config.community_prop,           # 0.1
            "top_k_mapped_entities": ls_config.top_k_entities,    # 10
            "top_k_relationships": ls_config.top_k_relationships, # 30
            "max_context_tokens": ls_config.max_context_tokens,   # 컨텍스트 조립 예산(OpenAI API 파라미터 아님, 안전)
            "include_entity_rank": True,
            "include_relationship_weight": True,
        },
        # "multiple paragraphs"(SFT 학습 시 재구성한 프롬프트에도 쓰인 값)에서
        # 개조식(마크다운 불릿)을 명시적으로 요구
        response_type="a concise breakdown organized as short markdown bullet points, one distinct point per line — avoid long flowing paragraphs",
    )
    return engine, model

# parquet(엔티티·커뮤니티·리포트)을 읽어 GlobalSearch 엔진과 채팅 모델을 새로 조립해 반환한다
def _build_global_engine(output_dir: str, graphrag_root: str) -> tuple[GlobalSearch, "DirectOpenAIChatModel"]:
    import pandas as pd
    config = load_config(Path(graphrag_root))

    llm_config = config.completion_models["default_chat_model"]
    gs_config  = config.global_search  # settings.yaml의 global_search 설정

    model = DirectOpenAIChatModel(
        api_key=os.environ["LLM_API_KEY"],
        model=llm_config.model,
        api_base=getattr(llm_config, "api_base", None),
    )
    tokenizer = create_tokenizer(TokenizerConfig(type="tiktoken", encoding_name=config.chunking.encoding_model))

    # LocalSearch와 달리 text_units, lancedb, 임베딩 모델 불필요 (커뮤니티 보고서와 엔티티만 필요함)
    entity_df    = pd.read_parquet(os.path.join(output_dir, "entities.parquet"))
    community_df = pd.read_parquet(os.path.join(output_dir, "communities.parquet"))
    report_df    = pd.read_parquet(os.path.join(output_dir, "community_reports.parquet"))

    # 글로벌 서치는 가장 낮은 레벨 선택 (전체 트랜드 파악하기 위함)
    best_level = 0 # int(community_df['level'].min())
    print(f"[ENGINE] global community_level 자동 선택: {best_level}")

    entities = read_indexer_entities(entity_df, community_df, community_level=best_level)
    reports  = read_indexer_reports(report_df, community_df, community_level=best_level)
    communities = read_indexer_communities(community_df, report_df)

    # GlobalCommunityContext: 커뮤니티 보고서를 계층적으로 조립해서 LLM에 넘기는 컨텍스트 빌더
    context_builder = GlobalCommunityContext(
        entities=entities,
        communities=communities,
        community_reports=reports,
        tokenizer=tokenizer,
    )

    prompts_dir = os.path.join(graphrag_root, "prompts")
    with open(os.path.join(prompts_dir, "global_search_map.txt"), "r", encoding="utf-8") as f:
        map_prompt = f.read()
    with open(os.path.join(prompts_dir, "global_search_reduce.txt"), "r", encoding="utf-8") as f:
        reduce_prompt = f.read()

    engine = GlobalSearch(
        model=model,
        context_builder=context_builder,
        tokenizer=tokenizer,
        map_system_prompt=map_prompt,         # 각 커뮤니티 보고서 개별 요약용
        reduce_system_prompt=reduce_prompt,   # 개별 요약 → 최종 답변 합산용
        json_mode=False,                      # JSON 강제 파싱 비활성화
        map_llm_params=dict(llm_config.call_args),
        reduce_llm_params=dict(llm_config.call_args),
        max_data_tokens=gs_config.data_max_tokens,  # reduce 단계에 넣을 map 결과 최대 토큰 (v3: GlobalSearch 생성자 인자)
        concurrent_coroutines=config.concurrent_requests,   # concurrent_requests(settings.j2 전역 설정)를 map 단계 동시 실행 개수로 사용
        context_builder_params={
            "max_context_tokens": gs_config.max_context_tokens, # map 단계 컨텍스트(커뮤니티 리포트) 조립 예산
            "use_community_summary": False,
            "include_community_rank": True,
            "community_weight_name": "occurrence weight",  # build_community_context()의 실제 기본 가중치 속성명과 일치
        },
    )
    return engine, model

# 유저별로 캐시된 (LocalSearch, GlobalSearch) 엔진을 반환한다 (캐시 미스·인덱스 갱신 시 새로 빌드)
def get_engines(user_id: str, output_dir: str, graphrag_root: str) -> tuple[LocalSearch, GlobalSearch]:
    mtime = _get_output_mtime(output_dir)

    # 인덱스가 아직 생성되지 않은 상태._is_index_ready()로 이미 걸러지지만 방어적으로 한 번 더 체크
    if mtime == 0.0:
        raise RuntimeError(f"인덱스가 아직 생성되지 않았습니다: {output_dir}")

    with _cache_lock:  # 동시 접근 방지
        cached = _engine_cache.get(user_id)

        if cached and cached["mtime"] == mtime:
            return cached["local"], cached["global"]

        # 캐시 miss 또는 인덱스 갱신 감지 (index/update 실행 후 mtime 변경): 새로 빌드
        print(f"[ENGINE] 빌드 시작: {user_id}")
        local_engine,  local_model  = _build_local_engine(output_dir, graphrag_root)
        global_engine, global_model = _build_global_engine(output_dir, graphrag_root)
        _engine_cache[user_id] = {
            "local":         local_engine,
            "global":        global_engine,
            "local_model":   local_model,
            "global_model":  global_model,
            "mtime":         mtime,
        }
        print(f"[ENGINE] 빌드 완료: {user_id}")
        return local_engine, global_engine


# 지정한 method(local/global) 엔진의 누적 토큰 사용량을 반환하고 초기화한다
def get_and_reset_usage(user_id: str, method: str) -> dict:
    with _cache_lock:
        cached = _engine_cache.get(user_id)
        if not cached:
            return {"model_name": None, "input_tokens": 0, "output_tokens": 0}
        key = "local_model" if method == "local" else "global_model"
        model: DirectOpenAIChatModel = cached[key]
        return model.consume_usage()
