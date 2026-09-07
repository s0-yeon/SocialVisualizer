# util — 수집 · 파싱 · 인덱싱 · 통계 · 질의 유틸

`app.py`가 호출하는 백엔드 로직이 모여 있는 계층이다. 메일/메신저 데이터를 IMAP·파일로 받아 파싱하고, RAG 엔진(GraphRAG / LightRAG)으로 인덱싱·질의하며, 통계를 뽑아 DB에 저장하는 과정을 담당한다. 하위 3개 패키지는 각자 README를 가진다.

## 구성

### 하위 패키지

| 폴더 | 역할 |
|------|------|
| [`database/`](database/README.md) | MySQL 읽기/쓰기 — 계정·대화방·메일·통계 |
| [`jobs/`](jobs/README.md) | 백그라운드 job 저장소 + 인덱싱 파이프라인 |
| [`lightrag_backend/`](lightrag_backend/README.md) | LightRAG 엔진 전용 백엔드 (`RAG_ENGINE="lightrag"`일 때) |

### 수집 · 파싱

| 파일 | 역할 |
|------|------|
| `imap_connect.py` | IMAP 로그인, 폴더 선택, 메일 fetch, 폴더명 인코딩 처리 |
| `imap_message.py` | 메일 메시지(헤더·본문·첨부)를 인덱싱용 텍스트 블록으로 파싱 |
| `mail_data_manager.py` | 메일 블록 병합·분할·재정렬, `mail_latest.txt` → CSV 변환 |
| `message_parser.py` | 카카오톡 대화 내보내기 텍스트 파싱 → 메시지·방 ID |
| `attachment_manager.py` | 첨부파일(PDF·DOCX·HWP·PPTX·XLSX·CSV) 텍스트 추출 |

### 통계 추출

| 파일 | 역할 |
|------|------|
| `extract_statics.py` | 메일 본문에서 LLM으로 키워드·어조·관계 프로필 추출 (GraphRAG/LightRAG 공용) |
| `message_statics.py` | 대화 블록 기반 참여자별 이력·프로필·키워드 통계 |
| `message_mood.py` / `message_summary.py` | 대화방 분위기 판별 / 월·연 단위 요약 |

### GraphRAG 엔진

| 파일 | 역할 |
|------|------|
| `graphrag.py` | GraphRAG CLI 질의 실행, 응답 정제, 질의 로그 DB 저장, 인덱싱 완료 확인 |
| `graphrag_engine.py` | LocalSearch/GlobalSearch 엔진을 유저별 메모리 캐싱 |
| `graphrag_query.py` / `graphrag_date_query.py` | 단일·연합 질의 / 날짜 범위 질의 |
| `graphrag_mail_summary.py` | 월별·연별 메일 요약 |
| `graphrag_progress.py` | 인덱싱 단계별 진행률 계산 |

### 공통 인프라

| 파일 | 역할 |
|------|------|
| `user_path.py` | 계정·엔진별 작업 디렉터리 경로 규칙, 인덱싱 여부 판정 |
| `file_manager.py` | 파일명 정규화, 오래된 업데이트 산출물 정리 |
| `sse_broadcaster.py` | 진행 상황 SSE 브로드캐스트 |
| `avatar_generator.py` | 인물 아바타 이미지 생성 |

## 관련

- 상위: [`src/`](..)
- 엔진 전환: [`src/config/settings.py`](../config/settings.py)의 `RAG_ENGINE`
- 새 RAG 엔진 추가 방법: [`lightrag_backend/README.md`](lightrag_backend/README.md)

---

# util — collection · parsing · indexing · statistics · query utilities

This layer holds the backend logic called by `app.py`.
It ingests mail/messenger data over IMAP or from files, parses it, indexes and queries it with a RAG engine (GraphRAG / LightRAG), and extracts statistics to store in the database.
The three sub-packages each have their own README.

## Layout

### Sub-packages

| Dir | Role |
|-----|------|
| [`database/`](database/README.md) | MySQL reads/writes — accounts, chatrooms, mail, stats |
| [`jobs/`](jobs/README.md) | Background job store + indexing pipelines |
| [`lightrag_backend/`](lightrag_backend/README.md) | LightRAG-only backend (when `RAG_ENGINE="lightrag"`) |

### Collection · parsing

| File | Role |
|------|------|
| `imap_connect.py` | IMAP login, folder select, mail fetch, folder-name encoding |
| `imap_message.py` | Parse a mail message (headers, body, attachments) into an indexing text block |
| `mail_data_manager.py` | Merge/split/renumber mail blocks, `mail_latest.txt` → CSV |
| `message_parser.py` | Parse KakaoTalk chat exports → messages, room IDs |
| `attachment_manager.py` | Extract text from attachments (PDF/DOCX/HWP/PPTX/XLSX/CSV) |

### Statistics extraction

| File | Role |
|------|------|
| `extract_statics.py` | LLM extraction of keywords/tone/relationship profiles from mail (shared by both engines) |
| `message_statics.py` | Per-participant history, profile, keyword stats from chat blocks |
| `message_mood.py` / `message_summary.py` | Chatroom mood classification / monthly-yearly summaries |

### GraphRAG engine

| File | Role |
|------|------|
| `graphrag.py` | Run GraphRAG CLI queries, clean responses, log queries to DB, check indexing completion |
| `graphrag_engine.py` | Per-user in-memory cache of LocalSearch/GlobalSearch engines |
| `graphrag_query.py` / `graphrag_date_query.py` | Single/federated query / date-range query |
| `graphrag_mail_summary.py` | Monthly and yearly mail summaries |
| `graphrag_progress.py` | Per-stage indexing progress |

### Shared infrastructure

| File | Role |
|------|------|
| `user_path.py` | Per-account / per-engine working-directory paths, indexed-state checks |
| `file_manager.py` | Filename sanitizing, cleanup of stale update artifacts |
| `sse_broadcaster.py` | SSE broadcast of progress events |
| `avatar_generator.py` | Person avatar image generation |

## Related

- Parent: [`src/`](..)
- Engine switch: `RAG_ENGINE` in [`src/config/settings.py`](../config/settings.py)
- How to add a new RAG engine: [`lightrag_backend/README.md`](lightrag_backend/README.md)
