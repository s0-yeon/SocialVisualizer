# user_data — 계정 · 대화방별 데이터 (git 미추적)

각 메일 계정과 카카오톡 단톡방의 수집 원본, 인덱싱 산출물, 캐시가 쌓이는 곳이다.
**개인정보라 git에 커밋하지 않는다** — [`.gitignore`](../.gitignore)에서 `.gitkeep`만 남기고 전부 무시한다.
이 README는 폴더 구조만 설명하며, 실제 내용물은 앱 실행 시 생성된다.

## 구조

```
user_data/
└─ <domain>/                     mail | messenger
   └─ <계정·단톡방 dir_name>/
      ├─ graphrag/               RAG_ENGINE="graphrag"일 때의 데이터. 하위 `parquet/`가 GraphRAG CLI 작업 디렉터리(input·output·settings.yaml)
      └─ lightrag/               RAG_ENGINE="lightrag"일 때의 데이터 (input·output·logs·statics)
```

- 도메인(메일/메신저)으로 먼저 나누고, 그 아래 계정·방별로 나눈다.
- 엔진별 저장 위치를 완전히 분리한다 (`graphrag/`, `lightrag/` 세그먼트).
- 경로 규칙과 계정 목록 스캔은 [`src/util/user_path.py`](../src/util/user_path.py)의 `UserPaths` · `list_accounts()`가 담당한다.

## 관련

- 경로 규칙: [`src/util/user_path.py`](../src/util/user_path.py)
- 무시 규칙: [`.gitignore`](../.gitignore) (`user_data/*`, `!user_data/.gitkeep`)
- 공용 `.env`(LLM API 키 등)가 있는 곳: [`src/parquet/`](../src/parquet) (`.env`는 git 미추적)

---

# user_data — per-account / per-chatroom data (not tracked by git)

Holds the collected sources, indexing output, and caches for each mail account and KakaoTalk group chat.
**It contains personal data and is never committed** — [`.gitignore`](../.gitignore) ignores everything except `.gitkeep`.
This README only describes the folder layout; the actual contents are created when the app runs.

## Layout

```
user_data/
└─ <domain>/                     mail | messenger
   └─ <account or chatroom dir_name>/
      ├─ graphrag/               data when RAG_ENGINE="graphrag"; its `parquet/` subdir is the GraphRAG CLI working dir (input·output·settings.yaml)
      └─ lightrag/               data when RAG_ENGINE="lightrag" (input·output·logs·statics)
```

- Split first by domain (mail / messenger), then by account / room.
- Per-engine storage is fully separated (`graphrag/`, `lightrag/` segments).
- Path rules and account scanning live in `UserPaths` / `list_accounts()` in [`src/util/user_path.py`](../src/util/user_path.py).

## Related

- Path rules: [`src/util/user_path.py`](../src/util/user_path.py)
- Ignore rules: [`.gitignore`](../.gitignore) (`user_data/*`, `!user_data/.gitkeep`)
- Location of the shared `.env` (LLM API keys, etc.): [`src/parquet/`](../src/parquet) (`.env` is untracked)