# jobs — 백그라운드 job 저장소 + 인덱싱 파이프라인

업로드·인덱싱·업데이트처럼 오래 걸리는 작업을 백그라운드 스레드로 돌리고, 그 진행 상태를 메모리에 보관하는 계층이다.
`app.py`는 `RAG_ENGINE` 값에 따라 `job_run_graphrag` / `job_run_lightrag` 중 하나를 import 해서 같은 함수 이름으로 호출한다.

## 구성

| 파일 | 역할 |
|------|------|
| `job_store.py` | 메모리 기반 job 딕셔너리 (`create_job` / `update_job` / `append_job_log`). 서버 재시작 시 소멸 — 영속성 없음 |
| `job_run_graphrag.py` | GraphRAG 인덱싱/업데이트 파이프라인. GraphRAG CLI subprocess 실행, parquet 진행률 감시, 통계·요약·DB 저장까지 |
| `job_run_lightrag.py` | 위 파일의 복사본을 LightRAG 라이브러리 직접 호출로 교체한 버전 |

## 엔진 간 계약

두 `job_run_*.py`는 **함수 시그니처를 동일하게** 맞춰 `app.py`가 import 경로만 바꿔 재사용할 수 있게 한다:

- `start_graph_pipeline_background`
- `start_graph_update_pipeline_background`
- `build_*_update`
- `build_graph_json`

> `job_run_lightrag.build_graph_json`은 미완성이다 — 시각화용 JSON 변환기가 GraphRAG의 `entities.parquet` / `relationships.parquet` 스키마를 전제하므로 LightRAG 결과에는 그대로 못 쓰고, 현재는 스킵한다.

## 관련

- 상위: [`src/util/`](../README.md)
- 새 엔진용 job 작성법: [`../lightrag_backend/README.md`](../lightrag_backend/README.md) 「다른 RAG 엔진을 붙이고 싶을 때」 > 「인덱싱 job 작성」
- 저장 대상: [`../database/`](../database/README.md)

---

# jobs — background job store + indexing pipelines

This layer runs long tasks (upload, indexing, update) on background threads and keeps their progress in memory.
Based on `RAG_ENGINE`, `app.py` imports either `job_run_graphrag` or `job_run_lightrag` and calls them by the same function names.

## Layout

| File | Role |
|------|------|
| `job_store.py` | In-memory job dict (`create_job` / `update_job` / `append_job_log`). Lost on server restart — no persistence |
| `job_run_graphrag.py` | GraphRAG indexing/update pipeline — runs the GraphRAG CLI subprocess, watches parquet progress, does stats/summary/DB writes |
| `job_run_lightrag.py` | A copy of the above with the engine swapped to direct LightRAG library calls |

## Cross-engine contract

Both `job_run_*.py` files keep **identical function signatures** so `app.py` only has to swap the import path:

- `start_graph_pipeline_background`
- `start_graph_update_pipeline_background`
- `build_*_update`
- `build_graph_json`

> `job_run_lightrag.build_graph_json` is unfinished — the visualization JSON converter assumes GraphRAG's `entities.parquet` / `relationships.parquet` schema, so it does not work on LightRAG output and is currently skipped.

## Related

- Parent: [`src/util/`](../README.md)
- Writing a job for a new engine: [`../lightrag_backend/README.md`](../lightrag_backend/README.md) → "다른 RAG 엔진을 붙이고 싶을 때" → "인덱싱 job 작성"
- Write targets: [`../database/`](../database/README.md)
