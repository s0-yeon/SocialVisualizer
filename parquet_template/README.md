# parquet_template — GraphRAG 프롬프트 템플릿 시스템

GraphRAG는 인덱싱·질의에 쓰는 프롬프트와 `settings.yaml`을 파일로 읽는다.
이 디렉터리는 그 파일들을 **소셜 데이터 유형(도메인)별로 렌더링**하는 시스템이다.
원본은 Jinja2 템플릿(`.j2`) + 도메인 config(`.json`)이고, 렌더 결과가 실제 GraphRAG가 읽는 텍스트다.

```
src/prompts/*.j2  +  src/configs/{domain}.json
        │  renderer.py
        ▼
rendered/{domain}/prompts/*.txt   ← 인덱싱/질의 코드가 읽는 최종 프롬프트
rendered/{domain}/settings.yaml
```

`rendered/`는 생성물이라 git에 커밋하지 않는다.
인덱싱 job이 시작될 때 `renderer.render_all_prompts()`가 호출되어, config·템플릿보다 오래됐거나 없는 도메인만 다시 렌더링한다.

## 구성

| 경로 | 역할 |
|------|------|
| `src/prompts/*.j2` | 워크플로우별 프롬프트 템플릿 — `extract_graph`, `community_reports`, `local_search`, `global_search_{map,reduce,knowledge}`, `summarize_descriptions`, `summarize_attachment`, `extract_claims` |
| `src/prompts/settings.j2` | GraphRAG `settings.yaml` 템플릿 |
| `src/configs/{domain}.json` | 도메인별 값 — 현재 `mail`, `messenger` |
| `src/renderer.py` | 템플릿 + config → `rendered/{domain}/` 로 렌더링 (`PromptTemplate`, `render_all_prompts`) |
| `src/graphrag_patches/sitecustomize.py` | GraphRAG 런타임 패치 (`sys.path` 주입으로 적용) |

## 새 도메인 추가

1. `src/configs/<domain>.json` 작성 (기존 `mail.json` 참고)
2. 인덱싱 시 `render_all_prompts()`가 자동으로 `rendered/<domain>/` 생성
3. 프롬프트 문구를 바꾸려면 `.j2` 원본을 수정 — `rendered/`를 직접 고치지 말 것

## 관련

- 상위: [`README.md`](../README.md)
- 렌더된 프롬프트를 읽는 코드: [`src/util/`](../src/util/README.md)의 `graphrag_*`
- LightRAG 프롬프트는 별도: [`src/util/lightrag_backend/README.md`](../src/util/lightrag_backend/README.md)

---

# parquet_template — GraphRAG prompt template system

GraphRAG reads its indexing/query prompts and `settings.yaml` from files.
This directory is the system that **renders those files per social-data domain**.
The sources are Jinja2 templates (`.j2`) plus per-domain configs (`.json`); the rendered output is what GraphRAG actually reads.

```
src/prompts/*.j2  +  src/configs/{domain}.json
        │  renderer.py
        ▼
rendered/{domain}/prompts/*.txt   ← final prompts read by indexing/query code
rendered/{domain}/settings.yaml
```

`rendered/` is generated output and is not committed.
When an indexing job starts, `renderer.render_all_prompts()` re-renders only the domains that are missing or older than their config/templates.

## Layout

| Path | Role |
|------|------|
| `src/prompts/*.j2` | Per-workflow prompt templates — `extract_graph`, `community_reports`, `local_search`, `global_search_{map,reduce,knowledge}`, `summarize_descriptions`, `summarize_attachment`, `extract_claims` |
| `src/prompts/settings.j2` | GraphRAG `settings.yaml` template |
| `src/configs/{domain}.json` | Per-domain values — currently `mail`, `messenger` |
| `src/renderer.py` | Templates + config → `rendered/{domain}/` (`PromptTemplate`, `render_all_prompts`) |
| `src/graphrag_patches/sitecustomize.py` | GraphRAG runtime patch (applied via `sys.path` injection) |

## Adding a new domain

1. Write `src/configs/<domain>.json` (use `mail.json` as a reference)
2. `render_all_prompts()` auto-creates `rendered/<domain>/` at indexing time
3. To change prompt wording, edit the `.j2` source — never edit `rendered/` directly

## Related

- Parent: [`README.md`](../README.md)
- Code that reads rendered prompts: `graphrag_*` in [`src/util/`](../src/util/README.md)
- LightRAG prompts are separate: [`src/util/lightrag_backend/README.md`](../src/util/lightrag_backend/README.md)
