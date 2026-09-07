# src/util/jobs/job_run_lightrag.py

# LightRAG 인덱싱/업데이트 전체 파이프라인을 실행하는 잡 모듈. 
# mail_latest.txt/csv를 읽어 첨부 요약 병합, LightRAG 라이브러리로 실제 인덱싱(ainsert), 그래프 시각화 JSON 생성, 메일 통계·DB 저장까지 순서대로 실행하고 진행률을 job 로그와 SSE로 보고한다. 
# GraphRAG CLI를 subprocess로 띄우는 대신 LightRAG 라이브러리를 코드에서 직접 호출하는 방식으로 동작한다.
# 그래프 시각화 JSON은 GraphRAG의 entities/relationships parquet 스키마를 전제로 만들어져 있어 LightRAG 결과에 그대로 못 쓰므로, build_graph_json은 LightRAG 전용 변환기를 따로 쓴다.

# Runs the full LightRAG indexing/update pipeline as a background job. 
# Reads mail_latest.txt/csv, merges summarized attachments, indexes the mail via the LightRAG library (ainsert), builds the graph visualization JSON, and saves mail statistics/DB records, reporting progress through job logs and SSE. 
# Calls the LightRAG library directly instead of spawning the GraphRAG CLI as a subprocess. 
# Uses a LightRAG-specific converter for the graph JSON since GraphRAG's version assumes GraphRAG's own entities/relationships parquet schema.

import os
import sys
import re
import time
import threading
import traceback
import asyncio        # rag.ainsert()가 코루틴이라 동기 함수 안에서 돌리기 위해 필요
from functools import partial
import openai
import pandas as pd    # mail_latest.csv(id, text) 읽어서 인덱싱 입력으로 변환하는 데 사용

from config.settings import MAIL_BLOCK_SEP, BASE_DIR

# LightRAG는 pip 패키지가 아니라, 개발자가 프로젝트 루트(MailGrapher/) 밑에 직접
# 클론해서 쓰는 오픈소스 전제로 간다 (MailGrapher/LightRAG/lightrag/ 가 실제 패키지 폴더).
# pip install 없이도 import가 되도록 그 경로를 sys.path에 추가해준다.
sys.path.insert(0, os.path.join(BASE_DIR, "LightRAG"))
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc
from lightrag.llm.openai import openai_complete_if_cache, openai_embed

# 인덱싱/쿼리에 쓰는 모델 이름은 .env에서 읽는다 (하드코딩 금지).
#   RAG_CHAT_MODEL      : LightRAG가 엔티티 추출·답변 생성에 쓰는 채팅 모델
#   RAG_EMBEDDING_MODEL : LightRAG가 벡터 검색에 쓰는 임베딩 모델
_RAG_CHAT_MODEL = os.environ.get("RAG_CHAT_MODEL", "gpt-4o-mini")
_RAG_EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "text-embedding-3-small")

# 임베딩 모델별 실제 벡터 차원 수. RAG_EMBEDDING_MODEL을 바꾸면 이 표도 같이 맞춰야
# 벡터DB 차원이 안 어긋난다 (LightRAG는 embedding_dim을 미리 알아야 해서 자동 감지 안 됨).
_EMBEDDING_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "BAAI/bge-m3": 1024,
}

from util.jobs.job_store import update_job, append_job_log, get_job
from util.sse_broadcaster import broadcast
from util.lightrag_backend.lightrag_progress import get_stage_progress
from util.extract_statics import start_timer,end_timer,format_elapsed_time
from util.lightrag_backend.lightrag_extract_statics import _extract_statics_pipeline_lightrag
from util.database.db_writer import create_mail_account,save_person_stats_to_db,save_keyword_stats_to_db, collect_indexing_stats, update_mail_account_indexing_stats, save_graph_stats_to_db
from util.lightrag_backend.lightrag_db_writer import save_mail_folder_to_db_lightrag, save_mail_to_db_lightrag
from util.lightrag_backend.lightrag_mail_summary import generate_mail_summaries_lightrag

sys.path.insert(0, os.path.join(BASE_DIR, "parquet_template", "src"))
from renderer import render_all_prompts

# (함수, 인자) 목록을 각각 스레드로 병렬 실행하고 모두 끝날 때까지 기다린다 (에러가 나면 첫 에러를 재발생)
def _run_and_join(jobs):
    errors = []
    # 함수를 실행하고 예외를 errors 리스트에 모은다
    def _wrap(fn, args):
        try:
            fn(*args)
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=_wrap, args=(fn, args)) for fn, args in jobs]
    for t in threads: t.start()
    for t in threads: t.join()
    if errors:
        raise errors[0]


# job_store의 메모리 로그를 LIGHTRAG_LOGS_DIR 밑에 파일로 떠서 남긴다
def _write_lightrag_job_log(paths, job_id, label):
    try:
        os.makedirs(paths.LIGHTRAG_LOGS_DIR, exist_ok=True)
        job = get_job(job_id) or {}
        lines = job.get("logs", [])
        log_path = os.path.join(paths.LIGHTRAG_LOGS_DIR, f"{label}_{job_id}.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[JOB][lightrag] 로그 파일 저장 실패(무시): {e}")


# working_dir의 문서 상태 JSON을 3초마다 감시해 문서 처리 비율을 job 진행도/SSE로 반영한다 (stop_event 세트 시 종료)
def _watch_lightrag_progress(job_id, working_dir, start_time, stop_event, base_progress=30):
    current = base_progress
    while not stop_event.wait(3):
        stages = get_stage_progress(working_dir, start_time, reported_progress=current)
        for prog, msg in stages:
            current = prog
            update_job(job_id, progress=prog, message=msg)
            broadcast({"type": "progress", "job_id": job_id, "progress": prog, "message": msg})

# 첨부파일 텍스트를 LLM으로 요약해 반환한다 (짧으면 원문 그대로, 실패해도 원문 반환)
def _summarize_attachment_text(text: str, paths, filename: str) -> str:
    pure_len = len(text.replace(" ", "").replace("\n", ""))
    if pure_len < 500:
        return text  # 짧은 텍스트는 요약 없이 그대로 반환

    prompt_path = os.path.join("parquet_template", "rendered", paths.DOMAIN, "prompts", "summarize_attachment.txt")

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read().strip()

    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,  # 지정 시 로컬 Qwen으로 라우팅
    )
    try:
        response = client.chat.completions.create(
            model=os.environ.get("SUB_TASK_CHAT_MODEL", "gpt-4o-mini"),  # 첨부파일 요약 = 보조 작업
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"파일명: {filename}\n\n{text}"}
            ],
            max_completion_tokens=150  # 한글 약 300자 기준. RAG_CHAT_MODEL/SUB_TASK_CHAT_MODEL이
            # gpt-5 계열처럼 max_tokens 대신 max_completion_tokens만 받는 모델일 수 있어서 이걸 씀
            # (gpt-4o-mini 등 구형 모델도 max_completion_tokens를 그대로 받아준다).
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[summarize_attachment error] {filename}: {e}")
        return text  # 실패하면 원문 그대로 반환

# 요약된 첨부 텍스트를 mail_latest.txt의 각 메일 블록 끝에 삽입해 파일을 다시 쓴다
def _merge_summarized_attachments(mail_latest_path: str, attachment_texts_by_mail: dict):
    if not os.path.exists(mail_latest_path):
        return

    with open(mail_latest_path, "r", encoding="utf-8") as f:
        content = f.read()

    parts = content.split(MAIL_BLOCK_SEP)
    merged_blocks = []

    for part in parts:
        block = part.strip()
        if not block:
            continue

        # 구분선 복원
        block_text = f"{MAIL_BLOCK_SEP}\n{block}\n{MAIL_BLOCK_SEP}"

        # _extract_mail_id_from_block()과 같은 패턴으로 두 형식 다 받음.
        m = re.search(r"^\s*(?:\[ID\]|ID:)\s*(.+?)\s*$", block_text, re.MULTILINE)
        mail_id = m.group(1).strip() if m else None

        # 해당 메일 ID에 첨부 내용이 없으면 그대로 추가
        if not mail_id or mail_id not in attachment_texts_by_mail:
            merged_blocks.append(block_text)
            continue

        # 첨부 내용 섹션 생성
        attachment_section = "\n[첨부 추출 내용]\n"
        for item in attachment_texts_by_mail[mail_id]:
            attachment_section += f"[File name] {item['name']}\n{item['text']}\n"

        # 블록 하단(마지막 구분선 직전)에 첨부 내용 삽입
        insert_pos = block_text.rfind(MAIL_BLOCK_SEP)
        if insert_pos == -1:
            merged_blocks.append(block_text + attachment_section)
        else:
            merged_blocks.append(
                block_text[:insert_pos].rstrip() + "\n\n" +
                attachment_section.rstrip() + "\n" +
                MAIL_BLOCK_SEP
            )

    # 병합 결과를 mail_latest.txt에 덮어씀
    with open(mail_latest_path, "w", encoding="utf-8") as f:
        f.write("\n".join(merged_blocks) + "\n")


# LightRAG의 graphml을 그래프 시각화용 JSON으로 변환한다 (실패해도 파이프라인은 계속 진행)
def build_graph_json(job_id, paths, env):
    from util.lightrag_backend.lightrag_graph_json import build_lightrag_graph_json

    try:
        result = build_lightrag_graph_json(paths)
        node_count = len(result.get("nodes", []))
        edge_count = len(result.get("edges", []))
        msg = f"그래프 JSON 변환 완료 (노드 {node_count}, 엣지 {edge_count})"
        print(f"[JOB][lightrag2json] {msg}")
        append_job_log(job_id, f"[INFO] {msg}")
        update_job(job_id, progress=15, message=msg)
    except Exception as e:
        # 그래프 시각화는 부가 기능이라, 여기서 실패해도 인덱싱 파이프라인 전체를 죽이지 않는다
        # (/graph-data는 json이 없으면 빈 nodes/edges를 반환하도록 이미 처리돼 있음).
        msg = f"그래프 JSON 변환 실패 (무시하고 계속 진행): {e}"
        print(f"[JOB][lightrag2json][ERROR] {msg}")
        append_job_log(job_id, f"[ERROR] {msg}")
        update_job(job_id, progress=15, message="그래프 JSON 변환 실패 (건너뜀)")


# mail_latest.txt(와 대응 CSV)를 최신 max_mails개 메일 블록만 남기고 잘라낸다
def _trim_mail_latest(paths, max_mails, job_id):
    if not os.path.exists(paths.MAIL_LATEST_PATH):
        return
    with open(paths.MAIL_LATEST_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    blocks = [p.strip() for p in content.split(MAIL_BLOCK_SEP) if p.strip()]
    if len(blocks) <= max_mails:
        return
    trimmed = blocks[:max_mails]
    result = '\n'.join(
        f"{MAIL_BLOCK_SEP}\n{b}\n{MAIL_BLOCK_SEP}" for b in trimmed
    ) + '\n'
    with open(paths.MAIL_LATEST_PATH, 'w', encoding='utf-8') as f:
        f.write(result)

    # CSV도 트리밍 (_load_mail_rows_for_indexing()이 이 csv를 읽어 LightRAG에 넘김)
    trimmed_ids = set()
    for block in trimmed:
        m = re.search(r'^\s*ID:\s*(.+?)\s*$', block, re.MULTILINE)
        if m:
            trimmed_ids.add(m.group(1).strip())
    csv_path = paths.MAIL_LATEST_PATH.replace('.txt', '.csv')
    if os.path.exists(csv_path) and trimmed_ids:
        df = pd.read_csv(csv_path)
        id_col = next((c for c in df.columns if 'id' in c.lower()), None)
        if id_col:
            df = df[df[id_col].astype(str).isin(trimmed_ids)]
            df.to_csv(csv_path, index=False)

    msg = f"[max_mails] {len(blocks)}개 중 {max_mails}개만 인덱싱"
    print(f"[JOB][lightrag] {msg}")
    append_job_log(job_id, f"[INFO] {msg}")


# mail_latest.csv(id, text)를 읽어 LightRAG.ainsert()에 넘길 (텍스트 리스트, id 리스트)로 반환한다
def _load_mail_rows_for_indexing(paths) -> tuple[list[str], list[str]]:
    csv_path = paths.MAIL_LATEST_PATH.replace(".txt", ".csv")  # 기존 _trim_mail_latest()와 동일한 규칙(txt -> csv)
    if not os.path.exists(csv_path):
        print(f"[JOB][lightrag] mail csv 없음: {csv_path}")
        return [], []

    df = pd.read_csv(csv_path)
    ids = df["id"].astype(str).tolist()
    texts = df["text"].astype(str).tolist()
    return texts, ids


# LLM/임베딩 함수를 바인딩한 LightRAG 인스턴스를 만들어 texts/ids를 실제로 인덱싱(ainsert)한다
async def _lightrag_ainsert(paths, texts: list[str], ids: list[str]):
    api_key = os.environ.get("LLM_API_KEY")

    # RAG_CHAT_MODEL을 바인딩한 채팅 함수. openai_complete_if_cache(model, prompt, ...) 형태라
    # model 자리만 partial로 고정하면 LightRAG가 기대하는 (prompt, system_prompt=...) 시그니처가 된다.
    llm_model_func = partial(
        openai_complete_if_cache,
        _RAG_CHAT_MODEL,
        api_key=api_key,
        base_url=os.environ.get("RAG_CHAT_API_BASE") or None,  # 지정 시 로컬 vLLM(라마)으로 라우팅
    )

    # RAG_EMBEDDING_MODEL을 바인딩한 임베딩 함수. openai_embed는 이미 EmbeddingFunc로
    # 감싸져 있어서(embedding_dim=1536 고정) model만 바꿔치기하면 안 되고, .func(원본 함수)만
    # 꺼내 새 EmbeddingFunc로 다시 감싸야 한다 — 이때 embedding_dim도 모델에 맞게 같이 바꿔줌.
    embedding_func = EmbeddingFunc(
        embedding_dim=_EMBEDDING_DIMS.get(_RAG_EMBEDDING_MODEL, 1536),
        func=partial(
            openai_embed.func,
            model=_RAG_EMBEDDING_MODEL,
            api_key=api_key,
            base_url=os.environ.get("INDEXING_EMBEDDING_API_BASE") or None,  # 로컬 bge-m3로 라우팅
        ),
    )

    rag = LightRAG(
        working_dir=paths.LIGHTRAG_OUTPUT_DIR,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )

    # LightRAG는 생성만으로 저장소가 준비되지 않는다 — 반드시 명시적으로 초기화해야 함
    await rag.initialize_storages()
    try:
        await rag.ainsert(input=texts, ids=ids)
    finally:
        await rag.finalize_storages()  # 저장소(파일 핸들 등) 정리


# mail_latest.csv를 읽어 LightRAG로 인덱싱하고 진행률을 감시한다 (동기 함수, 내부에서 asyncio.run 사용)
def build_lightrag_index(job_id, paths, env, max_mails=None):
    print(f"[JOB][lightrag] START job_id={job_id}")
    print(f"[JOB][lightrag] cwd={os.getcwd()}")
    print(f"[JOB][lightrag] LIGHTRAG_OUTPUT_DIR={paths.LIGHTRAG_OUTPUT_DIR}")
    print(f"[JOB][lightrag] root_exists={os.path.exists(paths.LIGHTRAG_OUTPUT_DIR)}")

    update_job(job_id, progress=20, message="인덱싱 시작 (LightRAG)")
    append_job_log(job_id, "[START] build_lightrag_index")
    append_job_log(job_id, f"[INFO] cwd={os.getcwd()}")
    append_job_log(job_id, f"[INFO] LIGHTRAG_OUTPUT_DIR={paths.LIGHTRAG_OUTPUT_DIR}")
    append_job_log(job_id, f"[INFO] root_exists={os.path.exists(paths.LIGHTRAG_OUTPUT_DIR)}")

    render_all_prompts()  # 첨부파일 요약 프롬프트(summarize_attachment.txt) 렌더링을 위해 필요

    if max_mails is not None:
        _trim_mail_latest(paths, max_mails, job_id)

    # [LightRAG] mail_latest.csv에서 인덱싱할 (텍스트, id) 목록을 읽어온다.
    # 이 전처리(메일 텍스트 -> CSV) 자체는 어떤 인덱싱 엔진을 쓰든 동일한 단계다.
    texts, ids = _load_mail_rows_for_indexing(paths)
    print(f"[JOB][lightrag] 인덱싱 대상 메일 수={len(texts)}")
    append_job_log(job_id, f"[INFO] 인덱싱 대상 메일 수={len(texts)}")

    # util/lightrag_backend/lightrag_progress.py가 kv_store_doc_status.json을 3초 간격으로
    # 폴링해서 텍스트유닛→엔티티→관계 추출이 진행되는 동안에도(30~90% 구간) 문서 처리
    # 비율을 보여준다. 이 파일이 LIGHTRAG_OUTPUT_DIR 밑에 생기므로 감시 대상도 LIGHTRAG_OUTPUT_DIR.
    start_time = time.time()
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=_watch_lightrag_progress,
        args=(job_id, paths.LIGHTRAG_OUTPUT_DIR, start_time, stop_event, 30),
        daemon=True,
    )
    watcher.start()

    try:
        update_job(job_id, progress=30, message="LightRAG 인덱싱 실행 중")

        # build_lightrag_index() 자체는 동기 함수(스레드로 백그라운드 실행됨)라서
        # 코루틴인 _lightrag_ainsert()를 asyncio.run()으로 직접 돌린다.
        asyncio.run(_lightrag_ainsert(paths, texts, ids))

        append_job_log(job_id, "[END] build_lightrag_index success")
        update_job(job_id, progress=90, message="LightRAG 인덱싱 완료")
        print(f"[JOB][lightrag] SUCCESS job_id={job_id}")

    except Exception as e:
        print(f"[JOB][lightrag][ERROR] job_id={job_id} error={e}")
        traceback.print_exc()
        append_job_log(job_id, f"[ERROR] build_lightrag_index failed: {e}")
        raise

    finally:
        stop_event.set()
        watcher.join(timeout=5)
        _write_lightrag_job_log(paths, job_id, "index")


# mail_latest.csv 전체를 다시 LightRAG로 넣어 증분 업데이트한다 (ainsert가 upsert라 기존 id는 자동 스킵)
def build_lightrag_update(job_id, paths, env):
    print(f"[JOB][lightrag-update] START job_id={job_id}")
    print(f"[JOB][lightrag-update] LIGHTRAG_OUTPUT_DIR={paths.LIGHTRAG_OUTPUT_DIR}")
    print(f"[JOB][lightrag-update] root_exists={os.path.exists(paths.LIGHTRAG_OUTPUT_DIR)}")

    update_job(job_id, progress=20, message="업데이트 시작 (LightRAG)")
    append_job_log(job_id, "[START] build_lightrag_update")
    append_job_log(job_id, f"[INFO] LIGHTRAG_OUTPUT_DIR={paths.LIGHTRAG_OUTPUT_DIR}")
    append_job_log(job_id, f"[INFO] root_exists={os.path.exists(paths.LIGHTRAG_OUTPUT_DIR)}")

    render_all_prompts()  # 첨부파일 요약 프롬프트(summarize_attachment.txt) 렌더링을 위해 필요

    # mail_latest.csv 전체를 다시 넘긴다 (index와 동일한 소스). 이미 인덱싱된 id는
    # LightRAG가 내부적으로 알아서 스킵하므로, "새로 추가된 것만 골라 넘기는" 별도 로직이 필요 없다.
    texts, ids = _load_mail_rows_for_indexing(paths)
    print(f"[JOB][lightrag-update] 대상 메일 수={len(texts)}")
    append_job_log(job_id, f"[INFO] 대상 메일 수={len(texts)}")

    start_time = time.time()
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=_watch_lightrag_progress,
        args=(job_id, paths.LIGHTRAG_OUTPUT_DIR, start_time, stop_event, 30),
        daemon=True,
    )
    watcher.start()

    try:
        update_job(job_id, progress=30, message="LightRAG 업데이트 실행 중")

        asyncio.run(_lightrag_ainsert(paths, texts, ids))

        append_job_log(job_id, "[END] build_lightrag_update success")
        update_job(job_id, progress=90, message="LightRAG 업데이트 완료")
        print(f"[JOB][lightrag-update] SUCCESS job_id={job_id}")

    except Exception as e:
        print(f"[JOB][lightrag-update][ERROR] job_id={job_id} error={e}")
        traceback.print_exc()
        append_job_log(job_id, f"[ERROR] build_lightrag_update failed: {e}")
        raise

    finally:
        stop_event.set()
        _write_lightrag_job_log(paths, job_id, "update")
        watcher.join(timeout=5)


# 첨부 요약 → LightRAG 인덱싱 → 그래프 JSON → 통계/DB 저장까지 전체 인덱싱 파이프라인을 실행한다
def run_graph_pipeline(job_id, paths, env, attachment_texts_by_mail=None, added_count=0, max_mails=None, mail_platform="gmail"):
    print(f"[JOB][pipeline] START job_id={job_id}")
    append_job_log(job_id, "[START] run_graph_pipeline")

    # 프롬프트의 최신 상태 유지
    render_all_prompts()

    try:
        update_job(job_id, progress=0, status="running", message="작업 시작")

        # 첨부파일 요약 후 mail_latest.txt에 병합 (백그라운드에서 처리)
        if attachment_texts_by_mail:
            print(f"[JOB][summarize] START job_id={job_id}")
            update_job(job_id, progress=5, message="첨부파일 요약 중")

            # 각 첨부파일 텍스트를 요약으로 교체
            summarized_by_mail = {}
            for mail_id, items in attachment_texts_by_mail.items():
                summarized_by_mail[mail_id] = [
                    {
                        "name": item["name"],
                        "text": _summarize_attachment_text(item["text"], paths, item["name"])
                    }
                    for item in items
                ]

            # 요약된 첨부 내용을 mail_latest.txt 각 블록에 삽입
            _merge_summarized_attachments(paths.MAIL_LATEST_PATH, summarized_by_mail)
            print(f"[JOB][summarize] DONE job_id={job_id}")

        timer = start_timer() #인덱싱 시간 측정용, 측정 시작
        build_lightrag_index(job_id, paths, env, max_mails=max_mails)
        time_result = end_timer(timer) #인덱싱 시간 측정용, 측정 끝

        build_graph_json(job_id,paths, env)

        formatted_time = format_elapsed_time(time_result["elapsed_sec"])

        _extract_statics_pipeline_lightrag(paths, mode='rewrite')
        target_update_date = time_result["ended_at"]

        create_mail_account(
                user_mail_account_id=paths.USER_ID,
                ended_at=target_update_date,
                index_time=formatted_time,
                mail_count=added_count,
                mail_platform=mail_platform,
            )
        indexing_stats = collect_indexing_stats(paths)
        update_mail_account_indexing_stats(paths.USER_ID, None, indexing_stats)
        save_graph_stats_to_db(paths, target_update_date)

        # mail.mail_folder_name은 mail_folder에 대한 FK이므로, mail INSERT 전에
        # mail_folder row가 먼저 존재해야 함 (동시 스레드로 돌리면 FK 위반 위험)
        save_mail_folder_to_db_lightrag(paths, target_update_date)

        # mail_keyword는 person에 대한 FK이므로, person 저장이 끝난 뒤에 키워드를 넣어야
        # valid_persons 조회가 비어서 키워드가 통째로 스킵되는 문제(FK 대상 없음)가 안 생김
        save_person_stats_to_db(paths, target_update_date)

        _run_and_join([
            (save_mail_to_db_lightrag, (paths, target_update_date)),
            (save_keyword_stats_to_db, (paths, target_update_date)),
            (generate_mail_summaries_lightrag, (paths,)),
        ])


        update_job(job_id, progress=100, status="done", message="인덱싱 완료")
        broadcast({"type": "done", "job_id": job_id, "message": "인덱싱 완료"})
        append_job_log(job_id, "[END] run_graph_pipeline success")
        print(f"[JOB][pipeline] SUCCESS job_id={job_id}")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        update_job(job_id, status="failed", message=error_msg)
        broadcast({"type": "failed", "job_id": job_id, "message": error_msg})
        append_job_log(job_id, f"[ERROR] run_graph_pipeline failed: {error_msg}")
        print(f"[JOB][pipeline][ERROR] job_id={job_id} error={error_msg}")
        traceback.print_exc()


# LightRAG 증분 업데이트 → 그래프 JSON → 통계/DB 저장까지 전체 업데이트 파이프라인을 실행한다
def run_graph_update_pipeline(job_id, paths, env):
    print(f"[JOB][update-pipeline] START job_id={job_id}")
    append_job_log(job_id, "[START] run_graph_update_pipeline")

    try:
        update_job(job_id, progress=0, status="running", message="업데이트 작업 시작")

        # 1단계: LightRAG 업데이트
        build_lightrag_update(job_id, paths, env)

        # 2단계: json 생성
        build_graph_json(job_id,paths, env)

        _extract_statics_pipeline_lightrag(paths, mode='append')
        indexing_stats = collect_indexing_stats(paths)
        update_mail_account_indexing_stats(paths.USER_ID, None, indexing_stats)
        save_graph_stats_to_db(paths)

        # mail.mail_folder_name은 mail_folder에 대한 FK이므로, mail INSERT 전에
        # 새로 추가된 폴더가 먼저 존재해야 함
        save_mail_folder_to_db_lightrag(paths)

        # mail_keyword는 person에 대한 FK이므로, person 저장이 끝난 뒤에 키워드를 넣어야 함
        save_person_stats_to_db(paths)

        _run_and_join([
            (save_mail_to_db_lightrag, (paths,)),
            (save_keyword_stats_to_db, (paths,)),
        ])

        update_job(job_id, progress=100, status="done", message="업데이트 완료")
        broadcast({"type": "done", "job_id": job_id, "message": "업데이트 완료"})
        append_job_log(job_id, "[END] run_graph_update_pipeline success")
        print(f"[JOB][update-pipeline] SUCCESS job_id={job_id}")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        update_job(job_id, status="failed", message=error_msg, error=error_msg)
        broadcast({"type": "failed", "job_id": job_id, "message": error_msg})
        append_job_log(job_id, f"[ERROR] run_graph_update_pipeline failed: {error_msg}")
        print(f"[JOB][update-pipeline][ERROR] job_id={job_id} error={error_msg}")
        traceback.print_exc()


# 인덱싱 파이프라인을 데몬 스레드로 백그라운드 실행하고 스레드 객체를 반환한다
def start_graph_pipeline_background(job_id, paths, env, attachment_texts_by_mail=None, added_count=0, max_mails=None,  mail_platform="gmail"):
    print(f"[JOB][pipeline] BACKGROUND START job_id={job_id}")
    append_job_log(job_id, "[INFO] background thread starting")

    # 새로운 스레드 생성
    t = threading.Thread(
        target=run_graph_pipeline,  # 실행할 함수: LightRAG 파이프라인 (인덱싱) 실행 함수
        args=(job_id, paths, env.copy(), attachment_texts_by_mail, added_count, max_mails, mail_platform),
        daemon=True,                # app.py 종료 시 같이 종료
    )
    t.start()  # 스레드 실행 (비동기 시작)

    print(f"[JOB][pipeline] BACKGROUND THREAD STARTED job_id={job_id} thread={t.name}")
    append_job_log(job_id, f"[INFO] background thread started name={t.name}")
    return t


# 업데이트 파이프라인을 데몬 스레드로 백그라운드 실행하고 스레드 객체를 반환한다
def start_graph_update_pipeline_background(job_id,paths, env):
    print(f"[JOB][update-pipeline] BACKGROUND START job_id={job_id}")
    append_job_log(job_id, "[INFO] update background thread starting")

    t = threading.Thread(
        target=run_graph_update_pipeline, # 실행할 함수 : LightRAG 업데이트 파이프라인 실행 함수
        args=(job_id,paths, env.copy()),
        daemon=True,                      # app.py 종료 시 같이 종료

    )
    t.start()  # 스레드 실행 (비동기 시작)

    print(f"[JOB][update-pipeline] BACKGROUND THREAD STARTED job_id={job_id} thread={t.name}")
    append_job_log(job_id, f"[INFO] update background thread started name={t.name}")
    return t