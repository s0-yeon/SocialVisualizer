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


# 헤더 표기 차이(예: "박세아" vs "박세아 (채팅방)")로 같은 방이 ChatRoom 엔티티 2개로 쪼개진 경우
# 코어 이름(_strip_chatroom_decorations 기준)이 같으면 하나로 병합한다 (messenger 전용).
# LLM이 인덱싱마다 접미사를 다르게 붙이더라도, 이 후처리가 매번 자동으로 다시 합쳐주므로
# 프롬프트 수정만으로는 줄 수 없는 재발 방지 보장을 제공한다.
def _merge_chatroom_aliases(paths):
    if getattr(paths, "DOMAIN", None) != "messenger":
        return

    import pandas as pd

    output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
    entities_path = os.path.join(output_dir, "entities.parquet")
    relationships_path = os.path.join(output_dir, "relationships.parquet")

    if not os.path.exists(entities_path):
        return

    entities = pd.read_parquet(entities_path)
    is_chatroom = entities["type"].astype(str).str.upper() == "CHATROOM"
    chatroom = entities[is_chatroom]
    if len(chatroom) <= 1:
        return 0

    # 코어 이름(접미사 제거)별로 그룹화 -- 2개 이상 모이면 같은 방의 별칭으로 간주
    core_names = chatroom["title"].map(_strip_chatroom_decorations)
    groups = {}
    for idx, core in zip(chatroom.index, core_names):
        groups.setdefault(core, []).append(idx)
    dup_groups = {core: idxs for core, idxs in groups.items() if core and len(idxs) > 1}
    if not dup_groups:
        return 0

    rename_map = {}
    drop_idx = []
    merged_count = 0

    for core, idxs in dup_groups.items():
        rows = entities.loc[idxs]
        # 접미사 없이 코어 이름 그대로인 제목을 대표로 우선 채택, 없으면 첫 번째로 채택
        exact = rows[rows["title"] == core]
        canonical_idx = exact.index[0] if len(exact) else idxs[0]
        canonical_title = entities.loc[canonical_idx, "title"]

        for idx in idxs:
            if idx == canonical_idx:
                continue
            dup_title = entities.loc[idx, "title"]
            rename_map[dup_title] = canonical_title
            drop_idx.append(idx)
            merged_count += 1

            # description/text_unit_ids는 대표 엔티티로 흡수
            if "description" in entities.columns:
                cv = str(entities.at[canonical_idx, "description"] or "")
                dv = str(entities.at[idx, "description"] or "")
                if dv and dv not in cv:
                    entities.at[canonical_idx, "description"] = (cv + "\n" + dv).strip()
            if "text_unit_ids" in entities.columns:
                cv = entities.at[canonical_idx, "text_unit_ids"]
                dv = entities.at[idx, "text_unit_ids"]
                merged_ids = list(cv) if cv is not None else []
                for tid in (list(dv) if dv is not None else []):
                    if tid not in merged_ids:
                        merged_ids.append(tid)
                entities.at[canonical_idx, "text_unit_ids"] = merged_ids

    if not drop_idx:
        return 0

    entities.drop(index=drop_idx).to_parquet(entities_path, index=False)

    merged_rel = 0
    if os.path.exists(relationships_path) and rename_map:
        rel = pd.read_parquet(relationships_path)
        rel["source"] = rel["source"].replace(rename_map)
        rel["target"] = rel["target"].replace(rename_map)
        rel = rel[rel["source"] != rel["target"]]  # 병합으로 자기참조가 된 관계 제거
        before = len(rel)
        rel = rel.drop_duplicates(subset=["source", "target"], keep="first")
        merged_rel = before - len(rel)
        rel.to_parquet(relationships_path, index=False)

    print(f"[FILTER] ChatRoom 별칭 병합: {merged_count}개 -> {rename_map}" + (f" (중복 relationship {merged_rel}개 정리)" if merged_rel else ""))
    return merged_count


# ChatRoom 별칭이 병합된 뒤(entities/relationships가 바뀐 뒤), 그 변화를 반영해
# communities/community_reports/text_embeddings만 다시 만든다. extract_graph 등
# 앞단은 다시 돌리지 않으므로 추가 추출 LLM 호출 없이 병합 결과와 일관된 그래프로 맞춰진다.
# 이걸 build_graphrag_index 안에서 병합이 실제로 일어났을 때만 자동으로 호출하므로,
# "ChatRoom 2개 생기는" 문제가 다시 발생해도 사람이 수동으로 재인덱싱할 필요가 없다.
def _rerun_communities_after_chatroom_merge(paths, env):
    import shutil

    settings_path = paths.USER_GRAPH_SETTINGS_PATH
    backup_path = settings_path + ".bak"
    workflows_override = (
        "\nworkflows: [create_communities, create_final_text_units, "
        "create_community_reports, generate_text_embeddings]\n"
    )

    shutil.copy2(settings_path, backup_path)
    with open(settings_path, "a", encoding="utf-8") as f:
        f.write(workflows_override)

    run_env = env.copy()
    run_env["PYTHONUNBUFFERED"] = "1"
    patches_dir = os.path.join(BASE_DIR, "parquet_template", "src", "graphrag_patches")
    run_env["PYTHONPATH"] = patches_dir + os.pathsep + run_env.get("PYTHONPATH", "")

    try:
        cmd = [
            sys.executable, "-u", "-X", "utf8",
            "-m", "graphrag", "index", "--root", paths.GRAPHRAG_ROOT,
        ]
        print(f"[FILTER] ChatRoom 별칭 병합 반영을 위해 communities/reports/embeddings 재생성 시작")
        subprocess.run(cmd, check=True, env=run_env)
        print(f"[FILTER] communities/reports/embeddings 재생성 완료")
    finally:
        shutil.move(backup_path, settings_path)


# 1:1 채팅방인데(참여자 정확히 2명) 상대방 Person 엔티티가 통째로 안 만들어진 경우를 복구한다 (messenger 전용).
# messenger.json 프롬프트에 이 실패를 막는 명시적 규칙(+few-shot 예시)이 이미 있음에도 모델이 가끔
# ChatRoom "(채팅방)" 접미사 규칙과 Person 생성 규칙을 동시에 놓치는 사례가 실제로 관측되어 추가한 결정론적 안전망.
# 원본 text_unit에서 "HH:MM 이름:" 발화 패턴을 직접 스캔해 누락된 Person과 최소 관계(participates_in/spoke_on/interacts_with)를
# 재구성하므로, 몇 번을 다시 인덱싱해도 이 실패가 재발할 때마다 자동으로 고쳐진다.
# 저비용 부가작업용 로컬 모델(SUB_TASK_CHAT_MODEL, Qwen2.5-7B / GPU3:8003)로 짧은 텍스트 하나를 생성한다.
# extract_graph에 쓰이는 메인 인덱싱 모델보다 훨씬 저렴 -- 이미 첨부파일 요약 등 부가 작업에 쓰이는 것과 동일한 모델/경로를 재사용.
# 실패하면 None을 반환하므로 호출부는 항상 기계적 템플릿 문장으로 폴백해야 한다 (이 함수 자체가 절대 예외를 올리지 않음).
def _llm_subtask_complete(system_prompt: str, user_content: str, max_tokens: int = 120):
    try:
        client = openai.OpenAI(
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("SUB_TASK_API_BASE") or None,
        )
        response = client.chat.completions.create(
            model=os.getenv("SUB_TASK_CHAT_MODEL"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=max_tokens,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or None
    except Exception as e:
        print(f"[FILTER][WARN] LLM 서술 보강 실패 (템플릿으로 대체): {e}")
        return None


# 1:1 채팅방인데(참여자 정확히 2명) 상대방 Person 엔티티가 통째로 안 만들어진 경우를 복구한다 (messenger 전용).
# messenger.json 프롬프트에 이 실패를 막는 명시적 규칙(+few-shot 예시)이 이미 있음에도 모델이 가끔
# ChatRoom "(채팅방)" 접미사 규칙과 Person 생성 규칙을 동시에 놓치는 사례가 실제로 관측되어 추가한 결정론적 안전망.
# 원본 text_unit에서 "HH:MM 이름:" 발화 패턴을 직접 스캔해 누락된 Person과 관계(participates_in/spoke_on/interacts_with)를
# 재구성하고, spoke_on/interacts_with의 서술은 SUB_TASK 모델로 실제 대화 내용을 요약해 채운다(실패 시 기계적 템플릿으로 폴백)
# -- 그래야 정상적으로 추출된 다른 엔티티들과 서술 품질 격차가 크지 않다.
def _reconstruct_missing_person_in_1on1(paths):
    if getattr(paths, "DOMAIN", None) != "messenger":
        return 0

    import pandas as pd
    import uuid

    output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
    entities_path = os.path.join(output_dir, "entities.parquet")
    relationships_path = os.path.join(output_dir, "relationships.parquet")
    text_units_path = os.path.join(output_dir, "text_units.parquet")

    if not (os.path.exists(entities_path) and os.path.exists(text_units_path)):
        return 0

    entities = pd.read_parquet(entities_path)
    text_units = pd.read_parquet(text_units_path)
    tu_text_by_id = dict(zip(text_units["id"], text_units["text"].astype(str)))

    chatroom = entities[entities["type"].astype(str).str.upper() == "CHATROOM"]
    if len(chatroom) == 0:
        return 0  # ChatRoom 자체가 없으면(비정상 계정 등) 이 안전망의 대상이 아님
    if len(chatroom) > 1:
        # _merge_chatroom_aliases가 먼저 실행되어 있어야 하는데도 1개로 안 줄었다면(코어 이름이 서로 다른 채로 남는 등)
        # 이 함수가 자동으로 판단하기 애매한 상황이라 손대지 않고 경고만 남긴다 -- 예전엔 조용히 스킵돼서 안 보였음
        print(f"[FILTER][WARN] 1:1 Person 복구 스킵: ChatRoom이 병합 후에도 {len(chatroom)}개 남음 -- 수동 확인 필요")
        return 0
    chatroom_idx = chatroom.index[0]
    chatroom_title = str(entities.at[chatroom_idx, "title"])
    core_name = _strip_chatroom_decorations(chatroom_title)

    # 원본 대화에서 실제 참여자 목록을 직접 읽는다 (LLM 추출 결과가 아니라 원본 "참여자:" 헤더 기준)
    participants = set()
    for text in text_units["text"].astype(str):
        for m in re.finditer(r"참여자\s*:\s*(.+)", text):
            for name in m.group(1).split(","):
                name = name.strip()
                if name:
                    participants.add(name)

    if len(participants) != 2:
        return 0  # 그룹 채팅이면 대상이 아님

    persons = set(entities[entities["type"].astype(str).str.upper() == "PERSON"]["title"].astype(str))
    missing = participants - persons
    if not missing:
        return 0  # 이미 둘 다 정상 -- 손대지 않음

    # 1:1 방인데 ChatRoom 이름에 "(채팅방)" 접미사가 없으면(=이번 실패의 짝) 여기서 같이 바로잡는다
    if chatroom_title == core_name:
        new_chatroom_title = f"{core_name} (채팅방)"
        entities.at[chatroom_idx, "title"] = new_chatroom_title
        if os.path.exists(relationships_path):
            rel_fix = pd.read_parquet(relationships_path)
            rel_fix["source"] = rel_fix["source"].replace({chatroom_title: new_chatroom_title})
            rel_fix["target"] = rel_fix["target"].replace({chatroom_title: new_chatroom_title})
            rel_fix.to_parquet(relationships_path, index=False)
        chatroom_title = new_chatroom_title

    two_participants = list(participants)

    new_person_rows = []
    new_rels = []
    rel = pd.read_parquet(relationships_path) if os.path.exists(relationships_path) else pd.DataFrame(
        columns=["id", "human_readable_id", "source", "target", "description", "weight", "combined_degree", "text_unit_ids"]
    )
    existing_pairs = set(zip(rel["source"], rel["target"])) if len(rel) else set()
    next_hrid = int(entities["human_readable_id"].max()) + 1 if len(entities) else 0
    next_rel_hrid = int(rel["human_readable_id"].max()) + 1 if len(rel) else 0

    def _mk_rel(source, target, description, tu_ids):
        nonlocal next_rel_hrid
        r = {
            "id": str(uuid.uuid4()),
            "human_readable_id": next_rel_hrid,
            "source": source,
            "target": target,
            "description": description,
            "weight": float(len(tu_ids)),
            "combined_degree": 0,
            "text_unit_ids": tu_ids,
        }
        next_rel_hrid += 1
        return r

    date_entities = entities[entities["type"].astype(str).str.upper() == "DATE"]
    per_person_tu_ids = {}

    for missing_name in missing:
        # 누락된 사람이 발화자로 등장하는 text_unit을 원본 텍스트에서 직접 찾는다
        sender_re = re.compile(rf"\d{{1,2}}:\d{{2}}\s+{re.escape(missing_name)}\s*:")
        missing_tu_ids = [tid for tid, text in tu_text_by_id.items() if sender_re.search(text)]
        if not missing_tu_ids:
            print(f"[FILTER][WARN] 1:1 Person 복구 실패: '{missing_name}' 발화 근거를 text_unit에서 못 찾음 ({chatroom_title}) -- 만들어내지 않고 스킵")
            continue
        per_person_tu_ids[missing_name] = missing_tu_ids

        new_person_rows.append({
            "id": str(uuid.uuid4()),
            "human_readable_id": next_hrid,
            "title": missing_name,
            "type": "PERSON",
            "description": f"Name: {missing_name}",
            "text_unit_ids": missing_tu_ids,
            "frequency": len(missing_tu_ids),
            "degree": 0,  # 아래에서 생성하는 관계 수만큼 갱신
        })
        next_hrid += 1

        # participates_in: 누락된 사람 -> ChatRoom (실제 추출된 데이터도 이 관계는 항상 기계적 템플릿이라 그대로 둠)
        new_rels.append(_mk_rel(
            missing_name, chatroom_title,
            f"{missing_name}은(는) {chatroom_title} 채팅방의 대화 참여자다.",
            missing_tu_ids,
        ))

        # spoke_on: 누락된 사람이 실제로 발화한 날짜마다, 그 날의 실제 대화 내용을 SUB_TASK 모델로 한 줄 요약해서 채운다
        missing_tu_set = set(missing_tu_ids)
        for _, drow in date_entities.iterrows():
            date_tu_ids = list(drow["text_unit_ids"]) if drow["text_unit_ids"] is not None else []
            overlap = [tid for tid in date_tu_ids if tid in missing_tu_set]
            if not overlap:
                continue
            date_title = str(drow["title"])
            chunk_text = "\n".join(tu_text_by_id.get(tid, "") for tid in overlap)[:3000]
            summary = _llm_subtask_complete(
                "너는 카카오톡 대화 로그를 보고 특정 인물이 그 날 대화에서 무엇을 했는지 한국어 한 문장으로 요약하는 도우미다. "
                "예시 스타일: '여러 주제를 제안하고 대화를 이끌었다', '식사 약속을 제안하고 만남을 조율했다', '메시지를 보냈다'. "
                "다른 설명 없이 딱 한 문장만 출력해.",
                f"[{date_title}, 발화자: {missing_name}]\n{chunk_text}",
                max_tokens=60,
            )
            desc = f"{missing_name}이(가) {date_title}에 {summary}" if summary else f"{missing_name}이(가) {date_title}에 메시지를 보냈다."
            new_rels.append(_mk_rel(missing_name, date_title, desc, overlap))

    if not new_person_rows:
        return 0

    # interacts_with: 두 참여자 사이 관계 서술을 SUB_TASK 모델로 한 번 생성 (이미 정상 추출된 방향이 있으면 그건 건드리지 않음)
    a, b = two_participants
    if a in per_person_tu_ids or b in per_person_tu_ids:
        evidence_ids = sorted(set(per_person_tu_ids.get(a, []) + per_person_tu_ids.get(b, [])))
        chunk_text = "\n".join(tu_text_by_id.get(tid, "") for tid in evidence_ids[:20])[:4000]
        summary = _llm_subtask_complete(
            "너는 카카오톡 1:1 대화 로그를 보고 두 사람의 관계와 대화 스타일을 요약하는 도우미다. "
            "'[관계: 친구/연인/동료/가족 등 추정]'으로 시작한 뒤, 존댓말/반말 여부와 주요 화제를 2~3문장 한국어로 요약해. "
            "예시: '[관계: 친구] 반말을 사용해 자연스럽게 안부와 일상 이야기를 주고받았다. 저녁 약속과 장소를 편하게 조율했다.'",
            f"[참여자: {a}, {b}]\n{chunk_text}",
            max_tokens=150,
        )
        desc_ab = summary or f"{a}과(와) {b}은(는) 이 채팅방에서 대화를 나눴다."
        desc_ba = summary or f"{b}과(와) {a}은(는) 이 채팅방에서 대화를 나눴다."
        if (a, b) not in existing_pairs:
            new_rels.append(_mk_rel(a, b, desc_ab, evidence_ids))
        if (b, a) not in existing_pairs:
            new_rels.append(_mk_rel(b, a, desc_ba, evidence_ids))

    rel_count_by_person = {}
    for r in new_rels:
        rel_count_by_person[r["source"]] = rel_count_by_person.get(r["source"], 0) + 1
    for row in new_person_rows:
        row["degree"] = rel_count_by_person.get(row["title"], 0)

    entities = pd.concat([entities, pd.DataFrame(new_person_rows)], ignore_index=True)
    entities.to_parquet(entities_path, index=False)

    rel = pd.concat([rel, pd.DataFrame(new_rels)], ignore_index=True)
    rel.to_parquet(relationships_path, index=False)

    names = ", ".join(row["title"] for row in new_person_rows)
    print(f"[FILTER] 1:1 채팅 Person 엔티티 복구: '{names}' ({chatroom_title}, 관계 {len(new_rels)}개 생성, LLM 서술 보강 적용)")
    return len(new_person_rows)

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

        merged_chatrooms = 0
        reconstructed_persons = 0
        try:
            merged_chatrooms = _merge_chatroom_aliases(paths)
        except Exception as e:
            print(f"[FILTER][WARN] ChatRoom 별칭 병합 실패 (무시): {e}")

        try:
            reconstructed_persons = _reconstruct_missing_person_in_1on1(paths)
        except Exception as e:
            print(f"[FILTER][WARN] 1:1 채팅 Person 엔티티 복구 실패 (무시): {e}")

        if merged_chatrooms or reconstructed_persons:
            try:
                _rerun_communities_after_chatroom_merge(paths, env)
            except Exception as e:
                print(f"[FILTER][WARN] communities/reports/embeddings 재생성 실패 (무시): {e}")

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