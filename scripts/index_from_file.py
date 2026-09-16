# scripts/index_from_file.py

# 로컬 메일/대화 블록 텍스트 파일 하나를 곧바로 인덱싱시키는 CLI 스크립트. IMAP 수집이나
# 수동 curl/PowerShell 호출 없이, app.py의 /upload 로직을 Flask 테스트 클라이언트로 인프로세스
# 호출해 실제 서버(python src/app.py)를 따로 띄우지 않고도 동일한 코드 경로로 인덱싱을 시작한다.
# 시작 후에는 /job-status를 폴링해 인덱싱이 끝날 때까지 기다렸다가 결과를 출력한다.

# CLI script that indexes a local mail/chat block text file directly. Instead of collecting
# via IMAP or manually calling curl/PowerShell, it invokes app.py's /upload logic in-process
# through Flask's test client, so the same code path runs without starting a separate server
# (python src/app.py). After kicking off the job, it polls /job-status until indexing finishes
# and prints the result.

import os
import sys
import json
import time
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

# app.run()은 `if __name__ == "__main__"` 안에 있어서 import만 해서는 서버가 뜨지 않는다
import app as flask_app


def main():
    parser = argparse.ArgumentParser(description="파일 경로에서 바로 인덱싱 (서버를 따로 안 띄우고 /upload 로직 재사용)")
    parser.add_argument("file_path", help="메일/대화 블록 텍스트 파일 경로")
    parser.add_argument("user_id", help="계정 이메일(mail) 또는 채팅방 식별자(messenger)")
    parser.add_argument("--domain", default="mail", choices=["mail", "messenger"])
    parser.add_argument("--platform", default="gmail", help="mail_platform 값 (메신저는 보통 kakao)")
    parser.add_argument("--syncmode", default="rewrite", choices=["rewrite", "append"])
    args = parser.parse_args()

    with open(args.file_path, "r", encoding="utf-8") as f:
        content = f.read()

    payload = {
        "filename": os.path.basename(args.file_path),
        "user_id": args.user_id,
        "domain": args.domain,
        "mail_platform": args.platform,
        "syncmode": args.syncmode,
        "content": content,
        "is_last": True,
    }

    client = flask_app.app.test_client()

    resp = client.post("/upload", data=json.dumps(payload), content_type="application/json")
    body = resp.get_json()
    print(f"[UPLOAD] status={resp.status_code} body={body}")

    if resp.status_code != 200 or not body or not body.get("ok"):
        print("[FAIL] 업로드 단계에서 실패, 인덱싱 시작 안 됨")
        return

    job_id = body["job_id"]
    print(f"[WAIT] job_id={job_id} 인덱싱 진행 상황 폴링 시작")

    while True:
        status_resp = client.get(f"/job-status/{job_id}")
        status = status_resp.get_json() or {}
        print(f"[JOB] status={status.get('status')} progress={status.get('progress')} message={status.get('message')}")

        if status.get("status") in ("done", "failed"):
            break
        time.sleep(3)


if __name__ == "__main__":
    main()
