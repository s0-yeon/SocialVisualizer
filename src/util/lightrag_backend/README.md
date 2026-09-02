# LightRAG 사용 가이드

본 문서는 SocialVisualizer의 지식 그래프 생성 기법을 **기본 GraphRAG에서 LightRAG로 전환·설정**하고, 나아가 같은 패턴으로 **제3의 RAG 엔진**을 붙이거나 **LightRAG 자체 웹 UI**를 별도로 띄우는 방법을 안내하는 **개발자용 가이드**이다.

---

## 🔌 LightRAG 기능 켜기

SocialVisualizer는 기본적으로 GraphRAG로 동작한다. 인덱싱/질의 엔진을 LightRAG로 바꾸고 싶을 때만 아래를 추가로 진행하면 된다. 진행하지 않으면 GraphRAG 그대로 동작하니 건너뛰어도 무방하다.

### 1. LightRAG 클론

LightRAG는 pip 패키지로 설치하지 않고 소스를 그대로 클론해서 라이브러리처럼 가져다 쓴다.

백엔드 코드 중 lightrag의 이름이 포함된 파일을 직접 참조하므로, **반드시 프로젝트 루트(`SocialVisualizer/`)
바로 밑에 클론해야 한다.**

위 2번에서 만든 `socialvisualizer-venv`에 이미 필요한 패키지가 설치되어
있으므로 별도 가상환경이나 추가 설치는 필요 없다.

```bash
git clone https://github.com/HKUDS/LightRAG.git
```

### 2. LightRAG 엔진 전환

`src/config/settings.py`의 `RAG_ENGINE` 값을 바꾼다.

```python
RAG_ENGINE = "lightrag"   # 기본값은 "graphrag"
```

---

## ⚙️ RAG 사용자 편의/프롬프트 설정

### 1. 사용자 편의 설정 (인덱싱/질의/통계 추출)

- `src/util/graphrag_*.py` — GraphRAG 엔진 전용 로직
- `src/util/jobs/job_run_graphrag.py` — GraphRAG 인덱싱 파이프라인
- `src/graphrag_parquet2json.py` — GraphRAG 그래프 시각화용 JSON 변환기
- `src/util/lightrag_backend/*.py` — LightRAG 엔진 전용 로직
- `src/util/jobs/job_run_lightrag.py` — LightRAG 인덱싱 파이프라인
- `src/util/extract_statics.py` — 통계 추출 (GraphRAG/LightRAG 공용)

### 2. 프롬프트 설정

프롬프트를 수정하거나 설계해서 사용하고 싶다면 다음과 같은 프롬프트 내용을 참고해라.
LightRAG는 라이브러리 내 기본 프롬프트를 사용하고 있으니, 프롬프트를 수정하여 사용하는 것을 권장한다.

#### 2-1. LightRAG 프롬프트

현재 LightRAG 모듈은 LightRAG 라이브러리 내부 로직(엔티티 추출, 그래프 검색 응답, 키워드 추출 등)이 잘 다듬어진 프롬프트를 그대로 사용하고 있다. 이 프롬프트를 수정해서 사용할 수 있다.

`LightRAG/lightrag/prompt.py`의 `PROMPTS` 딕셔너리
(`entity_extraction_system_prompt`, `rag_response`, `naive_rag_response`, `keywords_extraction` 등)을 참고해라.

#### 2-2. GraphRAG 프롬프트

GraphRAG는 인덱싱과 질의(LocalSearch/GlobalSearch) 프롬프트를 프로젝트 안 템플릿 파일로 관리한다.

`parquet_template/src/prompts/*.j2` 원본 템플릿이 도메인별로 렌더링되어
`parquet_template/rendered/{domain}/prompts/*.txt` 파일로 만들어지고, 인덱싱/질의 코드는
이 렌더링된 `.txt` 파일을 읽어서 그대로 프롬프트로 쓴다.

#### 2-3. 공통 프롬프트

- 연합 검색 답변 프롬프트 — `lightrag_query.py`의 `system_prompt` 변수
- 질의 모드 분류 프롬프트 — `lightrag_query.py`의 `prompt` 변수 (`_classify_query_method` 함수 참고)
- 메일 요약 프롬프트 — `lightrag_mail_summary.py`의 `system 메시지`
- 날짜 범위 질의 답변 프롬프트 — `lightrag_date_query.py`의 `run_date_range_query()` 안 `messages=[...]`의 `system 메시지`

---

## 🧩 다른 RAG 엔진을 붙이고 싶을 때

GraphRAG/LightRAG 두 엔진이 비슷한 패턴으로 설계되어 있으니, 세 번째 엔진(예: 다른 RAG 프레임워크)도 같은 패턴을 따라가면 된다.
아래 순서를 참고해라.

### 1. 엔진 이름 등록

`src/config/settings.py`의 `SUPPORTED_RAG_ENGINES`에 새 엔진 이름을 추가한다(안 하면 앱 시작 시
ValueError로 막힌다).

### 2. 전용 패키지 만들기

`src/util/lightrag_backend/`를 따라 `src/util/<엔진명>_backend/`
패키지를 새로 만들고, 그 안에 `<엔진명>_` 접두사가 붙은 파일들을 채운다. LightRAG나 GraphRAG 엔진 코드를 참고하여 함수 이름을 동일하게 작성하면 `RAG_ENGINE` 값에 따라 import 경로만 바꿔서 그대로 재사용할 수 있다.

- `<엔진명>_engine.py` — 인스턴스/엔진 빌드 및 캐싱
- `<엔진명>_query.py` — 단일/연합(다중) 데이터 소스 질의 + 다중 검색 모드 지원
- `<엔진명>_mail_summary.py` — 월별/연별 메일 요약
- `<엔진명>_date_query.py` — 날짜(시간) 관련 질의
- `<엔진명>_graph_json.py` — 그래프 시각화용 JSON 변환기
- `<엔진명>_extract_statics.py` — 키워드/연락처 통계 추출
- `<엔진명>_db_writer.py` — DB 저장 로직
- `<엔진명>_mail_parser.py` — 위 통계/요약/DB 저장 코드들이 공통으로 쓰는 파싱 헬퍼
- `<엔진명>_progress.py` — 인덱싱 진행률 표시
- `<엔진명>_loop.py` — 동기 코드에서 async 질의를 실행하는 공용 백그라운드 이벤트 루프

### 3. 인덱싱 job 작성

`src/util/jobs/job_run_<엔진명>.py`를 만들고 `job_run_lightrag.py`/`job_run_graphrag.py`와 같은
함수 시그니처를 맞춘다:

- `start_graph_pipeline_background`
- `start_graph_update_pipeline_background`
- `build_*_update`
- `build_graph_json`
  함수 이름을 동일하게 작성하면 app.py는 `RAG_ENGINE` 값에 따라 import 경로만 바꿔서 그대로 재사용할 수 있다.

### 4. 경로 세그먼트 추가

`src/util/user_path.py`에 새로운 엔진 전용 작업 디렉터리 경로를 추가한다

- `GRAPHRAG_ROOT`/ `LIGHTRAG_ROOT`처럼 `<엔진명>_ROOT`
- `GRAPH_JSON_PATH`/ `LIGHTRAG_GRAPH_JSON_PATH`처럼 `<엔진명>_GRAPH_JSON_PATH`
  `_account_indexed()` 함수에도 `elif RAG_ENGINE == "<엔진명>":` 분기를 추가한다 (안 하면
  새 엔진으로 인덱싱해도 계정 목록에 "인덱싱 안 됨"으로 표시됨).

### 5. `app.py`에 분기 추가

`RAG_ENGINE`으로 그래프/라이트래그를 나누는 지점마다 새 엔진 분기(`elif`)를 추가해야 한다. 현재 분기 지점은 다음과 같다:

- 모듈 상단 — 인덱싱 시작 함수(`start_graph_pipeline_background` 등) import 스위치
- 날짜 범위 질의 함수(`run_date_range_query`) import 스위치
- `_index_ready` 헬퍼 — 인덱스 생성 여부 확인
- `/run-query-async`, `/run-query` 라우트 — 실제 질의 실행부
- `/upload` 라우트 — 인덱스 준비 마커 파일 삭제, 인덱싱 파이프라인 트리거
- `/graph-data` 라우트 — 그래프 JSON 경로 선택
- `/upload-attachments` 라우트, `util/attachment_manager.py` — 첨부파일 반영 업데이트 함수 선택

### 6. DB 저장은 대부분 그대로 재사용 가능

`src/util/database/db_writer.py`의 `save_query_to_db`, `save_mail_summarize_to_db` 등은 엔진에
상관없이 그냥 행을 저장하는 함수라 새 엔진에서도 그대로 가져다 쓰면 된다. 예외는
`collect_indexing_stats`인데, 이건 GraphRAG의 캐시 폴더 구조(`community_reporting`,
`extract_graph` 등)를 하드코딩하고 있어서 GraphRAG 전용이다 — 새 엔진에서 인덱싱 비용/통계를
집계하고 싶다면 이 함수의 엔진별 버전을 따로 만들어야 한다.

### 7. 프롬프트

위 섹션 중 `RAG 사용자 편의/프롬프트 설정`의 2번 `프롬프트 설정`을 참고해라.

---

## 🖥️ LightRAG 자체 웹 UI 따로 띄우기 (선택)

### 1. uv 설치

Windows에는 `make` 명령어가 기본으로 없어서, LightRAG 공식 가이드의 `make dev` 대신
`uv`(파이썬 의존성 관리 도구)를 직접 설치해서 사용.

PowerShell에서 실행, 설치 후 Git Bash 재시작

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

- 설치 위치: `C:\Users\2471369\.local\bin`

Git Bash에서 `uv: command not found`가 뜨면(PowerShell/cmd용 PATH 등록이 Git Bash(MINGW64)에는
적용되지 않아서 생기는 문제) 아래로 PATH를 등록한다.

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

영구 등록 (한 번만 실행):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

### 2. 전용 가상환경(`lightrag-venv`) 생성 + 의존성 설치

`socialvisualizer-venv`와 별도로 `lightrag-venv`를 하나 더 만든다(uv가 자체적으로 관리하는 전용 가상환경).

`LightRAG` 폴더 안에서 실행.

```bash
cd LightRAG
export UV_PROJECT_ENVIRONMENT=lightrag-venv
uv venv lightrag-venv
uv sync --extra test --extra offline
```

영구 등록 (한 번만 실행):

```bash
echo 'export UV_PROJECT_ENVIRONMENT=lightrag-venv' >> ~/.bashrc
```

### 3. 가상환경 활성화

```bash
source lightrag-venv/Scripts/activate
```

### 4. 웹 UI 빌드

PowerShell에서 실행, 설치 후 Git Bash 재시작

```powershell
powershell -c "irm bun.sh/install.ps1|iex"
```

```bash
cd lightrag_webui
bun install --frozen-lockfile
bun run build
cd ..
```

### 5. 설정 파일(.env) 생성

```bash
cp env.example .env
```

### 6. 서버 실행

```bash
lightrag-server
```

브라우저에서 `http://localhost:9621` 접속 → 확인