# output 폴더에 단계별 parquet 파일이 얼마나 생겼는지 보고 GraphRAG 인덱싱 진행률과 완료 단계 메시지를 계산한다.

# Computes GraphRAG indexing progress and stage-completion messages by checking which per-stage parquet files have appeared in the output folder.

import re
import os

# output 폴더에 단계별 parquet이 얼마나 생겼는지 보고 인덱싱 진행률/메시지 목록을 계산한다
def get_stage_progress(output_dir, start_time, reported_progress=0):
    stage_map = [
        ("text_units.parquet",        15, "텍스트 유닛 생성 완료"),
        ("documents.parquet",         25, "문서 처리 완료"),
        ("entities.parquet",          65, "엔티티 추출 완료"),
        ("relationships.parquet",     75, "관계 추출 완료"),
        ("communities.parquet",       82, "커뮤니티 생성 완료"),
        ("community_reports.parquet", 95, "커뮤니티 리포트 생성 완료"),
    ]

    if not os.path.isdir(output_dir):
        return []

    try:
        entries = set(os.listdir(output_dir))
    except OSError:
        return []

    results = []
    for filename, prog, msg in stage_map:
        if prog <= reported_progress:
            continue
        if filename not in entries:
            continue
        try:
            if os.path.getmtime(os.path.join(output_dir, filename)) > start_time:
                results.append((prog, msg))
        except OSError:
            pass

    return results  # stage_map 순서 그대로 (낮은 % → 높은 %)