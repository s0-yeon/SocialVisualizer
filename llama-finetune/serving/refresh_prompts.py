"""
configs/*.json(local_search 프롬프트 규칙)만 바꿨을 때, 이미 인덱싱된 계정들의
prompts/local_search.txt를 재인덱싱 없이 최신 내용으로 갱신하는 스크립트.

extract_graph 같은 무거운 LLM 인덱싱 작업은 전혀 다시 돌리지 않는다 — 이미 인덱싱된
entities/relationships는 그대로 두고, 검색 시 시스템 프롬프트로 쓰이는
prompts/local_search.txt 파일 하나만 최신 config 기준으로 다시 렌더링해서 계정마다
덮어쓴다. reembed_entities.py의 _refresh_settings_yaml()이 settings.yaml을 갱신하는
것과 정확히 같은 패턴.

동작:
1. parquet_template/src/renderer.py의 render_all_prompts()를 호출해
   parquet_template/rendered/{domain}/prompts/local_search.txt를 최신 config.json
   기준으로 재생성한다 (config.json이 settings.yaml보다 최신일 때만 실제로 재생성됨 —
   renderer.py의 mtime 비교 로직 그대로 재사용).
2. user_data/{domain}/{계정}/graphrag/parquet/prompts/local_search.txt를 방금
   재생성된 rendered 파일로 덮어쓴다.

사용법 (저장소 루트에서, venv 활성화한 상태로 실행 — 파일 위치는
llama-finetune/serving/이지만 실행 경로는 저장소 루트 기준):
    python llama-finetune/serving/refresh_prompts.py                       # mail+messenger 전체, 인덱싱된 계정 전부
    python llama-finetune/serving/refresh_prompts.py messenger              # messenger 도메인 전체
    python llama-finetune/serving/refresh_prompts.py mail                   # mail 도메인 전체
    python llama-finetune/serving/refresh_prompts.py messenger <계정ID>      # 특정 계정 1개만

실행 후에는 Flask 서버를 재시작해야 한다 — get_engines()가 프로세스 내에서 엔진을
캐싱해두기 때문에, 파일만 바꾸고 서버를 안 껐다 켜면 캐시된 예전 엔진(예전 프롬프트가
이미 물려있는 LocalSearch 객체)을 계속 재사용해서 이 스크립트의 변경이 반영 안 된다.

주의: reembed_entities.py와 마찬가지로 이 파일은 llama-finetune/serving/ 안에
있어야 한다(저장소 루트 기준 2단계 아래) — BASE_DIR을 이 파일 위치에서 3단계 위로
고정 계산해서 CWD와 무관하게 항상 저장소 루트를 가리키게 했다.
"""

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # llama-finetune/serving/에서 3단계 위 = MailGrapher 저장소 루트
sys.path.insert(0, str(BASE_DIR / "parquet_template" / "src"))
from renderer import render_all_prompts  # noqa: E402  (reportMissingImports 무시: sys.path.insert가 런타임에만 반영되는 동적 경로라 정적 분석기가 못 찾는 오탐)

USER_DATA_DIR = BASE_DIR / "user_data"
RENDERED_DIR = BASE_DIR / "parquet_template" / "rendered"


def discover_accounts(domains=("mail", "messenger")) -> list[tuple[str, Path]]:
    """output/entities.parquet가 실제로 있는(=이미 인덱싱된) 계정만 골라낸다."""
    roots: list[tuple[str, Path]] = []
    for domain in domains:
        domain_dir = USER_DATA_DIR / domain
        if not domain_dir.exists():
            continue
        for account_dir in sorted(domain_dir.iterdir()):
            if not account_dir.is_dir():
                continue
            graphrag_root = account_dir / "graphrag" / "parquet"
            if (graphrag_root / "output" / "entities.parquet").exists():
                roots.append((domain, graphrag_root))
    return roots


def refresh_account(domain: str, graphrag_root: Path) -> None:
    src = RENDERED_DIR / domain / "prompts" / "local_search.txt"
    if not src.exists():
        raise FileNotFoundError(f"렌더링된 프롬프트를 찾을 수 없음: {src}")
    dst_dir = graphrag_root / "prompts"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_dir / "local_search.txt")


def main(argv: list[str]) -> None:
    print("[1/2] config.json 기준으로 parquet_template/rendered/*/prompts/local_search.txt 재생성")
    render_all_prompts()

    if not argv:
        accounts = discover_accounts()
    elif len(argv) == 1:
        accounts = discover_accounts(domains=(argv[0],))
    else:
        domain, account_id = argv[0], argv[1]
        accounts = [(domain, USER_DATA_DIR / domain / account_id / "graphrag" / "parquet")]

    if not accounts:
        print("대상 계정을 찾지 못했습니다 (output/entities.parquet가 있는 계정이 없음).")
        return

    print(f"\n[2/2] 총 {len(accounts)}개 계정의 prompts/local_search.txt 갱신 시작\n")
    ok, fail = 0, 0
    for i, (domain, graphrag_root) in enumerate(accounts, 1):
        print(f"[{i}/{len(accounts)}] ({domain}) {graphrag_root}")
        try:
            refresh_account(domain, graphrag_root)
        except Exception as e:
            print(f"    실패: {e}")
            fail += 1
        else:
            print("    완료")
            ok += 1

    print(f"\n총 {len(accounts)}개 중 성공 {ok}개, 실패 {fail}개")
    print("Flask 서버를 재시작해야 캐시된 엔진이 새 프롬프트를 읽어들입니다.")


if __name__ == "__main__":
    main(sys.argv[1:])
