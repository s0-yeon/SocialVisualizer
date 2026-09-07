# extract_graph + community_reports SFT 데이터 구축

이 폴더의 스크립트는 GraphRAG의 `extract_graph`(엔티티/관계 추출)와 `community_reports`
(커뮤니티 요약) 두 태스크의 gold 라벨을 만드는 파이프라인이다. 합성 이메일·메신저
텍스트를 실제 GraphRAG 인덱싱 파이프라인에 태워 gpt-5.4-mini가 만든 응답을 distillation
라벨로 재사용하는 방식이다.

- `build_context.py`, `survey.py`, `build_pairs.py`, `compose_oversized.py`,
  `finalize_pairs.py`, `convert_to_sharegpt.py`, `global_build_context.py` —
  community_reports SFT 페어 구축(컨텍스트 재구성 → 페어링 → ShareGPT 포맷 변환)
- `extract_graph_matching/` — extract_graph 캐시 응답을 원본 청크와 매칭해 SFT 페어로
  변환 (v2, Jaccard 유사도 기반 근사 매칭 포함)

---

## 인덱싱 파이프라인 자체의 버그 수정/진단 기록은 여기 없음

작업 중 GraphRAG 인덱싱 파이프라인 자체에서 발견된 버그 4건(relationship 포맷 붕괴,
청크 경계 파편으로 인한 ChatRoom 오생성, 학습데이터 누출, Date 엔티티 GATE 부재)을
찾고 고친 패치 스크립트 7개와, 그 과정에서 쓴 진단용 스크립트 11개가 있었지만 이 폴더에는
넣지 않았다 — "SFT 데이터를 만드는 법"이 아니라 "GraphRAG 인덱싱 파이프라인 자체의
버그를 찾고 고친 기록"이라 성격이 다르고, 원인·수정 내용·전후 수치는 별도로
상세히 기록해두었다.
그 패치들은 이미 SocialVisualizer 앱 본체의 인덱싱 코드에 반영되어 있다.

요약만 남기면: Bug A(`frequency_penalty` 오염으로 relationship 포맷 92.5% 붕괴 → 분리),
Bug B(청크 경계 단어 파편이 ChatRoom으로 오인 → `LineAwareTokenChunker` 도입), Bug C(학습
데이터가 원문에 그대로 새어나옴 → 근거 검증 필터), Bug D(Date 엔티티 GATE 부재로 특정
날짜에 1,771개 관계가 쏠림 → ChatRoom과 동일한 GATE 규칙 추가). 최종적으로 노드/엣지
비율 0.09→1.55, 고립 노드 31.5%→3.2%까지 개선됐다.