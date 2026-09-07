# 설치 및 실행 가이드

## To-do list
- [ ] Python 3.11 · Node.js 20.19+ · MySQL 설치
- [ ] 저장소 fork 후 clone
- [ ] 가상환경 생성 및 활성화
- [ ] 의존성 설치 
- [ ] MySQL 서버 실행 + `db/schema.sql` 실행 
- [ ] `.env` 생성 후 DB 접속 정보 입력
- [ ] 프론트엔드 빌드
- [ ] 저장소 루트에서 서버 실행 
- [ ] `http://localhost/dashboard/` 접속 확인

---

> 본 문서에 기재된 모든 명령어는 **Windows + Git Bash** 기준입니다.
> macOS / Linux · PowerShell 은 명령이 갈라지는 지점에만 별도 표기했으니 참고 바랍니다.
> 경로 구분자는 `/` 로 통일했으며 Windows의 모든 셸에서 그대로 동작합니다.

---

## 1. 사전 준비

- **Python 3.11**
- **Node.js 20.19 이상** (또는 22.12 이상)
- **MySQL** (8.0 권장)

---

## 2. 프로젝트 설치

1. 레포지토리 fork 후 clone. 이후 모든 명령은 **클론한 저장소 루트 디렉터리**에서 실행한다.
2. 가상환경 생성 및 활성화

```bash
python -m venv socialvisualizer-venv
source socialvisualizer-venv/Scripts/activate
```
```bash
# macOS / Linux
source socialvisualizer-venv/bin/activate

# PowerShell
socialvisualizer-venv\Scripts\Activate.ps1
```

3. 의존성 설치

가상환경을 활성화한 상태로 저장소 루트에서 실행한다. 패키지가 170여 개(azure-* 등 포함)라 설치에 수 분 정도 걸린다.

```bash
pip install -r requirements.txt
```

---

## 3. MySQL DB 준비

1. MySQL 서버 실행
Windows는 설치 시 서비스로 자동 실행된다. 수동이면 `services.msc` 에서 MySQL 서비스를 시작한다.

2. db/schema.sql 파일 실행
프로젝트 루트에서 실행한다. 데이터베이스(`social_visualizer_db`)와 테이블이 함께 생성된다.

```bash
mysql -u root -p < db/schema.sql

# PowerShell
Get-Content db/schema.sql | mysql -u root -p
```

- `mysql` 명령이 인식되지 않으면 MySQL `bin` 폴더(예: `C:/Program Files/MySQL/MySQL Server 8.0/bin`)를
  시스템 환경변수 `Path` 에 추가하거나, `mysql` 대신 `mysql.exe` 전체 경로를 쓴다.
- 재실행해도 기존 데이터는 보존된다(`IF NOT EXISTS`). 완전 초기화가 필요하면 파일 상단 주석을 참고한다.
- 이때 생성되는 DB 이름은 `.env` 의 `DB_NAME` 과 일치해야 한다.

---

## 4. 환경변수 설정

1. .env 파일 작성
예시 파일을 복사한다. 원본과 대상 모두 `src/parquet/` 에 있다.

```bash
cp src/parquet/.env.example src/parquet/.env

# PowerShell
copy src\parquet\.env.example src\parquet\.env
```

2. DB 접속 및 정보 수정
`.env` 상단 `# Database` 블록을 자신의 MySQL 환경에 맞게 채운다.

```ini
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=본인이_설정한_MySQL_비밀번호
DB_NAME=social_visualizer_db   # db/schema.sql 이 생성하는 이름과 일치해야 함
```

3. AI 서버 선택

- <b>오픈 AI 사용</b>
각 모델 서버(Llama/Qwen/BGE-M3/FLUX)를 직접 설치·실행하는 방법은
[`llama-finetune/serving/gpu_server_ops.md`](../llama-finetune/serving/gpu_server_ops.md)를 참고한다.
이때 표준 로컬 구성(포트 8001~8005)을 그대로 쓴다면 수정하지 않아도 되며, `LLM_API_KEY` 는 값 검증을 하지 않지만 줄 자체를 지우면 KeyError가 발생하므로 `dummy` 로 둔다.<br><br>

- <b>상용 API 사용</b>
OpenAI 등 상용 API로 대체하려면 `.env` 의 `# 질의응답` 블록에서 각 모델명을 원하는 모델로 바꾸고 `LLM_API_KEY` 에 발급받은 실제 키를 넣는다. 이 경우 로컬 AI 서버는 띄우지 않아도 된다.

---

## 5. 프론트엔드 빌드

```bash
cd src/web
npm install
npm run build
cd ../..
```

빌드 결과물(`src/web/dist/`)은 백엔드 서버가 직접 서빙한다. 화면을 수정한 뒤에는 다시 빌드해야 반영된다.

---

## 6. 서버 실행

**반드시 저장소 루트 디렉터리에서 실행한다.**
(`src/parquet/.env` 를 상대경로로 읽기 때문에 다른 위치에서 실행하면 DB 접속 정보를 불러오지 못하고 종료된다.)

```bash
python src/app.py
```

---

## 7. 실행 확인

서버가 정상 기동되면 콘솔에 다음과 비슷한 출력이 나타난다.

```text
$ python src/app.py 
============================================================
[RAG_ENGINE] 서버가 사용할 RAG 엔진: GRAPHRAG
============================================================
[DB] processed_attachments 테이블 준비 완료
[DB] mail_keyword 테이블 준비 완료
[DB] chatroom 관련 테이블 준비 완료
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:80
 * Running on http://10.30.0.98:80
Press CTRL+C to quit

```

브라우저에서 접속한다.

- **최초 실행:** `http://localhost/init` — 서버 주소를 브라우저에 저장한 뒤 자동으로 대시보드로 이동한다.
- **이후:** `http://localhost/dashboard/`

홈 화면이 보이면 설치가 정상적으로 완료된 것이다.