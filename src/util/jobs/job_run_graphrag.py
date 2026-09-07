# 메일·카카오톡 원본을 정제한 뒤 GraphRAG 인덱싱을 실행하고, parquet 후처리·그래프 JSON 변환·DB 통계·요약·아바타 생성까지 하나의 백그라운드 잡으로 묶어 돌리는 GraphRAG 인덱싱 파이프라인 진입점.

# Entry point of the GraphRAG indexing pipeline: cleans raw mail/KakaoTalk data, runs GraphRAG indexing, then chains parquet post-processing, graph-JSON conversion, DB stats, summaries, and avatar generation into a single background job.

import time
import os
import sys
import re
import subprocess
import threading
import traceback
import openai
import networkx as nx
from dotenv import load_dotenv

from util.jobs.job_store import update_job, append_job_log
from util.graphrag_progress import get_stage_progress
from util.sse_broadcaster import broadcast
from util.user_path import user_graphrag_init

from config.settings import MAIL_BLOCK_SEP, BASE_DIR
from util.extract_statics import start_timer,end_timer,format_elapsed_time, _extract_statics_pipeline
from util.database.db_writer import create_mail_account,save_person_stats_to_db,save_keyword_stats_to_db, save_mail_folder_to_db, save_mail_to_db, collect_indexing_stats, update_mail_account_indexing_stats, save_graph_stats_to_db
from util.graphrag_mail_summary import generate_mail_summaries

from util.message_statics import _extract_message_statics_pipeline, _parse_message_blocks_from_parquet, count_total_messages
from util.database.chatroom_db_writer import (
    create_chatroom, update_chatroom_indexing_stats, save_chatroom_graph_stats_to_db,
    save_message_block_to_db, save_chatroom_people_to_db, save_message_keyword_to_db,
    save_chatroom_relationships_to_db,
)
from util.message_summary import generate_message_summaries
from util.message_mood import recompute_all_message_moods
from util.avatar_generator import generate_chatroom_people_avatars_batch, generate_all_person_avatars

sys.path.insert(0, os.path.join(BASE_DIR, "parquet_template", "src"))
from renderer import render_all_prompts     # reportMissingImports 발생한다면 무시: sys.path.insert가 런타임에만 반영되는 동적 경로라 정적 분석기가 renderer 모듈을 못 찾아서 뜨는 오탐. 실행 시엔 정상 동작함

load_dotenv("src/parquet/.env")

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

# output 폴더를 3초마다 감시해 인덱싱 단계 변화를 job 진행도/SSE로 반영한다 (stop_event 세트 시 종료)
def _watch_graphrag_output(job_id, output_dir, start_time, stop_event, base_progress=5):
    current = base_progress
    while not stop_event.wait(3):
        stages = get_stage_progress(output_dir, start_time, reported_progress=current)
        for prog, msg in stages:
            current = prog
            update_job(job_id, progress=prog, message=msg)
            broadcast({"type": "progress", "job_id": job_id, "progress": prog, "message": msg})


# SUB_TASK_CHAT_MODEL(Qwen2.5-7B, max_model_len=32768)에 안전하게 들어가도록 첨부파일
# 텍스트 길이를 문자 수 기준으로 제한한다 
MAX_ATTACHMENT_CHARS = 25000

# 첨부파일 텍스트를 LLM으로 요약해 반환한다 (짧으면 원문 그대로, 너무 길면 잘라서 요약)
def _summarize_attachment_text(text: str, paths, filename: str) -> str:
    pure_len = len(text.replace(" ", "").replace("\n", ""))
    if pure_len < 500:
        return text  # 짧은 텍스트는 요약 없이 그대로 반환

    if len(text) > MAX_ATTACHMENT_CHARS:
        print(f"[summarize_attachment] {filename}: {len(text)}자 → {MAX_ATTACHMENT_CHARS}자로 잘라서 요약 (컨텍스트 초과 방지)")
        text = text[:MAX_ATTACHMENT_CHARS]

    prompt_path = os.path.join("parquet_template", "rendered", paths.DOMAIN, "prompts", "summarize_attachment.txt")

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read().strip()

    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,
    )
    try:
        response = client.chat.completions.create(
            model=os.getenv("SUB_TASK_CHAT_MODEL"), 
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"파일명: {filename}\n\n{text}"}
            ],
            max_completion_tokens=150  
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[summarize_attachment error] {filename}: {e}")
        # 실패해도 요약 성공 시 규격(max_completion_tokens=150 ≈ 한글 300자)에 맞춰 반환한다
        return text[:300]

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

        # 블록에서 메일 ID 추출
        m = re.search(r"^\s*\[ID\]\s*(.+?)\s*$", block_text, re.MULTILINE)
        mail_id = m.group(1).strip() if m else None

        # 해당 메일 ID에 첨부 내용이 없으면 그대로 추가
        if not mail_id or mail_id not in attachment_texts_by_mail:
            merged_blocks.append(block_text)
            continue

        # 첨부 내용 섹션 생성
        attachment_section = "\n[첨부파일 추출 내용]\n"
        for i, item in enumerate(attachment_texts_by_mail[mail_id], start=1):
            attachment_section += f"File {i}: {item['name']}\n{item['text']}\n\n"
        attachment_section = attachment_section.rstrip() + "\n"

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


# graphrag_parquet2json.py를 서브프로세스로 실행해 parquet을 그래프 시각화용 JSON으로 변환한다
def build_graph_json(job_id, paths, env):
    print(f"[JOB][mail2json] START job_id={job_id}")
    print(f"[JOB][mail2json] cwd={os.getcwd()}")
    print(f"[JOB][mail2json] sys.executable={sys.executable}")
    print(f"[JOB][mail2json] GRAPH_BUILD_SCRIPT={paths.GRAPH_BUILD_SCRIPT}")
    print(f"[JOB][mail2json] script_exists={os.path.exists(paths.GRAPH_BUILD_SCRIPT)}")

    update_job(job_id, progress=5, message="메일 텍스트를 그래프 데이터 JSON으로 변환 중")
    append_job_log(job_id, "[START] build_graph_json")
    append_job_log(job_id, f"[INFO] cwd={os.getcwd()}")
    append_job_log(job_id, f"[INFO] sys.executable={sys.executable}")
    append_job_log(job_id, f"[INFO] GRAPH_BUILD_SCRIPT={paths.GRAPH_BUILD_SCRIPT}")
    append_job_log(job_id, f"[INFO] script_exists={os.path.exists(paths.GRAPH_BUILD_SCRIPT)}")

    # GraphRAG CLI 실행 명령어 구성
    cmd = [
        sys.executable, "-u", "-X", "utf8",
        paths.GRAPH_BUILD_SCRIPT,
        "--base-dir", paths.BASE_DIR,
        "--user-id", paths.USER_ID,
        "--domain", paths.DOMAIN
        ]
    print(f"[JOB][mail2json] CMD={cmd}")

    append_job_log(job_id, f"[CMD] {cmd}")

    try:
        # 파이썬 스크립트 실행
        subprocess.run(
            cmd,
            check=True,         # 실패 시 exception 발생
            stdout=sys.stdout,  # 출력 → 서버 콘솔로 바로 전달
            stderr=sys.stderr,  # 에러 → 서버 콘솔로 바로 전달
            env=env,            # 환경변수 전달
        )

        append_job_log(job_id, "[END] build_graph_json success")
        update_job(job_id, progress=15, message="그래프 데이터 JSON 생성 완료")
        print(f"[JOB][parquet2json] SUCCESS job_id={job_id}")

    except Exception as e:
        print(f"[JOB][parquet2json][ERROR] job_id={job_id} error={e}")
        traceback.print_exc()
        append_job_log(job_id, f"[ERROR] build_graph_json failed: {e}")
        raise


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

    # CSV 트리밍 (GraphRAG는 csv를 읽음)
    trimmed_ids = set()
    for block in trimmed:
        m = re.search(r'^\s*\[ID\]\s*(.+?)\s*$', block, re.MULTILINE)
        if m:
            trimmed_ids.add(m.group(1).strip())
    csv_path = paths.MAIL_LATEST_PATH.replace('.txt', '.csv')
    if os.path.exists(csv_path) and trimmed_ids:
        import pandas as pd
        df = pd.read_csv(csv_path)
        id_col = next((c for c in df.columns if 'id' in c.lower()), None)
        if id_col:
            df = df[df[id_col].astype(str).isin(trimmed_ids)]
            df.to_csv(csv_path, index=False)

    msg = f"[max_mails] {len(blocks)}개 중 {max_mails}개만 인덱싱"
    print(f"[JOB][graphrag] {msg}")
    append_job_log(job_id, f"[INFO] {msg}")


# 인덱싱 완료 직후 아래 목록과 정확히 일치하는 엔티티/관계를 결과 parquet에서 제거한다.

_FEWSHOT_LEAKAGE_BLOCKLIST = {
    # 이전 예시(Vocarush) — 이미 생성된 그래프에 남아있을 수 있어 계속 걸러냄
    "19D4DA32341500E4", "MINJUN.KIM@VOCARUSH.IO", "SEOYEON.PARK@VOCARUSH.IO",
    "스프린트 계획 수립", "SPRINT_PLAN.PDF",
    # 현재 예시(Nexbloom) — 이름을 실제 데이터와 안 겹치게 새로 지정했지만, 혹시 모를 누출 대비
    "1A2B3C4D5E6F7890", "HAJUN.JUNG@NEXBLOOM.IO", "SOMIN.YOON@NEXBLOOM.IO",
    "NEXBLOOM", "3분기 로드맵 검토", "ROADMAP_Q3.PDF",
}

# "None/NULL/없음/- 같은 값은 엔티티 이름으로 제외한다
_NULL_VALUE_LITERALS = {"NONE", "NULL", "없음", "-"}


_CHATROOM_HEADER_RE_TMPL = r"채팅방\s*:\s*{name}"


# 엔티티 title에서 "채팅방:" 접두사와 "(채팅방)" 접미사를 떼어낸 순수 방 이름을 반환한다
def _strip_chatroom_decorations(title: str) -> str:
    t = str(title).strip()
    if t.startswith("채팅방:"):
        t = t[len("채팅방:"):].strip()
    if t.endswith("(채팅방)"):
        t = t[: -len("(채팅방)")].strip()
    return t


# 근거 청크에 '채팅방: <이름>'으로 등장하지 않는 ChatRoom 엔티티와 그 관계를 parquet에서 제거한다 (messenger 전용)
def _filter_invalid_chatrooms(paths):
    if getattr(paths, "DOMAIN", None) != "messenger":
        return

    import pandas as pd

    output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
    entities_path = os.path.join(output_dir, "entities.parquet")
    relationships_path = os.path.join(output_dir, "relationships.parquet")
    text_units_path = os.path.join(output_dir, "text_units.parquet")

    if not (os.path.exists(entities_path) and os.path.exists(text_units_path)):
        return

    entities = pd.read_parquet(entities_path)
    if "text_unit_ids" not in entities.columns:
        print("[FILTER][WARN] entities.parquet에 text_unit_ids 컬럼이 없어 ChatRoom 검증 스킵")
        return

    text_units = pd.read_parquet(text_units_path)
    text_lookup = dict(zip(text_units["id"], text_units["text"]))

    is_chatroom = entities["type"].astype(str).str.upper() == "CHATROOM"
    chatroom_idx = entities.index[is_chatroom]

    if len(chatroom_idx) <= 1:
        return  # 방 0~1개는 정상 범위, 검증할 필요 없음

    drop_idx = []
    invalid_titles = []
    for idx in chatroom_idx:
        row = entities.loc[idx]
        core_name = _strip_chatroom_decorations(row["title"])
        grounded = False
        if core_name:
            pattern = re.compile(_CHATROOM_HEADER_RE_TMPL.format(name=re.escape(core_name)))
            tu_ids = row.get("text_unit_ids")
            tu_ids = list(tu_ids) if tu_ids is not None else []
            grounded = any(pattern.search(text_lookup.get(tid, "") or "") for tid in tu_ids)
        if not grounded:
            drop_idx.append(idx)
            invalid_titles.append(row["title"])

    if not drop_idx:
        print("[FILTER] ChatRoom 전부 근거 확인됨 (제거 없음)")
        return

    invalid_set = set(invalid_titles)
    entities.drop(index=drop_idx).to_parquet(entities_path, index=False)

    removed_rels = 0
    if os.path.exists(relationships_path):
        rel = pd.read_parquet(relationships_path)
        mask = rel["source"].isin(invalid_set) | rel["target"].isin(invalid_set)
        removed_rels = int(mask.sum())
        if removed_rels:
            rel[~mask].to_parquet(relationships_path, index=False)

    print(f"[FILTER] 근거 없는 ChatRoom 엔티티 제거: {len(drop_idx)}개 -> {sorted(invalid_set)}")
    if removed_rels:
        print(f"[FILTER] 연결된 relationship {removed_rels}개도 함께 제거")


_DATE_HEADER_RE_TMPL = r"\ub0a0\uc9dc\s*:\s*{date}"


def _filter_invalid_dates(paths):
    if getattr(paths, "DOMAIN", None) != "messenger":
        return

    import pandas as pd

    output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
    entities_path = os.path.join(output_dir, "entities.parquet")
    relationships_path = os.path.join(output_dir, "relationships.parquet")
    text_units_path = os.path.join(output_dir, "text_units.parquet")

    if not (os.path.exists(entities_path) and os.path.exists(text_units_path)):
        return

    entities = pd.read_parquet(entities_path)
    if "text_unit_ids" not in entities.columns:
        print("[FILTER][WARN] entities.parquet\uc5d0 text_unit_ids \ucef4\ub7fc\uc774 \uc5c6\uc5b4 Date \uac80\uc99d \uc2a4\ud0b5")
        return

    text_units = pd.read_parquet(text_units_path)
    text_lookup = dict(zip(text_units["id"], text_units["text"]))

    is_date = entities["type"].astype(str).str.upper() == "DATE"
    date_idx = entities.index[is_date]
    if len(date_idx) == 0:
        return

    drop_idx = []
    invalid_titles = []
    for idx in date_idx:
        row = entities.loc[idx]
        title = str(row["title"]).strip()
        grounded = False
        if title:
            pattern = re.compile(_DATE_HEADER_RE_TMPL.format(date=re.escape(title)))
            tu_ids = row.get("text_unit_ids")
            tu_ids = list(tu_ids) if tu_ids is not None else []
            grounded = any(pattern.search(text_lookup.get(tid, "") or "") for tid in tu_ids)
        if not grounded:
            drop_idx.append(idx)
            invalid_titles.append(row["title"])

    if not drop_idx:
        print("[FILTER] Date \uc804\ubd80 \uadfc\uac70 \ud655\uc778\ub428 (\uc81c\uac70 \uc5c6\uc74c)")
        return

    invalid_set = set(invalid_titles)
    entities.drop(index=drop_idx).to_parquet(entities_path, index=False)

    removed_rels = 0
    if os.path.exists(relationships_path):
        rel = pd.read_parquet(relationships_path)
        mask = rel["source"].isin(invalid_set) | rel["target"].isin(invalid_set)
        removed_rels = int(mask.sum())
        if removed_rels:
            rel[~mask].to_parquet(relationships_path, index=False)

    preview = sorted(invalid_set)[:20]
    suffix = "..." if len(invalid_set) > 20 else ""
    print(f"[FILTER] \uadfc\uac70 \uc5c6\ub294 Date \uc5d4\ud2f0\ud2f0 \uc81c\uac70: {len(drop_idx)}\uac1c -> {preview}{suffix}")
    if removed_rels:
        print(f"[FILTER] \uc5f0\uacb0\ub41c relationship {removed_rels}\uac1c\ub3c4 \ud568\uaed8 \uc81c\uac70")


_SENDER_LINE_RE_MESSENGER = re.compile(r"^\d{2}:\d{2}\s+(.+?):\s", re.MULTILINE)
_SENDER_LINE_RE_MAIL = re.compile(r"\[\ubc1c\uc2e0\uc778\][^\n]*?<([^<>\s]+@[^<>\s]+)>")
_RECONNECT_ELIGIBLE_TYPES = {
    "messenger": {"KEYWORD", "NAMEDENTITY", "EVENT", "ATTACHMENT"},
    "mail": {"TOPIC", "ATTACHMENT", "EVENT", "ORGANIZATION"},
}


# 후보 문자열과 일치하는 Person 엔티티 title을 대소문자 무시로 찾아 반환한다 (없으면 None)
def _match_person_title(cand, person_titles):
    if cand in person_titles:
        return cand
    low = cand.lower()
    for pt in person_titles:
        if str(pt).lower() == low:
            return pt
    return None


# 메신저 근거 청크의 "HH:MM 이름:" 줄에서 Person 엔티티와 일치하는 발신자를 찾는다
def _find_sender_messenger(text_lookup, tu_ids, person_titles):
    for tid in tu_ids:
        text = text_lookup.get(tid, "") or ""
        for m in _SENDER_LINE_RE_MESSENGER.finditer(text):
            cand = m.group(1).strip()
            hit = _match_person_title(cand, person_titles)
            if hit:
                return hit
    return None


# 메일 근거 청크(같은 문서의 앞 청크 포함)의 "[발신인] ... <email>"에서 일치하는 Person을 찾는다
def _find_sender_mail(text_units, tu_ids, person_titles, tu_index, tu_doc):
    for tid in tu_ids:
        if tid not in tu_index:
            continue
        own_idx = tu_index[tid]
        doc_id = tu_doc.get(tid)
        same_doc = text_units[text_units["document_id"] == doc_id]
        same_doc = same_doc[same_doc.index <= own_idx].sort_index(ascending=False)
        for _, row in same_doc.iterrows():
            m = _SENDER_LINE_RE_MAIL.search(row["text"] or "")
            if m:
                hit = _match_person_title(m.group(1).strip(), person_titles)
                if hit:
                    return hit
    return None


def _reconnect_isolated_via_person(paths):
    domain = getattr(paths, "DOMAIN", None)
    if domain not in ("messenger", "mail"):
        return

    import pandas as pd

    output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
    entities_path = os.path.join(output_dir, "entities.parquet")
    relationships_path = os.path.join(output_dir, "relationships.parquet")
    text_units_path = os.path.join(output_dir, "text_units.parquet")

    if not (os.path.exists(entities_path) and os.path.exists(relationships_path) and os.path.exists(text_units_path)):
        return

    entities = pd.read_parquet(entities_path)
    relationships = pd.read_parquet(relationships_path)
    text_units = pd.read_parquet(text_units_path)

    if "text_unit_ids" not in entities.columns:
        print("[FILTER][WARN] entities.parquet\uc5d0 text_unit_ids \ucef4\ub7fc\uc774 \uc5c6\uc5b4 \uc7ac\uc5f0\uacb0 \uc2a4\ud0b5")
        return

    text_lookup = dict(zip(text_units["id"], text_units["text"]))
    connected = set(relationships["source"]) | set(relationships["target"])
    person_titles = set(entities.loc[entities["type"].astype(str).str.upper() == "PERSON", "title"])

    eligible_types = _RECONNECT_ELIGIBLE_TYPES.get(domain, set())
    is_eligible = entities["type"].astype(str).str.upper().isin(eligible_types)
    isolated = entities[is_eligible & ~entities["title"].isin(connected)]

    if len(isolated) == 0:
        print("[FILTER] \uc7ac\uc5f0\uacb0\ud560 \uace0\ub9bd \ub178\ub4dc \uc5c6\uc74c")
        return

    tu_index = {}
    tu_doc = {}
    if domain == "mail":
        if "document_id" not in text_units.columns:
            print("[FILTER][WARN] text_units.parquet\uc5d0 document_id \ucef4\ub7fc\uc774 \uc5c6\uc5b4 \uba54\uc77c \uc7ac\uc5f0\uacb0 \uc2a4\ud0b5")
            return
        tu_index = {tid: idx for idx, tid in text_units["id"].items()}
        tu_doc = dict(zip(text_units["id"], text_units["document_id"]))

    new_rows = []
    for _, row in isolated.iterrows():
        title = row["title"]
        tu_ids = row.get("text_unit_ids")
        tu_ids = list(tu_ids) if tu_ids is not None else []

        if domain == "messenger":
            sender = _find_sender_messenger(text_lookup, tu_ids, person_titles)
            desc = f"{title} \uc5b8\uae09/\uacf5\uc720\ub41c \ub300\ud654\uc758 \ucc38\uc5ec\uc790\uc640 \uc790\ub3d9 \uc7ac\uc5f0\uacb0 (\ud5e4\ub354 \uc720\uc2e4 \uccad\ud06c)."
        else:
            sender = _find_sender_mail(text_units, tu_ids, person_titles, tu_index, tu_doc)
            desc = f"{title} \uc5b8\uae09/\uacf5\uc720\ub41c \uba54\uc77c\uc758 \ubc1c\uc2e0\uc790\uc640 \uc790\ub3d9 \uc7ac\uc5f0\uacb0 (\ud5e4\ub354 \uc720\uc2e4 \uccad\ud06c)."

        if sender and sender != title:
            new_rows.append({
                "source": sender,
                "target": title,
                "description": desc,
                "weight": 3.0,
                "text_unit_ids": tu_ids,
            })

    if not new_rows:
        print("[FILTER] \uace0\ub9bd \ub178\ub4dc \uc911 \ubc1c\uc2e0\uc790\ub97c \ucc3e\uc740 \ud56d\ubaa9 \uc5c6\uc74c")
        return

    new_rel_df = pd.DataFrame(new_rows)

    if "human_readable_id" in relationships.columns:
        start_id = int(pd.to_numeric(relationships["human_readable_id"], errors="coerce").max() or 0) + 1
        new_rel_df["human_readable_id"] = range(start_id, start_id + len(new_rel_df))
    if "id" in relationships.columns:
        import hashlib
        new_rel_df["id"] = [
            hashlib.sha256(f"{r.source}|{r.target}|reconnect".encode("utf-8")).hexdigest()
            for r in new_rel_df.itertuples()
        ]
    if "combined_degree" in relationships.columns:
        deg = pd.concat([relationships["source"], relationships["target"]]).value_counts()
        new_rel_df["combined_degree"] = [
            int(deg.get(r.source, 0) + deg.get(r.target, 0) + 1) for r in new_rel_df.itertuples()
        ]

    for col in relationships.columns:
        if col not in new_rel_df.columns:
            new_rel_df[col] = None
    new_rel_df = new_rel_df[relationships.columns]

    combined = pd.concat([relationships, new_rel_df], ignore_index=True)
    combined.to_parquet(relationships_path, index=False)

    print(f"[FILTER] \uace0\ub9bd \ub178\ub4dc {len(new_rows)}\uac1c\ub97c \ubc1c\uc2e0\uc790\uc5d0\uac8c \uc7ac\uc5f0\uacb0 (domain={domain})")


# few-shot 예시 누출/NULL 리터럴 blocklist에 해당하는 엔티티·관계를 결과 parquet에서 제거한다
def _filter_fewshot_leakage(paths):
    import pandas as pd

    blocklist = _FEWSHOT_LEAKAGE_BLOCKLIST | _NULL_VALUE_LITERALS
    output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
    entities_path = os.path.join(output_dir, "entities.parquet")
    relationships_path = os.path.join(output_dir, "relationships.parquet")

    removed_entities = 0
    if os.path.exists(entities_path):
        df = pd.read_parquet(entities_path)
        mask = df["title"].astype(str).str.upper().isin(blocklist)
        removed_entities = int(mask.sum())
        if removed_entities:
            df[~mask].to_parquet(entities_path, index=False)

    removed_rels = 0
    if os.path.exists(relationships_path):
        df = pd.read_parquet(relationships_path)
        mask = (
            df["source"].astype(str).str.upper().isin(blocklist)
            | df["target"].astype(str).str.upper().isin(blocklist)
        )
        removed_rels = int(mask.sum())
        if removed_rels:
            df[~mask].to_parquet(relationships_path, index=False)

    if removed_entities or removed_rels:
        print(f"[FILTER] few-shot 예시 누출 제거: 엔티티 {removed_entities}개, 관계 {removed_rels}개")


# GraphRAG CLI(index)를 서브프로세스로 실행하고 진행률을 감시한 뒤 결과 parquet 정제 필터들을 적용한다
def build_graphrag_index(job_id, paths, env, max_mails=None):
    print(f"[JOB][graphrag] START job_id={job_id}")
    print(f"[JOB][graphrag] cwd={os.getcwd()}")
    print(f"[JOB][graphrag] sys.executable={sys.executable}")
    print(f"[JOB][graphrag] GRAPHRAG_ROOT={paths.GRAPHRAG_ROOT}")
    print(f"[JOB][graphrag] root_exists={os.path.exists(paths.GRAPHRAG_ROOT)}")

    update_job(job_id, progress=20, message="GraphRAG 인덱싱 시작")
    append_job_log(job_id, "[START] build_graphrag_index")
    append_job_log(job_id, f"[INFO] cwd={os.getcwd()}")
    append_job_log(job_id, f"[INFO] sys.executable={sys.executable}")
    append_job_log(job_id, f"[INFO] GRAPHRAG_ROOT={paths.GRAPHRAG_ROOT}")
    append_job_log(job_id, f"[INFO] root_exists={os.path.exists(paths.GRAPHRAG_ROOT)}")

    if max_mails is not None:
        _trim_mail_latest(paths, max_mails, job_id)

    render_all_prompts()
    user_graphrag_init(paths)

    # GraphRAG CLI 실행 명령어 구성
    cmd = [
        sys.executable,
        "-u",              # stdout/stderr 버퍼링 최소화
        "-X", "utf8",
        "-m", "graphrag",  # graphrag 모듈 실행
        "index",           # graphrag 모듈의 index 명령
        "--root", paths.GRAPHRAG_ROOT
    ]

    env = env.copy()
    env["PYTHONUNBUFFERED"] = "1"
    _patches_dir = os.path.join(BASE_DIR, "parquet_template", "src", "graphrag_patches")
    env["PYTHONPATH"] = _patches_dir + os.pathsep + env.get("PYTHONPATH", "")

    print(f"[JOB][graphrag] CMD={cmd}")
    append_job_log(job_id, f"[CMD] {cmd}")

    output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
    start_time = time.time()
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=_watch_graphrag_output,
        args=(job_id, output_dir, start_time, stop_event, 5),
        daemon=True,
    )
    watcher.start()

    try:
        update_job(job_id, progress=30, message="GraphRAG 인덱싱 실행 중")

        subprocess.run(
            cmd,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=env,
        )

        append_job_log(job_id, "[END] build_graphrag_index success")
        update_job(job_id, progress=90, message="GraphRAG 인덱싱 완료")
        print(f"[JOB][graphrag] SUCCESS job_id={job_id}")

        try:
            _filter_fewshot_leakage(paths)
        except Exception as e:
            print(f"[FILTER][WARN] few-shot 누출 필터링 실패 (무시): {e}")

        try:
            _filter_invalid_chatrooms(paths)
        except Exception as e:
            print(f"[FILTER][WARN] ChatRoom 근거 검증 필터링 실패 (무시): {e}")

        try:
            _filter_invalid_dates(paths)
        except Exception as e:
            print(f"[FILTER][WARN] Date 근거 검증 필터링 실패 (무시): {e}")

        try:
            _reconnect_isolated_via_person(paths)
        except Exception as e:
            print(f"[FILTER][WARN] 고립 노드 재연결 실패 (무시): {e}")

    except Exception as e:
        print(f"[JOB][graphrag][ERROR] job_id={job_id} error={e}")
        traceback.print_exc()
        append_job_log(job_id, f"[ERROR] build_graphrag_index failed: {e}")
        raise

    finally:
        stop_event.set()
        watcher.join(timeout=5)


# GraphRAG CLI(update)를 서브프로세스로 실행해 증분 인덱싱하고 delta graphml을 기존 그래프에 병합한다
def build_graphrag_update(job_id,paths, env):
    print(f"[JOB][graphrag-update] START job_id={job_id}")
    print(f"[JOB][graphrag-update] cwd={os.getcwd()}")
    print(f"[JOB][graphrag-update] sys.executable={sys.executable}")
    print(f"[JOB][graphrag-update] GRAPHRAG_ROOT={paths.GRAPHRAG_ROOT}")
    print(f"[JOB][graphrag-update] root_exists={os.path.exists(paths.GRAPHRAG_ROOT)}")

    update_job(job_id, progress=20, message="GraphRAG 업데이트 시작")
    append_job_log(job_id, "[START] build_graphrag_update")
    append_job_log(job_id, f"[INFO] cwd={os.getcwd()}")
    append_job_log(job_id, f"[INFO] sys.executable={sys.executable}")
    append_job_log(job_id, f"[INFO] GRAPHRAG_ROOT={paths.GRAPHRAG_ROOT}")
    append_job_log(job_id, f"[INFO] root_exists={os.path.exists(paths.GRAPHRAG_ROOT)}")

    render_all_prompts()
    user_graphrag_init(paths)

    # GraphRAG CLI 실행 명령어 구성
    cmd = [
        sys.executable,
        "-u",              # stdout/stderr 버퍼링 최소화
        "-X", "utf8",
        "-m", "graphrag",  # graphrag 모듈 실행
        "update",          # graphrag 모듈 update 명령
        "--root", paths.GRAPHRAG_ROOT
    ]

    env = env.copy()
    env["PYTHONUNBUFFERED"] = "1"
    _patches_dir = os.path.join(BASE_DIR, "parquet_template", "src", "graphrag_patches")
    env["PYTHONPATH"] = _patches_dir + os.pathsep + env.get("PYTHONPATH", "")

    print(f"[JOB][graphrag] CMD={cmd}")
    append_job_log(job_id, f"[CMD] {cmd}")

    update_output_base = os.path.join(paths.GRAPHRAG_ROOT, "output")
    start_time = time.time()
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=_watch_graphrag_output,
        args=(job_id, update_output_base, start_time, stop_event, 5),
        daemon=True,
    )
    watcher.start()

    try:
        update_job(job_id, progress=30, message="GraphRAG 업데이트 실행 중")

        subprocess.run(
            cmd,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=env,
        )

        append_job_log(job_id, "[END] build_graphrag_update success")
        update_job(job_id, progress=90, message="GraphRAG 업데이트 완료")
        print(f"[JOB][graphrag-update] SUCCESS job_id={job_id}")

        # 새로운 데이터 graphml과 현재 존재하는 output graphml 병합
        output_graphml = os.path.join(paths.GRAPHRAG_ROOT, "output", "graph.graphml")
        update_output_dir = os.path.join(paths.GRAPHRAG_ROOT, "update_output")
        
        # latest = sorted(os.listdir(update_output_dir))[-1]
        if not os.path.exists(update_output_dir):
            print(f"[JOB][graphrag-update] update_output 없음 — 새 문서 없음으로 처리")
            append_job_log(job_id, "[INFO] update_output not found, no new documents")
            return  # 정상 종료

        latest = sorted(os.listdir(update_output_dir))[-1]

        delta_graphml = os.path.join(update_output_dir, latest, "delta", "graph.graphml")

        if os.path.exists(delta_graphml):
            G_output = nx.read_graphml(output_graphml)  # 기존 graphml
            G_delta = nx.read_graphml(delta_graphml)    # 새로운 graphml
            G_merged = nx.compose(G_output, G_delta)    # 두 graphml 병합
            nx.write_graphml(G_merged, output_graphml)  # 병합 결과 기존 graphml에 덮어씀

    except Exception as e:
        print(f"[JOB][graphrag-update][ERROR] job_id={job_id} error={e}")
        traceback.print_exc()
        append_job_log(job_id, f"[ERROR] build_graphrag_update failed: {e}")
        raise

    finally:
        stop_event.set()
        watcher.join(timeout=5)


# 첨부 요약 → GraphRAG 인덱싱 → 그래프 JSON → 통계/DB 저장 → 아바타 생성까지 전체 인덱싱 파이프라인을 실행한다
def run_graph_pipeline(job_id, paths, env, attachment_texts_by_mail=None, added_count=0, max_mails=None, mail_platform="gmail"):
    print(f"[JOB][pipeline] START job_id={job_id}")
    append_job_log(job_id, "[START] run_graph_pipeline")

    render_all_prompts()
    user_graphrag_init(paths)
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
        build_graphrag_index(job_id, paths, env, max_mails=max_mails)
        time_result = end_timer(timer) #인덱싱 시간 측정용, 측정 끝

        build_graph_json(job_id,paths, env)

        formatted_time = format_elapsed_time(time_result["elapsed_sec"])

        target_update_date = time_result["ended_at"]

        if paths.DOMAIN == "messenger":
            _extract_message_statics_pipeline(paths, mode='rewrite')

            blocks = _parse_message_blocks_from_parquet(paths)
            chatroom_name = blocks[0]["chatroom_name"] if blocks else paths.USER_ID

            create_chatroom(
                chatroom_id=paths.USER_ID,
                chatroom_name=chatroom_name,
                ended_at=target_update_date,
                index_time=formatted_time,
                message_count=count_total_messages(paths),
                message_platform=mail_platform,
            )
            indexing_stats = collect_indexing_stats(paths)
            update_chatroom_indexing_stats(paths.USER_ID, target_update_date, indexing_stats)
            save_chatroom_graph_stats_to_db(paths, target_update_date)

            save_message_block_to_db(paths, target_update_date)

            _run_and_join([
                (save_chatroom_people_to_db, (paths, target_update_date)),
                (save_message_keyword_to_db, (paths, target_update_date)),
                (generate_message_summaries, (paths,)),
            ])

            save_chatroom_relationships_to_db(paths, target_update_date)
            recompute_all_message_moods(paths)

            try:
                generate_chatroom_people_avatars_batch(paths)
            except Exception as e:
                print(f"[JOB] 참여자 아바타 생성 실패 (인덱싱은 계속 진행): {e}")
        else:
            _extract_statics_pipeline(paths, mode='rewrite')

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

            save_mail_folder_to_db(paths, target_update_date)

            save_person_stats_to_db(paths, target_update_date)

            _run_and_join([
                (save_mail_to_db, (paths, target_update_date)),
                (save_keyword_stats_to_db, (paths, target_update_date)),
                (generate_mail_summaries, (paths,)),
            ])

            try:
                generate_all_person_avatars(paths)
            except Exception as e:
                print(f"[JOB] 연락처 아바타 생성 실패 (인덱싱은 계속 진행): {e}")


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


# GraphRAG 증분 업데이트 → 그래프 JSON → 통계/DB 저장 → 아바타 생성까지 전체 업데이트 파이프라인을 실행한다
def run_graph_update_pipeline(job_id, paths, env):
    print(f"[JOB][update-pipeline] START job_id={job_id}")
    append_job_log(job_id, "[START] run_graph_update_pipeline")

    render_all_prompts()
    user_graphrag_init(paths)
    try:
        update_job(job_id, progress=0, status="running", message="업데이트 작업 시작")

        # 1단계: graphrag 업데이트
        build_graphrag_update(job_id,paths, env)

        # 2단계: json 생성 
        build_graph_json(job_id,paths, env)

        if paths.DOMAIN == "messenger":
            _extract_message_statics_pipeline(paths, mode='append')
            indexing_stats = collect_indexing_stats(paths)
            update_chatroom_indexing_stats(paths.USER_ID, None, indexing_stats)
            save_chatroom_graph_stats_to_db(paths)

            save_message_block_to_db(paths)

            _run_and_join([
                (save_chatroom_people_to_db, (paths,)),
                (save_message_keyword_to_db, (paths,)),
            ])

            save_chatroom_relationships_to_db(paths)

            try:
                generate_chatroom_people_avatars_batch(paths)
            except Exception as e:
                print(f"[JOB] 참여자 아바타 생성 실패 (인덱싱은 계속 진행): {e}")
        else:
            _extract_statics_pipeline(paths, mode='append')
            indexing_stats = collect_indexing_stats(paths)
            update_mail_account_indexing_stats(paths.USER_ID, None, indexing_stats)
            save_graph_stats_to_db(paths)

            save_mail_folder_to_db(paths)

            save_person_stats_to_db(paths)

            _run_and_join([
                (save_mail_to_db, (paths,)),
                (save_keyword_stats_to_db, (paths,)),
            ])

            try:
                generate_all_person_avatars(paths)
            except Exception as e:
                print(f"[JOB] 연락처 아바타 생성 실패 (인덱싱은 계속 진행): {e}")

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
        target=run_graph_pipeline,  # 실행할 함수: 그래프라그 파이프라인 (인덱싱) 실행 함수
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
        target=run_graph_update_pipeline, # 실행할 함수 : 그래프라그 업데이트파이프라인 실행 함수
        args=(job_id,paths, env.copy()),
        daemon=True,                      # app.py 종료 시 같이 종료

    )
    t.start()  # 스레드 실행 (비동기 시작)

    print(f"[JOB][update-pipeline] BACKGROUND THREAD STARTED job_id={job_id} thread={t.name}")
    append_job_log(job_id, f"[INFO] update background thread started name={t.name}")
    return t