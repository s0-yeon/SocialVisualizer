# database — MySQL reader / writer

인덱싱 파이프라인의 산출물을 user DB에 저장(writer)하고, 프론트엔드 화면이 쓸 통계를 DB에서 조회(reader)하는 함수 모음이다.
메일 계정용과 메신저 대화방용이 짝을 이룬다.
DB 접속은 [`src/config/db.py`](../../config/db.py)의 `get_db_connection()`을 통한다.

## 구성

| 파일 | 역할 |
|------|------|
| `db_reader.py` | 메일 계정의 통계·친밀도(EIS)·키워드·연락처 관계 조회 |
| `db_writer.py` | 메일 인덱싱 결과 저장 — 계정·연락처·메일·키워드·요약·폴더·비용 통계 |
| `chatroom_reader.py` | 대화방 목록·참여자·관계·키워드·분위기·메시지·요약 조회 |
| `chatroom_db_writer.py` | 대화방 인덱싱 결과 저장 — 참여자·대화 블록·관계·키워드·요약·분위기 |

## 주의

- `db_writer.collect_indexing_stats`는 GraphRAG 캐시 폴더 구조(`community_reporting`, `extract_graph` 등)를 하드코딩한 **GraphRAG 전용** 함수다. 다른 엔진에서 인덱싱 비용을 집계하려면 엔진별 버전을 따로 만들어야 한다.
- `save_query_to_db`, `save_mail_summarize_to_db` 등 순수 저장 함수는 엔진과 무관하게 재사용 가능하다.

## 관련

- 상위: [`src/util/`](../README.md)
- 스키마: [`db/schema.sql`](../../../db/schema.sql)
- 호출부: [`src/util/jobs/`](../jobs/README.md)

---

# database — MySQL reader / writer

Functions that persist indexing-pipeline output into the user DB (writer) and read back the statistics the frontend needs (reader).
Mail-account and messenger-chatroom variants are paired.
All DB access goes through `get_db_connection()` in [`src/config/db.py`](../../config/db.py).

## Layout

| File | Role |
|------|------|
| `db_reader.py` | Reads mail-account stats, affinity (EIS), keywords, contact relationships |
| `db_writer.py` | Persists mail indexing results — accounts, contacts, mail, keywords, summaries, folders, cost stats |
| `chatroom_reader.py` | Reads chatroom lists, participants, relationships, keywords, mood, messages, summaries |
| `chatroom_db_writer.py` | Persists chatroom indexing results — participants, message blocks, relationships, keywords, summaries, mood |

## Notes

- `db_writer.collect_indexing_stats` hardcodes GraphRAG cache folder names (`community_reporting`, `extract_graph`, …) and is **GraphRAG-only**. Other engines need their own version to aggregate indexing cost.
- Plain persistence functions such as `save_query_to_db` and `save_mail_summarize_to_db` are engine-agnostic and reusable as-is.

## Related

- Parent: [`src/util/`](../README.md)
- Schema: [`db/schema.sql`](../../../db/schema.sql)
- Callers: [`src/util/jobs/`](../jobs/README.md)
