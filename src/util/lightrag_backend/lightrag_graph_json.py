# src/util/lightrag_backend/lightrag_graph_json.py

# LightRAG의 graphml 그래프 파일을 프론트엔드가 그리는 그래프 시각화용 JSON으로 변환하는 모듈.
# NetworkX로 graphml을 읽어 노드/엣지를 GraphRAG와 동일한 {nodes, edges} 스키마로 맞춰 저장한다. 
# LightRAG는 GraphRAG의 커뮤니티(cluster) 개념이 없어 해당 필드는 항상 None이다.

# Converts LightRAG's graphml graph file into the JSON schema the frontend uses to render graph visualizations. 
# Reads the graphml with NetworkX and emits nodes/edges matching GraphRAG's {nodes, edges} schema. 
# LightRAG has no community/cluster concept, so that field is always None here.

import os
import json
import networkx as nx

_GRAPHML_FILENAME = "graph_chunk_entity_relation.graphml"  # lightrag_engine.py의 _get_storage_mtime과 동일한 파일명


# 빈 문자열은 None으로, float은 소수점 6자리로 정리해 JSON 직렬화용 값으로 변환한다
def _convert(val):
    if val is None:
        return None
    if isinstance(val, str) and val == "":
        return None
    if isinstance(val, float):
        return round(val, 6)
    return val


# NetworkX 그래프의 노드들을 프론트 렌더용 노드 dict 리스트로 변환한다
def _build_nodes(graph: "nx.Graph") -> list[dict]:
    nodes = []
    for idx, (node_id, data) in enumerate(graph.nodes(data=True)):
        entity_type = data.get("entity_type")
        nodes.append({
            "id":                str(node_id),
            "label":             str(node_id),  # graph-render.js가 forceLink().id(d => d.label)로 엣지를 이 값에 연결하므로 id와 동일하게 맞춘다
            "entity_type":       str(entity_type).upper() if entity_type else None,
            "description":       _convert(data.get("description")),
            "human_readable_id": idx,
            "source_id":         _convert(data.get("source_id")),  # 이 엔티티가 나온 청크 id(들), GRAPH_FIELD_SEP로 join된 문자열
            "degree":            graph.degree(node_id),
            "weight":            _convert(data.get("weight")),
            "cluster":           None,  # LightRAG 기본 그래프엔 커뮤니티 개념이 없음
            "level":             None,
        })
    print(f"[GRAPH-JSON][lightrag] 노드 {len(nodes)}개 생성")
    return nodes


# NetworkX 그래프의 엣지들을 프론트 렌더용 엣지 dict 리스트로 변환한다
def _build_edges(graph: "nx.Graph") -> list[dict]:
    edges = []
    for idx, (src, tgt, data) in enumerate(graph.edges(data=True)):
        edges.append({
            "source":            str(src),
            "target":            str(tgt),
            "id":                _convert(data.get("id")) or str(idx),
            "human_readable_id": idx,
            "description":       _convert(data.get("description")),
            "weight":            _convert(data.get("weight", 1.0)),
            "source_id":         _convert(data.get("source_id")),
            "level":             None,
        })
    print(f"[GRAPH-JSON][lightrag] 엣지 {len(edges)}개 생성")
    return edges


# LightRAG의 graphml을 읽어 GraphRAG와 동일한 {nodes, edges} 스키마의 그래프 JSON으로 저장하고 반환한다
def build_lightrag_graph_json(paths) -> dict:
    graphml_path = os.path.join(paths.LIGHTRAG_OUTPUT_DIR, _GRAPHML_FILENAME)

    if not os.path.exists(graphml_path):
        print(f"[GRAPH-JSON][lightrag] graphml 없음, 건너뜀: {graphml_path}")
        return {"nodes": [], "edges": []}

    graph = nx.read_graphml(graphml_path)

    print("노드 생성 중...")
    nodes = _build_nodes(graph)
    print("엣지 생성 중...")
    edges = _build_edges(graph)

    os.makedirs(os.path.dirname(paths.LIGHTRAG_GRAPH_JSON_PATH), exist_ok=True)
    graph_data = {"nodes": nodes, "edges": edges}

    with open(paths.LIGHTRAG_GRAPH_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)

    print(f"[GRAPH-JSON][lightrag] 저장 완료 → {paths.LIGHTRAG_GRAPH_JSON_PATH} (노드 {len(nodes)}, 엣지 {len(edges)})")
    return graph_data
