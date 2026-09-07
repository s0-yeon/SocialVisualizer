"""
rebuild_lancedb.py — 1536차원(OpenAI) lancedb → bge-m3 1024차원 lancedb 재생성

배경: 기존 lancedb(메일 + 메신저 13개 방 전부)가 1536차원(OpenAI text-embedding-3-small/
ada-002 계열)으로 저장돼 있었으나, 실제 쿼리 시점에 쓰는 임베딩 모델은 bge-m3(1024차원)라
그대로는 검색이 안 됨. 재인덱싱 없이 다음 3단계로 해결:

1. entities.parquet의 description 텍스트(메일 3,492개 + 메신저 13개 방 1,348개, 총 4,840개)만
   추출해 GPU 서버의 실제 bge-m3 vLLM 임베딩 서버(localhost:8001)로 배치 64개씩 재임베딩
2. 결과(1024차원)를 LanceDBVectorStore.create_index() + load_documents()로
   output/lancedb_bgem3/ 경로에 새 벡터스토어 생성 (기존 lancedb는 그대로 보존)
3. 질문도 동일 서버로 미리 임베딩해 검색 시점엔 API 재호출 없이 사용 (→ local_build_context.py의
   StubTextEmbedder가 이 사전계산 임베딩을 사용함)

## English summary
rebuild_lancedb.py regenerates the lancedb from 1536-dim (OpenAI) to 1024-dim (bge-m3).

Background: the existing lancedb (mail + all 13 messenger rooms) was stored at 1536 dimensions
(OpenAI text-embedding-3-small/ada-002 family), but the embedding model actually used at query
time is bge-m3 (1024 dimensions), so retrieval doesn't work as-is. Solved without re-indexing, in
3 steps:

1. Extract only the description text from entities.parquet (mail 3,492 + messenger 13 rooms
   1,348 = 4,840 total) and re-embed it in batches of 64 through the real bge-m3 vLLM embedding
   server on the GPU box (localhost:8001).
2. Build a new vector store at output/lancedb_bgem3/ from the 1024-dim results via
   LanceDBVectorStore.create_index() + load_documents() (the existing lancedb is left untouched).
3. Pre-embed the questions through the same server too, so no live API call is needed at
   retrieval time (-> local_build_context.py's StubTextEmbedder consumes these precomputed
   embeddings).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import requests

# graphrag 라이브러리(3.1.1)의 LanceDBVectorStore를 그대로 재사용
from graphrag.vector_stores.lancedb import LanceDBVectorStore
from graphrag.vector_stores.base import VectorStoreDocument

BGE_M3_ENDPOINT = "http://localhost:8001/v1/embeddings"  # vllm-embed 서버 (GPU3)
BGE_M3_MODEL = "BAAI/bge-m3"
BATCH_SIZE = 64


# bge-m3 vLLM 임베딩 서버에 텍스트 배치를 보내 임베딩 벡터를 받아옴
def embed_batch(texts: list[str]) -> list[list[float]]:
    """bge-m3 vLLM OpenAI 호환 임베딩 엔드포인트 호출."""
    resp = requests.post(
        BGE_M3_ENDPOINT,
        json={"model": BGE_M3_MODEL, "input": texts},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    # 응답 순서가 입력 순서와 같다고 보장되므로 index로 정렬해서 반환
    data.sort(key=lambda d: d["index"])
    return [d["embedding"] for d in data]


# 도메인/방별 entities.parquet에서 description을 모아 배치 단위로 재임베딩함
def embed_entities(entities_parquet_paths: dict[str, Path]) -> pd.DataFrame:
    """도메인/방별 entities.parquet에서 description을 뽑아 bge-m3로 재임베딩.

    entities_parquet_paths: {domain_or_room_id: entities.parquet 경로}
    """
    rows = []
    for source, path in entities_parquet_paths.items():
        df = pd.read_parquet(path)
        df = df[df["description"].notna() & (df["description"].str.strip() != "")]
        for _, row in df.iterrows():
            rows.append({
                "id": row["id"],
                "source": source,
                "title": row["title"],
                "description": row["description"],
            })

    print(f"임베딩 대상 엔티티 총 {len(rows)}개 (배치 {BATCH_SIZE}개씩)")

    embeddings: list[list[float]] = []
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        texts = [r["description"] for r in batch]
        embeddings.extend(embed_batch(texts))
        print(f"  {min(i + BATCH_SIZE, len(rows))}/{len(rows)} 완료")

    out_df = pd.DataFrame(rows)
    out_df["embedding"] = embeddings
    return out_df


# 재임베딩된 엔티티로 새 LanceDB 벡터스토어를 생성함
def build_lancedb_index(entities_with_embeddings: pd.DataFrame, out_dir: Path, collection_name: str):
    """graphrag의 LanceDBVectorStore로 새 벡터스토어 생성."""
    store = LanceDBVectorStore(collection_name=collection_name)
    store.connect(db_uri=str(out_dir))
    store.create_index()  # bge-m3 1024차원 스키마로 인덱스 생성

    documents = [
        VectorStoreDocument(
            id=row["id"],
            text=row["description"],
            vector=row["embedding"],
            attributes={"title": row["title"], "source": row["source"]},
        )
        for _, row in entities_with_embeddings.iterrows()
    ]
    store.load_documents(documents)
    print(f"{collection_name}: {len(documents)}개 문서 -> {out_dir}")


# 질문 목록을 미리 bge-m3로 임베딩해서 JSON으로 저장함
def embed_queries(questions_json: Path, out_json: Path):
    """질문 143개를 미리 bge-m3로 임베딩해서 저장 (StubTextEmbedder가 이걸 읽어서 사용)."""
    questions = json.loads(questions_json.read_text(encoding="utf-8"))
    texts = [q["question"] for q in questions]
    embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        embeddings.extend(embed_batch(texts[i:i + BATCH_SIZE]))
    out = {q["question"]: emb for q, emb in zip(questions, embeddings)}
    out_json.write_text(json.dumps(out), encoding="utf-8")
    print(f"질문 {len(out)}개 사전 임베딩 완료 -> {out_json}")


# CLI 인자를 파싱해 엔티티 재임베딩, lancedb 생성, (선택) 질문 사전임베딩을 실행함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mail-entities", type=Path, required=True)
    parser.add_argument("--messenger-entities-dir", type=Path, required=True,
                         help="방별 entities.parquet가 모여있는 디렉터리 (방ID 서브폴더 구조 가정)")
    parser.add_argument("--out-dir", type=Path, default=Path("output/lancedb_bgem3"))
    parser.add_argument("--questions-json", type=Path, default=None,
                         help="질문 사전 임베딩용 (선택)")
    args = parser.parse_args()

    entities_paths = {"mail": args.mail_entities}
    for room_dir in sorted(args.messenger_entities_dir.glob("msg_*")):
        parquet = room_dir / "entities.parquet"
        if parquet.exists():
            entities_paths[room_dir.name] = parquet

    embedded = embed_entities(entities_paths)
    build_lancedb_index(embedded, args.out_dir, collection_name="entity_description_embedding")

    if args.questions_json:
        embed_queries(args.questions_json, args.out_dir / "query_embeddings.json")


if __name__ == "__main__":
    main()
