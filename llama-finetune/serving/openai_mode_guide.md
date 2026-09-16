# OpenAI 모드로 실행하기 (`refactor_224` 브랜치)

이 브랜치는 로컬 라마 서버 없이 OpenAI API만으로 인덱싱·질의응답이 동작하도록
설정된 버전이다. GPU 서버 연결이 필요 없다. 브랜치를 받은 뒤 아래 순서대로 진행한다.

## 1. `.env` 설정

`.env`는 `.gitignore`에 포함돼 있어 git으로 안 넘어온다 — 직접 만들어야 한다.

```bash
cp src/parquet/.env.example src/parquet/.env
```

그리고 다음 값들을 채운다(`LLM_API_KEY`는 실제 OpenAI API 키로):

```env
LLM_API_KEY = <OpenAI API 키>
LOCAL_API_KEY = <LLM_API_KEY와 동일한 값으로 둬도 무방>
MODEL_PROVIDER = openai

RAG_CHAT_MODEL = gpt-5.4-mini
RAG_CHAT_API_BASE =
# 비워두면 실제 OpenAI 엔드포인트로 요청이 감 (질의응답: local_search/global_search)

INDEXING_CHAT_MODEL = gpt-5.4-mini
INDEXING_API_BASE = https://api.openai.com/v1

INDEXING_EMBEDDING_MODEL = text-embedding-3-small
INDEXING_EMBEDDING_API_BASE = https://api.openai.com/v1

INDEXING_COMPLETION_MODEL_ID = default_chat_model
INDEXING_REPORTS_MODEL_ID = default_chat_model
INDEXING_EMBEDDING_MODEL_ID = indexing_embedding_model

SUB_TASK_CHAT_MODEL = gpt-5.4-mini
# SUB_TASK_API_BASE는 주석 처리된 채로 둔다 (비워두면 실제 OpenAI로 감)

IMAGE_API_BASE = http://localhost:8005
# 아바타 이미지 생성만 예외로 로컬 FLUX 서버 유지 — 별도로 flux_server.py를 띄워야 함
```

## 2. 이미 인덱싱된 계정이 있다면 — 임베딩 재생성

기존에 로컬(bge-m3, 1024차원)로 인덱싱해둔 계정이 있으면, OpenAI 임베딩(1536차원)과
차원이 안 맞아 검색이 `vector dim mismatch` 에러로 깨진다. 아래 스크립트로 이미
추출된 엔티티 설명은 그대로 두고 벡터만 다시 계산한다(`extract_graph`/
`community_reports` 같은 무거운 재추출은 하지 않음):

```bash
python llama-finetune/serving/reembed_entities.py
```

전부 다시 인덱싱된 계정만 있다면(로컬로 인덱싱한 적이 아예 없다면) 이 단계는
건너뛰어도 된다.

## 3. 구조화 답변 형식 프롬프트 반영

답변 형식(번호 매김 + 제목/날짜/계정/내용 필드) 관련 프롬프트 룰이 바뀐 상태라,
이미 인덱싱된 계정에도 최신 프롬프트를 반영해야 한다(재인덱싱 불필요):

```bash
python llama-finetune/serving/refresh_prompts.py
```

## 4. Flask 서버 재시작

엔진이 프로세스 내에 캐싱되므로, 2·3번에서 파일만 바꾸고 서버를 안 껐다 켜면
예전 캐시가 그대로 남아 변경이 반영되지 않는다.

## 5. 확인

아무 계정으로 자연어 검색을 한 번 날려서, 에러 없이 응답이 오고 답변이 번호+필드
형식으로 나오는지 확인한다.
