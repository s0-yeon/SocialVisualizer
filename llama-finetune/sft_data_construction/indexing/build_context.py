"""
GraphRAG의 community_reports 입력 컨텍스트를 충실히 재구성한 모듈로,
graphrag/index/operations/summarize_communities/graph_context/{context_builder,sort_context}.py와
graphrag/index/workflows/create_community_reports.py (_prep_nodes/_prep_edges/explode_communities)를
그대로 따른다.

메일 도메인과 13개 방 메신저 도메인(Llama_mail_output / Llama_messenger_output)의 GraphRAG
산출물로부터 community_reports 태스크용 SFT 학습 쌍(입력 컨텍스트 ↔ gold full_content_json)을
재구성하는 데 쓰인다.

Faithful reconstruction of GraphRAG's community_reports input context,
mirroring graphrag/index/operations/summarize_communities/graph_context/{context_builder,sort_context}.py
and graphrag/index/workflows/create_community_reports.py (_prep_nodes/_prep_edges/explode_communities).

Used to rebuild SFT training pairs (input context <-> gold full_content_json) for the
community_reports task, from the GraphRAG output artifacts for the mail corpus and the
13-room messenger corpus (Llama_mail_output / Llama_messenger_output).
"""
import json
import os
import re
import pandas as pd

# 실제 BPE 토크나이저를 받아올 네트워크 접근이 없어 근사치로 대체: CJK/한글 문자는
# 1글자 ≈ 1토큰(한국어 BPE 동작과 유사), 그 외 텍스트는 공백 기준 분리로 1단어 ≈ 1토큰으로 계산.
# 이 값은 어떤 커뮤니티가 비정상적으로 커서 별도 처리(트리밍/수작업)가 필요한지 판단하는
# 용도로만 쓰이며, 프로덕션과 정확히 일치시키기 위한 값은 아니다.
_CJK_RE = re.compile(r"[ㄱ-힝一-鿿]")

# 텍스트의 대략적인 토큰 수를 구함 (CJK 문자는 1글자당 1토큰, 나머지는 공백 기준 단어 수로 근사)
def num_tokens(s: str) -> int:
    if not s:
        return 0
    cjk_chars = _CJK_RE.findall(s)
    non_cjk = _CJK_RE.sub(" ", s)
    words = non_cjk.split()
    return len(cjk_chars) + len(words)

# faithful port of graphrag's context building

# entities 테이블의 description 결측치를 채우고, 노드 상세정보(node_details) 컬럼을 만듦
def prep_nodes(entities: pd.DataFrame) -> pd.DataFrame:
    df = entities.copy()
    df["description"] = df["description"].fillna("No Description")
    df["node_details"] = df[["human_readable_id", "title", "description", "degree"]].to_dict(orient="records")
    return df

# relationships 테이블의 description 결측치를 채우고, 엣지 상세정보(edge_details) 컬럼을 만듦
def prep_edges(relationships: pd.DataFrame) -> pd.DataFrame:
    df = relationships.copy()
    df["description"] = df["description"].fillna("No Description")
    df["edge_details"] = df[["human_readable_id", "source", "target", "description", "combined_degree"]].to_dict(orient="records")
    return df

# 커뮤니티별 entity_ids를 행 단위로 펼쳐 엔티티 정보와 조인하고, 커뮤니티가 없는(-1) 행은 제외함
def explode_communities(communities: pd.DataFrame, entities: pd.DataFrame) -> pd.DataFrame:
    community_join = communities.explode("entity_ids").loc[:, ["community", "level", "entity_ids"]]
    nodes = entities.merge(community_join, left_on="id", right_on="entity_ids", how="left")
    return nodes.loc[nodes["community"] != -1]

# 엔티티/관계 리스트를 GraphRAG 프롬프트 형식의 CSV 텍스트로 직렬화함
def _get_context_string(entities, edges):
    contexts = []
    for label, data in [("Entities", entities), ("Relationships", edges)]:
        if data:
            data_df = pd.DataFrame(data)
            if not data_df.empty:
                contexts.append(f"-----{label}-----\n{data_df.to_csv(index=False, sep=',')}")
    return "\n\n".join(contexts)

# 커뮤니티 컨텍스트를 degree 내림차순으로 정렬하며 채워 넣고, 토큰 한도를 넘으면 잘라냄
def sort_context(local_context: list, max_context_tokens=None):
    """Faithful port of sort_context.py (no claims, since extract_claims is disabled)."""
    edges = [
        {**e, "human_readable_id": int(e["human_readable_id"])}
        for record in local_context
        for e in record.get("edge_details", [])
        if isinstance(e, dict)
    ]
    node_details = {
        record["title"]: {**record["node_details"], "human_readable_id": int(record["node_details"]["human_readable_id"])}
        for record in local_context
    }
    edges.sort(key=lambda x: (-x.get("combined_degree", 0), x.get("human_readable_id", "")))

    edge_ids, node_ids = set(), set()
    sorted_edges, sorted_nodes = [], []
    context_string = ""
    truncated = False

    for edge in edges:
        source, target = edge["source"], edge["target"]
        for node in [node_details.get(source), node_details.get(target)]:
            if node and node["human_readable_id"] not in node_ids:
                node_ids.add(node["human_readable_id"])
                sorted_nodes.append(node)
        if edge["human_readable_id"] not in edge_ids:
            edge_ids.add(edge["human_readable_id"])
            sorted_edges.append(edge)

        new_context_string = _get_context_string(sorted_nodes, sorted_edges)
        if max_context_tokens and num_tokens(new_context_string) > max_context_tokens:
            truncated = True
            break
        context_string = new_context_string

    if not context_string:
        context_string = _get_context_string(sorted_nodes, sorted_edges)

    return context_string, truncated

# 커뮤니티·레벨별로 sort_context를 호출해 SFT 학습용 입력 컨텍스트 딕셔너리를 만듦
def build_local_contexts(entities: pd.DataFrame, relationships: pd.DataFrame, communities: pd.DataFrame, max_context_tokens=None):
    """Returns a dict: (community_id, level) -> {"context_string", "context_size", "truncated", "n_entities", "n_relationships"}"""
    nodes = explode_communities(communities, entities)
    nodes = prep_nodes(nodes)
    edges = prep_edges(relationships)

    results = {}
    levels = sorted(nodes["level"].dropna().unique().tolist())
    for level in levels:
        level_nodes = nodes[nodes["level"] == level]
        nodes_set = set(level_nodes["title"])
        level_edges = edges[edges["source"].isin(nodes_set) & edges["target"].isin(nodes_set)]

        # edge_details를 노드(source 또는 target) 기준으로 그룹핑해 첫 값만 취함 — context_builder.py의 pandas groupby.agg("first")와 동일한 방식
        edge_by_source = level_edges.groupby("source")["edge_details"].first()
        edge_by_target = level_edges.groupby("target")["edge_details"].first()

        for community_id, grp in level_nodes.groupby("community"):
            all_context = []
            for _, row in grp.iterrows():
                title = row["title"]
                # 프로덕션과 동일: combine_first(source_edge, target_edge) 후 list(x.dropna())
                # 즉 노드 하나당 edge_details 딕셔너리가 최대 1개만 붙음 — 이 graphrag 버전의
                # context builder가 갖는 실제 특성이며, 여기서도 동일하게 재현함
                ed = edge_by_source.get(title)
                if ed is None:
                    ed = edge_by_target.get(title)
                all_context.append({
                    "title": title,
                    "node_details": row["node_details"],
                    "edge_details": [ed] if isinstance(ed, dict) else [],
                })
            context_string, truncated = sort_context(all_context, max_context_tokens=max_context_tokens)
            results[(int(community_id), int(level))] = {
                "context_string": context_string,
                "context_size": num_tokens(context_string),
                "truncated": truncated,
                "n_entities": len(grp),
            }
    return results


# GraphRAG가 생성한 entities/relationships/communities/community_reports parquet 파일들을 읽어옴
def load_domain(base_dir):
    entities = pd.read_parquet(os.path.join(base_dir, "entities.parquet"))
    relationships = pd.read_parquet(os.path.join(base_dir, "relationships.parquet"))
    communities = pd.read_parquet(os.path.join(base_dir, "communities.parquet"))
    community_reports = pd.read_parquet(os.path.join(base_dir, "community_reports.parquet"))
    return entities, relationships, communities, community_reports
