# GraphRAG 전용 파일. GraphRAG의 entities/relationships/communities parquet을 그래프 시각화용 JSON으로 변환한다. job_run_graphrag.py가 subprocess(paths.GRAPH_BUILD_SCRIPT)로 실행하며, LightRAG는 이 변환기를 쓰지 않는다.

# GraphRAG-only script. Converts GraphRAG's entities/relationships/communities parquet files into JSON for graph visualization; run as a subprocess by job_run_graphrag.py (paths.GRAPH_BUILD_SCRIPT). LightRAG does not use this converter.

import pandas as pd
import json
import argparse
import os
import re
from config.settings import *
from util.user_path import UserPaths

# Email 엔티티 description에서 Subject 값만 추출한다 (없으면 None)
def _extract_email_subject(description: str) -> str | None:
    m = re.search(r"Subject:\s*(.+?)\s*\|", description)
    return m.group(1).strip() if m and m.group(1).strip() else None

# 엣지 description 앞의 "[관계: 친구]" 태그를 분리해 별도 필드로 뽑아낸다.
# 태그가 없으면(다른 도메인/엣지 타입) relation_label은 None, description은 원본 그대로 둔다.
_RELATION_TAG_RE = re.compile(r"^\[관계:\s*([^\]]+?)\]\s*")

# description에서 "[관계: ...]" 태그를 떼어내 (관계 라벨, 태그 제거된 description) 튜플로 반환한다
def _extract_relation_tag(description: str | None) -> tuple[str | None, str | None]:
    if not description:
        return None, description
    m = _RELATION_TAG_RE.match(description)
    if not m:
        return None, description
    return m.group(1).strip(), description[m.end():].strip()

# pandas에서 읽은 값을 JSON 직렬화 가능한 타입으로 변환한다 (NaN→None, float 6자리 반올림)
def _convert(val):
    try:
        if pd.isna(val): # 값이 비어있으면
            return None
    
    except Exception:
        pass
 
    if isinstance(val, float): # 실수이면
        return round(val, 6) # 소수점 6자리 끊어서 반올림
 
    if isinstance(val, (list, dict)): # 리스트나 딕셔너리이면
        return val
 
    return val

# 값이 비어있음을 나타내는 자리표시자 (extract_graph 프롬프트의 grounding rule과 동일 기준)
# title이 이중 하나면 무조건 노이즈로 간주
_PLACEHOLDER_TITLES = {"NONE", "NULL", "N/A", "없음", "-", ""}

# relationships DataFrame에서 source/target 역할을 하는 컬럼명을 찾아 반환한다
def _rel_endpoint_cols(rel_df: pd.DataFrame) -> tuple[str, str]:
    src_col = next((c for c in ["source", "src", "source_id"] if c in rel_df.columns), rel_df.columns[0])
    tgt_col = next((c for c in ["target", "tgt", "target_id"] if c in rel_df.columns), rel_df.columns[1])
    return src_col, tgt_col

# 자리표시자 이름 노드와 고립 노드(연결 엣지 없음), 그 노드를 참조하는 엣지를 제거한 DataFrame 쌍을 반환한다
def _clean_entities_and_relationships(
    entities_df: pd.DataFrame, rel_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    title_col = "title" if "title" in entities_df.columns else "name"

    # 비교용으로 문자열을 trim + 대문자화한다
    def _norm(v) -> str:
        return str(v).strip().upper()

    # 1) 자리표시자 이름을 가진 엔티티 제거
    is_placeholder = entities_df[title_col].map(lambda v: _norm(v) in _PLACEHOLDER_TITLES)
    removed_placeholder = entities_df.loc[is_placeholder, title_col].tolist()
    entities_df = entities_df.loc[~is_placeholder].copy()

    src_col, tgt_col = _rel_endpoint_cols(rel_df)

    # 2) 제거된 엔티티를 참조하는 관계도 함께 제거
    removed_norm = {_norm(t) for t in removed_placeholder}
    if removed_norm:
        rel_df = rel_df.loc[
            ~(rel_df[src_col].map(_norm).isin(removed_norm) | rel_df[tgt_col].map(_norm).isin(removed_norm))
        ].copy()

    # 3) 남은 relationships 기준으로 실제 연결 여부 재계산. degree=0인 노드 제거
    connected = set(rel_df[src_col].map(_norm)) | set(rel_df[tgt_col].map(_norm))
    is_isolated = ~entities_df[title_col].map(lambda v: _norm(v) in connected)
    removed_isolated = entities_df.loc[is_isolated, title_col].tolist()
    entities_df = entities_df.loc[~is_isolated].copy()

    if removed_placeholder:
        print(f"[정제] 자리표시자 이름(NONE 등) 노드 {len(removed_placeholder)}개 제거")
    if removed_isolated:
        print(f"[정제] 고립 노드(연결된 엣지 없음) {len(removed_isolated)}개 제거")

    return entities_df, rel_df


# entities/communities DataFrame을 프론트 렌더용 노드 dict 리스트로 변환한다
def _build_nodes(entities_df: pd.DataFrame, communities_df: pd.DataFrame | None) -> list[dict]:
 
    print(f"entities 컬럼: {list(entities_df.columns)}")

    # { entity_id : community_id } 형태의 딕셔너리
    community_map = {}
 
    if communities_df is not None: # 커뮤니티가 있다면
        print(f"communities 컬럼: {list(communities_df.columns)}")
        # entity_ids = 해당 커뮤니티에 속한 entity id들의 리스트
        if "entity_ids" in communities_df.columns:
            # iterrows() : 표의 각 행을 (인덱스, 행데이터) 튜플로 순회, _ : 인덱스는 사용 안 하므로 무시
            for _, row in communities_df.iterrows():
                cid = str(row.get("community", row.get("id", ""))) # 커뮤니티 id 추출
                eids = row["entity_ids"] # 해당 커뮤니티 속 엔티티 id
                if isinstance(eids, list):    
                    for eid in eids:   
                        # { entity_id : community_id } 형태로 저장        
                        community_map[str(eid)] = cid
 
    nodes = [] # 최종 노드 리스트

    # entities.parquet의 각 행(= 엔티티 하나)을 순회
    for _, row in entities_df.iterrows():

        # 엣지의 source/target이 title(이름)을 사용하므로 노드 ID도 title로 통일
        nid = str(row.get("title", row.get("name", row.get("id", _))))
        entity_type = _convert(row.get("entity_type", row.get("type", None)))
        description = _convert(row.get("description", None))

        # Email 노드는 title이 mail_id(16자리 hex)라 그래프에 그대로 표시하면 너무 길고 안 읽혀서,
        # description 안의 Subject 값을 표시용 라벨로 대신 쓴다. id(엣지 연결용)는 그대로 mail_id 유지.
        label = nid
        if str(entity_type).upper() == "EMAIL" and isinstance(description, str):
            subject = _extract_email_subject(description)
            if subject:
                label = subject

        node = {
            "id":                nid,
            "label":             label, # 그래프 노드 안에 표시될 이름
            "entity_type":       entity_type, # 엔티티 종류
            "description":       description, # 엔티티 설명
            "human_readable_id": _convert(row.get("human_readable_id", None)), # GraphRAG가 부여한 숫자 형태의 ID
            "source_id":         _convert(row.get("source_id", None)), # 이 엔티티가 어느 원본 문서에서 추출됐는지 추적용 ID
            "degree":            _convert(row.get("degree", None)), # 이 노드에 연결된 엣지 수
            "weight":            _convert(row.get("weight", None)), # 노드 중요도 가중치
            "cluster":           _convert(row.get("cluster", community_map.get(nid, None))), # 소속 커뮤니티 ID
            "level":             _convert(row.get("level", None)), # GraphRAG 계층 레벨    
        }
        nodes.append(node)
 
    print(f"노드 {len(nodes)}개 생성")

    return nodes
 
# relationships DataFrame을 프론트 렌더용 엣지 dict 리스트로 변환한다
def _build_edges(rel_df: pd.DataFrame) -> list[dict]:
 
    print(f"relationships 컬럼: {list(rel_df.columns)}") # rel_df : relationships.parquet을 pandas로 읽은 표
 
    src_col = next((c for c in ["source", "src", "source_id"] if c in rel_df.columns), rel_df.columns[0]) # 출발 노드 이름이 들어있는 컬럼명을 찾음
    tgt_col = next((c for c in ["target", "tgt", "target_id"] if c in rel_df.columns), rel_df.columns[1]) # 도착 노드 이름이 들어있는 컬럼명을 찾음
 
    edges = []
 
    # relationships.parquet의 각 행(= 관계 하나)을 순회
    for i, row in rel_df.iterrows():
        relation_label, description = _extract_relation_tag(_convert(row.get("description", None)))
        edge = {
            "source":            str(row[src_col]), # 엣지 출발 노드
            "target":            str(row[tgt_col]), # 엣지 도착 노드
            "id":                _convert(row.get("id", str(i))), # 엣지 고유 식별자
            "human_readable_id": _convert(row.get("human_readable_id", None)), # GraphRAG가 부여한 숫자 형태의 ID
            "description":       description, # 엣지 설명문 ("[관계: ...]" 태그는 relation_label로 분리하고 제거)
            "relation_label":    relation_label, # 사람-사람 interacts_with 엣지의 관계 카테고리(가족/연인/친구/동료/지인). 없으면 None
            "weight":            _convert(row.get("weight", 1.0)), # 엣지 가중치
            "source_id":         _convert(row.get("source_id", None)), # 관계가 어느 원본 문서에서 추출됐는지 추적용 ID
            "level":             _convert(row.get("level", None)), # GraphRAG 계층 레벨
        }
        edges.append(edge)
 
    print(f"엣지 {len(edges)}개 생성")

    return edges
 
# CLI 인자로 받은 계정/도메인의 parquet들을 읽어 그래프 시각화용 JSON을 생성·저장한다 (subprocess 진입점)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    paths = UserPaths(args.base_dir, args.user_id, args.domain)
    print("parquet → JSON 변환 시작\n")
 
    # 인덱싱이 안된 경우
    if not os.path.exists(paths.ENTITIES_PATH):
        print(f"[ERROR] 파일 없음: {paths.ENTITIES_PATH}")
        return
 
    if not os.path.exists(paths.RELATIONSHIPS_PATH):
        print(f"[ERROR] 파일 없음: {paths.RELATIONSHIPS_PATH}")
        return
 
    entities_df = pd.read_parquet(paths.ENTITIES_PATH) # entities.parquet 에서 pandas DataFrame으로 메모리 로드
    rel_df = pd.read_parquet(paths.RELATIONSHIPS_PATH) # relationships.parquet 에서 pandas DataFrame으로 메모리 로드
    # 커뮤니티는 없을수도 있으니까 None로 둠
    communities_df = None # 커뮤니티는 없을수도 있음
    if os.path.exists(paths.COMMUNITIES_PATH):
        communities_df = pd.read_parquet(paths.COMMUNITIES_PATH) # communities.parquet 에서 pandas DataFrame으로 메모리 로드

    # 노이즈 정제: NONE 등 자리표시자 이름 노드 + 고립 노드 제거 (시각화 JSON에만 반영, 원본 parquet은 그대로 둠)
    entities_df, rel_df = _clean_entities_and_relationships(entities_df, rel_df)

    # 노드/엣지 생성
    print("노드 생성 중...")
    nodes = _build_nodes(entities_df, communities_df)    # entities → 노드 리스트
 
    print("\n엣지 생성 중...")
    edges = _build_edges(rel_df)     # relationships → 엣지 리스트

    os.makedirs(os.path.dirname(paths.GRAPH_JSON_PATH), exist_ok=True) # src/json안에 저장
 
    graph_data = {
        "nodes": nodes,             # 전체 노드
        "edges": edges,             # 전체 엣지
    }

    with open(paths.GRAPH_JSON_PATH, "w", encoding="utf-8") as f: # 쓰기 모드로 한글 깨짐 방지
        json.dump(graph_data, f, ensure_ascii=False, indent=2)

    print(f"\n완료")
    print(f"저장 경로 : {paths.GRAPH_JSON_PATH}")
    print(f"노드 수   : {len(nodes)}")
    print(f"엣지 수   : {len(edges)}")
 
if __name__ == "__main__":
    main()