"""
global_context_all.py — global_search MAP 배치 사전 계산

핵심 발견: `GlobalCommunityContext.build_context()`의 `query` 인자는
`dynamic_community_selection`이 설정된 경우에만 배치 구성에 영향을 주는데, 이 앱은 이
옵션을 안 쓴다. `GlobalCommunityContext.__init__`의 `random_state` 기본값이 86으로
고정돼 있어서, 같은 도메인/방이면 MAP 배치 구성(어떤 community report가 어떤 배치에
들어가는지)이 모든 질문에 대해 완전히 동일함이 소스 코드로 확인됐다. 덕분에 도메인당
배치 세트를 한 번만 만들어두고 파일럿 질문 전체에 재사용할 수 있다 — 이 스크립트가
그 "한 번만 만들기"를 담당한다.

config: max_context_tokens=12000, data_max_tokens=12000, map_max_length=1000,
reduce_max_length=2000, use_community_summary=False, include_community_rank=True,
community_weight_name="occurrence weight", community_level=0

실측 배치 수: 메일 도메인(238개 level-0 커뮤니티) → 17개 배치, 메신저 도메인(13개 방)
→ 총 14개 배치(12개 방은 각 1배치, msg_1422f5f2만 2배치).

## English summary
global_context_all.py pre-computes the global_search MAP batches.

Key finding: `GlobalCommunityContext.build_context()`'s `query` argument only affects batch
composition when `dynamic_community_selection` is configured, which this app doesn't use.
`GlobalCommunityContext.__init__`'s `random_state` default is fixed at 86, so for a given
domain/room the MAP batch composition (which community report lands in which batch) is confirmed
by the source code to be identical across every question. That means the batch set only needs to
be built once per domain and reused across all pilot questions — this script is that one-time
build step.

config: max_context_tokens=12000, data_max_tokens=12000, map_max_length=1000,
reduce_max_length=2000, use_community_summary=False, include_community_rank=True,
community_weight_name="occurrence weight", community_level=0.

Measured batch counts: mail domain (238 level-0 communities) -> 17 batches; messenger domain (13
rooms) -> 14 batches total (12 rooms get 1 batch each, only msg_1422f5f2 gets 2).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from graphrag.query.structured_search.global_search.community_context import (
    GlobalCommunityContext,
)

GLOBAL_SEARCH_CONFIG = dict(
    max_context_tokens=12000,
    use_community_summary=False,
    include_community_rank=True,
    community_weight_name="occurrence weight",
    community_level=0,
)
RANDOM_STATE = 86  # GlobalCommunityContext 기본값 — 질문과 무관하게 배치 구성을 고정시킴


# 한 도메인(메일 또는 방)의 community_reports/entities로 MAP 배치 텍스트 리스트를 한 번 계산함
def build_batches_for_domain(community_reports_df, entities_df) -> list[str]:
    """query 인자를 안 쓰므로(dynamic_community_selection 미사용), 아무 placeholder
    질문으로 build_context를 호출해도 배치 구성은 항상 동일하다."""
    ctx = GlobalCommunityContext(
        community_reports=community_reports_df,
        entities=entities_df,
        random_state=RANDOM_STATE,
    )
    # query는 배치 구성에 영향을 주지 않으므로 placeholder 사용
    context_result = ctx.build_context(query="__batch_precompute_placeholder__", **GLOBAL_SEARCH_CONFIG)
    # context_result.context_chunks는 배치별 텍스트 리스트 (구현체에 따라 str 하나로 올 수도 있어
    # extract_global_batches.py에서 실제 분리 로직을 담당)
    return context_result.context_chunks


# CLI 엔트리포인트: 메일 도메인과 방별(messenger) 도메인의 MAP 배치를 계산해 텍스트 파일로 저장함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mail-community-reports", type=Path, required=True)
    parser.add_argument("--mail-entities", type=Path, required=True)
    parser.add_argument("--messenger-root", type=Path, required=True,
                         help="방별 community_reports.parquet/entities.parquet가 있는 루트")
    parser.add_argument("--out-dir", type=Path, default=Path("global_batches"))
    args = parser.parse_args()

    import pandas as pd

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # 메일 도메인
    mail_reports = pd.read_parquet(args.mail_community_reports)
    mail_entities = pd.read_parquet(args.mail_entities)
    mail_batches = build_batches_for_domain(mail_reports, mail_entities)
    mail_dir = args.out_dir / "mail"
    mail_dir.mkdir(exist_ok=True)
    for i, batch_text in enumerate(mail_batches):
        (mail_dir / f"batch_{i:02d}.txt").write_text(batch_text, encoding="utf-8")
    print(f"메일: {len(mail_batches)}개 배치 -> {mail_dir}")

    # 메신저 도메인 (방별)
    for room_dir in sorted(args.messenger_root.glob("msg_*")):
        reports_path = room_dir / "community_reports.parquet"
        entities_path = room_dir / "entities.parquet"
        if not (reports_path.exists() and entities_path.exists()):
            continue
        room_reports = pd.read_parquet(reports_path)
        room_entities = pd.read_parquet(entities_path)
        room_batches = build_batches_for_domain(room_reports, room_entities)
        room_out = args.out_dir / "messenger" / room_dir.name
        room_out.mkdir(parents=True, exist_ok=True)
        for i, batch_text in enumerate(room_batches):
            (room_out / f"batch_{i:02d}.txt").write_text(batch_text, encoding="utf-8")
        print(f"{room_dir.name}: {len(room_batches)}개 배치 -> {room_out}")


if __name__ == "__main__":
    main()
