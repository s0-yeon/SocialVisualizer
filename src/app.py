# MailGrapher 백엔드 Flask 서버. 채팅/질의 잡, 메일·카카오톡 업로드와 인덱싱 파이프라인 실행, SSE 진행 스트림, 통계·관계·요약·아바타 조회 등 프론트엔드가 쓰는 모든 REST 엔드포인트를 제공한다.

# MailGrapher backend Flask server: exposes every REST endpoint the frontend uses — chat/query jobs, mail/KakaoTalk upload and indexing-pipeline runs, the SSE progress stream, and stats/relationship/summary/avatar lookups.

import datetime
import os
import re
import subprocess
import time
import sys
import json
import threading
import uuid
import openai  
import base64
import requests
import shutil
import zlib
import traceback
import urllib.parse
import imaplib     
from concurrent.futures import ( 
    ThreadPoolExecutor,
    as_completed 
)
from dotenv import load_dotenv
from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    Response,
    stream_with_context
)
from flask_cors import CORS
from docx import Document
import olefile
import csv
from pptx import Presentation
from openpyxl import load_workbook

# Job 이용 공통함수 import
from util.jobs.job_store import *
from config.settings import *

# RAG_ENGINE(config/settings.py)에 따라 인덱싱 파이프라인 진입점을 고른다.
# job_run_graphrag.py/job_run_lightrag.py 둘 다 함수 이름을
# start_graph_pipeline_background/start_graph_update_pipeline_background로 맞춰뒀기 때문에
# import 경로만 바뀌고 아래에서 이 함수들을 부르는 코드는 그대로 쓸 수 있다.
if RAG_ENGINE == "lightrag":
    from util.jobs.job_run_lightrag import (
        start_graph_pipeline_background,
        start_graph_update_pipeline_background
    )
elif RAG_ENGINE == "graphrag":
    from util.jobs.job_run_graphrag import (
        start_graph_pipeline_background,
        start_graph_update_pipeline_background
    )

# 날짜 범위 질의(예: "어제 메일 보여줘") 처리 함수 또한 RAG_ENGINE에 따라 고른다.
if RAG_ENGINE == "lightrag":
    from util.lightrag_backend.lightrag_date_query import run_date_range_query
elif RAG_ENGINE == "graphrag":
    from util.graphrag_date_query import run_date_range_query

from util.user_path import UserPaths, list_accounts, list_indexed_user_ids, set_account_room_name
from util.database.db_reader import (
    get_mail_stats,
    get_keyword_stats,
    get_mail_keyword_monthly_stats,
    get_mail_keyword_daily_stats,
    get_mail_keyword_mentioners,
    get_mail_sync_stats,
    get_user_rating_stats,
    get_high_affinity_person_stats,
    get_keywords_by_person_date,
    get_mail_date_range,
    get_mail_exchange_stats,
    get_mail_person_daily_stats,
    calculate_eis,
    get_person_descriptions,
    get_mail_relationships,
    get_mail_people,
    get_mail_summaries,
    get_date_range_person_stats,
    get_person_mail_ids_in_range
)
from util.mail_data_manager import get_mail_bodies_by_ids
from util.file_manager import (
    _sanitize_filename
)
from util.attachment_manager import (
    _save_attachment_from_base64,
    _extract_text_from_pdf,
    _extract_text_from_docx,
    _extract_text_from_hwp,
    _extract_text_from_txt,
    _extract_text_from_pptx,
    _extract_text_from_xlsx,
    _extract_text_from_csv,
)
if RAG_ENGINE == "lightrag":
    from util.jobs.job_run_lightrag import (
        _summarize_attachment_text,
        _merge_summarized_attachments,
        render_all_prompts,
    )
elif RAG_ENGINE == "graphrag":
    from util.jobs.job_run_graphrag import (
         _summarize_attachment_text,
         _merge_summarized_attachments,
         render_all_prompts,
    )
from util.database.db_writer import (
    save_query_to_db,
    filter_unprocessed_attachments,
    mark_attachments_as_processed,
    rebuild_keyword_mail,
)
from util.database.chatroom_reader import (
    list_indexed_chatrooms,
    get_messenger_date_range,
    get_chatroom_sync_stats,
    get_chatroom_name,
    get_chatroom_people,
    get_chatroom_people_stats,
    get_chatroom_relationships,
    get_chatroom_relationship_stats,
    get_chatroom_person_detail,
    get_chatroom_mood,
    get_chatroom_keywords_by_person,
    get_chatroom_keyword_stats,
    get_chatroom_monthly_message_stats,
    get_chatroom_keyword_monthly_stats,
    get_chatroom_keyword_daily_stats,
    get_chatroom_keyword_mentioners,
    get_chatroom_person_monthly_stats,
    get_chatroom_person_daily_stats,
    get_chatroom_day_messages,
    get_chatroom_summaries,
)
from util.extract_statics import start_statics_pipeline_background
from util.avatar_generator import (
    get_cached_person_avatars,
    get_cached_self_avatar,
    generate_self_avatar,
    get_cached_chatroom_people_avatars,
)
from util.sse_broadcaster import (
    subscribe,
    unsubscribe,
    broadcast
)
from config.db import get_db_connection
from util.graphrag import (
    _run_graphrag,
    _is_index_ready
)
from util.graphrag_query import _classify_query_method

# 현재 RAG_ENGINE에 맞는 방식으로 이 계정의 인덱싱 완료 여부를 반환한다
def _index_ready(paths) -> bool:
    if RAG_ENGINE == "lightrag":
        from util.lightrag_backend.lightrag_engine import is_index_ready
        return is_index_ready(paths.LIGHTRAG_OUTPUT_DIR)
    elif RAG_ENGINE == "graphrag":
        return _is_index_ready(paths)
from util.mail_data_manager import (
    _read_latest_text,
    _extract_message_ids,
    _split_mail_blocks,
    _extract_mail_id_from_block,
    _renumber_mail_blocks,
    _extract_block_for_sort,
    _build_mail_csv
)
from util.file_manager import _delete_incremental_files
from util.imap_connect import (
    _imap_parse_list_line,
    _imap_fetch_content,
    _detect_imap_platform
)
from util.message_parser import (
    parse_message_export,
    build_message_blocks,
    guess_room_name,
    build_room_id,
)
# 환경변수 로드
load_dotenv("src/parquet/.env")

# 서버 시작 시 터미널에서 사용할 RAG_ENGINE 출력.
print("=" * 60)
print(f"[RAG_ENGINE] 서버가 사용할 RAG 엔진: {RAG_ENGINE.upper()}")
print("=" * 60)

# Flask 앱 초기화
app = Flask(__name__)
CORS(app)

# 한글 출력 시 깨지거나 에러 나는 것 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 질의를 백그라운드 잡으로 등록하고 jobId를 즉시 반환한다 (날짜 범위 → 연합 RAG 검색 순으로 시도)
@app.route('/run-query-async', methods=['POST'])
def run_query_async():
    data = request.json or {}

    print("[DEBUG] content_type =", request.content_type)
    print("[DEBUG] raw body =", request.data)
    print("[DEBUG] parsed data =", data)

    if data is None:
        return jsonify({'error': 'JSON 본문을 읽지 못했습니다.'}), 400

    message = request.json.get('message', '')
    resMethod = request.json.get('resMethod', 'local')
    resType = request.json.get('resType', 'text')
    user_id = data.get('user_id', '').strip()
    domain = (data.get('domain') or 'mail').strip().lower()

    if not str(message).strip():
        return jsonify({'error': 'message가 비어있습니다.'}), 400

    if not user_id:
        return jsonify({'error': 'user_id가 비어있습니다.'}), 400

    print("[DEBUG] message =", repr(message))
    print("[DEBUG] user_id =", repr(user_id))

    job_id = str(uuid.uuid4())[:8]
    create_job(job_id, job_type="query")
    update_job(job_id, status="pending", result=None, resType=resType)

    # 백그라운드 스레드에서 실제 질의를 수행하고 job 상태를 갱신한다
    def _worker():
        try:
            env = os.environ.copy()
            env["USER_ID"] = user_id

            # local/global, 날짜 범위 쿼리 모두 해당 도메인에서 인덱싱된 계정(또는 카카오 대화방) 전체를 대상으로 함(연합 검색).
            accounts_paths = [UserPaths(BASE_DIR, uid, domain) for uid in list_indexed_user_ids(BASE_DIR, domain)]

            # 인덱싱된 계정/방이 하나도 없을 때 프론트가 보낸 user_id로 폴백 경로를 만든다.
            if not accounts_paths:
                accounts_paths = [UserPaths(BASE_DIR, user_id, domain)]

            fallback_paths = accounts_paths[0]

            # accounts_paths 전체(인덱싱된 계정 전부)를 대상으로 연합해서 필터링한다.
            answer = run_date_range_query(message, accounts_paths) if domain == "mail" else None # 이게 None이면 GraphRAG/LightRAG로
            source_ids = []  # 초기화
            if answer is None:
                full_message = message + " 영어 말고 한국어로 답변해줘."

                if RAG_ENGINE == "lightrag":
                    from util.lightrag_backend.lightrag_query import _classify_query_method as _classify_lightrag_method, run_federated_search, run_lightrag_query

                    resMethod = _classify_lightrag_method(message)
                    print(f"[QUERY] RAG_ENGINE=lightrag mode={resMethod}")

                    if len(accounts_paths) == 1:
                        # 계정(또는 방)이 하나뿐이면 바로 단일 엔진으로 검색한다.
                        answer, source_ids = run_lightrag_query(full_message, message, fallback_paths, method=resMethod)
                    else:
                        try:
                            answer, source_ids = run_federated_search(full_message, message, accounts_paths, resMethod, primary_user_id=user_id)
                        except Exception as e:
                            print(f"[ENGINE][lightrag] 연합 검색 실패, 선택된 계정으로 폴백: {e}")
                            answer, source_ids = run_lightrag_query(full_message, message, fallback_paths, method=resMethod)

                elif RAG_ENGINE == "graphrag":
                    from util.graphrag_query import run_graphrag_query, run_federated_local_search, run_federated_global_search
                    resMethod = _classify_query_method(message)
                    print(f"[QUERY] RAG_ENGINE=graphrag mode={resMethod}")

                    if len(accounts_paths) == 1:
                        # 계정(또는 방)이 하나뿐이면 단일 엔진으로 검색한다.
                        try:
                            answer, source_ids = run_graphrag_query(full_message, message, fallback_paths, method=resMethod)
                        except Exception as e2:
                            print(f"[ENGINE] API 실패, CLI fallback: {e2}")
                            answer = _run_graphrag(full_message, resMethod, message, fallback_paths, resType)
                    elif resMethod == "local":
                        try:
                            answer, source_ids = run_federated_local_search(full_message, message, accounts_paths, primary_user_id=user_id)
                        except Exception as e:
                            print(f"[ENGINE] 연합 검색 실패, 선택된 계정으로 폴백: {e}")
                            try:
                                answer, source_ids = run_graphrag_query(full_message, message, fallback_paths, method=resMethod)
                            except Exception as e2:
                                print(f"[ENGINE] API 실패, CLI fallback: {e2}")
                                answer = _run_graphrag(full_message, resMethod, message, fallback_paths, resType)
                    else:
                        try:
                            answer, source_ids = run_federated_global_search(full_message, message, accounts_paths, primary_user_id=user_id)
                        except Exception as e:
                            print(f"[ENGINE] 연합 글로벌 검색 실패, 선택된 계정으로 폴백: {e}")
                            try: # 엔진 객체 직접 호출 방식
                                answer, source_ids = run_graphrag_query(full_message, message, fallback_paths, method=resMethod)
                            except Exception as e2:
                                # API 방식 실패 시 기존 CLI 방식으로 자동 fallback
                                print(f"[ENGINE] API 실패, CLI fallback: {e2}")
                                answer = _run_graphrag(full_message, resMethod, message, fallback_paths, resType)
                                # source_ids = _extract_source_mail_ids(answer)

            result = answer
            update_job(job_id, status="done", result=result, source_ids=source_ids)

        except Exception as e:
            update_job(job_id, status="error", result=str(e))

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"jobId": job_id})

# job_id로 잡의 상태·진행률·결과(text 또는 calendar JSON)·근거 메일 ID를 반환한다
@app.route('/job-status/<job_id>', methods=['GET'])
def job_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404

    if job["status"] == "done" and job["resType"].lower() == "calendar":
        try:
            return jsonify({"status": "done", "data": json.loads(job["result"])})
        except Exception:
            return jsonify({"status": "done", "data": {"events": []}})

    # text 타입: result 필드에 문자열 그대로 반환
    return jsonify({
        "status": job["status"],
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "result": job["result"] or "",
        "source_ids": job.get("source_ids") or [],
    })

# 인덱싱 progress/완료/실패 이벤트를 SSE로 실시간 push한다 (15초마다 keepalive)
@app.route("/indexing-stream", methods=["GET"])
def indexing_stream():
    q = subscribe()

    # 구독 큐에서 이벤트를 꺼내 SSE 형식으로 스트리밍한다
    @stream_with_context
    def generate():
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return Response(generate(), content_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive",
                        "ngrok-skip-browser-warning": "true",
                    })

# 최근 job 상태 목록(최대 20개, 최신순)을 반환한다 (페이지 로드 시 이전 상태 복원용)
@app.route("/indexing-history", methods=["GET"])
def indexing_history():
    all_jobs = get_all_jobs()
    # 최신순 정렬, 최대 20개
    sorted_jobs = sorted(all_jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True)[:20]
    events = []
    for job in sorted_jobs:
        events.append({
            "type": job.get("status", "idle"),
            "job_id": job.get("job_id"),
            "progress": job.get("progress", 0),
            "message": job.get("message", ""),
        })
    return jsonify(events)

# 질의를 동기로 처리해 답변을 바로 반환한다 (단일 계정, 연합/날짜 검색 없음)
@app.route('/run-query', methods=['POST'])
def run_query():
    data = request.json or {}
    message = data.get('message', '')
    resMethod = data.get('resMethod', 'local')
    resType = data.get('resType', 'text')
    user_id = (data.get('user_id') or '').strip().lower()

    print(f'message: {message}')
    print(f'resMethod: {resMethod}')
    print(f'resType: {resType}')

    if not str(message).strip():
        return jsonify({'error': 'message가 비어있습니다.'}), 400
    if not user_id:
        return jsonify({'error': 'user_id가 비어있습니다.'}), 400

    paths = UserPaths(BASE_DIR, user_id, "mail")
    message += " 영어 말고 한국어로 답변해줘."

    try:
        if RAG_ENGINE == "lightrag":
            print(f"[QUERY] RAG_ENGINE=lightrag mode={resMethod}")
            from util.lightrag_backend.lightrag_query import run_lightrag_query
            answer, _source_ids = run_lightrag_query(message, message, paths, method=resMethod)
        elif RAG_ENGINE == "graphrag":
            print(f"[QUERY] RAG_ENGINE=graphrag mode={resMethod}")
            answer = _run_graphrag(message, resMethod, message, paths, resType)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'result': answer})

# 미처리 첨부파일의 텍스트를 추출·요약해 mail_latest.txt에 병합하고 처리 완료로 기록한다 (인덱싱 시작 전에 실행)
def _extract_and_merge_attachments(paths, attachments, user_id):
    unprocessed = filter_unprocessed_attachments(user_id, attachments)
    if not unprocessed:
        return

    # 프롬프트의 최신 상태 유지
    render_all_prompts()

    attachment_texts_by_mail: dict[str, list[dict]] = {}
    for file_info in unprocessed:
        f_name = file_info.get("name") or "attachment.bin"
        mail_id = str(file_info.get("mail_id") or "").strip()
        try:
            saved_path, original_name = _save_attachment_from_base64(file_info, paths.ATTACHMENT_DIR)
            ext = os.path.splitext(original_name)[-1].lower()
            mime = (file_info.get("mime") or "").lower()
            file_text = ""
            if ext == ".pdf" or "pdf" in mime:      file_text = _extract_text_from_pdf(saved_path)
            elif ext == ".docx":                     file_text = _extract_text_from_docx(saved_path)
            elif ext == ".hwp":                      file_text = _extract_text_from_hwp(saved_path)
            elif ext == ".txt" or "plain" in mime:   file_text = _extract_text_from_txt(saved_path)
            elif ext == ".pptx":                     file_text = _extract_text_from_pptx(saved_path)
            elif ext == ".xlsx":                     file_text = _extract_text_from_xlsx(saved_path)
            elif ext == ".csv":                      file_text = _extract_text_from_csv(saved_path)

            if file_text and file_text.strip():
                summary = _summarize_attachment_text(file_text.strip(), paths, original_name)
                attachment_texts_by_mail.setdefault(mail_id, []).append({"name": original_name, "text": summary})
        except Exception as e:
            print(f"[UPLOAD] 첨부파일 추출 실패 {f_name}: {e}")

    if attachment_texts_by_mail:
        _merge_summarized_attachments(paths.MAIL_LATEST_PATH, attachment_texts_by_mail)
        print(f"[UPLOAD] 첨부파일 {len(attachment_texts_by_mail)}건 본문에 병합 완료")

    mark_attachments_as_processed(user_id, unprocessed)

# 메일/대화 텍스트를 받아 mail_latest.txt에 누적(rewrite/append, mail_id 중복 체크)하고 인덱싱 파이프라인을 시작한다
@app.route("/upload", methods=["POST"])
def upload():
    # 1) 데이터 수신
    data = request.json or {}
    filename = data.get("filename") or f"mail_{int(time.time())}.txt"
    mail_platform = (data.get("mail_platform") or "gmail").strip().lower()
    content = data.get("content") or ""
    attachments = data.get("attachment") or []
    requested_mode = data.get("syncmode", "append")
    user_id = (data.get("user_id") or "").strip().lower()
    domain = (data.get("domain") or "mail").strip().lower()
    # 메일은 최신 메일이 위로 오는 "받은편지함" 순서를, 카카오는 대화를 처음부터 읽어내려가는
    # "대화 기록" 순서(오래된 게 위)를 기대하므로 도메인별로 정렬 방향을 다르게 함.
    sort_newest_first = domain != "messenger"

    paths = UserPaths(BASE_DIR, user_id, domain)

    if not str(content).strip():
        return jsonify({"ok": False, "error": "content가 비어있습니다."}), 400
    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    print("user_id =", user_id)

    # append인데 기존 인덱스가 없으면 rewrite로 전환
    fallback_to_rewrite = False
    sync_mode = requested_mode

    if requested_mode == "append" and not _index_ready(paths):
        print("[UPLOAD] index not ready -> fallback to rewrite")
        sync_mode = "rewrite"
        fallback_to_rewrite = True

    # 2) 저장 디렉토리 준비
    os.makedirs(paths.MAIL_DIR, exist_ok=True)

    if sync_mode == "rewrite":
        # rewrite: input 폴더 내 기존 메일 파일 전체 초기화
        # mail_latest.txt, mail_latest.csv, inc_*.txt 등 전부 삭제
        # 이전 데이터가 남아있으면 중복 체크에 걸려 새 메일이 스킵되는 버그 방지
        if os.path.exists(paths.MAIL_DIR):
            for fname in os.listdir(paths.MAIL_DIR):
                fpath = os.path.join(paths.MAIL_DIR, fname)
                try:
                    if os.path.isfile(fpath):  # 파일만 삭제, 폴더는 건너뜀
                        os.remove(fpath)
                except Exception as e:
                    print(f"[CLEAN] 파일 삭제 실패 (무시): {fpath} / {e}")

            print(f"[CLEAN] input 폴더 초기화 완료: {paths.MAIL_DIR}")
        if os.path.exists(paths.ATTACHMENT_DIR):
            shutil.rmtree(paths.ATTACHMENT_DIR)
            print(f"[CLEAN] attachment 폴더 초기화 완료: {paths.ATTACHMENT_DIR}")

        # lancedb 벡터 인덱스 삭제 
        if RAG_ENGINE == "graphrag":
            lancedb_dir = os.path.join(paths.GRAPHRAG_ROOT, "output", "lancedb")
            if os.path.exists(lancedb_dir):
                shutil.rmtree(lancedb_dir)
                print(f"[CLEAN] lancedb 벡터 인덱스 초기화 완료: {lancedb_dir}")

        # rewrite 완료 전에 첨부파일이 먼저 처리되는 문제 방지. RAG_ENGINE에 맞는 인덱스 준비 여부 판단 기준 파일을 지운다.
        if RAG_ENGINE == "lightrag":
            ready_marker_path = os.path.join(paths.LIGHTRAG_OUTPUT_DIR, "graph_chunk_entity_relation.graphml")
        elif RAG_ENGINE == "graphrag":
            ready_marker_path = os.path.join(paths.GRAPHRAG_ROOT, "output", "stats.json")
        if os.path.exists(ready_marker_path):
            try:
                os.remove(ready_marker_path)
                print(f"[CLEAN] 인덱스 준비 마커 삭제 완료 (rewrite 시작): {ready_marker_path}")
            except Exception as e:
                print(f"[CLEAN] 인덱스 준비 마커 삭제 실패 (무시): {e}")

        try:
            from util.database.db_writer import get_latest_mail_account
            latest_account = get_latest_mail_account(user_id)
            if latest_account:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM processed_attachments WHERE user_mail_account_id = %s AND index_date = %s",
                    (latest_account["user_mail_account_id"], latest_account["index_date"])
                )
                conn.commit()
                cursor.close()
                conn.close()
            print(f"[CLEAN] processed_attachments DB 초기화 완료 (user_id={user_id})")
        except Exception as e:
            print(f"[CLEAN] processed_attachments DB 초기화 실패 (무시): {e}")

    # 3) 원본 메일 텍스트 저장 (append 모드만 — rewrite는 mail_latest.txt에 바로 씀)
    if sync_mode != "rewrite":
        file_path = os.path.join(paths.MAIL_DIR, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    extracted_count = 0
    failed_attachments = []
    valid_attachments = []

    # 4) 첨부파일 메타데이터 카운트
    for file_info in attachments:
        f_name = file_info.get("name") or "attachment.bin"
        mail_id = str(file_info.get("mail_id") or "").strip()
        if f_name and mail_id:
            extracted_count += 1
            valid_attachments.append(file_info)

    # 5) 로그
    print(f"[UPLOAD] Received filename: {filename}")
    print(f"[UPLOAD] Content length: {len(content)}")
    print(f"[UPLOAD] Attachment count received: {len(attachments)}")
    print(f"[UPLOAD] Attachment extracted count: {extracted_count}")
    print(f"[UPLOAD] Requested mode: {requested_mode}")
    print(f"[UPLOAD] Actual mode: {sync_mode}")
    print("[UPLOAD] cwd:", os.getcwd())

    added_count  = 0
    skipped_count = 0
    saved_mail_path = ""

    # 메일 텍스트 누적 로직
    # rewrite: mail_latest.txt를 새로 씀 (기존 내용 무시)
    # append: 기존 mail_latest.txt를 읽어서 합친 후 재저장
    # 공통: mail_id 기반 중복 체크
    if sync_mode == "rewrite":
        existing_text = ""
        existing_ids  = set()
    else:
        existing_text = _read_latest_text(paths)
        existing_ids  = _extract_message_ids(existing_text)

    # 최근 날짜의 블록 스킵하지 않고 최신 내용으로 덮어쓴다
    # 그 외 과거 날짜는 정상 스킵한다
    overwrite_ids = set()
    if domain == "messenger" and existing_ids:
        dated_ids = [i for i in existing_ids if re.match(r"^\d{4}-\d{2}-\d{2}", i)]
        if dated_ids:
            latest_date = max(i[:10] for i in dated_ids)
            overwrite_ids = {i for i in dated_ids if i.startswith(latest_date)}

    new_blocks    = _split_mail_blocks(content)
    append_blocks = []

    for block in new_blocks:
        msg_id = _extract_mail_id_from_block(block)
        if not msg_id:
            skipped_count += 1
            continue
        if msg_id in existing_ids and msg_id not in overwrite_ids:
            skipped_count += 1
            continue
        append_blocks.append(block.strip())
        existing_ids.add(msg_id)

    # overwrite_ids 중 실제로 새 블록이 들어온 것만 "교체 확정"으로 남긴다
    if overwrite_ids:
        replaced_ids = {_extract_mail_id_from_block(b) for b in append_blocks}
        overwrite_ids &= replaced_ids

    added_count = len(append_blocks)

    if sync_mode == "rewrite":
        _delete_incremental_files(paths)

    if append_blocks:
        append_blocks.sort(key=_extract_block_for_sort, reverse=sort_newest_first)
        inc_content = "\n\n".join(append_blocks).strip() + "\n"
        if sync_mode == "rewrite":
            with open(paths.MAIL_LATEST_PATH, "w", encoding="utf-8") as f:
                f.write(_renumber_mail_blocks(inc_content))
        else:
            # append: 기존 내용 앞에 새 메일 추가 후 mail_latest.txt 저장
            existing_lines = existing_text.splitlines()
            existing_clean = "\n".join(existing_lines).lstrip("\n")
            if overwrite_ids:
                # 덮어쓰기 대상(카카오 최신 날짜) 블록은 기존 내용에서 먼저 제거
                kept_blocks = [
                    b for b in _split_mail_blocks(existing_clean)
                    if _extract_mail_id_from_block(b) not in overwrite_ids
                ]
                existing_clean = "\n\n".join(b.strip() for b in kept_blocks).strip()
            updated_content = inc_content + "\n" + existing_clean
            with open(paths.MAIL_LATEST_PATH, "w", encoding="utf-8") as f:
                f.write(_renumber_mail_blocks(updated_content.strip()))

        saved_mail_path = paths.MAIL_LATEST_PATH

        # 새로 추가된 메일 ID 수집
        new_ids = set()
        for block in append_blocks:
            mid = _extract_mail_id_from_block(block)
            if mid:
                new_ids.add(mid)

        # 이메일 전용 statics 파이프라인
        if domain == "mail":
            statics_job_id = str(uuid.uuid4())[:8]
            create_job(statics_job_id, job_type="statics")

            if sync_mode == "rewrite":
                final_text = _read_latest_text(paths)
                statics_blocks = _split_mail_blocks(final_text)
                statics_blocks = [b for b in statics_blocks if _extract_mail_id_from_block(b)]
            else:
                statics_blocks = append_blocks

            start_statics_pipeline_background(
                statics_job_id, paths,
                mode="rewrite" if sync_mode == "rewrite" else "append"
            )

    else:
        saved_mail_path = ""
        new_ids = set()

    print("[UPLOAD] added:", added_count)
    print("[UPLOAD] skipped:", skipped_count)
    if saved_mail_path:
        print("[UPLOAD] saved mail path:", os.path.abspath(saved_mail_path))

    # GraphRAG 파이프라인 실행
    graph_job_id = str(uuid.uuid4())[:8]

    if sync_mode == "rewrite":
        create_job(graph_job_id, job_type="index")
        update_job(graph_job_id, message="업로드 완료, 그래프 파이프라인 시작")
    else:
        create_job(graph_job_id, job_type="update")
        update_job(graph_job_id, message="업로드 완료, 그래프 업데이트 파이프라인 시작")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # 첨부파일은 CSV 빌드 전에 텍스트 추출/요약해서 mail_latest.txt에 미리 병합해둔다 
    if valid_attachments:
        _extract_and_merge_attachments(paths, valid_attachments, user_id)

    if sync_mode == "rewrite":
        update_dir = os.path.join(paths.GRAPHRAG_ROOT, "update_output")
        if os.path.exists(update_dir):
            shutil.rmtree(update_dir)
            print(f"[CLEAN] update_output 삭제 완료: {update_dir}")

        # _build_mail_csv는 동기 실행 후 GraphRAG 스레드 시작
        # CSV 파일이 완전히 쓰인 뒤 GraphRAG가 읽도록 순서 보장
        _build_mail_csv(paths)
        final_text = _read_latest_text(paths)
        total_mail_count = len([b for b in _split_mail_blocks(final_text) if _extract_mail_id_from_block(b)])
        print(f"[INDEX] RAG_ENGINE={RAG_ENGINE} 로 전체 인덱싱(rewrite) 시작 job_id={graph_job_id}")
        start_graph_pipeline_background(graph_job_id, paths, env, added_count=total_mail_count, mail_platform=mail_platform)

    else:  # append
        if new_ids:
            # _build_mail_csv 반환값 None 체크 추가
            # new_ids 없을 때 None 반환하도록 수정했으므로 None이면 update 생략
            csv_path = _build_mail_csv(paths, mode="append", new_ids=new_ids)
            if csv_path:
                print(f"[INDEX] RAG_ENGINE={RAG_ENGINE} 로 증분 업데이트 시작 job_id={graph_job_id}")
                start_graph_update_pipeline_background(graph_job_id, paths, env)
            else:
                update_job(graph_job_id, status="done", message="CSV 없음, 업데이트 생략")
                print("[UPLOAD] CSV 생성 실패 → graphrag update 생략")
        else:
            # 증분 대상(new_ids)이 없으면 rewrite 파이프라인으로 전환한다
            print("[UPLOAD] new_ids 없음 → 증분할 새 메일 없음, 전체 재인덱싱으로 전환")
            update_job(graph_job_id, message="증분 대상 없음 → 전체 재인덱싱으로 전환")

            _build_mail_csv(paths)
            final_text = _read_latest_text(paths)
            total_mail_count = len([b for b in _split_mail_blocks(final_text) if _extract_mail_id_from_block(b)])
            print(f"[INDEX] RAG_ENGINE={RAG_ENGINE} 로 전체 인덱싱(rewrite, 증분 폴백) 시작 job_id={graph_job_id}")
            start_graph_pipeline_background(graph_job_id, paths, env, added_count=total_mail_count, mail_platform=mail_platform)
            sync_mode = "rewrite"  # 응답 필드(actual_mode)에도 실제로 rewrite로 처리됐음을 반영
            fallback_to_rewrite = True  # index-not-ready 폴백과 같은 필드로 프론트에 "요청과 다르게 처리됨"을 알림

    return jsonify({
        "ok": True,
        "requested_mode": requested_mode,
        "job_id": graph_job_id,
        "actual_mode": sync_mode,
        "fallback_to_rewrite": fallback_to_rewrite,
        "latest_path": os.path.abspath(paths.MAIL_LATEST_PATH),
        "saved_mail_path": os.path.abspath(saved_mail_path) if saved_mail_path else "",
        "attachment_dir": os.path.abspath(paths.ATTACHMENT_DIR),
        "content_length": len(content),
        "added_count": added_count,
        "skipped_count": skipped_count,
        "attachment_received_count": len(attachments),
        "attachment_extracted_count": extracted_count,
        "failed_attachments": failed_attachments,
    })

# 이 계정의 그래프 시각화용 JSON(nodes/edges)을 반환한다 (엔진별 경로에서 읽고 없으면 빈 그래프)
@app.route("/graph-data", methods=["GET", "OPTIONS"])
def graph_data():
    if request.method == "OPTIONS":
        return "", 200

    user_id = (request.args.get("user_id") or "").strip().lower()
    domain = (request.args.get("domain") or "mail").strip().lower()

    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    paths = UserPaths(BASE_DIR, user_id, domain)

    # 그래프 시각화 json 경로 엔진별로 분리
    if RAG_ENGINE == "lightrag":
        graph_json_path = paths.LIGHTRAG_GRAPH_JSON_PATH
    elif RAG_ENGINE == "graphrag":
        graph_json_path = paths.GRAPH_JSON_PATH

    if not os.path.exists(graph_json_path):
        return jsonify({"nodes": [], "edges": [], "error": "graph json not found"}), 200

    try:
        with open(graph_json_path, "rb") as f:
            raw = f.read().rstrip(b'\x00')  # null 바이트 제거 (비정상 종료 방어)
        data = json.loads(raw.decode("utf-8"))
        print(f"[GRAPH-DATA] 반환: {len(data.get('nodes', []))} 노드")
        return jsonify(data)
    except Exception as e:
        print(f"[GRAPH-DATA] 에러: {e}")
        return jsonify({"nodes": [], "edges": [], "error": str(e)}), 500

# 그래프 시각화용 정적 HTML(graph_view.html)을 서빙한다
@app.route("/graph-view", methods=["GET"])
def graph_view():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "json"),
        "graph_view.html"
    )

# 그래프 렌더링 공용 스크립트(graph-render.js)를 서빙한다
@app.route('/graph-render.js')
def graph_render_js():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "json"),
        "graph-render.js"
    )

# 이 계정의 인덱싱 완료 여부를 {indexed: bool}로 반환한다
@app.route("/index-status", methods=["GET"])
def index_status():
    user_id = (request.args.get("user_id") or "").strip().lower()
    if not user_id:
        return jsonify({"error": "user_id가 비어있습니다."}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"indexed": _index_ready(paths)})

# 현재 서버 URL을 localStorage에 저장하는 스크립트를 내려주고 대시보드로 리다이렉트한다
@app.route('/init')
def init_storage():
    from flask import request as _req
    origin = _req.host_url.rstrip('/')
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Initializing...</title></head>
<body>
<script>
  localStorage.setItem('gw_flask_url', {repr(origin)});
  window.location.replace('/dashboard/');
</script>
<p>설정 중... 자동으로 이동합니다.</p>
</body></html>""", 200, {{'Content-Type': 'text/html; charset=utf-8'}}

# dist 루트의 favicon.ico를 서빙한다 (브라우저 기본 요청의 404 로그 방지)
@app.route('/favicon.ico')
def favicon():
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist')
    return send_from_directory(dist_dir, 'favicon.ico')

# 빌드된 웹앱(dist) 파일을 서빙한다 (HTML은 캐시 금지 헤더 부착)
@app.route('/dashboard/', defaults={'path': 'production/index.html'})
@app.route('/dashboard/<path:path>')
def dashboard(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist')
    if not path.startswith('production/') and path.endswith('.html'):
        path = 'production/' + path
    response = send_from_directory(dist_dir, path)
    if path.endswith('.html'):
        # HTML 응답은 캐시를 못 하게 막는다
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response

# dist/assets 정적 파일을 서빙한다
@app.route('/assets/<path:path>')
def static_assets(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist', 'assets')
    return send_from_directory(dist_dir, path)

# dist/js 정적 파일을 서빙한다
@app.route('/js/<path:path>')
def static_js(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist', 'js')
    return send_from_directory(dist_dir, path)

# dist/fonts 정적 파일을 서빙한다
@app.route('/fonts/<path:path>')
def static_fonts(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist', 'fonts')
    return send_from_directory(dist_dir, path)

# dist/images 정적 파일을 서빙한다
@app.route('/images/<path:path>')
def static_images(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist', 'images')
    return send_from_directory(dist_dir, path)

# 연락처별 메일 송수신 통계(mail_contact_stats.json)를 반환한다
@app.route("/mail-stats", methods=["POST"])
def send_mail_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    print(f"[MAIL_STATS] user_id={user_id}")
    print(f"[MAIL_STATS] path={paths.USER_ROOT}")
    return jsonify({"user_id": user_id, "data": get_mail_stats(paths)})

# 이 계정 메일의 가장 이른/늦은 날짜를 반환한다
@app.route("/mail-date-range", methods=["POST"])
def send_mail_date_range():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    return jsonify({"user_id": user_id, "data": get_mail_date_range(user_id)})

# 이 계정의 키워드별 언급 수 목록을 반환한다
@app.route("/keyword-stats", methods=["POST"])
def send_keyword_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_keyword_stats(paths)})

# 특정 상대방과 날짜 범위 내 주고받은 메일의 키워드별 언급 수·날짜를 반환한다
@app.route("/keyword-by-person-date", methods=["POST"])
def keyword_by_person_date():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    person_user_id = data.get("person_user_id", "").strip()
    # 시간 범위 내에 있는 메일의 키워드들을 추출
    start_date = data.get("start_date", "").strip()
    end_date = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_user_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    try:
        keywords = get_keywords_by_person_date(user_id, person_user_id, start_date, end_date)
        return jsonify({"keywords": keywords})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 계정 전체(모든 상대방 합산)의 월별 키워드 목록·언급 수를 반환한다
@app.route("/mail-keyword-monthly-stats", methods=["POST"])
def send_mail_keyword_monthly_stats():
    data = request.json or {}
    user_id    = data.get("user_id", "").strip()
    start_date = (data.get("start_date") or "").strip() or None
    end_date   = (data.get("end_date") or "").strip() or None

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    return jsonify({
        "user_id": user_id,
        "data": get_mail_keyword_monthly_stats(user_id, start_date, end_date),
    })

# 계정 전체가 특정 월에 날짜별로 언급한 키워드 목록·횟수를 반환한다
@app.route("/mail-keyword-daily-stats", methods=["POST"])
def send_mail_keyword_daily_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    month   = data.get("month", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not month:
        return jsonify({"error": "month is required"}), 400

    return jsonify({
        "user_id": user_id,
        "month":   month,
        "data": get_mail_keyword_daily_stats(user_id, month),
    })

# 특정 날짜에 특정 키워드를 언급한 상대방 목록(이름·횟수·아바타)을 반환한다
@app.route("/mail-keyword-mentioners", methods=["POST"])
def send_mail_keyword_mentioners():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    date    = data.get("date", "").strip()
    keyword = data.get("keyword", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not date:
        return jsonify({"error": "date is required"}), 400
    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    mentioners = get_mail_keyword_mentioners(user_id, date, keyword)

    paths = UserPaths(BASE_DIR, user_id, "mail")
    avatar_map = get_cached_person_avatars(paths)
    for m in mentioners:
        m["avatar_url"] = avatar_map.get((m["person_id"] or "").strip().lower())

    return jsonify({
        "user_id": user_id,
        "date":    date,
        "keyword": keyword,
        "data": mentioners,
    })

# mail_keyword 테이블을 LLM 없이 문자열 매칭으로 재구성한다
@app.route("/rebuild-keyword-mail", methods=["POST"])
def rebuild_keyword_mail_route():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    try:
        rebuild_keyword_mail(paths)
        return jsonify({"ok": True, "message": "mail_keyword 테이블 재구성 완료"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 사용자가 올린 연락처 사진(이메일→base64)을 contact_photos.json에 병합 저장한다
@app.route("/upload-photos", methods=["POST"])
def upload_contact_photos():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    photos   = data.get("photos", {})
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not isinstance(photos, dict) or not photos:
        return jsonify({"ok": True, "message": "사진 없음"}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    existing = {}
    if os.path.exists(paths.MAIL_PHOTOS_PATH):
        with open(paths.MAIL_PHOTOS_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.update({k.lower(): v for k, v in photos.items()})
    with open(paths.MAIL_PHOTOS_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "saved": len(photos)})

# 저장된 연락처 사진 맵(contact_photos.json)을 반환한다
@app.route("/contact-photos", methods=["POST"])
def get_contact_photos():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    if not os.path.exists(paths.MAIL_PHOTOS_PATH):
        return jsonify({}), 200
    with open(paths.MAIL_PHOTOS_PATH, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))

# 캐시된 연락처 아바타 맵(이메일→URL)을 반환한다
@app.route("/person-avatars", methods=["POST"])
def get_person_avatars():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify(get_cached_person_avatars(paths))

# 연락처 아바타 이미지 파일을 서빙한다
@app.route("/person-avatar-image/<user_id>/<filename>")
def person_avatar_image(user_id, filename):
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return send_from_directory(paths.AVATAR_IMAGES_DIR, filename)

# 채팅방 참여자 아바타 이미지 파일을 서빙한다
@app.route("/chatroom-person-avatar-image/<chatroom_id>/<filename>")
def chatroom_person_avatar_image(chatroom_id, filename):
    paths = UserPaths(BASE_DIR, chatroom_id, "messenger")
    return send_from_directory(paths.MESSAGE_AVATAR_IMAGES_DIR, filename)

# 메일 기간 요약 삽화 이미지 파일을 서빙한다
@app.route("/mail-summary-image/<user_id>/<filename>")
def mail_summary_image(user_id, filename):
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return send_from_directory(paths.MAIL_SUMMARY_IMAGES_DIR, filename)

# 메신저 기간 요약 삽화 이미지 파일을 서빙한다
@app.route("/message-summary-image/<chatroom_id>/<filename>")
def message_summary_image(chatroom_id, filename):
    paths = UserPaths(BASE_DIR, chatroom_id, "messenger")
    return send_from_directory(paths.MESSAGE_SUMMARY_IMAGES_DIR, filename)

# 로그인한 사용자 본인 아바타의 캐시 URL을 반환한다
@app.route("/self-avatar", methods=["POST"])
def get_self_avatar():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"url": get_cached_self_avatar(paths)})

# 사용자 본인 아바타를 없으면 생성해 URL을 반환한다
@app.route("/generate-self-avatar", methods=["POST"])
def generate_self_avatar_route():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    name = data.get("name", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    url = generate_self_avatar(paths, name)
    return jsonify({"url": url})

# 연락처별 친밀도(EIS) 내림차순 목록을 반환한다
@app.route("/high_affinity_person_stats", methods=["POST"])
def send_high_affinity_person_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_high_affinity_person_stats(paths)})

# 전체 유저 만족도 통계를 반환한다
@app.route("/user_rating_stats", methods=["POST"])
def send_user_rating_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_user_rating_stats()})

# 가장 최근 인덱싱의 동기화 메일 수·소요 시간·날짜를 반환한다
@app.route("/mail_sync_stats", methods=["POST"])
def send_mail_sync_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_mail_sync_stats(paths)})

# 특정 상대방과 날짜 범위 내 월별 발신/수신 메일 수를 반환한다
@app.route("/mail-exchange-stats", methods=["POST"])
def send_mail_exchange_stats():
    data = request.json or {}
    user_id       = data.get("user_id", "").strip()
    person_mail_id = data.get("person_user_id", "").strip()
    start_date     = data.get("start_date", "").strip()
    end_date       = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_mail_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    return jsonify({"data": get_mail_exchange_stats(user_id, person_mail_id, start_date, end_date)})

# 특정 상대방과 특정 월에 날짜별로 주고받은 메일 수를 반환한다
@app.route("/mail-person-daily-stats", methods=["POST"])
def send_mail_person_daily_stats():
    data = request.json or {}
    user_id       = data.get("user_id", "").strip()
    person_mail_id = data.get("person_user_id", "").strip()
    month          = data.get("month", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_mail_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not month:
        return jsonify({"error": "month is required"}), 400

    return jsonify({
        "user_id":        user_id,
        "person_user_id": person_mail_id,
        "month":          month,
        "data": get_mail_person_daily_stats(user_id, person_mail_id, month),
    })

# 단톡방 목록(이름·메시지 수·참여자)을 반환한다 (기간 지정 시 그 기간 집계)
@app.route("/messenger-chatrooms", methods=["POST"])
def send_messenger_chatrooms():
    data = request.json or {}
    start_date = (data.get("start_date") or "").strip() or None
    end_date   = (data.get("end_date") or "").strip() or None
    chatrooms = list_indexed_chatrooms(BASE_DIR, start_date, end_date)
    return jsonify({"data": {"chatrooms": chatrooms}})

# 인덱싱된 모든 단톡방을 통틀어 가장 이른/늦은 메시지 날짜를 반환한다
@app.route("/messenger-date-range", methods=["POST"])
def send_messenger_date_range():
    return jsonify({"data": get_messenger_date_range(BASE_DIR)})

# 채팅방의 가장 최근 인덱싱 메시지 수·소요 시간·날짜를 반환한다
@app.route("/chatroom-sync-stats", methods=["POST"])
def send_chatroom_sync_stats():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400

    return jsonify({
        "chatroom_id": chatroom_id,
        "data": get_chatroom_sync_stats(chatroom_id),
    })

# chatroom_id로 방 이름을 반환한다
@app.route("/chatroom-name", methods=["POST"])
def send_chatroom_name():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()
    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400

    chatroom_name = get_chatroom_name(chatroom_id)
    if chatroom_name is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "data": {"chatroom_name": chatroom_name},
    })

# 채팅방 참여자 목록(이름·메시지 수·설명·아바타)을 반환한다
@app.route("/chatroom-people", methods=["POST"])
def send_chatroom_people():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400

    people = get_chatroom_people(chatroom_id)
    if people is None:
        return jsonify({"error": "chatroom not found"}), 404

    paths = UserPaths(BASE_DIR, chatroom_id, "messenger")
    avatar_map = get_cached_chatroom_people_avatars(paths)
    for p in people:
        p["avatar_url"] = avatar_map.get(p["participant_id"])

    return jsonify({
        "chatroom_id": chatroom_id,
        "data": {"people": people},
    })

# 채팅방에 실제 저장된 사람-사람 관계를 relation_label별 개수·순위로 반환한다
@app.route("/chatroom-relationship-stats", methods=["POST"])
def send_chatroom_relationship_stats():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400

    stats = get_chatroom_relationship_stats(chatroom_id)
    if stats is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "data": stats,
    })

# 지정 기간에 활동한 참여자들 사이의 사람-사람 관계 목록을 반환한다
@app.route("/chatroom-relationships", methods=["POST"])
def send_chatroom_relationships():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()
    start_date  = data.get("start_date", "").strip()
    end_date    = data.get("end_date", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    # 필터링 기준으로 쓸 활동 참여자 이름 집합이 필요
    people = get_chatroom_people_stats(chatroom_id, start_date, end_date)
    if people is None:
        return jsonify({"error": "chatroom not found"}), 404

    paths = UserPaths(BASE_DIR, chatroom_id, "messenger")
    active_names = {p["name"] for p in people}
    relationships = get_chatroom_relationships(paths, active_names)

    return jsonify({
        "chatroom_id": chatroom_id,
        "start_date":  start_date,
        "end_date":    end_date,
        "data": {
            "relationships": relationships,
        },
    })

# 채팅방 참여자 명단의 프로필 설명과 지정 기간 메시지 수·아바타를 반환한다
@app.route("/chatroom-person-detail", methods=["POST"])
def send_chatroom_person_detail():
    data = request.json or {}
    chatroom_id    = data.get("chatroom_id", "").strip()
    participant_id = data.get("participant_id", "").strip() or None
    start_date     = data.get("start_date", "").strip()
    end_date       = data.get("end_date", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    people = get_chatroom_person_detail(chatroom_id, start_date, end_date, participant_id)
    if people is None:
        if participant_id:
            return jsonify({"error": "person not found"}), 404
        return jsonify({"error": "chatroom not found"}), 404

    paths = UserPaths(BASE_DIR, chatroom_id, "messenger")
    avatar_map = get_cached_chatroom_people_avatars(paths)
    for p in people:
        p["avatar_url"] = avatar_map.get(p["participant_id"])

    return jsonify({
        "chatroom_id":    chatroom_id,
        "participant_id": participant_id,
        "start_date":     start_date,
        "end_date":       end_date,
        "data": {
            "people": people,
        },
    })

# 채팅방의 지정 기간 월별/연별 분위기 점수·설명을 반환한다
@app.route("/chatroom-mood", methods=["POST"])
def send_chatroom_mood():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()
    start_date  = data.get("start_date", "").strip()
    end_date    = data.get("end_date", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    mood = get_chatroom_mood(chatroom_id, start_date, end_date)
    if mood is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "start_date":  start_date,
        "end_date":    end_date,
        "data": mood,
    })

# 특정 참여자가 지정 기간에 사용한 키워드별 언급 횟수를 반환한다
@app.route("/chatroom-keywords-by-person", methods=["POST"])
def send_chatroom_keywords_by_person():
    data = request.json or {}
    chatroom_id    = data.get("chatroom_id", "").strip()
    participant_id = data.get("participant_id", "").strip()
    start_date     = data.get("start_date", "").strip()
    end_date       = data.get("end_date", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not participant_id:
        return jsonify({"error": "participant_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    keywords = get_chatroom_keywords_by_person(chatroom_id, start_date, end_date, participant_id)
    if keywords is None:
        return jsonify({"error": "chatroom not found"}), 404
    if keywords is False:
        return jsonify({"error": "person not found"}), 404

    return jsonify({
        "chatroom_id":    chatroom_id,
        "participant_id": participant_id,
        "start_date":     start_date,
        "end_date":       end_date,
        "data": {
            "keywords": keywords,
        },
    })

# 채팅방 전체(모든 참여자·전체 기간 합산)의 키워드별 총 언급 수를 순위(내림차순)로 반환한다
@app.route("/chatroom-keyword-stats", methods=["POST"])
def send_chatroom_keyword_stats():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400

    stats = get_chatroom_keyword_stats(chatroom_id)
    if stats is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "data": stats,
    })

# 채팅방 전체의 월별 메시지 수(송수신 횟수)를 반환한다
@app.route("/chatroom-monthly-message-stats", methods=["POST"])
def send_chatroom_monthly_message_stats():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400

    stats = get_chatroom_monthly_message_stats(chatroom_id)
    if stats is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "data": {"monthly": stats},
    })

# 채팅방 전체(모든 참여자 합산)의 월별 키워드 목록·언급 수를 반환한다
@app.route("/chatroom-keyword-monthly-stats", methods=["POST"])
def send_chatroom_keyword_monthly_stats():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()
    start_date  = (data.get("start_date") or "").strip() or None
    end_date    = (data.get("end_date") or "").strip() or None

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400

    stats = get_chatroom_keyword_monthly_stats(chatroom_id, start_date, end_date)
    if stats is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "data": stats,
    })

# 채팅방 전체가 특정 월에 날짜별로 언급한 키워드 목록·횟수를 반환한다
@app.route("/chatroom-keyword-daily-stats", methods=["POST"])
def send_chatroom_keyword_daily_stats():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()
    month       = data.get("month", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not month:
        return jsonify({"error": "month is required"}), 400

    stats = get_chatroom_keyword_daily_stats(chatroom_id, month)
    if stats is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "month":       month,
        "data": stats,
    })

# 특정 날짜에 특정 키워드를 언급한 참여자 목록(이름·횟수·아바타)을 반환한다
@app.route("/chatroom-keyword-mentioners", methods=["POST"])
def send_chatroom_keyword_mentioners():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()
    date        = data.get("date", "").strip()
    keyword     = data.get("keyword", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not date:
        return jsonify({"error": "date is required"}), 400
    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    mentioners = get_chatroom_keyword_mentioners(chatroom_id, date, keyword)
    if mentioners is None:
        return jsonify({"error": "chatroom not found"}), 404

    paths = UserPaths(BASE_DIR, chatroom_id, "messenger")
    avatar_map = get_cached_chatroom_people_avatars(paths)
    for m in mentioners:
        m["avatar_url"] = avatar_map.get(m["participant_id"])

    return jsonify({
        "chatroom_id": chatroom_id,
        "date":        date,
        "keyword":     keyword,
        "data": mentioners,
    })

# 특정 참여자가 월별로 보낸 메시지 수를 반환한다
@app.route("/chatroom-person-monthly-stats", methods=["POST"])
def send_chatroom_person_monthly_stats():
    data = request.json or {}
    chatroom_id    = data.get("chatroom_id", "").strip()
    participant_id = data.get("participant_id", "").strip()
    start_date     = (data.get("start_date") or "").strip() or None
    end_date       = (data.get("end_date") or "").strip() or None

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not participant_id:
        return jsonify({"error": "participant_id is required"}), 400

    stats = get_chatroom_person_monthly_stats(chatroom_id, participant_id, start_date, end_date)
    if stats is None:
        return jsonify({"error": "chatroom not found"}), 404
    if stats is False:
        return jsonify({"error": "person not found"}), 404

    return jsonify({
        "chatroom_id":    chatroom_id,
        "participant_id": participant_id,
        "data": stats,
    })

# 특정 참여자가 특정 월에 날짜별로 보낸 메시지 수를 반환한다
@app.route("/chatroom-person-daily-stats", methods=["POST"])
def send_chatroom_person_daily_stats():
    data = request.json or {}
    chatroom_id    = data.get("chatroom_id", "").strip()
    participant_id = data.get("participant_id", "").strip()
    month          = data.get("month", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not participant_id:
        return jsonify({"error": "participant_id is required"}), 400
    if not month:
        return jsonify({"error": "month is required"}), 400

    stats = get_chatroom_person_daily_stats(chatroom_id, participant_id, month)
    if stats is None:
        return jsonify({"error": "chatroom not found"}), 404
    if stats is False:
        return jsonify({"error": "person not found"}), 404

    return jsonify({
        "chatroom_id":    chatroom_id,
        "participant_id": participant_id,
        "month":          month,
        "data": stats,
    })

# 채팅방의 특정 날짜 하루치 대화 원문 메시지를 시간순으로 반환한다
@app.route("/chatroom-day-messages", methods=["POST"])
def send_chatroom_day_messages():
    data = request.json or {}
    chatroom_id = data.get("chatroom_id", "").strip()
    date        = data.get("date", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if not date:
        return jsonify({"error": "date is required"}), 400

    messages = get_chatroom_day_messages(BASE_DIR, chatroom_id, date)
    if messages is None:
        return jsonify({"error": "chatroom not found"}), 404

    return jsonify({
        "chatroom_id": chatroom_id,
        "date":        date,
        "data": {"messages": messages},
    })

# 채팅방의 월별/연별 LLM 요약을 주요 연락처(설명 포함)와 함께 반환한다
@app.route("/chatroom-summaries", methods=["POST"])
def send_chatroom_summaries():
    data = request.json or {}
    chatroom_id    = data.get("chatroom_id", "").strip()
    summarize_unit = data.get("summarize_unit", "").strip()

    if not chatroom_id:
        return jsonify({"error": "chatroom_id is required"}), 400
    if summarize_unit not in ("monthly", "yearly"):
        return jsonify({"error": "summarize_unit must be 'monthly' or 'yearly'"}), 400

    summaries = get_chatroom_summaries(chatroom_id, summarize_unit)
    if summaries is None:
        return jsonify({"error": "chatroom not found"}), 404

    people = get_chatroom_people(chatroom_id) or []
    people_map = {p["name"]: p for p in people}

    for s in summaries:
        s["contacts"] = [
            {
                "person_name": name,
                "description": people_map.get(name, {}).get("description"),
                "short_bio":    people_map.get(name, {}).get("short_bio"),
            }
            for name in s["contacts"]
        ]

    return jsonify({
        "chatroom_id":    chatroom_id,
        "summarize_unit": summarize_unit,
        "data": {
            "summaries": summaries,
        },
    })

_mail_message_cache_lock = threading.Lock()

# 메일 본문 파일 캐시(mail_message_cache.json)를 읽어 dict로 반환한다 (없거나 깨졌으면 빈 dict)
def _load_mail_message_cache(paths):
    if not os.path.exists(paths.MAIL_MESSAGE_CACHE_PATH):
        return {}
    try:
        with open(paths.MAIL_MESSAGE_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

# 메일 본문 파일 캐시(mail_message_cache.json)를 저장한다
def _save_mail_message_cache(paths, cache):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(paths.MAIL_MESSAGE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# 특정 상대방과 날짜 범위 내 주고받은 메일 목록(캐시된 본문 포함)을 반환한다
@app.route("/mail-person-emails", methods=["POST"])
def send_person_emails_in_range():
    data = request.json or {}
    user_id       = data.get("user_id", "").strip()
    person_mail_id = data.get("person_user_id", "").strip()
    start_date     = data.get("start_date", "").strip()
    end_date       = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_mail_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    # 1) MySQL mail 테이블에서 이 기간에 오간 메일 ID 목록을 가져온다
    mail_refs = get_person_mail_ids_in_range(user_id, person_mail_id, start_date, end_date)

    # 2) 제목/본문은 메일 ID별로 파일 캐시에서 조회한다. 캐시에 없는 메일은 건너뛴다.
    paths = UserPaths(BASE_DIR, user_id, "mail")
    mail_cache = _load_mail_message_cache(paths)

    # 메일 참조 하나를 캐시에서 조회해 본문 dict로 만든다 (캐시에 없으면 None)
    def _fetch_one(ref):
        cached = mail_cache.get(ref["id"])
        if cached:
            return {**cached, "id": ref["id"], "direction": ref["direction"], "date": ref["date"]}
        return None

    emails = []
    if mail_refs:
        with ThreadPoolExecutor(max_workers=min(len(mail_refs), 6)) as executor:
            futures = [executor.submit(_fetch_one, ref) for ref in mail_refs]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    emails.append(result)
    emails.sort(key=lambda e: e["date"])

    return jsonify({"data": emails})

# 특정 상대방과 특정 날짜에 주고받은 메일 전체(documents.parquet에서 읽은 본문 포함)를 반환한다
@app.route("/mail-day-emails", methods=["POST"])
def send_mail_day_emails():
    data = request.json or {}
    user_id        = data.get("user_id", "").strip()
    person_mail_id = data.get("person_user_id", "").strip()
    date           = data.get("date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_mail_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not date:
        return jsonify({"error": "date is required"}), 400

    mail_refs = get_person_mail_ids_in_range(user_id, person_mail_id, date, date)
    paths = UserPaths(BASE_DIR, user_id, "mail")
    bodies = get_mail_bodies_by_ids(paths, {ref["id"] for ref in mail_refs})
    emails = [
        {**bodies[ref["id"]], "id": ref["id"], "direction": ref["direction"], "date": ref["date"]}
        for ref in mail_refs if ref["id"] in bodies
    ]
    emails.sort(key=lambda e: e["date"])

    return jsonify({
        "user_id":        user_id,
        "person_user_id": person_mail_id,
        "date":           date,
        "data": {"emails": emails},
    })

# 근거 메일 하나(account + mail_id)의 제목/발신/수신/본문을 반환한다
@app.route("/mail-body-by-ids", methods=["POST"])
def send_mail_body_by_ids():
    data = request.json or {}
    account = data.get("account", "").strip()
    mail_id = data.get("mail_id", "").strip()

    if not account:
        return jsonify({"error": "account is required"}), 400
    if not mail_id:
        return jsonify({"error": "mail_id is required"}), 400

    paths = UserPaths(BASE_DIR, account, "mail")
    bodies = get_mail_bodies_by_ids(paths, {mail_id})
    body = bodies.get(mail_id)
    if not body:
        return jsonify({"error": "메일을 찾을 수 없습니다."}), 404

    return jsonify({"id": mail_id, "account": account, **body})

# 여러 근거 메일 refs의 제목만 {mail_id: subject}로 한 번에 반환한다 (계정별로 묶어 parquet을 계정당 1회만 읽음)
@app.route("/mail-subjects-by-ids", methods=["POST"])
def send_mail_subjects_by_ids():
    data = request.json or {}
    refs = data.get("refs") or []

    ids_by_account = {}
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        mail_id = (ref.get("id") or "").strip()
        account = (ref.get("account") or "").strip()
        if not mail_id or not account:
            continue
        ids_by_account.setdefault(account, set()).add(mail_id)

    subjects = {}
    for account, mail_ids in ids_by_account.items():
        paths = UserPaths(BASE_DIR, account, "mail")
        bodies = get_mail_bodies_by_ids(paths, mail_ids)
        for mail_id, body in bodies.items():
            subjects[mail_id] = body.get("subject", "")

    return jsonify({"subjects": subjects})

# 날짜 범위 내 발신 메일을 상대방별로 집계해 반환한다
@app.route("/mail-person-sent-stats", methods=["POST"])
def send_mail_person_sent_stats():
    data = request.json or {}
    user_id   = data.get("user_id", "").strip()
    start_date = data.get("start_date", "").strip()
    end_date   = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    return jsonify({"user_id": user_id, "data": get_date_range_person_stats(user_id, start_date, end_date, "sent")})

# 날짜 범위 내 수신 메일을 상대방별로 집계해 반환한다
@app.route("/mail-person-received-stats", methods=["POST"])
def send_mail_person_received_stats():
    data = request.json or {}
    user_id   = data.get("user_id", "").strip()
    start_date = data.get("start_date", "").strip()
    end_date   = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    return jsonify({"user_id": user_id, "data": get_date_range_person_stats(user_id, start_date, end_date, "received")})

# 특정 상대방과 지정 기간의 친밀도(EIS) 상세 점수를 반환한다
@app.route("/intimacy", methods=["POST"])
def send_intimacy():
    data = request.json or {}
    user_id        = data.get("user_id", "").strip()
    person_user_id = data.get("person_user_id", "").strip()
    start_date      = data.get("start_date", "").strip()
    end_date        = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_user_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    result = calculate_eis(
        user_mail_account_id=user_id,
        person_mail_account_id=person_user_id,
        start_date=start_date,
        end_date=end_date,
        apply_volume_correction=False,
        apply_time_decay=False,
    )
    return jsonify({
        "user_id":        user_id,
        "person_user_id": person_user_id,
        "start_date":      start_date,
        "end_date":        end_date,
        "data":            result,
    })

# 연락처별 LLM 프로필(description) 목록을 반환한다
@app.route("/person-descriptions", methods=["POST"])
def send_person_descriptions():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    return jsonify({"user_id": user_id, "data": get_person_descriptions(user_id)})

# 연락처별 관계 라벨(relation_label) 목록을 반환한다
@app.route("/mail-relationships", methods=["POST"])
def send_mail_relationships():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    return jsonify({"user_id": user_id, "data": get_mail_relationships(user_id)})

# 최신 인덱싱 기준 연락처 전체 목록(메일수·description·relation_label·short_bio 포함)을 반환한다
@app.route("/mail-people", methods=["POST"])
def send_mail_people():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    people = get_mail_people(user_id)
    if people is None:
        return jsonify({"error": "mail account not found"}), 404

    return jsonify({"user_id": user_id, "data": {"people": people}})

# 메일 기간 요약(monthly/yearly)을 주요 연락처(설명 포함)와 함께 반환한다
@app.route("/mail-summaries", methods=["POST"])
def send_mail_summaries():
    data = request.json or {}
    user_id      = data.get("user_id", "").strip()
    summary_type = data.get("type", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if summary_type not in ("monthly", "yearly"):
        return jsonify({"error": "type must be 'monthly' or 'yearly'"}), 400

    summaries = get_mail_summaries(user_id, summary_type)
    if summaries is None:
        return jsonify({"error": "mail account not found"}), 404

    return jsonify({
        "user_id": user_id,
        "type": summary_type,
        "data": {
            "summaries": summaries,
        },
    })

# 연락처 관련 프록시 액션(자주 연락하는 상대 조회 등)을 처리한다
@app.route('/contacts-proxy', methods=['POST'])
def contacts_proxy():
    data = request.get_json() or {}
    action = data.get('action', '')
    user_id = (data.get('user_id') or '').strip().lower()

    if not user_id:
        return jsonify({'ok': False, 'error': 'user_id가 비어있습니다.'}), 400

    paths = UserPaths(BASE_DIR, user_id, "mail")

    if action == 'getFrequentContacts':
        max_results = int(data.get('maxResults', 100))
        try:
            if not os.path.exists(paths.MAIL_CONTACTS_PATH):
                return jsonify({'ok': True, 'contacts': []})
            with open(paths.MAIL_CONTACTS_PATH, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            result = []
            for email, info in stats.items():
                count = info.get('sent', 0) + info.get('received', 0)
                result.append({
                    'email': email,
                    'name': info.get('name', '') or email.split('@')[0],
                    'count': count,
                    'lastMailAt': None,
                })
            result.sort(key=lambda x: -x['count'])
            return jsonify({'ok': True, 'contacts': result[:max_results]})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)})

    elif action == 'getMailHistory':
        email = (data.get('email') or '').strip()
        if not email:
            return jsonify({'ok': False, 'error': 'email이 비어있습니다.'}), 400
        try:
            if not os.path.exists(paths.MAIL_CONTACTS_PATH):
                return jsonify({'ok': True, 'sentCount': 0, 'receivedCount': 0})
            with open(paths.MAIL_CONTACTS_PATH, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            info = stats.get(email, {})
            return jsonify({
                'ok': True,
                'sentCount': info.get('sent', 0),
                'receivedCount': info.get('received', 0),
            })
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)})

    return jsonify({'ok': False, 'error': f'unknown action: {action}'})

# IMAP 서버에 로그인해 선택 가능한 폴더 목록을 반환한다
@app.route("/imap-list-folders", methods=["POST"])
def imap_list_folders():
    data = request.json or {}
    host = (data.get("host") or "").strip()
    user = (data.get("user") or "").strip()
    password = data.get("password") or ""
    use_ssl = data.get("ssl", True)

    try:
        port = int(data.get("port") or 993)
    except (TypeError, ValueError):
        port = 993

    if not host:
        return jsonify({"ok": False, "error": "IMAP 호스트가 비어있습니다."}), 400
    if not user:
        return jsonify({"ok": False, "error": "이메일 주소가 비어있습니다."}), 400
    if not password:
        return jsonify({"ok": False, "error": "앱 비밀번호가 비어있습니다."}), 400

    conn = None
    try:
        conn = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
        conn.login(user, password)

        status, list_data = conn.list()
        if status != "OK":
            return jsonify({"ok": False, "error": "폴더 목록을 가져오지 못했습니다."}), 400

        folders = []
        for line in list_data or []:
            if not line:
                continue
            name = _imap_parse_list_line(line)
            if name and name not in folders:
                folders.append(name)

        return jsonify({"ok": True, "folders": folders})

    except imaplib.IMAP4.error as e:
        return jsonify({"ok": False, "error": f"IMAP 로그인/연결 오류: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"폴더 조회 중 오류: {e}"}), 500
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass

# IMAP 메일 수집을 백그라운드 잡으로 시작한다 (수집 후 내부적으로 /upload 호출해 인덱싱)
@app.route("/imap-collect", methods=["POST"])
def imap_collect():
    data = request.json or {}
    host = (data.get("host") or "").strip()
    user = (data.get("user") or "").strip()
    password = data.get("password") or ""
    folders = data.get("folders") or []
    use_ssl = data.get("ssl", True)
    sync_mode = data.get("sync_mode") or "append"
    user_id = (data.get("user_id") or user or "").strip().lower()

    try:
        port = int(data.get("port") or 993)
    except (TypeError, ValueError):
        port = 993

    limit_raw = data.get("limit")
    try:
        limit = int(limit_raw) if limit_raw not in (None, "") else 100
    except (TypeError, ValueError):
        limit = 100

    if not host:
        return jsonify({"ok": False, "error": "IMAP 호스트가 비어있습니다."}), 400
    if not user:
        return jsonify({"ok": False, "error": "이메일 주소가 비어있습니다."}), 400
    if not password:
        return jsonify({"ok": False, "error": "앱 비밀번호가 비어있습니다."}), 400
    if not folders:
        return jsonify({"ok": False, "error": "수집할 폴더가 비어있습니다."}), 400
    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    job_id = str(uuid.uuid4())[:8]
    create_job(job_id, job_type="imap_collect")

    # 백그라운드에서 IMAP 수집 후 /upload로 인덱싱까지 위임하고 job 상태를 갱신한다
    def _worker():
        print(f"[IMAP-COLLECT] host={host}:{port} ssl={use_ssl} user={user} folders={folders} limit={limit} mode={sync_mode}")
        update_job(job_id, status="running", message="IMAP 서버에서 메일 수집 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "IMAP 서버에서 메일 수집 중"})

        # 폴더별 배치 수집 진행 상황을 job/SSE로 알린다
        def _on_batch(folder, batch_num, total_batches, count):
            msg = f"{folder} 배치 {batch_num}/{total_batches} ({count}개)"
            update_job(job_id, message=msg)
            broadcast({"type": "progress", "job_id": job_id, "message": msg})

        fetch_started = time.perf_counter()
        try:
            content, attachments = _imap_fetch_content(
                host, port, use_ssl, user, password, folders, limit, user, on_batch=_on_batch
            )
        except imaplib.IMAP4.error as e:
            update_job(job_id, status="error", message="실패", error=f"IMAP 로그인/연결 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"IMAP 로그인/연결 오류: {e}"})
            return
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"IMAP 수집 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"IMAP 수집 중 오류: {e}"})
            return
        fetch_elapsed = time.perf_counter() - fetch_started
        print(f"[IMAP-COLLECT] 수집 완료: {fetch_elapsed:.2f}초 소요")

        if not content.strip():
            result = {"ok": True, "added_count": 0, "skipped_count": 0, "message": "수집된 메일이 없습니다."}
            update_job(job_id, status="done", message="완료", result=result)
            broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": result})
            return

        filename = f"imap_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
        update_job(job_id, message="수집한 메일 저장/인덱싱 준비 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "수집한 메일 저장/인덱싱 준비 중"})
        mail_platform = _detect_imap_platform(host)

        try:
            with app.test_request_context(
                "/upload", method="POST",
                json={
                    "filename": filename,
                    "content": content,
                    "attachment": attachments,
                    "syncmode": sync_mode,
                    "user_id": user_id,
                    "mail_platform": mail_platform,
                },
                content_type="application/json",
            ):
                result = upload()
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"업로드 처리 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"업로드 처리 중 오류: {e}"})
            return

        body, status_code = result if isinstance(result, tuple) else (result, 200)
        try:
            body_data = body.get_json()
        except Exception:
            body_data = None

        if status_code >= 400 or not body_data:
            error_msg = (body_data or {}).get("error", "업로드 처리 실패")
            update_job(job_id, status="error", message="실패", error=error_msg)
            broadcast({"type": "failed", "job_id": job_id, "message": error_msg})
            return

        update_job(job_id, status="done", message="완료", result=body_data)
        broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": body_data})

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "jobId": job_id})

# IMAP 수집 잡의 상태·메시지·결과·에러를 반환한다
@app.route('/imap-collect-status/<job_id>', methods=['GET'])
def imap_collect_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404

    return jsonify({
        "status": job["status"],
        "message": job.get("message", ""),
        "result": job.get("result"),
        "error": job.get("error"),
    })

# 카카오톡 대화 내보내기(.txt)를 파싱해 messenger 도메인으로 업로드/인덱싱하는 백그라운드 잡을 시작한다
@app.route("/message-upload", methods=["POST"])
def message_upload():
    data = request.json or {}
    raw_text = data.get("content") or ""
    room_name_input = (data.get("room_name") or "").strip()
    sync_mode = data.get("sync_mode") or "append"
    filename_hint = (data.get("filename") or "").strip()

    if not raw_text.strip():
        return jsonify({"ok": False, "error": "대화 내용이 비어있습니다."}), 400

    room_name = room_name_input or guess_room_name(raw_text, filename_hint or "카카오톡 대화")
    room_id = build_room_id(room_name)

    # 인덱싱이 끝나기 전에 account.json에 미리 저장
    try:
        set_account_room_name(UserPaths(BASE_DIR, room_id, "messenger"), room_name)
    except Exception as e:
        print(f"[WARN] set_account_room_name 실패(치명적이지 않음): {e}")

    job_id = str(uuid.uuid4())[:8]
    create_job(job_id, job_type="message_upload")

    # 백그라운드에서 대화를 파싱해 블록으로 만들고 /upload로 인덱싱까지 위임한다
    def _worker():
        update_job(job_id, status="running", message="카카오톡 대화 파싱 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "카카오톡 대화 파싱 중"})

        try:
            messages = parse_message_export(raw_text)
            blocks = build_message_blocks(messages, room_name)
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"파싱 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"파싱 중 오류: {e}"})
            return

        if not blocks:
            result = {"ok": True, "added_count": 0, "skipped_count": 0, "message": "파싱된 대화가 없습니다.", "room_id": room_id}
            update_job(job_id, status="done", message="완료", result=result)
            broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": result})
            return

        content = "\n\n".join(blocks).strip() + "\n"
        filename = f"message_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"

        update_job(job_id, message="파싱한 대화 저장/인덱싱 준비 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "파싱한 대화 저장/인덱싱 준비 중"})

        try:
            with app.test_request_context(
                "/upload", method="POST",
                json={
                    "filename": filename,
                    "content": content,
                    "attachment": [],
                    "syncmode": sync_mode,
                    "user_id": room_id,
                    "mail_platform": "message",
                    "domain": "messenger",
                },
                content_type="application/json",
            ):
                result = upload()
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"업로드 처리 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"업로드 처리 중 오류: {e}"})
            return

        body, status_code = result if isinstance(result, tuple) else (result, 200)
        try:
            body_data = body.get_json()
        except Exception:
            body_data = None

        if status_code >= 400 or not body_data:
            error_msg = (body_data or {}).get("error", "업로드 처리 실패")
            update_job(job_id, status="error", message="실패", error=error_msg)
            broadcast({"type": "failed", "job_id": job_id, "message": error_msg})
            return

        body_data["room_id"] = room_id
        body_data["room_name"] = room_name
        update_job(job_id, status="done", message="완료", result=body_data)
        broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": body_data})

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "jobId": job_id, "room_id": room_id, "room_name": room_name})

# 메신저 업로드 잡의 상태·메시지·결과·에러를 반환한다
@app.route('/message-upload-status/<job_id>', methods=['GET'])
def message_upload_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404

    return jsonify({
        "status": job["status"],
        "message": job.get("message", ""),
        "result": job.get("result"),
        "error": job.get("error"),
    })

# 해당 도메인의 계정(또는 대화방) 목록을 반환한다
@app.route("/accounts", methods=["GET"])
def accounts_route():
    domain = (request.args.get("domain") or "mail").strip().lower()
    return jsonify({"accounts": list_accounts(BASE_DIR, domain)})

# IMAP 계정 연결 시작 페이지(imap-start.html)를 서빙한다
@app.route('/imap-start')
def imap_start():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), 'web', 'production'),
        'imap-start.html'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)