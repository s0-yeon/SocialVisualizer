# src/util/lightrag_backend/lightrag_progress.py

# LightRAG 인덱싱 진행률 계산 모듈. 
# LightRAG가 내부적으로 남기는 kv_store_doc_status.json의 문서별 처리 상태를 읽어 처리 완료 비율을 구하고, job_run_lightrag.py가 미리 정해둔 30~90 진행률 구간에 매핑해 프런트에 보여줄 (진행률, 메시지) 목록으로 반환한다.

# Computes LightRAG indexing progress. 
# Reads per-document processing status from LightRAG's own kv_store_doc_status.json, turns it into a completion ratio, and maps that onto the 30-90 progress range reserved by job_run_lightrag.py, returning(progress, message) pairs for the frontend.

import os
import json

# job_run_lightrag.py가 인덱싱 시작 시 이미 progress=30으로 세팅해두고, 완료 후 90으로
# 올리므로, 그 사이(30~90) 구간을 문서 처리 비율로 채운다.
_PROGRESS_START = 30
_PROGRESS_END = 90

# 더 이상 상태가 안 바뀌는(=끝난) 상태들. 실패한 문서도 "처리는 끝났다"는 의미로 포함한다.
_TERMINAL_STATUSES = ("processed", "failed")


# kv_store_doc_status.json에서 처리 끝난 문서 비율을 계산해 진행률/메시지를 반환한다
def get_stage_progress(working_dir, start_time, reported_progress=0):
    status_path = os.path.join(working_dir, "kv_store_doc_status.json")
    if not os.path.exists(status_path):
        return []

    try:
        # 이전 인덱싱 실행이 남긴 파일이면 무시한다
        if os.path.getmtime(status_path) < start_time:
            return []
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    total = len(data)
    if total == 0:
        return []

    done = sum(1 for v in data.values() if v.get("status") in _TERMINAL_STATUSES)
    prog = _PROGRESS_START + int((_PROGRESS_END - _PROGRESS_START) * done / total)

    if prog <= reported_progress:
        return []

    msg = f"문서 처리 중 ({done}/{total})"
    return [(prog, msg)]
