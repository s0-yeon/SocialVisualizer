# -*- coding: utf-8 -*-
"""
production 그대로: graphrag==3.1.1 라이브러리의 실제 GlobalCommunityContext를 사용해서
global_search MAP 단계 배치(context_chunks)를 재현.
graphrag_engine.py._build_global_engine()과 동일한 파라미터로 맞춤:
  - community_level = 0 (가장 낮은 레벨)
  - use_community_summary = False (전문 full_content 사용)
  - include_community_rank = True
  - community_weight_name = "occurrence weight"
  - max_context_tokens = 12000 (GlobalSearchConfig 기본값, settings.yaml에 override 없음)
  - data_max_tokens(reduce용) = 12000, map_max_length=1000, reduce_max_length=2000 (모두 기본값)

## English summary
Faithful to production: uses the real GlobalCommunityContext from the graphrag==3.1.1 library to
reproduce the global_search MAP-stage batches (context_chunks). Parameters match
graphrag_engine.py._build_global_engine() exactly: community_level=0 (lowest level),
use_community_summary=False (uses full full_content text), include_community_rank=True,
community_weight_name="occurrence weight", max_context_tokens=12000 (GlobalSearchConfig default,
no override in settings.yaml), data_max_tokens(for reduce)=12000, map_max_length=1000,
reduce_max_length=2000 (all defaults).
"""
import asyncio
import pandas as pd
from graphrag.query.indexer_adapters import (
    read_indexer_entities,
    read_indexer_reports,
    read_indexer_communities,
)
from graphrag.query.structured_search.global_search.community_context import GlobalCommunityContext
from graphrag.tokenizer.get_tokenizer import get_tokenizer

MAX_CONTEXT_TOKENS = 12000  # GlobalSearchConfig default (settings.yaml에 override 없음)


# GraphRAG parquet 산출물(entities/communities/community_reports)로부터 GlobalCommunityContext를 구성함
def load_global_context_builder(output_dir: str) -> GlobalCommunityContext:
    entity_df = pd.read_parquet(f"{output_dir}/entities.parquet")
    community_df = pd.read_parquet(f"{output_dir}/communities.parquet")
    report_df = pd.read_parquet(f"{output_dir}/community_reports.parquet")

    best_level = 0
    entities = read_indexer_entities(entity_df, community_df, community_level=best_level)
    reports = read_indexer_reports(report_df, community_df, community_level=best_level)
    communities = read_indexer_communities(community_df, report_df)

    tokenizer = get_tokenizer(encoding_model="cl100k_base")

    return GlobalCommunityContext(
        entities=entities,
        communities=communities,
        community_reports=reports,
        tokenizer=tokenizer,
    )


# GraphRAG production과 동일한 파라미터로 MAP 단계 컨텍스트 배치를 생성함
async def build_map_batches(context_builder: GlobalCommunityContext, query: str):
    """실제 production과 동일한 파라미터로 context_result.context_chunks(=MAP 배치 리스트) 생성."""
    result = await context_builder.build_context(
        query=query,
        use_community_summary=False,
        include_community_rank=True,
        community_weight_name="occurrence weight",
        max_context_tokens=MAX_CONTEXT_TOKENS,
    )
    return result.context_chunks  # list[str], 각각 하나의 MAP LLM 호출에 대응


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="./raw_data/Llama_mail_output/Llama_mail_output/output",
                         help="GraphRAG parquet output dir (entities/communities/community_reports.parquet)")
    parser.add_argument("--query", default="최근 진행된 프로젝트나 협업에는 어떤 것들이 있었어?")
    args = parser.parse_args()

    cb = load_global_context_builder(args.output_dir)
    query = args.query
    batches = asyncio.run(build_map_batches(cb, query))
    print(f"query: {query}")
    print(f"num MAP batches: {len(batches)}")
    for i, b in enumerate(batches):
        print(f"--- batch {i} : {len(b)} chars ---")
        print(b[:300])
        print("...")
