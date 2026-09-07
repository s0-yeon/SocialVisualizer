# -*- coding: utf-8 -*-
"""
프로덕션 토큰 예산을 초과해(build_pairs.py / survey.py 참고) 원본 gold 리포트를 그대로
재사용할 수 없었던 커뮤니티들을 위한 수작업 community_reports gold. 아래의 모든 인용은
cite()를 통해 실제(트리밍된) 입력 컨텍스트에 대조 검증되며, 실제로 근거가 없으면
바로 에러를 낸다.

build_pairs.py가 이 커뮤니티들에 대한 work/id_maps.json을 생성한 뒤에 실행한다.

Hand-written community_reports gold for communities that exceeded the production
token budget (see build_pairs.py / survey.py) and therefore couldn't reuse the
original gold report directly. Every citation below is resolved against the
real (trimmed) input context via cite() and will raise loudly if it isn't
actually grounded there.

Run after build_pairs.py has produced work/id_maps.json for these communities.
"""
import argparse
import json
import os

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--work-dir", default="./work")
args = parser.parse_args()

id_maps = json.load(open(os.path.join(args.work_dir, "id_maps.json"), encoding="utf-8"))

# 엔티티 제목/관계 쌍을 해당 커뮤니티의 human_readable_id로 변환해 '[Data: ...]' 인용 문자열을 만듦
def cite(community, entity_titles=(), rel_pairs=()):
    """Resolve entity titles / relationship (src,tgt) pairs to their human_readable_id for
    this specific community's trimmed context, and return the '[Data: ...]' citation string.
    Raises KeyError loudly if a title/pair isn't actually present -- so every citation in the
    hand-written reports below is guaranteed grounded in the real (trimmed) input context."""
    m = id_maps[str(community)]
    ent_ids = []
    for t in entity_titles:
        if t not in m["entities"]:
            raise KeyError(f"entity title not found in community {community}: {t}")
        ent_ids.append(m["entities"][t])
    rel_ids = []
    for src, tgt in rel_pairs:
        found = None
        for rid, s, t in m["relationships"]:
            if s == src and t == tgt:
                found = rid
                break
        if found is None:
            raise KeyError(f"relationship not found in community {community}: {src} -> {tgt}")
        rel_ids.append(found)
    parts = []
    if ent_ids:
        parts.append(f"Entities ({', '.join(ent_ids)})")
    if rel_ids:
        parts.append(f"Relationships ({', '.join(rel_ids)})")
    return f"[Data: {'; '.join(parts)}]"

OWNER = "HAEUN.SYNTHETIC.OWNER@GMAIL.COM"

# community 2 (level 0) — 816개 엔티티로 가장 큰 케이스. 대부분이 메일함 소유자 계정 하나로만 연결되는 광범위한 허브형 커뮤니티
def report_2():
    c = 2
    f1 = cite(c, [OWNER, "95B9A6D558B5E020", "6E7C9F2544C6AA22", "ACA399DFC199448F"],
              [("95B9A6D558B5E020", OWNER), ("6E7C9F2544C6AA22", OWNER), ("ACA399DFC199448F", OWNER)])
    f2 = cite(c, ["591AC083971A360B", "E5D6CFF7C8AC6653", "9EA37F9E2168317A", "4E5013AD7A1D7509"],
              [("591AC083971A360B", OWNER), ("9EA37F9E2168317A", OWNER)])
    f3 = cite(c, ["E1517C1A7659BFC1", "D5F235030B28CC03", "9A959DB3C7540AA2", "2931930476BDBC4F"],
              [("E1517C1A7659BFC1", OWNER), ("2931930476BDBC4F", OWNER)])
    f4 = cite(c, ["1D581D8A371C2DF5", "6D9A73B6345CE4D2", "FBBC05E3E6EB6FA4"],
              [("1D581D8A371C2DF5", OWNER), ("FBBC05E3E6EB6FA4", OWNER)])
    return {
        "title": "이하은 메일함 허브 — 다수의 개별 학사·업무 메일 모음",
        "summary": "이 커뮤니티는 haeun.synthetic.owner@gmail.com(이하은) 계정을 유일한 공통 축으로 삼아 서로 다른 시기·주제의 이메일들이 함께 묶인 대규모 허브형 클러스터다. 졸업 요건 문의, 스터디 그룹 일정, 산학협력 프로젝트 보고 같은 학사·연구 관련 메일부터 서비스 프로모션·설문조사 안내 메일까지 성격이 크게 다른 메일들이 뒤섞여 있으며, 하나의 좁은 주제로 요약되지 않는다.",
        "findings": [
            {
                "summary": "haeun.synthetic.owner@gmail.com이 이 클러스터를 묶는 유일한 공통점",
                "explanation": f"클러스터 내 대부분의 이메일 엔티티가 haeun.synthetic.owner@gmail.com을 발신자 또는 수신자로 직접 연결하고 있을 뿐, 메일들 사이에 그 외의 뚜렷한 연결 고리는 나타나지 않는다. 예를 들어 졸업 요건 문의 관련 메일들이 이 계정을 매개로만 서로 묶여 있다. {f1}"
            },
            {
                "summary": "스터디 그룹·회의 일정 조율 메일이 반복적으로 등장",
                "explanation": f"스터디 그룹 모임 시간 조율, 12월 월례회의 시간 결정, 회의 시간 변경 요청 등 소규모 일정 조율 메일이 여러 건 포함되어 있어, 이 계정이 다양한 모임·회의의 실무 조율 창구로도 쓰이고 있음을 보여준다. {f2}"
            },
            {
                "summary": "서비스 프로모션·설문조사성 알림 메일이 상당수 섞여 있음",
                "explanation": f"투어 예약 확정, 설문조사 참여 안내, 여행 프로모션, 신규 가입 환영 메일처럼 실질적 업무와 무관한 마케팅·트랜잭션성 메일도 다수 포함되어 있어, 이 클러스터가 순수 학사·연구 목적만이 아니라 개인 계정으로 수신되는 잡다한 서비스 메일까지 아우르고 있다. {f3}"
            },
            {
                "summary": "과제·데이터 요청과 개인 상담 안내 등 실무성 메일도 혼재",
                "explanation": f"과제 자료 요청 및 실험 데이터 분석 도움 요청, 개인 상담 가능 시간 안내와 같이 실질적인 학업 협업 성격의 메일도 함께 나타나 있어, 이 커뮤니티가 여러 성격의 메일이 한 계정을 통해 뒤섞인 결과임을 뒷받침한다. {f4}"
            }
        ],
        "rating": 3.5,
        "rating_explanation": "특정 주제나 결정으로 응집된 대화라기보다 한 계정을 거쳐 가는 서로 무관한 다수의 메일이 섞여 있는 클러스터이므로, 개별 메일 각각의 중요도와 무관하게 클러스터 자체의 주제적 응집도는 낮다고 판단된다."
    }

# community 87 (level 0) — 등록/장학금 안내 및 개인 상담 일정 조율 허브
def report_87():
    c = 87
    f1 = cite(c, ["등록 및 장학금 안내", "F3F5A5724038107E", "7DEFF509D3B986F2", "6173613E46AFBAF6", "80AC76B5888BA99B"],
              [("F3F5A5724038107E", OWNER), ("7DEFF509D3B986F2", OWNER), ("6173613E46AFBAF6", OWNER)])
    f2 = cite(c, ["개인 상담 일정 조율", "9BA310047D6945C0", "573E0C460A84FF05", "948F79FAD6D10DF5", "상담", "개인 상담"],
              [("9BA310047D6945C0", OWNER), ("573E0C460A84FF05", OWNER)])
    f3 = cite(c, ["정림대학교", "SUN.CHAN.MIN@MINWOOCHUNG.UNIV.KR", "WON.SUN.YOUNG@JINSAEBYEOK.AC.KR", "EUN.SU.YEON@RIMINBARAM.ACADEMY.NET"],
              [("SUN.CHAN.MIN@MINWOOCHUNG.UNIV.KR", "정림대학교"), ("WON.SUN.YOUNG@JINSAEBYEOK.AC.KR", "정림대학교"), ("EUN.SU.YEON@RIMINBARAM.ACADEMY.NET", "정림대학교")]),
    # 위 cite() 호출 끝에 trailing comma가 있어 f3가 (문자열,) 튜플로 감싸짐 — 원래 문자열만 꺼내 다시 f3에 대입
    f3 = f3[0] if isinstance(f3, tuple) else f3
    f4 = cite(c, ["DCA31E8E40042598", "E497665DBCC7A190", "논문 제출 마감 안내"],
              [("DCA31E8E40042598", OWNER), ("E497665DBCC7A190", OWNER)])
    return {
        "title": "등록·장학금 안내 및 개인 상담 일정 조율 허브",
        "summary": "이하은(haeun.synthetic.owner@gmail.com) 계정을 중심으로, 여러 학기에 걸쳐 반복되는 등록 및 장학금 안내 메일과 교수와의 개인 상담 일정 조율 메일이 큰 축을 이루는 클러스터다. 정림대학교 소속의 다양한 부서(행정실·고객센터·안전센터 등) 발신 계정이 다수 포함되어 있으며, 학회 논문 제출 마감 안내도 함께 나타난다.",
        "findings": [
            {
                "summary": "등록 및 장학금 안내 메일이 여러 학기에 걸쳐 반복됨",
                "explanation": f"등록 확인서·등록금 납부 기한, 장학금 신청 기간·자격·필요 서류를 안내하는 유사한 제목의 메일이 여러 시점(2017, 2022, 2025년 등)에 걸쳐 반복적으로 발신되어, 매 학기 등록·장학금 절차 안내가 정기적으로 이루어지는 패턴을 보여준다. {f1}"
            },
            {
                "summary": "교수와의 개인 상담 일정 조율이 별도의 큰 흐름을 이룸",
                "explanation": f"다음 주 금요일, 수요일 오후 3시, 주말 등 구체적인 시간대를 두고 개인 상담 가능 여부를 확인·조율하는 메일이 다수 반복되며, 상담 장소(교육동 3층 멘토링실)까지 확정된 사례도 있어 실질적인 일정 조율 대화로 볼 수 있다. {f2}"
            },
            {
                "summary": "정림대학교 여러 부서 계정이 발신 주체로 다수 등장",
                "explanation": f"정림대학교 산하의 고객센터, 고객지원팀, 안전센터 등 서로 다른 부서의 계정들이 각각 이 클러스터에 메일을 보내고 있어, 정림대학교가 이 클러스터의 핵심 소속 기관임을 시사한다. {f3}"
            },
            {
                "summary": "학회 논문 제출 마감 안내도 부수적으로 포함됨",
                "explanation": f"학회 논문 제출 마감일과 제출 절차를 안내하는 메일이 별도로 포함되어 있어, 등록·상담 외에도 연구 활동 관련 행정 안내가 이 계정으로 함께 전달되고 있음을 보여준다. {f4}"
            }
        ],
        "rating": 6.0,
        "rating_explanation": "매 학기 반복되는 등록·장학금 절차와 실제 일정이 확정되는 개인 상담 조율이 포함되어 있어, 단순 안내를 넘어 확인이 필요한 실무적 학사 관리 성격의 클러스터로 판단된다."
    }

# communities 238 / 668 / 771 / 775 / 785 (level 1-5) — 산학협력 프로젝트/과제/세미나·논문/상담 메일 허브인 동일 클러스터가
# Leiden 커뮤니티 계층 구조에서 레벨마다 소속 구성원만 조금씩 달라진 채 재라벨링된 것. 하나의 내러티브를 레벨별로 ID만 다시 매칭
# id_maps.json에는 실제 추출된 엔티티명("동양대학교")이 그대로 들어있어 cite() lookup은
# 이 실제 이름과 맞춰야 하지만, 출력되는 리포트 텍스트에는 공개용 가상 대학명만 노출한다.
_REAL_ORG_NAME = "동양대학교"
_DISPLAY_ORG_NAME = "다온대학교"

def report_oyang(community):
    # {238,668,771,775,785} 전체의 트리밍된 컨텍스트에 공통으로 존재가 확인된 엔티티/관계만 인용 — 이 내러티브가 그 거의 동일한 계층 체인 전체에서 공유되기 때문
    has_org = _REAL_ORG_NAME in id_maps[str(community)]["entities"]
    f1 = cite(community, ["C8FE34FB9FCDF951", "1654BE769A685C83", "3D909D52FCA14AA4"],
              [("C8FE34FB9FCDF951", OWNER)])
    f2 = cite(community, ["CB0029397B6E4590", "49F2D6BA835E05BB", "A20753808645644D", "DE74DE2ED4BE6748"],
              [("A20753808645644D", OWNER), ("DE74DE2ED4BE6748", OWNER)])
    f3 = cite(community, ["89F0C97E86114B51", "2B8EF8A300277DD5", "E865685712E827EC"],
              [("2B8EF8A300277DD5", OWNER), ("E865685712E827EC", OWNER)])
    org_part = cite(community, [_REAL_ORG_NAME], [(OWNER, _REAL_ORG_NAME)]) if has_org else None
    f4 = cite(community, ["859FA85D4EB97C74"],
              [("859FA85D4EB97C74", OWNER)])
    org_sentence = (
        f" 발신 계정은 {_DISPLAY_ORG_NAME} 공과대학 재료공학과 소속으로 확인된다. {org_part}"
        if org_part else ""
    )
    return {
        "title": "산학협력 프로젝트 진행 보고 및 과제·논문 관련 메일 허브",
        "summary": f"이하은(haeun.synthetic.owner@gmail.com) 계정을 중심으로, 산학협력 프로젝트 진행 상황 보고와 회의록 공유, 과제 자료 요청 및 제출 기한 연장 요청, 세미나 발표자 변경·논문 초안 검토 같은 연구실 업무 메일이 반복적으로 나타나는 클러스터다.{org_sentence}",
        "findings": [
            {
                "summary": "산학협력 프로젝트 진행 상황 보고가 반복적으로 이어짐",
                "explanation": f"실험실 장비 부족 문제 보고, 프로젝트 회의록 공유, 진행 상황 및 다음 단계 계획 보고 등 산학협력 프로젝트와 관련된 메일이 여러 차례 오가며, 이 클러스터가 특정 연구 프로젝트의 진행 상황을 지속적으로 공유하는 성격을 가짐을 보여준다. {f1}"
            },
            {
                "summary": "과제 자료 요청과 제출 기한 연장 요청이 되풀이되는 패턴",
                "explanation": f"과제 준비를 위한 자료·데이터 요청과 과제 제출 기한을 한 주 연장해 달라는 요청이 여러 시점에 걸쳐 유사한 형태로 반복되어, 정기적인 과제 제출 주기를 따라 발생하는 실무 커뮤니케이션임을 알 수 있다. {f2}"
            },
            {
                "summary": "세미나 발표자 변경과 논문 검토가 함께 다뤄짐",
                "explanation": f"세미나 발표자 변경 사실을 확인하는 메일과 논문 리뷰 결과·초안 검토를 요청하는 메일이 함께 나타나, 이 클러스터가 발표·논문 준비 과정의 검토·확인 단계를 포함하고 있음을 보여준다. {f3}"
            },
            {
                "summary": "진로·개인 상담 요청도 부수적으로 포함됨",
                "explanation": f"취업·진학을 포함한 진로 고민 상담이나 연구 주제 방향 설정을 위한 개인 상담 요청 메일도 섞여 있어, 프로젝트 실무 외에 지도교수와의 개인적 상담 수요도 이 계정을 통해 함께 처리되고 있다. {f4}"
            }
        ],
        "rating": 6.5,
        "rating_explanation": "특정 산학협력 프로젝트의 진행 상황 공유와 반복되는 과제·논문 검토 요청이 포함되어 있어, 실질적인 연구실 협업이 이뤄지는 중간 이상 중요도의 클러스터로 판단된다."
    }

REPORTS = {
    2: report_2(),
    87: report_87(),
    238: report_oyang(238),
    668: report_oyang(668),
    771: report_oyang(771),
    775: report_oyang(775),
    785: report_oyang(785),
}

if __name__ == "__main__":
    for cid, rep in REPORTS.items():
        assert 3 <= len(rep["findings"]) <= 5, cid  # GraphRAG 프롬프트가 요구하는 finding 개수 범위(3~5개) 검증
        json.dumps(rep, ensure_ascii=False)  # sanity check it's serializable
    print("all", len(REPORTS), "hand-written reports composed and citation-verified OK")
    out_path = os.path.join(args.work_dir, "oversized_reports.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(REPORTS, f, ensure_ascii=False, indent=2)
    print(f"saved -> {out_path}")
