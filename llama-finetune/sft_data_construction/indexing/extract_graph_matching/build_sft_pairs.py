#!/usr/bin/env python3
"""
build_sft_pairs.py (v2) — GraphRAG extract_graph 캐시를 원본 청크와 매칭해
LoRA 파인튜닝용 (input, output) SFT 쌍을 만든다.

## v2에서 바뀐 점 (메신저 재매칭, 2026-08-18)
실제 데이터로 검증한 결과 두 가지가 확인됨:

1. **input 텍스트 소스가 틀렸었다.** v1은 document_id로 원본 CSV의 "문서 전체 텍스트"를
   input으로 썼는데, 한 문서가 여러 text_unit(청크)으로 쪼개지는 경우(주로 메신저: 하루치
   대화가 1500자 넘으면 분할) 모든 청크가 "문서 전체"라는 동일한 input을 공유하게 되어
   틀렸다. text_units.parquet에 각 청크의 실제 원문(`text` 컬럼)이 그대로 있으므로
   이제 이걸 input으로 쓴다 — 쪼개지지 않은 문서(이메일 전체, 메신저 대부분 방)는
   기존과 사실상 동일하고, 쪼개진 문서만 정확해진다.

2. **완전일치 매칭이 구조적으로 실패하는 케이스가 있다.** 같은 문서 안에서 여러 청크가
   150자씩 겹치며(overlap) 같은 인물/엔티티가 반복 언급되는 경우, GraphRAG가
   entities.parquet/relationships.parquet를 만들 때 그 반복 엔티티를 "첫 번째로 등장한
   청크" 하나에만 귀속시키고 나머지 청크의 entity_ids에는 남기지 않는다(그래프 병합 단계의
   내부 동작으로 추정, 재인덱싱해도 재현됨 — 실측: 9번의 독립적인 재인덱싱 전부 동일 패턴).
   반면 그 청크의 실제 raw LLM 응답에는 해당 엔티티가 제대로 들어있다(원문에도 실제로
   등장함). 즉 raw 응답이 "틀린" 게 아니라 GraphRAG의 사후 귀속이 보수적인 것뿐이므로,
   이런 청크에 한해 "완전일치" 대신 "최근접(고신뢰도) 매칭"으로 완화한다.

## 2-pass 매칭 전략
  Pass 1 (엄격): 기존과 동일하게 엔티티 집합 + 관계 집합이 완전히 일치하는 유일한 조합만
      채택. 이메일 전체와 쪼개지지 않은 메신저 문서는 거의 다 이 단계에서 100% 매칭된다.
  Pass 2 (완화, "쪼개진 문서"에 한해서만 시도): Pass 1에서 못 찾은 text_unit 중,
      같은 문서에 다른 청크가 더 있는(= 쪼개진 문서 소속인) 것만 대상으로, 아직 안 쓰인
      캐시 응답들과의 유사도(엔티티 Jaccard*0.6 + 관계 Jaccard*0.4)를 계산해 점수가
      threshold(기본 0.75) 이상인 것 중 가장 높은 점수 순으로 그리디하게 배정한다.
      쪼개지지 않은 문서(이메일 전체 포함)는 Pass 2 후보 풀에 아예 들어가지 않으므로,
      이미 잘 맞고 있던 매칭에는 부작용이 없다.

## 출력 형식 (JSONL)
    {"id": "2024-01-04_01", "text_unit_id": "...", "input": "<그 청크의 실제 원문>",
     "output": "<원본 raw 응답>", "n_entities": 8, "n_relationships": 11,
     "domain": "messenger", "room": "msg_823e7fcd",
     "match_method": "exact" | "relaxed", "match_score": 1.0}

실제 SFT jsonl(system prompt 포함, train/val 분리, 도메인 비율 결정)은
build_llamafactory_dataset.py에서 이 출력을 입력으로 받아 만든다(아직 별도 단계).

## English summary
build_sft_pairs.py (v2) matches the GraphRAG extract_graph cache against the original chunks to
build (input, output) SFT pairs for LoRA fine-tuning.

What changed in v2 (messenger re-matching, 2026-08-18) — two issues confirmed against real data:

1. Wrong input text source. v1 used the "full document text" from the original CSV (keyed by
   document_id) as input. When a document is split into multiple text_units/chunks (mainly
   messenger: a day's conversation over 1500 chars gets split), every chunk ended up sharing the
   same "full document" input, which is wrong. text_units.parquet already has each chunk's real
   raw text (the `text` column), so that is now used instead — unsplit documents (full emails,
   most messenger rooms) are effectively unchanged, only split documents get corrected.

2. Exact matching can structurally fail in some cases. When chunks in the same document overlap
   by 150 characters and the same person/entity is mentioned repeatedly, GraphRAG's
   entities.parquet/relationships.parquet generation attributes the repeated entity to only the
   "first chunk it appears in" and omits it from the other chunks' entity_ids (presumed internal
   behavior of the graph-merge step; reproduced consistently across 9 independent re-indexing
   runs). Meanwhile the chunk's actual raw LLM response does contain that entity (it genuinely
   appears in the source text). So the raw response isn't "wrong" — GraphRAG's post-hoc
   attribution is just conservative — and for these chunks, "exact match" is relaxed to
   "nearest (high-confidence) match" instead.

2-pass matching strategy:
  Pass 1 (strict): only accept a unique candidate whose entity set AND relationship set match
      completely, same as before. Nearly all whole emails and unsplit messenger documents get
      100% matched here.
  Pass 2 (relaxed, split documents only): for text_units Pass 1 couldn't match, restricted to
      those belonging to a document with other chunks (a split document), compute a similarity
      score against the still-unused cached responses (entity Jaccard*0.6 + relationship
      Jaccard*0.4) and greedily assign the highest-scoring pair above the threshold (default
      0.75). Unsplit documents never enter the Pass 2 pool, so already-correct matches are
      unaffected.

Output format (JSONL): {"id", "text_unit_id", "input": "<chunk's actual raw text>",
"output": "<original raw response>", "n_entities", "n_relationships", "domain", "room",
"match_method": "exact" | "relaxed", "match_score"}.

The actual SFT jsonl (with system prompt, train/val split, domain ratio) is built by
build_llamafactory_dataset.py from this output, as a separate later step.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas가 필요합니다: pip install pandas pyarrow")

csv.field_size_limit(10_000_000)

RECORD_SPLIT = re.compile(r"##")
ENTITY_RE = re.compile(r'\(\s*"entity"\s*<\|>\s*(.*?)\s*<\|>\s*(.*?)\s*<\|>\s*(.*)', re.DOTALL)
REL_RE = re.compile(
    r'\(\s*"relationship"\s*<\|>\s*(.*?)\s*<\|>\s*(.*?)\s*<\|>\s*(.*?)\s*<\|>\s*([\d.]+)', re.DOTALL
)


# graphrag 파일 캐시(JSON) 하나에서 LLM 응답 본문 텍스트만 꺼냄
def load_cache_response(path: Path) -> str | None:
    """graphrag 파일 캐시(JSON) 하나에서 LLM 응답 본문 텍스트만 꺼낸다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return data["result"]["response"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


# delimiter 포맷 응답을 (entity_name 집합, (source,target) 관계 쌍 집합)으로 파싱함
def parse_response(text: str):
    """delimiter 포맷 응답을 (entity_name 집합, (source,target) 관계 쌍 집합)으로 파싱."""
    entities = set()
    relationships = set()
    for rec in RECORD_SPLIT.split(text):
        rec = rec.strip()
        if not rec:
            continue
        m = ENTITY_RE.match(rec)
        if m:
            # GraphRAG는 entities.parquet에 저장할 때 title을 항상 대문자로 정규화한다.
            name = m.group(1).strip().strip('"').upper()
            entities.add(name)
            continue
        m = REL_RE.match(rec)
        if m:
            src = m.group(1).strip().strip('"').upper()
            tgt = m.group(2).strip().strip('"').upper()
            # GraphRAG는 그래프 저장 시 관계 방향을 정규화(정렬)하므로 무방향 쌍으로 비교.
            relationships.add(frozenset((src, tgt)))
    return frozenset(entities), frozenset(relationships)


# 두 집합의 Jaccard 유사도를 계산함 (둘 다 비어있으면 1.0으로 취급)
def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    if not u:
        return 1.0
    return len(a & b) / len(u)


# text_units.parquet + entities/relationships.parquet로 text_unit별 기대 시그니처를 만듦
def build_text_unit_signatures(graphrag_dir: Path):
    """text_units.parquet + entities/relationships.parquet로 text_unit별 기대 시그니처를 만든다.

    v2: 각 text_unit의 실제 청크 원문(text)과, 같은 문서에 속한 다른 text_unit 개수도 같이
    기록한다(쪼개진 문서인지 판별하기 위함).
    """
    out_dir = graphrag_dir / "output"
    entities_df = pd.read_parquet(out_dir / "entities.parquet")
    rel_df = pd.read_parquet(out_dir / "relationships.parquet")
    tu_df = pd.read_parquet(out_dir / "text_units.parquet")

    ent_title = dict(zip(entities_df["id"], entities_df["title"]))
    rel_pair = dict(zip(rel_df["id"], zip(rel_df["source"], rel_df["target"])))

    # 문서별 text_unit 개수 (쪼개진 문서 판별용)
    doc_tu_count = tu_df.groupby("document_id")["id"].count().to_dict()

    sigs = {}
    for _, row in tu_df.iterrows():
        ent_names = frozenset(
            ent_title[eid].strip().upper() for eid in row["entity_ids"] if eid in ent_title
        )
        rel_pairs = frozenset(
            frozenset(x.upper() for x in rel_pair[rid])
            for rid in row["relationship_ids"]
            if rid in rel_pair
        )
        doc_id = row["document_id"]
        sigs[row["id"]] = {
            "entities": ent_names,
            "relationships": rel_pairs,
            "document_id": doc_id,
            "text": row["text"],
            "n_entities": len(row["entity_ids"]),
            "n_relationships": len(row["relationship_ids"]),
            "is_split_doc": doc_tu_count.get(doc_id, 1) > 1,
        }
    return sigs


# 한 방(room)/도메인의 GraphRAG 캐시를 text_unit과 매칭함 (Pass 1 완전일치 -> Pass 2 최근접 매칭 순으로 시도)
def match_room(
    graphrag_dir: Path,
    input_csv: Path | None,
    domain: str,
    room_label: str,
    relaxed_threshold: float = 0.75,
):
    cache_dir = graphrag_dir / "cache" / "extract_graph"
    cache_files = sorted(cache_dir.glob("*_v4"))
    if not cache_files:
        cache_files = sorted(p for p in cache_dir.iterdir() if p.is_file())

    tu_sigs = build_text_unit_signatures(graphrag_dir)

    # 캐시 파일들을 한 번만 파싱해서 재사용 (Pass 1, Pass 2 공용)
    parsed_cache = []  # [(path, entities, relationships)]
    parse_failed = []
    for path in cache_files:
        resp = load_cache_response(path)
        if resp is None:
            parse_failed.append({"file": path.name, "reason": "cache_parse_failed"})
            continue
        ent_set, rel_set = parse_response(resp)
        if not ent_set:
            parse_failed.append({"file": path.name, "reason": "no_entities_parsed"})
            continue
        parsed_cache.append({"path": path, "resp": resp, "entities": ent_set, "relationships": rel_set})

    matched = []
    used_tu = set()
    used_cache_idx = set()

    # --- Pass 1: 완전일치 ---
    for idx, c in enumerate(parsed_cache):
        candidates = [
            tu_id
            for tu_id, sig in tu_sigs.items()
            if tu_id not in used_tu
            and sig["entities"] == c["entities"]
            and sig["relationships"] == c["relationships"]
        ]
        if len(candidates) == 1:
            tu_id = candidates[0]
            used_tu.add(tu_id)
            used_cache_idx.add(idx)
            sig = tu_sigs[tu_id]
            matched.append(
                {
                    "id": sig["document_id"],
                    "text_unit_id": tu_id,
                    "input": sig["text"],
                    "output": c["resp"],
                    "n_entities": len(c["entities"]),
                    "n_relationships": len(c["relationships"]),
                    "domain": domain,
                    "room": room_label,
                    "match_method": "exact",
                    "match_score": 1.0,
                }
            )
        # len==0 -> Pass 2에서 재시도 (miss)
        # len>1 -> 모호. Pass 2에서도 후보에 넣지 않고 그냥 미매칭 처리(안전 우선).

    ambiguous_pass1 = [
        {"file": parsed_cache[idx]["path"].name, "candidates": None}
        for idx in range(len(parsed_cache))
        if idx not in used_cache_idx
        and len(
            [
                tu_id
                for tu_id, sig in tu_sigs.items()
                if tu_id not in used_tu
                and sig["entities"] == parsed_cache[idx]["entities"]
                and sig["relationships"] == parsed_cache[idx]["relationships"]
            ]
        )
        > 1
    ]
    ambiguous_files = {a["file"] for a in ambiguous_pass1}

    # --- Pass 2: 쪼개진 문서에 한해 최근접 매칭 ---
    relaxed_tu_pool = [tu_id for tu_id, sig in tu_sigs.items() if tu_id not in used_tu and sig["is_split_doc"]]
    remaining_cache = [
        (idx, c) for idx, c in enumerate(parsed_cache) if idx not in used_cache_idx and c["path"].name not in ambiguous_files
    ]

    pairs = []  # (score, cache_idx, tu_id)
    for idx, c in remaining_cache:
        for tu_id in relaxed_tu_pool:
            sig = tu_sigs[tu_id]
            ent_j = jaccard(c["entities"], sig["entities"])
            rel_j = jaccard(c["relationships"], sig["relationships"])
            score = 0.6 * ent_j + 0.4 * rel_j
            if score >= relaxed_threshold:
                pairs.append((score, idx, tu_id))

    pairs.sort(key=lambda x: -x[0])
    used_tu_pass2 = set()
    used_cache_pass2 = set()
    for score, idx, tu_id in pairs:
        if tu_id in used_tu_pass2 or idx in used_cache_pass2:
            continue
        used_tu_pass2.add(tu_id)
        used_cache_pass2.add(idx)
        sig = tu_sigs[tu_id]
        c = parsed_cache[idx]
        matched.append(
            {
                "id": sig["document_id"],
                "text_unit_id": tu_id,
                "input": sig["text"],
                "output": c["resp"],
                "n_entities": len(c["entities"]),
                "n_relationships": len(c["relationships"]),
                "domain": domain,
                "room": room_label,
                "match_method": "relaxed",
                "match_score": round(score, 3),
            }
        )
        used_tu.add(tu_id)
        used_cache_idx.add(idx)

    # --- 최종 미매칭 캐시 파일 정리 ---
    unmatched = list(parse_failed)
    ambiguous = []
    for idx, c in enumerate(parsed_cache):
        if idx in used_cache_idx:
            continue
        if c["path"].name in ambiguous_files:
            ambiguous.append({"file": c["path"].name, "reason": "ambiguous (2개 이상 text_unit과 동시 매칭)"})
        else:
            unmatched.append(
                {
                    "file": c["path"].name,
                    "reason": "no_match (완전일치/최근접 매칭 모두 실패, stale 캐시로 추정)",
                    "n_entities": len(c["entities"]),
                    "n_relationships": len(c["relationships"]),
                }
            )

    unused_doc_ids = [tu_sigs[tu]["document_id"] for tu in tu_sigs if tu not in used_tu]
    n_exact = sum(1 for m in matched if m["match_method"] == "exact")
    n_relaxed = sum(1 for m in matched if m["match_method"] == "relaxed")
    return matched, unmatched, ambiguous, unused_doc_ids, (n_exact, n_relaxed)


# CLI 엔트리포인트: 방/도메인 하나에 대해 match_room을 실행하고 결과를 jsonl로 저장함
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphrag-dir", required=True, type=Path)
    ap.add_argument("--input-csv", type=Path, default=None, help="v2부터는 사용하지 않음(하위호환용, 무시됨)")
    ap.add_argument("--domain", required=True, choices=["email", "messenger"])
    ap.add_argument("--room", default="")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--unmatched-out", type=Path, default=None)
    ap.add_argument("--relaxed-threshold", type=float, default=0.75)
    args = ap.parse_args()

    matched, unmatched, ambiguous, unused_docs, (n_exact, n_relaxed) = match_room(
        args.graphrag_dir, args.input_csv, args.domain, args.room, args.relaxed_threshold
    )

    with open(args.out, "w", encoding="utf-8") as f:
        for row in matched:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if args.unmatched_out:
        with open(args.unmatched_out, "w", encoding="utf-8") as f:
            for row in unmatched + ambiguous:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    total_tu = len(matched) + len(unused_docs)
    print(
        f"[{args.domain}/{args.room or '-'}] "
        f"매칭 {len(matched)}/{total_tu}건 (완전일치 {n_exact}, 최근접 {n_relaxed}) "
        f"(미매칭 캐시 {len(unmatched)}건, 모호 {len(ambiguous)}건, 응답 없는 text_unit {len(unused_docs)}건)"
    )
    if unused_docs:
        print(f"  응답을 못 찾은 document_id: {unused_docs[:5]}{'...' if len(unused_docs) > 5 else ''}")


if __name__ == "__main__":
    main()
