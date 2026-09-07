# 캐싱된 LocalSearch/GlobalSearch 엔진을 직접 호출해 단일·다중 계정 질의에 답변하고, 근거 메일 ID와 질의 로그를 정리해 저장한다.

# Calls the cached LocalSearch/GlobalSearch engines directly to answer single- or multi-account queries, then organizes and saves the supporting mail IDs and query logs.

import os
import re
import json
import asyncio # 비동기 실행 지원
import traceback
import threading
import time
import openai
from dotenv import load_dotenv

from util.graphrag_engine import get_engines, get_and_reset_usage # 유저별 캐싱된 local. global 엔진 반환 함수 임포트
from util.database.db_writer import save_query_to_db
from config.settings import MAIL_BLOCK_SEP

load_dotenv("src/parquet/.env")

# 연합 검색 결과를 query 테이블에 1행으로 저장한다 (참여 계정들의 토큰 사용량 총합, 인용 계정은 refer_kg에 기록)
def _save_federated_query(accounts_paths: list, primary_user_id: str, original_message: str,
                           elapsed: float, method: str, answer: str, refer_accounts: list = None):
    total_input = 0
    total_output = 0
    model_name = None
    for paths in accounts_paths:
        usage = get_and_reset_usage(paths.USER_ID, method)
        total_input += usage["input_tokens"]
        total_output += usage["output_tokens"]
        if not model_name and usage["model_name"]:
            model_name = usage["model_name"]

    # 어떤 계정이 실제로 근거가 됐는지 확신할 수 없으면 그냥 비워둠
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
        id_m = re.search(r'^\[ID\]\s*(.+?)\s*$', block, re.MULTILINE)
        sender_m = re.search(r'^\[발신인\]\s*(.+?)\s*$', block, re.MULTILINE)
        if id_m and sender_m:
            sender_map[id_m.group(1).strip().lower()] = sender_m.group(1).strip()
    return sender_map

# 추출한 메일 ID 끝에 붙은 문장부호(대괄호·마침표 등)를 제거한다
def _strip_id_punct(mail_id: str) -> str:
    return mail_id.strip(']),.;:》」』')

# 메일 ID가 올바른지 판단한다 (LLM이 순번 "2" 등을 ID로 잘못 쓴 짧은 숫자는 걸러냄)
def _is_plausible_mail_id(mail_id: str) -> bool:
    return not (mail_id.isdigit() and len(mail_id) <= 6)

# 두 문자열 사이 최장 연속 공통 부분문자열의 길이를 계산한다 (동적 계획법)
def _longest_common_substring_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        curr = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
        prev = curr
    return best

# 메일 제목 앞의 회신/전달 표시(RE:, FW:, 회신:, 전달: 등)를 반복해서 제거한다
def _strip_reply_forward_prefix(subject: str) -> str:
    s = subject.strip()
    while True:
        stripped = re.sub(r'^\s*(fw|fwd|re|회신|전달)\s*[:：]\s*', '', s, flags=re.IGNORECASE)
        if stripped == s:
            return s
        s = stripped

# LLM이 답변 맨 앞에 되풀이한 "> 질문" 줄을 제거한다
def _strip_echoed_question(answer: str) -> str:
    return re.sub(r'^>.*\n+', '', answer)

# 문장 종결 "~다."를 "~습니다."/"~ㅂ니다."로 바꿔 존댓말로 통일한다. 답변이 문단마다 반말
# ("논의되었다", "보인다")과 존댓말이 섞여 나오는 문제 대응 — 한글 음절을 초성/중성/종성으로
# 분해해 일반 규칙으로 변환함: "다." 바로 앞 음절의 받침이
#   - 없음(모음으로 끝남, 예: "이다.") → 그 음절에 받침 'ㅂ'을 붙이고 "다."를 "니다."로
#   - 'ㄴ'(예: "보인다.") → 받침을 'ㅂ'으로 바꾸고 "다."를 "니다."로 (예: "보입니다.")
#   - 그 외 받침(예: "았다."/"었다.") → 음절은 그대로 두고 "다."만 "습니다."로 (예: "논의되었습니다.")
# 이미 존댓말인 "~습니다."/"~ㅂ니다."는 "다." 앞 음절이 항상 받침 없는 "니"라서, "니" 앞
# 음절이면 손대지 않고 그대로 둬 이중 변환을 막음. 실제로 누군가 한 말을 그대로 옮긴
# 따옴표 안 인용문은 화자의 말투를 바꾸면 안 되므로 이 변환에서 제외함.
_DA_ENDING_RE = re.compile(r'([\uac00-\ud7a3])다\.')

def _convert_da_ending_to_polite(match: "re.Match") -> str:
    prev = match.group(1)
    if prev == '니':  # 이미 "~습니다."/"~ㅂ니다."인 경우 — 그대로 둠
        return match.group(0)
    code = ord(prev) - 0xAC00
    final = code % 28
    medial = (code // 28) % 21
    initial = code // (28 * 21)
    if final in (0, 4):  # 받침 없음, 또는 받침 'ㄴ' → 받침을 'ㅂ'으로 바꾸고 "니다."
        new_char = chr(0xAC00 + (initial * 21 + medial) * 28 + 17)
        return f"{new_char}니다."
    return f"{prev}습니다."  # 그 외 받침(과거형 등) → "다."만 "습니다."로

def _apply_polite_form(text: str) -> str:
    quotes = []

    def _stash_quote(m):
        quotes.append(m.group(0))
        return f"\x00{len(quotes) - 1}\x00"

    stashed = re.sub(r'[“"]([^”"]*)[”"]', _stash_quote, text)  # 실제 발언 인용문은 말투를 안 바꿈
    converted = _DA_ENDING_RE.sub(_convert_da_ending_to_polite, stashed)
    return re.sub(r'\x00(\d+)\x00', lambda m: quotes[int(m.group(1))], converted)

# 소제목처럼 보이는 줄("학회 등록·결제" 등 — 앞뒤가 빈 줄이고 문장부호로 안 끝나는 짧은
# 단독 줄)을 <소제목> 형태로 감싸 본문과 구분되게 한다
def _wrap_heading_lines(text: str) -> str:
    lines = text.split('\n')
    result = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_blank = i == len(lines) - 1 or not lines[i + 1].strip()
        has_following_content = any(l.strip() for l in lines[i + 1:])  # 뒤에 아무 내용도 없으면(답변 전체가 이 한 줄뿐인 경우 포함) 소제목이 아니라 그냥 답변 본문임
        is_heading = (
            stripped
            and len(stripped) <= 20
            and not re.search(r'[.?!]$', stripped)
            and not re.match(r'^[-*]\s', stripped)
            and not re.match(r'^\d{4}-\d{2}-\d{2}', stripped)
            and prev_blank and next_blank and has_following_content
        )
        result.append(f"<{stripped}>" if is_heading else line)
    return '\n'.join(result)

# 화면 표시용으로 답변을 정리한다 (불릿 줄바꿈 정규화, ID/계정 줄 제거, 빈 번호 줄 정리,
# 존댓말 통일, 소제목 줄 강조)
# 모델이 'ID:'/'계정:' 값을 대괄호로 감싸 쓰는 경우(예: "[ID: 값]")까지 지우도록 대괄호를
# 선택적으로 함께 매칭함 — 안 그러면 "\S+"가 닫는 대괄호까지 통째로 먹어치우고 여는
# 대괄호만 홀로 남아 화면에 "[" 한 글자가 떠다니는 문제가 생김.
def strip_ids_for_display(text: str) -> str:
    # "— 제목: ... — 내용: ..."처럼 여러 필드를 줄바꿈 대신 대시(—)로 이어붙여 한 줄에
    # 몰아 쓰는 경우가 있어 필드마다 줄을 분리함. "제목:" 앞이면 새 항목이 시작된 것으로
    # 보고 불릿을 붙이고, 같은 항목의 "날짜:"/"내용:"은 불릿 없이 다음 줄로만 내림.
    text = re.sub(r'(?<=\S)[ \t]*[—–][ \t]*(?=제목\s*:)', '\n- ', text)
    text = re.sub(r'(?<=\S)[ \t]*[—–][ \t]*(?=(날짜|내용)\s*:)', '\n', text)
    # 줄 맨 앞의 불릿으로 대시(—/–)를 쓴 경우 하이픈(-) 불릿으로 통일함(다른 곳은 전부
    # "- " 불릿이라 대시가 섞이면 스타일이 들쭉날쭉해 보임)
    text = re.sub(r'^[—–][ \t]*', '- ', text, flags=re.MULTILINE)
    text = re.sub(r'(?<!\n) - (?=\S)', '\n- ', text)
    text = re.sub(r'^[ \t]*\[?[ \t]*[-*]?[ \t]*(ID|계정):\s*[^\s\]]+\]?[ \t]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[?(ID|계정):\s*[^\s\]]+\]?', '', text)
    text = re.sub(r'^[ \t]*(?:\d+[.)]|[-*])[ \t]*$', '', text, flags=re.MULTILINE)
    # 위 단계들이 인용 표기를 지우는 과정에서 짝이 안 맞는 대괄호가 낱개로 남을 수 있어
    # (예: 모델이 인용을 쓰다 만 경우) 남은 대괄호는 통째로 제거함
    text = re.sub(r'[\[\]]', '', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    text = _apply_polite_form(text)
    text = _wrap_heading_lines(text)
    return text

# 캐시된 LocalSearch/GlobalSearch 엔진을 직접 호출해 단일 계정 질의 답변과 근거 메일 ID 목록을 반환하고 query 로그를 저장한다
def run_graphrag_query(message: str, original_message: str, paths, method: str = "local") -> tuple[str, list]:
    start_time = time.time()
    result_container = {"result": None, "error": None} # 스레드 간에 결과나 에러를 공유하기 위한 컨테이너

    # 새 이벤트 루프를 가진 별도 스레드에서 비동기 검색을 실행하고 결과/에러를 컨테이너에 담는다
    def _run():
        loop = asyncio.new_event_loop() # 현재 스레드 전용 새 이벤트 루프 생성
        asyncio.set_event_loop(loop) # 현재 스레드의 기본 루프로 설정
        try:
            # 엔진을 검색해 답변을 정제하고 근거 메일 ID를 추출한다
            async def _search():
                output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
                local_engine, global_engine = get_engines(paths.USER_ID, output_dir, paths.GRAPHRAG_ROOT) # 유저별 캐싱된 local + global 엔진 둘 다 가져오기 (캐시에서 재사용)
                engine = local_engine if method == "local" else global_engine
                result = await engine.search(message) # 엔진 객체 함수 호출
                answer = result.response # 검색 결과 객체에서 답변 텍스트 추출
                answer = _strip_echoed_question(answer) # 답변 맨 앞에 붙는 "> 질문 그대로" 줄 제거
                answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', answer) # graphrag가 답변에 삽입하는 출처 태그 제거
                answer = re.sub(r'\*+|#+', '', answer) # 마크다운 강조 기호 제거 (**, ## 등)
                answer = answer.strip() # 앞뒤 공백 제거

                # 1차: 답변 텍스트에서 실제로 인용한 ID를 추출함
                found = [_strip_id_punct(m) for m in re.findall(r'ID:\s*(\S+)', answer)]
                found = [m for m in found if _is_plausible_mail_id(m)]

                # 2차: 답변이 ID를 하나도 안 썼을 때(요약형 답변 등) — 예전엔 LLM에 넘긴
                # 컨텍스트(context_text) 전체에서 ID를 긁어와 폴백으로 썼는데, 이러면 답변은
                # 메일 3건만 요약했는데 컨텍스트에 포함된 무관한 메일 10여 건까지 전부 근거로
                # 붙어버리는 문제가 있었음(사용자가 실제로 겪어 지적함). 대신 컨텍스트의 각
                # 메일 제목이 답변 문장과 실제로 겹치는지 대조해서, 겹치는 제목의 메일만 후보로
                # 남김 — 답변이 제목을 그대로 베끼지 않고 풀어 쓰는 경우가 많아서 완전
                # 일치가 아니라 "충분히 길게" 겹치는 연속 부분문자열을 기준으로 삼음(제목
                # 길이의 40% 이상 & 최소 4자 — 실측 결과 진짜 인용된 제목은 50~70%대로 겹치고
                # 무관한 제목은 20% 이하로 뚜렷이 갈려서 이 임계값으로 결정함). 이 조건도
                # 못 넘는 항목은 후보에서 빠지는데, 무관한 근거를 잘못 붙이는 것보단 근거가
                # 없는 쪽이 정직함.
                ctx = result.context_text
                if isinstance(ctx, list):
                    ctx = '\n'.join(ctx)
                ctx_blocks = re.split(r'\n(?=\[ID\])', ctx) if isinstance(ctx, str) else []

                if not found:
                    for block in ctx_blocks:
                        id_m = re.search(r'^\[ID\]\s*(.+?)\s*$', block, re.MULTILINE)
                        subj_m = re.search(r'^\[제목\]\s*(.+?)\s*$', block, re.MULTILINE)
                        if not id_m or not subj_m:
                            continue
                        mail_id = _strip_id_punct(id_m.group(1))
                        if not _is_plausible_mail_id(mail_id) or mail_id in found:
                            continue
                        subject = _strip_reply_forward_prefix(subj_m.group(1))
                        if len(subject) < 2:
                            continue
                        overlap = _longest_common_substring_len(subject, answer)
                        if overlap >= max(4, len(subject) * 0.4):
                            found.append(mail_id)

                # 3차: 제목을 답변에 그대로 담지 않는 답변 유형(예: "네, ~라는 내용의 메일이
                # 있습니다"처럼 사실만 요약하고 제목은 언급 안 하는 경우)을 잡기 위해 메일
                # 본문과도 대조함. 본문은 제목보다 훨씬 길어서 조사/어미 같은 흔한 짧은
                # 겹침이 우연히 걸리기 쉬우므로 임계값을 20자로 제목(4자)보다 크게 높여
                # 우연한 일치를 걸러냄.
                if not found:
                    for block in ctx_blocks:
                        id_m = re.search(r'^\[ID\]\s*(.+?)\s*$', block, re.MULTILINE)
                        body_m = re.search(r'\[메일 본문\]\n(.*)', block, re.DOTALL)
                        if not id_m or not body_m:
                            continue
                        mail_id = _strip_id_punct(id_m.group(1))
                        if not _is_plausible_mail_id(mail_id) or mail_id in found:
                            continue
                        body = body_m.group(1).strip()
                        if len(body) < 10:
                            continue
                        overlap = _longest_common_substring_len(body, answer)
                        if overlap >= 20:
                            found.append(mail_id)

                # 4차(최후 보루): 그래도 하나도 못 찾았을 때 — 답변이 "메일을 못 찾았다"류의
                # 부정 답변이면 근거를 억지로 붙이는 게 오히려 거짓 근거라 그대로 두지만,
                # 부정 표현이 없다면(=뭔가 있다고 답한 것으로 보임) 검색 엔진이 가장 관련도
                # 높다고 판단해 컨텍스트 맨 앞에 배치한 메일 1건만 근거로 붙임. 사용자가
                # "메일 답변에는 근거가 항상 있어야 한다"고 요구해서 넣은 안전망이며, 개수를
                # 1건으로 제한해 무관한 메일이 무더기로 붙던 예전 문제가 재발하지 않게 함.
                if not found and ctx_blocks:
                    negative_patterns = [
                        '찾을 수 없', '찾지 못', '없습니다', '없어요', '없네요',
                        '확인되지 않', '관련된 메일이 없', '해당하는 메일이 없', '알 수 없',
                    ]
                    if not any(p in answer for p in negative_patterns):
                        for block in ctx_blocks:
                            id_m = re.search(r'^\[ID\]\s*(.+?)\s*$', block, re.MULTILINE)
                            if not id_m:
                                continue
                            mail_id = _strip_id_punct(id_m.group(1))
                            if _is_plausible_mail_id(mail_id):
                                found.append(mail_id)
                            break

                # 순서 유지하면서 중복 제거. 연합 검색(run_federated_local_search) 형태 통일
                seen = set()
                source_ids = []
                for id in found:
                    if id not in seen:
                        seen.add(id)
                        source_ids.append({"id": id, "account": paths.USER_ID})

                display_answer = strip_ids_for_display(answer)

                return display_answer, source_ids # 답변 텍스트와 근거 메일 ID 목록을 튜플로 반환

            result_container["result"] = loop.run_until_complete(_search())

        except Exception as e:
            traceback.print_exc()
            result_container["error"] = e
        finally:
            loop.close()

    # 완전히 새로운 스레드에서 _run 실행
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=120)  # 최대 120초 대기. 120초 넘어도 답이 안 오면 런타임에러 발생 및 CLI fallback로 넘어감.

    if t.is_alive():
        raise RuntimeError("graphrag 검색 타임아웃 (120초)")

    if result_container["error"]:
        raise result_container["error"]

    elapsed = time.time() - start_time
    print(f"[ENGINE] 검색 완료: {elapsed:.2f}초")
    answer, source_ids = result_container["result"]  # 언패킹
    print(f"[ENGINE] 답변: {answer}")
    print(f"[ENGINE] source_ids: {source_ids}")
    try:
        usage = get_and_reset_usage(paths.USER_ID, method)
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

# 여러 계정의 로컬 서치 컨텍스트를 계정별로 조립·병합해 답변을 한 번만 생성하고, 근거 메일 ID·계정을 반환한다
def run_federated_local_search(message: str, original_message: str, accounts_paths: list,
                                primary_user_id: str = None, per_account_max_tokens: int = 3000) -> tuple[str, list]:
    start_time = time.time()
    result_container = {"result": None, "error": None}

    # 새 이벤트 루프를 가진 별도 스레드에서 연합 로컬 검색을 실행한다
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 계정별 로컬 엔진 컨텍스트를 모아 답변을 생성하고 근거를 추출한다
            async def _search():
                engines = []
                for paths in accounts_paths:
                    try:
                        output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
                        local_engine, _ = get_engines(paths.USER_ID, output_dir, paths.GRAPHRAG_ROOT)
                        engines.append((paths, local_engine))
                    except Exception as e:
                        print(f"[FEDERATED] {paths.USER_ID} 엔진 로드 실패, 스킵: {e}")

                if not engines:
                    return "인덱싱된 계정이 없습니다.", []

                combined_chunks = []
                account_sender_maps = {}  # user_id -> {메일ID(소문자): 진짜 발신인 값}
                for paths, engine in engines:
                    context_result = engine.context_builder.build_context(
                        query=message,
                        **engine.context_builder_params,
                    )
                    chunk_text = context_result.context_chunks
                    if isinstance(chunk_text, list):
                        chunk_text = "\n".join(chunk_text)

                    # 계정 하나가 프롬프트 예산을 독점하지 않도록 계정별로 토큰 상한을 둠
                    tokens = engine.tokenizer.encode(chunk_text)
                    if len(tokens) > per_account_max_tokens:
                        chunk_text = engine.tokenizer.decode(tokens[:per_account_max_tokens])

                    account_sender_maps[paths.USER_ID] = _load_account_sender_map(paths)
                    used_tokens = min(len(tokens), per_account_max_tokens)
                    print(f"[FEDERATED] {paths.USER_ID}: 컨텍스트 {used_tokens}토큰, 보유 메일 {len(account_sender_maps[paths.USER_ID])}건")

                    combined_chunks.append(f"[계정: {paths.USER_ID}]\n{chunk_text}")

                merged_context = "\n\n".join(combined_chunks)

                # 답변 속 메일 ID로 원본 데이터를 찾아 (진짜 ID, 계정 user_id)를 반환한다 (완전일치→부분일치 순 완화, 실패 시 None,None)
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

                # 답변 생성 설정(system_prompt/model 등)은 계정마다 동일하므로 첫 번째 엔진 것을 그대로 재사용
                _, first_engine = engines[0]
                search_prompt = first_engine.system_prompt.format(
                    context_data=merged_context,
                    response_type=first_engine.response_type,
                )

                # 도메인마다 원본 블록의 필드 구성이 다르므로(이메일: 발신인/수신인, 카카오: 채팅방/참여자)도메인별로 분기한다.
                domain = engines[0][0].DOMAIN
                if domain == "messenger":
                    search_prompt += (
                        "\n\n추가 지시사항: 위 데이터는 서로 다른 여러 카카오톡 채팅방에서 수집되었으며, "
                        "각 데이터 블록 앞에 [계정: 채팅방이름] 형태로 출처 채팅방이 표시되어 있다. "
                        "질문과 관련된 내용이 여러 채팅방에 걸쳐 있다면 한쪽 채팅방에 치우치지 말고 "
                        "관련 있는 채팅방을 빠짐없이 골고루 다루되, 특정 채팅방에 관련 내용이 없으면 "
                        "그 채팅방은 억지로 언급하지 말고 실제로 관련 있는 내용만으로 답하라. "
                        "원본 데이터의 각 대화 블록은 'ID:'(날짜 기준 블록 식별자), '채팅방:', '참여자:' 필드를 "
                        "갖고 있고, 실제 발화 내용은 '[대화 내용]' 아래 'HH:MM 이름: 메시지' 형태로 적혀있다. "
                        "발화자를 언급할 때는 그 줄의 이름을 그대로 쓰고, 'ID:' 필드의 값을 발화자 이름 "
                        "자리에 쓰지 마라. "
                        "목록으로 나열하든 묶어서 요약하든 답변 형식과 무관하게, 실제로 언급/근거로 삼은 "
                        "대화 블록마다 'ID: 원본ID값'을 요약 문장에 섞어 쓰지 말고 그 항목의 별도 줄로 표기하라. "
                        "'ID:' 뒤에는 반드시 데이터에 있는 실제 ID 값을 정확히 그대로 옮겨 적어야 한다. "
                        "답변에서 대화를 1번, 2번처럼 순서대로 나열하더라도 그 순번을 'ID: 1', 'ID: 2'처럼 "
                        "ID인 것으로 쓰지 마라 — 그건 데이터에 없는 값을 지어내는 것이다. "
                        "그리고 언급/근거로 삼은 대화 블록마다 'ID:'와 같은 줄에 '계정: 채팅방이름' 줄도 "
                        "추가하라 — 그 대화가 어느 [계정: ...] 블록에서 나온 데이터인지, 컨텍스트에 표시된 "
                        "채팅방 이름을 정확히 그대로 옮겨 적어라."
                    )
                else:
                    search_prompt += (
                        "\n\n추가 지시사항: 위 데이터는 서로 다른 여러 이메일 계정에서 수집되었으며, "
                        "각 데이터 블록 앞에 [계정: 이메일주소] 형태로 출처 계정이 표시되어 있다. "
                        "질문과 관련된 내용이 여러 계정에 걸쳐 있다면 한쪽 계정에 치우치지 말고 "
                        "관련 있는 계정을 빠짐없이 골고루 다루되, 특정 계정에 관련 내용이 없으면 "
                        "그 계정은 억지로 언급하지 말고 실제로 관련 있는 내용만으로 답하라. "
                        "원본 데이터에는 메일마다 '[ID]'와 '[발신인]'이 서로 다른 별개 필드로 있으니 "
                        "절대 혼동하지 말 것 — 발신자를 쓸 때는 반드시 '[발신인]' 필드의 이메일 주소를 쓰고, "
                        "'[ID]' 필드의 값을 발신자 자리에 쓰지 마라. "
                        "목록으로 나열하든 묶어서 요약하든 답변 형식과 무관하게, 실제로 언급/근거로 삼은 "
                        "메일마다 'ID: 원본ID값'을 요약 문장에 섞어 쓰지 말고 그 메일 항목의 별도 줄로 표기하라. "
                        "'ID:' 뒤에는 반드시 데이터에 있는 실제 ID 값을 정확히 그대로 옮겨 적어야 한다. "
                        "답변에서 메일을 1번, 2번처럼 순서대로 나열하더라도 그 순번을 'ID: 1', 'ID: 2'처럼 "
                        "ID인 것으로 쓰지 마라 — 그건 데이터에 없는 값을 지어내는 것이다. "
                        "그리고 언급/근거로 삼은 메일마다 'ID:', '발신인:'과 같은 줄에 '계정: 이메일주소' 줄도 "
                        "추가하라 — 그 메일이 어느 [계정: ...] 블록에서 나온 데이터인지, 컨텍스트에 표시된 "
                        "계정 이메일 주소를 정확히 그대로 옮겨 적어라."
                    )
                
                
                messages = [
                    {"role": "system", "content": search_prompt},
                    {"role": "user", "content": message},
                ]

                # LocalSearch.search()는 model_params(예: temperature=0, frequency_penalty=0.4 —
                # 개방형 요약 질문에서 같은 문구를 반복하며 늘어지는 현상을 막기 위한 설정,
                # settings.yaml default_chat_model.call_args 참고)를 항상 completion_async에
                # 실어 보내는데, 이 연합 검색 경로는 model을 직접 호출하느라 그 설정이 안 실려서
                # 메신저 답변이 반복·중복되다 컨텍스트 한도에 걸려 잘리는 원인이 됐음 — 단일
                # 계정 경로와 동일하게 넣어줌
                full_response = ""
                response = await first_engine.model.completion_async(
                    messages=messages,
                    stream=True,
                    **first_engine.model_params,
                )
                async for chunk in response:
                    full_response += chunk.choices[0].delta.content or ""

                full_response = _strip_echoed_question(full_response) # 답변 맨 앞에 붙는 "> 질문 그대로" 줄 제거
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

                # 항목마다 ID가 있으면 그 ID로 진짜 소속 계정을 역추적
                found = [_strip_id_punct(m) for m in re.findall(r'ID:\s*(\S+)', answer)]
                found = [m for m in found if _is_plausible_mail_id(m)]
                seen = set()
                source_ids = []
                for id in found:
                    if id not in seen:
                        seen.add(id)
                        source_ids.append({"id": id, "account": _resolve_account(id)})

                if not source_ids:
                    # ID를 하나도 못 찾았을 때(요약형 답변 등)만 LLM이 쓴 '계정:' 값으로 폴백.
                    valid_accounts = {p.USER_ID.strip().lower(): p.USER_ID for p, _ in engines}
                    cited_accounts = []
                    for m in re.findall(r'계정:\s*(\S+)', answer):
                        real = valid_accounts.get(_strip_id_punct(m).strip().lower())
                        if real:
                            cited_accounts.append(real)
                    source_ids = [{"id": None, "account": acc} for acc in cited_accounts]

                display_answer = strip_ids_for_display(answer)

                return display_answer, source_ids

            result_container["result"] = loop.run_until_complete(_search())

        except Exception as e:
            traceback.print_exc()
            result_container["error"] = e
        finally:
            loop.close()

    # 계정 수가 많으면 컨텍스트 조립(임베딩 검색)에 시간이 더 걸릴 수 있어 기존 120초보다 여유를 둠
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=180)

    if t.is_alive():
        raise RuntimeError("연합 검색 타임아웃 (180초)")

    if result_container["error"]:
        raise result_container["error"]

    elapsed = time.time() - start_time
    answer, source_ids = result_container["result"]
    print(f"[FEDERATED] 검색 완료: {elapsed:.2f}초, 계정 {len(accounts_paths)}개")

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
        original_message, elapsed, "local", answer, referenced,
    )
    return answer, source_ids

# 여러 계정의 글로벌 서치를 연합한다 (map은 계정별, reduce는 전체를 모아 1회 실행해 비용 절감)
def run_federated_global_search(message: str, original_message: str, accounts_paths: list,
                                 primary_user_id: str = None) -> tuple[str, list]:
    start_time = time.time()
    result_container = {"result": None, "error": None}

    # 새 이벤트 루프를 가진 별도 스레드에서 연합 글로벌 검색을 실행한다
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 계정별 map 응답을 모아 reduce를 1회 실행해 최종 답변을 만든다
            async def _search():
                engines = []
                for paths in accounts_paths:
                    try:
                        output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
                        _, global_engine = get_engines(paths.USER_ID, output_dir, paths.GRAPHRAG_ROOT)
                        engines.append((paths, global_engine))
                    except Exception as e:
                        print(f"[FEDERATED-GLOBAL] {paths.USER_ID} 엔진 로드 실패, 스킵: {e}")

                if not engines:
                    return "인덱싱된 계정이 없습니다.", [], []

                all_map_responses = []
                for paths, engine in engines:
                    context_result = await engine.context_builder.build_context(
                        query=message,
                        **engine.context_builder_params,
                    )
                    # map: 커뮤니티 보고서 묶음마다 개별 LLM 호출 (계정별로 각자 실행)
                    map_responses = await asyncio.gather(*[
                        engine._map_response_single_batch(
                            context_data=data, query=message,
                            max_length=engine.map_max_length,
                            **engine.map_llm_params,
                        )
                        for data in context_result.context_chunks
                    ])
                    print(f"[FEDERATED-GLOBAL] {paths.USER_ID}: map 배치 {len(map_responses)}개")
                    all_map_responses.extend(map_responses)

                # reduce: 전체 계정의 map 결과를 모아 딱 1번만 합성 (계정 수와 무관하게 항상 1번)
                _, first_engine = engines[0]
                reduce_response = await first_engine._reduce_response(
                    map_responses=all_map_responses,
                    query=message,
                    **first_engine.reduce_llm_params,
                )

                reduce_text = _strip_echoed_question(reduce_response.response) # 답변 맨 앞에 붙는 "> 질문 그대로" 줄 제거
                answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', reduce_text)
                answer = re.sub(r'\*+|#+', '', answer)
                answer = answer.strip()

                # 글로벌 서치는 원래도 개별 메일을 인용하는 방식이 아니라(전체 경향/패턴 요약) 근거 계정이 없음.
                # 다만 map 단계가 실제로 돌아간 계정 목록은 확실하므로 refer_kg용으로 같이 반환한다.
                participated = [paths.USER_ID for paths, _ in engines]
                return answer, [], participated

            result_container["result"] = loop.run_until_complete(_search())

        except Exception as e:
            traceback.print_exc()
            result_container["error"] = e
        finally:
            loop.close()

    # map 단계가 계정 수만큼 늘어날 수 있어 넉넉하게 대기
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=240)

    if t.is_alive():
        raise RuntimeError("연합 글로벌 검색 타임아웃 (240초)")

    if result_container["error"]:
        raise result_container["error"]

    elapsed = time.time() - start_time
    answer, source_ids, participated = result_container["result"]
    print(f"[FEDERATED-GLOBAL] 검색 완료: {elapsed:.2f}초, 계정 {len(accounts_paths)}개")
    _save_federated_query(
        accounts_paths, primary_user_id or accounts_paths[0].USER_ID,
        original_message, elapsed, "global", answer, participated,
    )
    return answer, source_ids

# 질문이 로컬 검색용인지 글로벌 검색용인지 LLM으로 분류해 "local"/"global"을 반환한다
def _classify_query_method(message: str) -> str:
    prompt = f"""다음 질문이 로컬 검색(특정 메일·인물·날짜·주제)에 적합한지,
                글로벌 검색(전체 경향·요약·패턴·빈도)에 적합한지 판단하라.
                "local" 또는 "global" 중 하나만 반환하라.

                질문: {message}"""

    client = openai.OpenAI(
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("SUB_TASK_API_BASE") or None,
    )

    res = client.chat.completions.create(
        model=os.getenv("SUB_TASK_CHAT_MODEL"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    method = res.choices[0].message.content.strip().lower()
    print(f"[CLASSIFY] 질의: {message[:30]} → {method}")
    return method if method in ("local", "global") else "local"
