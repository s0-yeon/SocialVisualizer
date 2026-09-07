# src/util/lightrag_backend/lightrag_query.py

# LightRAG 질의응답 모듈. 
# 단일 계정 검색(run_lightrag_query)과 여러 계정을 한 번에 훑는 연합 검색(run_federated_search)을 제공하고, 질문에 맞는 검색 모드를 LLM으로 분류하며(_classify_query_method), 답변 속 ID·발신인 표기를 실제 원본 데이터와 맞춰 정제한 뒤 질의 로그를 DB에 남긴다. 
# app.py의 질의 엔드포인트가 최종적으로 호출하는 곳이다.

# Handles LightRAG query answering: 
# single-account search (run_lightrag_query) and multi-account federated search (run_federated_search), LLM-based query mode classification (_classify_query_method), and post-processing that reconciles ID/sender mentions in the answer with the real source data before logging the query to the database. 
# Called from app.py's query endpoints.

import os
import sys
import re
import json
import concurrent.futures
import traceback
import time
import openai

from config.settings import MAIL_BLOCK_SEP, BASE_DIR
from util.lightrag_backend.lightrag_engine import get_lightrag_instance, get_and_reset_usage
from util.lightrag_backend.lightrag_loop import run_coroutine
from util.database.db_writer import save_query_to_db

sys.path.insert(0, os.path.join(BASE_DIR, "LightRAG"))
from lightrag import QueryParam

# 질의 분류(로컬/글로벌 판단)처럼 RAG 검색 자체가 아닌 보조 작업은 SUB_TASK_CHAT_MODEL을 쓴다.
_RAG_CHAT_MODEL = os.environ.get("RAG_CHAT_MODEL", "gpt-4o-mini")


# 연합 검색 결과를 query 테이블에 1행으로 저장한다 (참여 계정들의 토큰 사용량 총합, 인용 계정은 refer_kg에 기록)
def _save_federated_query(accounts_paths: list, primary_user_id: str, original_message: str,
                           elapsed: float, method: str, answer: str, refer_accounts: list = None):
    total_input = 0
    total_output = 0
    model_name = None
    for paths in accounts_paths:
        usage = get_and_reset_usage(paths.USER_ID)  # LightRAG는 엔진이 하나뿐이라 method 인자 불필요
        total_input += usage["input_tokens"]
        total_output += usage["output_tokens"]
        if not model_name and usage["model_name"]:
            model_name = usage["model_name"]

    refer_kg = json.dumps(refer_accounts) if refer_accounts else None

    try:
        save_query_to_db(
            primary_user_id, original_message, elapsed, method,
            model_name=model_name,
            input_tokens=total_input,
            output_tokens=total_output,
            answer=answer,
            refer_kg=refer_kg,
        )
    except Exception as e:
        print(f"[WARN] 연합 검색 query DB 저장 실패 (무시): {e}")


# 계정의 mail_latest.txt에서 {메일ID(소문자): 실제 발신인} 매핑을 읽어 반환한다
def _load_account_sender_map(paths) -> dict:
    try:
        with open(paths.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    sender_map = {}
    for block in text.split(MAIL_BLOCK_SEP):
        id_m = re.search(r'^\s*(?:\[ID\]|ID:)\s*(.+?)\s*$', block, re.MULTILINE)
        sender_m = re.search(r'^\s*(?:\[발신인\]|발신인:)\s*(.+?)\s*$', block, re.MULTILINE)
        if id_m and sender_m:
            sender_map[id_m.group(1).strip().lower()] = sender_m.group(1).strip()
    return sender_map


# 추출한 메일 ID 끝에 붙은 문장부호(대괄호·마침표 등)를 제거한다
def _strip_id_punct(mail_id: str) -> str:
    return mail_id.strip(']),.;:》」』')


# 메일 ID가 그럴듯한지 판단한다 (LLM이 순번 "2" 등을 ID로 잘못 쓴 짧은 숫자는 걸러냄)
def _is_plausible_mail_id(mail_id: str) -> bool:
    return not (mail_id.isdigit() and len(mail_id) <= 6)


# 화면 표시용으로 답변에서 ID/계정 줄과 빈 번호 줄을 제거해 정리한다
def strip_ids_for_display(text: str) -> str:
    text = re.sub(r'^[ \t]*[-*]?[ \t]*(ID|계정):\s*\S+[ \t]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'(ID|계정):\s*\S+', '', text)
    text = re.sub(r'^[ \t]*(?:\d+[.)]|[-*])[ \t]*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


# 텍스트에서 "ID: ..." 패턴 중 그럴듯한 메일 ID만 뽑아 리스트로 반환한다
def _extract_ids_from_text(text: str) -> list[str]:
    found = [_strip_id_punct(m) for m in re.findall(r'ID:\s*(\S+)', text)]
    return [m for m in found if _is_plausible_mail_id(m)]


# rag.aquery_data() 결과에서 근거 청크 본문만 이어붙여 반환한다
def _chunks_text(data: dict) -> str:
    chunks = data.get("data", {}).get("chunks", [])
    return "\n".join(c.get("content", "") for c in chunks)


# 캐시된 LightRAG 인스턴스로 단일 계정 질의 답변과 근거 메일 ID 목록을 반환하고 query 로그를 저장한다 (method는 QueryParam mode로 전달)
def run_lightrag_query(message: str, original_message: str, paths, method: str = "mix") -> tuple[str, list]:
    start_time = time.time()

    #  앱 전체가 공유하는 절대 안 닫는 루프(lightrag_loop.py)에 코루틴만 제출한다
    # LightRAG로 질의해 답변을 정제하고 근거 메일 ID를 추출한다
    async def _search():
        rag = await get_lightrag_instance(paths.USER_ID, paths.LIGHTRAG_OUTPUT_DIR)
        param = QueryParam(mode=method)

        answer = await rag.aquery(message, param)
        answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', answer)
        answer = re.sub(r'\*+|#+', '', answer)
        answer = answer.strip()

        # 답변 텍스트에서 ID 추출한다
        found = _extract_ids_from_text(answer)

        # 2차: 답변에 ID가 없으면(LLM이 안 썼으면) 생성 호출 없이 근거 청크만 다시 가져와서 추출한다
        if not found:
            data = await rag.aquery_data(message, param)
            found = _extract_ids_from_text(_chunks_text(data))

        # 순서 유지하면서 중복 제거
        seen = set()
        source_ids = []
        for id in found:
            if id not in seen:
                seen.add(id)
                source_ids.append({"id": id, "account": paths.USER_ID})

        display_answer = strip_ids_for_display(answer)
        return display_answer, source_ids

    try:
        result = run_coroutine(_search(), timeout=120)
    except concurrent.futures.TimeoutError:
        raise RuntimeError("lightrag 검색 타임아웃 (120초)")
    except Exception as e:
        traceback.print_exc()
        raise

    elapsed = time.time() - start_time
    print(f"[ENGINE][lightrag] 검색 완료: {elapsed:.2f}초")
    answer, source_ids = result
    print(f"[ENGINE][lightrag] 답변: {answer}")
    print(f"[ENGINE][lightrag] source_ids: {source_ids}")
    try:
        usage = get_and_reset_usage(paths.USER_ID)
        save_query_to_db(
            paths.USER_ID, original_message, elapsed, method,
            model_name=usage["model_name"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            answer=answer,
        )
    except Exception as e:
        print(f"[WARN] query DB 저장 실패 (무시): {e}")
    return answer, source_ids  # app.py의 _worker()로 튜플 반환


# 여러 계정의 근거 청크만 모아 답변 생성 LLM 호출을 1회만 실행하는 연합 검색 (mode는 QueryParam 6개 모드 모두 허용)
def run_federated_search(message: str, original_message: str, accounts_paths: list, mode: str,
                          primary_user_id: str = None, per_account_max_tokens: int = 3000) -> tuple[str, list]:
    start_time = time.time()

    # 계정별 근거 청크를 모아 답변을 1회 생성하고 근거 메일 ID·계정을 추출한다
    async def _search():
        param = QueryParam(mode=mode)
        combined_chunks = []
        account_sender_maps = {}  # user_id -> {메일ID(소문자): 진짜 발신인 값}
        valid_accounts_paths = []

        for paths in accounts_paths:
            try:
                rag = await get_lightrag_instance(paths.USER_ID, paths.LIGHTRAG_OUTPUT_DIR)
                data = await rag.aquery_data(message, param)
            except Exception as e:
                print(f"[FEDERATED] {paths.USER_ID} 인스턴스 로드/조회 실패, 스킵: {e}")
                continue

            chunk_text = _chunks_text(data)
            # 계정 하나가 프롬프트 예산을 독점하지 않도록 상한을 둔다
            max_chars = per_account_max_tokens * 4
            if len(chunk_text) > max_chars:
                chunk_text = chunk_text[:max_chars]

            account_sender_maps[paths.USER_ID] = _load_account_sender_map(paths)
            print(f"[FEDERATED] {paths.USER_ID}: 컨텍스트 {len(chunk_text)}자, 보유 메일 {len(account_sender_maps[paths.USER_ID])}건")

            combined_chunks.append(f"[계정: {paths.USER_ID}]\n{chunk_text}")
            valid_accounts_paths.append(paths)

        if not combined_chunks:
            return "인덱싱된 계정이 없습니다.", []

        merged_context = "\n\n".join(combined_chunks)

        # 답변 속 메일 ID로 원본 데이터를 찾아 (진짜 ID, 계정 user_id)를 반환한다 (완전일치→부분일치 순, 실패 시 None,None)
        def _find_real_id(mail_id: str):
            key = mail_id.lower()
            for user_id, smap in account_sender_maps.items():
                if key in smap:
                    return key, user_id
            key_local = key.split('@')[0]
            for user_id, smap in account_sender_maps.items():
                for real_id in smap:
                    if real_id.split('@')[0] == key_local:
                        return real_id, user_id
            if len(key) >= 8:
                for user_id, smap in account_sender_maps.items():
                    for real_id in smap:
                        if real_id.startswith(key) or key.startswith(real_id):
                            return real_id, user_id
            return None, None

        # 메일 ID로 소속 계정 user_id를 역추적한다 (실패 시 None)
        def _resolve_account(mail_id: str):
            _, user_id = _find_real_id(mail_id)
            if not user_id:
                print(f"[FEDERATED] 계정 매칭 실패, 원본 ID: {mail_id!r}")
            return user_id

        # 응답 형식/ID·발신인 혼동 방지 지시사항은 GraphRAG 라이브러리 프롬프트가 아니라
        # 이 파일에서 우리가 직접 짠 문구라 그대로 재사용한다.
        system_prompt = (
            "아래 데이터를 근거로 질문에 여러 문단(Multiple Paragraphs) 형식으로 답하라.\n\n"
            f"데이터:\n{merged_context}\n\n"
            "추가 지시사항: 위 데이터는 서로 다른 여러 이메일 계정에서 수집되었으며, "
            "각 데이터 블록 앞에 [계정: 이메일주소] 형태로 출처 계정이 표시되어 있다. "
            "질문과 관련된 내용이 여러 계정에 걸쳐 있다면 한쪽 계정에 치우치지 말고 "
            "관련 있는 계정을 빠짐없이 골고루 다루되, 특정 계정에 관련 내용이 없으면 "
            "그 계정은 억지로 언급하지 말고 실제로 관련 있는 내용만으로 답하라. "
            "원본 데이터에는 메일마다 'ID:'와 '발신인:'이 서로 다른 별개 필드로 있으니 "
            "절대 혼동하지 말 것 — 발신자를 쓸 때는 반드시 '발신인:' 필드의 이메일 주소를 쓰고, "
            "'ID:' 필드의 값을 발신자 자리에 쓰지 마라. "
            "목록으로 나열하든 묶어서 요약하든 답변 형식과 무관하게, 실제로 언급/근거로 삼은 "
            "메일마다 'ID: 원본ID값'을 요약 문장에 섞어 쓰지 말고 그 메일 항목의 별도 줄로 표기하라. "
            "'ID:' 뒤에는 반드시 데이터에 있는 실제 ID 값을 정확히 그대로 옮겨 적어야 한다. "
            "답변에서 메일을 1번, 2번처럼 순서대로 나열하더라도 그 순번을 'ID: 1', 'ID: 2'처럼 "
            "ID인 것으로 쓰지 마라 — 그건 데이터에 없는 값을 지어내는 것이다. "
            "그리고 언급/근거로 삼은 메일마다 'ID:', '발신인:'과 같은 줄에 '계정: 이메일주소' 줄도 "
            "추가하라 — 그 메일이 어느 [계정: ...] 블록에서 나온 데이터인지, 컨텍스트에 표시된 "
            "계정 이메일 주소를 정확히 그대로 옮겨 적어라."
        )

        client = openai.AsyncOpenAI(
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("RAG_CHAT_API_BASE") or None,  # 지정 시 로컬 vLLM(라마)으로 라우팅
        )
        try:
            # 여러 계정 내용을 종합하는 답변이라 계정 하나만 볼 때보다 더 길어질 수 있어 응답 길이 상한을 넉넉히 둠
            max_tokens = max(2000, 2000 * len(valid_accounts_paths))
            response = await client.chat.completions.create(
                model=_RAG_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                max_completion_tokens=max_tokens,  # RAG_CHAT_MODEL이 gpt-5 계열이면 max_tokens 대신 이 파라미터를 받는다
            )
        finally:
            await client.close()
        full_response = response.choices[0].message.content or ""

        answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', full_response)
        answer = re.sub(r'\*+|#+', '', answer)
        answer = answer.strip()

        # 답변 문단 하나에서 ID에 해당하는 진짜 발신인 값으로 '발신인:' 줄을 강제 교정한다
        def _fix_paragraph_sender(p):
            id_m = re.search(r'ID:\s*(\S+)', p)
            if not id_m:
                return p
            real_id, user_id = _find_real_id(_strip_id_punct(id_m.group(1)))
            if not real_id:
                return p
            real_sender = account_sender_maps[user_id].get(real_id)
            if not real_sender or not re.search(r'발신인:', p):
                return p
            return re.sub(r'(발신인:\s*)(.*)$', lambda m: m.group(1) + real_sender, p, count=1, flags=re.MULTILINE)

        answer = '\n\n'.join(_fix_paragraph_sender(p) for p in answer.split('\n\n'))

        # 항목마다 ID가 있으면 그 ID로 진짜 소속 계정을 역추적한다.
        found = _extract_ids_from_text(answer)
        seen = set()
        source_ids = []
        for id in found:
            if id not in seen:
                seen.add(id)
                source_ids.append({"id": id, "account": _resolve_account(id)})

        if not source_ids:
            # ID를 하나도 못 찾았을 때(요약형 답변 등)만 LLM이 쓴 '계정:' 값으로 폴백.
            # 실제 인덱싱된 계정 목록에 없는 값(오타/환각)은 조용히 버린다.
            valid_accounts = {p.USER_ID.strip().lower(): p.USER_ID for p in valid_accounts_paths}
            cited_accounts = []
            for m in re.findall(r'계정:\s*(\S+)', answer):
                real = valid_accounts.get(_strip_id_punct(m).strip().lower())
                if real:
                    cited_accounts.append(real)
            source_ids = [{"id": None, "account": acc} for acc in cited_accounts]

        display_answer = strip_ids_for_display(answer)
        return display_answer, source_ids

    # 계정 수가 많으면 근거 수집에 시간이 더 걸릴 수 있어 기존 120초보다 여유를 둠
    try:
        result = run_coroutine(_search(), timeout=180)
    except concurrent.futures.TimeoutError:
        raise RuntimeError("연합 검색 타임아웃 (180초)")
    except Exception:
        traceback.print_exc()
        raise

    elapsed = time.time() - start_time
    answer, source_ids = result
    print(f"[FEDERATED][lightrag] 검색 완료: {elapsed:.2f}초, 계정 {len(accounts_paths)}개, mode={mode}")

    # source_ids에서 실제로 인용된 계정만 refer_kg에 남긴다 (인용이 없으면 refer_kg는 비워둠)
    referenced = []
    seen_accounts = set()
    for s in source_ids:
        acc = s.get("account")
        if acc and acc not in seen_accounts:
            seen_accounts.add(acc)
            referenced.append(acc)
    _save_federated_query(
        accounts_paths, primary_user_id or accounts_paths[0].USER_ID,
        original_message, elapsed, mode, answer, referenced,
    )
    return answer, source_ids


# app.py 호환용 얇은 래퍼 — mode="local"로 run_federated_search를 호출한다
def run_federated_local_search(message: str, original_message: str, accounts_paths: list,
                                primary_user_id: str = None, per_account_max_tokens: int = 3000) -> tuple[str, list]:
    return run_federated_search(message, original_message, accounts_paths, "local",
                                 primary_user_id=primary_user_id, per_account_max_tokens=per_account_max_tokens)


# app.py 호환용 얇은 래퍼 — mode="global"로 run_federated_search를 호출한다
def run_federated_global_search(message: str, original_message: str, accounts_paths: list,
                                 primary_user_id: str = None) -> tuple[str, list]:
    return run_federated_search(message, original_message, accounts_paths, "global",
                                 primary_user_id=primary_user_id)


# LightRAG가 지원하는 질의 모드 6개. QueryParam(mode=...)에 그대로 들어가는 값이라
# 여기 없는 문자열이 들어오면 LightRAG 쪽에서 에러가 난다.
_VALID_MODES = ("local", "global", "hybrid", "naive", "mix", "bypass")

# 질문에 가장 적합한 LightRAG 검색 모드를 LLM으로 분류해 6개 모드 중 하나를 반환한다 (실패 시 "mix")
def _classify_query_method(message: str) -> str:
    prompt = f"""다음 질문에 가장 적합한 검색 모드를 아래 6개 중 하나만 골라 그 이름만 반환하라.

                - local: 특정 메일·인물·날짜·주제에 대한 구체적인 질문 (특정 엔티티 중심)
                - global: 전체 경향·요약·패턴·빈도 같은 폭넓은 질문 (전체 관계망 중심)
                - hybrid: 구체적인 근거와 전체적인 맥락이 둘 다 필요한 질문
                - naive: 특정 문구·키워드가 포함된 메일을 그대로 찾기만 하면 되는 단순 검색
                - mix: 위 성격이 애매하게 섞여 있거나 판단이 어려운 일반적인 질문 (기본값)
                - bypass: 메일 데이터와 무관한 일반 대화·인사말 등 검색이 필요 없는 질문

                질문: {message}"""

    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,  # 지정 시 로컬 Qwen으로 라우팅
    )

    res = client.chat.completions.create(
        model=os.environ.get("SUB_TASK_CHAT_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=10,  # SUB_TASK_CHAT_MODEL이 gpt-5 계열이면 max_tokens 대신 이 파라미터를 받는다
        temperature=0
    )

    method = res.choices[0].message.content.strip().lower()
    print(f"[CLASSIFY][lightrag] 질의: {message[:30]} → {method}")
    # LightRAG 자체가 mix를 "가장 무난한 기본 모드"로 권장하므로, 애매하거나 분류가
    # 실패했을 때의 기본값도 GraphRAG 시절의 "local"이 아니라 "mix"로 바꿨다.
    return method if method in _VALID_MODES else "mix"
