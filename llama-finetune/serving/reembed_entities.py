"""
엔티티 임베딩만 다시 생성하는 스크립트 (전체 재인덱싱 불필요)

extract_graph / summarize_descriptions / community_reports 같은 무거운 LLM 작업은
전혀 다시 돌리지 않는다 — entities.parquet에 이미 저장돼 있는 description을
그대로 재사용해서, output/lancedb의 entity_description 벡터스토어만 새로 만든다.
graphrag가 정상 인덱싱 때 쓰는 것과 똑같은 내부 워크플로우 함수
(graphrag.index.workflows.generate_text_embeddings.run_workflow)를 그대로 재사용하므로
별도로 lancedb 스키마를 직접 다룰 필요가 없다.

'로컬용', 'OpenAI용' 스크립트를 따로 두지 않는다 — 이 스크립트는 그때그때
src/parquet/.env 의 INDEXING_EMBEDDING_MODEL / INDEXING_EMBEDDING_API_BASE 가
가리키는 임베딩 모델을 그대로 따라간다. 즉:
  - 지금(.env가 OpenAI를 가리킴) 돌리면 → 로컬 → OpenAI 전환
  - 나중에 .env를 다시 로컬(bge-m3)로 돌려놓고 똑같이 돌리면 → OpenAI → 로컬 전환
어느 쪽이든 이 스크립트 하나로 처리된다.

실행 전 각 계정의 settings.yaml을 parquet_template/rendered/<domain>/settings.yaml
템플릿으로 새로 덮어쓴다 — ${...} 환경변수 자리가 최신 상태로 반영되게 하기 위함
(평소 인덱싱 때 [INIT] 단계가 하는 것과 동일).

중요: settings.yaml은 vector_size를 선언하지 않으므로 로드 시 항상 정적 기본값
(3072, text-embedding-3-large 기준)으로 잡힌다. 실제 `graphrag index` CLI는
색인 시작 전에 graphrag.index.validate_config._sync_vector_store_dimensions()를 돌려서
"진짜" 임베딩 모델을 한 번 호출해보고 그 응답 차원(예: text-embedding-3-small=1536,
bge-m3=1024)으로 vector_size/index_schema를 실시간 보정한다. 이 스크립트는 CLI를 타지
않고 load_config()만 쓰기 때문에 이 보정이 빠져서, 항상 3072로 테이블을 만들려다
"Vector for document ... has dimension 1536, but index ... is configured with
vector_size 3072" 에러가 났었다. 아래 _sync_vector_store_dimensions()가 그 보정 로직을
그대로 복제한 것 — graphrag/index/validate_config.py의 동명 함수와 동일한 동작이다
(단, 관련 없는 completion_models 전체를 검증하고 실패 시 sys.exit(1)하는 부분은
가져오지 않았다 — 여긴 재임베딩 스크립트라 임베딩 모델 하나만 확인하면 충분하다).

사용법 (저장소 루트에서, venv 활성화한 상태로 실행 — 파일 위치는
llama-finetune/serving/이지만 실행 경로는 저장소 루트 기준):
    python llama-finetune/serving/reembed_entities.py                       # mail+messenger 전체, 인덱싱된 계정 전부
    python llama-finetune/serving/reembed_entities.py messenger              # messenger 도메인 전체
    python llama-finetune/serving/reembed_entities.py mail                   # mail 도메인 전체
    python llama-finetune/serving/reembed_entities.py messenger <계정ID>      # 특정 계정 1개만

주의: 이 파일은 llama-finetune/serving/ 안에 있어야 한다(저장소 루트 기준 2단계
아래). src/util/ 안에 두면 같은 폴더의 앱 자체 파일 src/util/graphrag.py 가 진짜
graphrag 패키지 import를 가로채서 ModuleNotFoundError가 나기 때문에 거긴 피했고,
대신 BASE_DIR을 이 파일 위치에서 3단계 위(저장소 루트)로 고정 계산한다 — 어느
디렉터리에서 실행하든(CWD 무관) 항상 올바른 저장소 루트를 가리킨다.
"""

import asyncio
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # llama-finetune/serving/에서 3단계 위 = MailGrapher 저장소 루트
load_dotenv(BASE_DIR / "src" / "parquet" / ".env")

from graphrag.callbacks.noop_workflow_callbacks import NoopWorkflowCallbacks  # noqa: E402
from graphrag.config.load_config import load_config  # noqa: E402
from graphrag.index.run.utils import create_run_context  # noqa: E402
from graphrag.index.workflows.generate_text_embeddings import (  # noqa: E402
    run_workflow as run_generate_text_embeddings,
)
from graphrag_cache import CacheConfig, CacheType, create_cache  # noqa: E402
from graphrag_llm.embedding import create_embedding  # noqa: E402
from graphrag_storage import create_storage  # noqa: E402
from graphrag_storage.tables.table_provider_factory import create_table_provider  # noqa: E402

USER_DATA_DIR = BASE_DIR / "user_data"
TEMPLATE_DIR = BASE_DIR / "parquet_template" / "rendered"


def discover_accounts(domains=("mail", "messenger")) -> list[Path]:
    """output/entities.parquet가 실제로 있는(=이미 인덱싱된) 계정만 골라낸다."""
    roots: list[Path] = []
    for domain in domains:
        domain_dir = USER_DATA_DIR / domain
        if not domain_dir.exists():
            continue
        for account_dir in sorted(domain_dir.iterdir()):
            if not account_dir.is_dir():
                continue
            graphrag_root = account_dir / "graphrag" / "parquet"
            if (graphrag_root / "output" / "entities.parquet").exists():
                roots.append(graphrag_root)
    return roots


def _refresh_settings_yaml(graphrag_root: Path) -> None:
    """평소 인덱싱 [INIT] 단계와 동일하게, 도메인 템플릿으로 settings.yaml을 덮어쓴다."""
    domain = graphrag_root.relative_to(USER_DATA_DIR).parts[0]  # "mail" | "messenger"
    template_path = TEMPLATE_DIR / domain / "settings.yaml"
    if not template_path.exists():
        raise FileNotFoundError(f"settings.yaml 템플릿을 찾을 수 없음: {template_path}")
    shutil.copy2(template_path, graphrag_root / "settings.yaml")


async def _sync_vector_store_dimensions(config) -> None:
    """graphrag.index.validate_config._sync_vector_store_dimensions()와 동일한 로직.

    실제 인덱싱용 임베딩 모델(config.embed_text.embedding_model_id)을 한 번 호출해서
    응답 벡터의 실제 차원을 확인하고, config.vector_store.vector_size 및
    index_schema의 모든 항목의 vector_size를 그 값으로 맞춘다. settings.yaml이
    vector_size를 선언하지 않는 한 load_config() 직후엔 항상 정적 기본값(3072)이라,
    이 보정을 안 하면 실제 임베딩 모델(1536, 1024 등)과 불일치가 난다.
    """
    model_id = config.embed_text.embedding_model_id
    model_cfg = config.embedding_models[model_id]
    embed_llm = create_embedding(model_cfg)

    response = await embed_llm.embedding_async(input=["dimension probe"])
    detected = len(response.first_embedding)
    if detected == 0:
        print("    경고: 임베딩 차원 감지 실패 (빈 응답), vector_size 보정 생략")
        return

    configured = config.vector_store.vector_size
    if detected == configured:
        print(f"    vector_size 이미 일치: {configured}")
        return

    print(f"    vector_size 보정: {configured} -> {detected} (실제 임베딩 모델 응답 기준)")
    config.vector_store.vector_size = detected
    for schema in config.vector_store.index_schema.values():
        schema.vector_size = detected


async def reembed_account(graphrag_root: Path) -> None:
    _refresh_settings_yaml(graphrag_root)

    # load_config가 내부적으로 os.chdir(graphrag_root)까지 처리함 (set_cwd 기본값 True)
    config = load_config(graphrag_root)

    model_id = config.embed_text.embedding_model_id
    model_cfg = config.embedding_models[model_id]
    print(f"    임베딩 모델: {model_cfg.model}  api_base={model_cfg.api_base or '(OpenAI 기본)'}")

    # graphrag index CLI가 색인 시작 전에 하는 vector_size 실시간 보정을 여기서도 재현
    await _sync_vector_store_dimensions(config)

    output_storage = create_storage(config.output_storage)
    output_table_provider = create_table_provider(config.table_provider, output_storage)
    # 기본 캐시(Json, 파일 기반)를 그대로 쓰면 같은 엔티티 설명 텍스트에 대해
    # 예전 모델(로컬 bge-m3 등)로 계산해둔 임베딩을 그대로 재사용해버린다 —
    # vector_size는 새 모델 기준으로 고쳐놨는데 실제 값은 옛날 차원 그대로 나와서
    # "dimension 1024, but index ... configured with vector_size 1536" 같은 불일치가 난다.
    # 재임베딩의 목적 자체가 "다른 모델로 다시 계산"이므로 캐시를 아예 끄고
    # 매번 실제 임베딩 API를 새로 호출하게 강제한다.
    cache = create_cache(CacheConfig(type=CacheType.Noop))

    context = create_run_context(
        output_storage=output_storage,
        output_table_provider=output_table_provider,
        cache=cache,
        callbacks=NoopWorkflowCallbacks(),
    )

    await run_generate_text_embeddings(config, context)


async def main(argv: list[str]) -> None:
    if not argv:
        accounts = discover_accounts()
    elif len(argv) == 1:
        accounts = discover_accounts(domains=(argv[0],))
    else:
        domain, account_id = argv[0], argv[1]
        accounts = [USER_DATA_DIR / domain / account_id / "graphrag" / "parquet"]

    if not accounts:
        print("대상 계정을 찾지 못했습니다 (output/entities.parquet가 있는 계정이 없음).")
        return

    print(f"총 {len(accounts)}개 계정 재임베딩 시작\n")
    ok, fail = 0, 0
    for i, graphrag_root in enumerate(accounts, 1):
        print(f"[{i}/{len(accounts)}] {graphrag_root}")
        try:
            await reembed_account(graphrag_root)
        except Exception as e:
            print(f"    실패: {e}")
            fail += 1
        else:
            print("    완료")
            ok += 1

    print(f"\n총 {len(accounts)}개 중 성공 {ok}개, 실패 {fail}개")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
