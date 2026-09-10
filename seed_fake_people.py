# seed_fake_people.py
#
# 시연 영상용 "가라데이터" 일괄 생성 스크립트 (2026-08 재작성판 v2).
#
# 이 스크립트가 하는 일:
#   1. 메일 계정(03yeah03@gmail.com)에 avatar 폴더 사진 68장을 각각 다른 사람에게
#      매칭해서 person 테이블 + mail 테이블(실제 메일 왕복 기록)을 채운다.
#      친밀도(가족/베프/동료/가끔연락/소원함/광고)를 다양하게 섞고, 영어 이름 8명,
#      광고/브랜드 계정 6개를 포함한다.
#   2. mail_keyword 테이블에 2020-01 ~ 2026-08까지 매달 빼곡하게 키워드 데이터를 채운다
#      (My Time 메일 뷰의 월별/일별 키워드 그래프용). My Time 요약 카드(mail_summaries.json,
#      DB가 아니라 파일 자체가 소스)의 특정 달 텍스트 하드코딩도 MAIL_SUMMARY_OVERRIDES +
#      apply_mail_summary_overrides()로 여기서 같이 관리한다(예: 2026-08).
#   3. 메신저(카카오) 쪽 채팅방 5개의 이름을 "가족 단톡방" 등으로 바꾸고, 마찬가지로
#      2020-01 ~ 2026-08 채팅 요약(message_summarize) + 키워드(message_keyword)를 채운다.
#      그중 "3학년 4반 고등학교 단톡방"(HS_CHATROOM_ID)은 멤버 15명, 데이터 범위
#      2022-01~올해까지로, 대학 새내기→전공/알바/입대→휴학복학/인턴→취업준비→
#      사회초년생을 반영한 연도별 서사 + 그에 맞는 키워드로 채운다(2022-09는
#      HS_MONTH_TEXT_OVERRIDES/HS_MONTH_CONTACTS_OVERRIDES/HS_MONTH_KEYWORD_OVERRIDES로
#      직접 손으로 채운 내용으로 대체). 그 중 김도현은
#      2022년엔 거의 매번 말하다가, 2023년 1~4월까지는 여전히 눈에 띄게 남아있고
#      그 뒤로는 매달 점점 줄어드는 곡선으로 잦아드는 걸로(총 1382건, HS_KIM_2022_TOTAL/
#      HS_KIM_TAIL_TOTAL/HS_KIM_TAIL_DECAY 참고), 15명 사이 관계도 chatroom_relationship에
#      전부 심어서 관계 탭에 다 뜨게 한다. 다만 2026-05 한 달만은 그 연도별 서사(사회초년생
#      테마) 대신 "대학 다니는 서로의 근황" 내용으로 손으로 고정(HS_MAY2026_* 참고) —
#      일반 로직이 그 달 블록을 만든 직후 같은 함수 안에서 바로 덮어쓰므로 이 스크립트
#      한 번 실행으로 전부 반영되고, 따로 실행할 스크립트는 없다.
#
# ※ 하드코딩된 값을 손으로 고칠 땐 이 파일만 고치고 재실행한다 — mail_summaries.json
#    등 산출물 파일을 직접 열어 고치지 않는다(다음 재실행 때 다시 덮어써서 어긋남).
#
# ※ 화면/DB 어디에도 "[DEMO]" 같은 표식 문구를 넣지 않는다 — 실제 데이터처럼 보여야
#    한다는 요청에 따라, 대신 person_mail_account_id 목록(roster)과 chatroom_id +
#    summary_period 목록처럼 "우리가 이미 아는 값"으로 정리 대상을 정확히 특정한다.
#    (mail_id/block_id의 DEMO-MAIL-/DEMO-BLK- 접두어는 화면에 노출되지 않는 내부 PK라
#    그대로 유지 — cleanup 시 빠르게 대상만 골라내는 용도.)
#
# ※ 로컬 MySQL이라 클라우드 세션에서는 직접 실행이 안 되고, 사용자 컴퓨터에서
#    한 번 실행해야 합니다.
#
# 실행 방법 (MailGrapher 폴더에서):
#   python seed_fake_people.py
# (venv가 이미 활성화돼 있지 않다면 socialvisualizer-venv/Scripts/python.exe seed_fake_people.py)
#
# 되돌리려면 cleanup_fake_people.py를 실행하면 이 스크립트가 넣은 데이터만 깨끗이
# 지워집니다(실제 인덱싱 데이터는 건드리지 않음).

import datetime
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv

load_dotenv("src/parquet/.env")

import mysql.connector
from util.user_path import UserPaths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAIL_USER_ID = "03yeah03@gmail.com"  # 실제 계정 식별자 — 화면 표시만 accountPicker.js에서 3924ewa@gmail.com으로 바뀜(DB는 그대로)
AVATAR_DIR = os.path.join("src", "web", "public", "images", "avatar")
DEMO_MAIL_PREFIX = "DEMO-MAIL-"  # mail_id 내부 PK 접두어(화면 비노출) — cleanup 타겟팅용
DEMO_BLOCK_PREFIX = "DEMO-BLK-"  # block_id 내부 PK 접두어(화면 비노출) — cleanup 타겟팅용
DEMO_FOLDER = "가라데이터"

# ────────────────────────────── 1. 로스터(사람 목록) 생성 ──────────────────────────────
# person_avatars.json / mail_contact_stats.json / mail_summaries.json을 만들 때 쓴 것과
# 완전히 동일한 로직(랜덤 없음, 인덱스 기반 결정적 생성) — 그래야 화면에 이미 반영된
# 이름/아바타와 여기서 DB에 넣는 이름/아바타가 100% 일치한다.

AVATAR_FILES = [
    "0c892936f612a86a0bb2b9f8ddb8ae2a.png","1906e30eada27b664ff6262f19a941c1.png",
    "1a65913f07fcdcfa60c14c60b731b604.png","222f8e1efd037bb30e9676307f1dacde.png",
    "2fc559ef33f96ade3e1b4a067af3ce2c.png","36410ed68e8390b33b707b8d54a079a7.png",
    "3a5ae5c84f7840837380d07c09c59c05.png","44d8dc2dfb929c26a486610daae26e6e.png",
    "47924a6863b9526f4f305df370e7a4f7.png","5e6fdc02baab7b92dd194e60aa14eb8a.png",
    "61ed6b2a4f5c5b54ded59343a9845108.png","6ca4105b44d746cfbe9c8317ab012c5e.png",
    "75bd6be54b7b1e0f050b6b199361d808.png","78ada5f67be3326a4be4f95927993cc4.png",
    "7bdacc093805886bea6eb138c145aef3.png","7c055c0effc89888b2fa68dd7a54fd31.png",
    "7c1a215e5a67cdc5adf70b93d331f7df.png","807dbe7d1c25a633894d4a231b1c76d3.png",
    "896e19ffd61fa7d4bb7ec22457ff685e.png","907d8d01276e79a4e4e0a139208f7e97.png",
    "9c6d0f982227f105db5c3863a13e90eb.png","9fee3c0329144b4d41172af062cb508d.png",
    "accb39d9d0709430e5d77f50ab891908.png","bb596759819c65af81d38e93588389b4.png",
    "d5a841b364d2d4acb2edc7bcfcb29cd4.png","d6627afc686b26db3489c41015f6e8ff.png",
    "d9f69ac6b95a5f8cb11f5b2fa39b25f8.png",
    "KakaoTalk_20260818_194325435.png","KakaoTalk_20260818_194331288.png",
    "KakaoTalk_20260818_194334623.png","KakaoTalk_20260818_195956948.png",
    "KakaoTalk_20260818_200011207.png","KakaoTalk_20260818_200014611.png",
    "KakaoTalk_20260818_200018953.png","KakaoTalk_20260818_200920318.png",
    "KakaoTalk_20260818_200923187.png","KakaoTalk_20260818_200925777.png",
    "KakaoTalk_20260818_200948506.png","KakaoTalk_20260818_200950994.png",
    "KakaoTalk_20260818_201101433.png","KakaoTalk_20260818_201109547.png",
    "KakaoTalk_20260818_201116324.png","KakaoTalk_20260818_201122581.png",
    "KakaoTalk_20260818_201134301.png","KakaoTalk_20260818_201200278.png",
    "KakaoTalk_20260818_201213179.png","KakaoTalk_20260818_201236327.png",
    "KakaoTalk_20260818_201243637.png","KakaoTalk_20260818_201311699.png",
    "KakaoTalk_20260818_201326313.png","KakaoTalk_20260818_201350614.png",
    "KakaoTalk_20260818_201410885.png","KakaoTalk_20260818_201448134.png",
    "KakaoTalk_20260818_201459069.png","KakaoTalk_20260818_201713891.png",
    "KakaoTalk_20260818_201717668.png","KakaoTalk_20260818_201802278.png",
    "KakaoTalk_20260818_201827944.png","KakaoTalk_20260818_201853339.png",
    "KakaoTalk_20260818_201908143.png","KakaoTalk_20260818_201926634.png",
    "KakaoTalk_20260818_201953499.png","KakaoTalk_20260818_202011909.png",
    "KakaoTalk_20260818_202033673.png","KakaoTalk_20260818_202057056.png",
    "KakaoTalk_20260818_202115913.png","KakaoTalk_20260818_202134624.png",
    "KakaoTalk_20260818_202151276.png",
]

# 친밀도 티어별 파라미터: 왕복비율/답장비율/답장까지걸리는시간(h)/톤/메일수범위/활동기간(년)
# (인원수는 아래 ROSTER가 실제 소스 오브 트루스 — 여기 n은 참고용으로 남겨두지 않음)
TIER_PARAMS = {
    "family":   dict(label="가족",       balance=0.95, reply=0.75, elapsed=(1,6),   tone="casual", mails=(40,70), years=(2020,2026)),
    "bff":      dict(label="베프/절친",   balance=0.85, reply=0.6,  elapsed=(1,10),  tone="casual", mails=(25,50), years=(2020,2026)),
    "coworker": dict(label="동료/지인",   balance=0.6,  reply=0.35, elapsed=(4,30),  tone="mixed",  mails=(8,20),  years=(2022,2026)),
    "casual":   dict(label="가끔 연락",   balance=0.4,  reply=0.2,  elapsed=(10,50), tone="formal", mails=(3,9),   years=(2021,2026)),
    "distant":  dict(label="소원함",      balance=0.2,  reply=0.05, elapsed=(20,80), tone="notif",  mails=(1,4),   years=(2020,2023)),
    "brand":    dict(label="광고/브랜드", balance=0.0,  reply=0.0,  elapsed=(0,0),   tone="notif",  mails=(3,12),  years=(2024,2026)),
    # 요청 — 이서연 상세보기 전용("관계: 친구") — 실제 메일 생성은 아래
    # leeseoyeon_mail_plan()으로 완전히 따로 하드코딩하므로 여기 값들은
    # person 테이블의 relation_label/기본값 용도로만 쓰인다.
    "friend":   dict(label="친구",       balance=0.55, reply=0.4,  elapsed=(2,20),  tone="mixed",  mails=(15,35), years=(2024,2026)),
}

TONE_MAP = {  # tier의 대표 tone → mail.kg_tone에 넣을 값 풀
    "casual": ["casual", "casual", "transactional"],
    "mixed": ["transactional", "casual", "formal"],
    "formal": ["formal", "transactional"],
    "notif": ["notification", "alert"],
}

# 화면에 그대로 노출되는 person.description — "[DEMO]" 같은 표식 없이 자연스러운
# 한 줄 소개 문장. 친밀도 tier별로 톤을 다르게.
PERSON_DESC_TEMPLATES = {
    "family":   "자주 연락하고 지내는 가족입니다.",
    "bff":      "오래 알고 지낸 친한 친구입니다.",
    "coworker": "함께 일하며 알게 된 동료/지인입니다.",
    "casual":   "가끔 안부를 주고받는 사이입니다.",
    "distant":  "예전에 연락하다 요즘은 뜸해진 사이입니다.",
    "brand":    "구독 중인 브랜드/서비스 소식지입니다.",
    "friend":   "친하게 지내는 친구입니다.",  # 이서연은 PERSON_OVERRIDES로 별도 설명을 씀
}

# ────────────────────────────── 로스터(사람 목록) — 고정 목록 ──────────────────────────────
# 예전엔 (surname_i % 20, given_i % 40) 조합으로 이름을 생성했는데, 인원수가 40명을
# 넘어가는 지점(가끔연락/소원함 티어)에서 조합이 그대로 반복돼 "김민준"이 두 명 생기는 등
# 이름 중복 버그가 있었다. 사용자가 직접 지적한 중복 건들(김민준/이서연/박지훈/최수아/
# 정도윤/강하은/조시우/윤지민/장은우/임예은/한현우/오다은/서준서/신서윤)을 이름 변경 +
# 중복분 삭제로 정리하고, 이후 요청대로 가끔연락/소원함에서 총 10명을 줄이고 베프(아주
# 친밀한 관계)에 5명을 새로 추가했다. 광고 계정도 Apple/네이버/토스/당근마켓을 추가해
# 총 10개로 늘렸다. 그래서 더 이상 "생성 알고리즘"이 아니라 검증된 고정 목록을 쓴다
# (이름/이메일 전부 유일함이 이미 확인됨 — 중복 재발 걱정 없음).
ROSTER_RAW = [
    ("family", "김민주", "0c892936f612a86a0bb2b9f8ddb8ae2a.png", "sunny10@gmail.com"),
    # 요청 — 상세보기를 손으로 채운 "친구" 전용 하드코딩(leeseoyeon_mail_plan 참고).
    ("friend", "이서연", "1906e30eada27b664ff6262f19a941c1.png", "moonlight17@naver.com"),
    ("family", "박지연", "1a65913f07fcdcfa60c14c60b731b604.png", "blue24@daum.net"),
    ("family", "박소정", "222f8e1efd037bb30e9676307f1dacde.png", "haru31@kakao.com"),
    ("family", "doheeya", "2fc559ef33f96ade3e1b4a067af3ce2c.png", "yoon38@hanmail.net"),
    ("family", "강세준", "36410ed68e8390b33b707b8d54a079a7.png", "cotton45@nate.com"),
    # 요청 — 실제 메일에는 외국인과 주고받은 게 없어서 "진짜 영어 이름"이면 어색함.
    # Daniel Cho 한 명만 실명으로 남기고 나머지 영어 이름은 전부 아이디(닉네임) 스타일로 변경.
    ("bff", "j.carter92", "44d8dc2dfb929c26a486610daae26e6e.png", "james.carter@outlook.com"),
    ("bff", "윤지민", "47924a6863b9526f4f305df370e7a4f7.png", "jelly59@naver.com"),
    ("bff", "장은우", "5e6fdc02baab7b92dd194e60aa14eb8a.png", "milkyway66@daum.net"),
    ("bff", "임예은", "61ed6b2a4f5c5b54ded59343a9845108.png", "cloud973@kakao.com"),
    ("bff", "emilychen_", "6ca4105b44d746cfbe9c8317ab012c5e.png", "emily.chen@outlook.com"),
    ("bff", "한희우", "75bd6be54b7b1e0f050b6b199361d808.png", "greenlight80@hanmail.net"),
    # 요청 — "진짜 이름 말고 아이디"로 변경
    ("bff", "dahun.o", "78ada5f67be3326a4be4f95927993cc4.png", "dallae87@nate.com"),
    ("bff", "서주희", "7bdacc093805886bea6eb138c145aef3.png", "dodam94@gmail.com"),
    ("bff", "신서윤", "7c055c0effc89888b2fa68dd7a54fd31.png", "hodu12@naver.com"),
    ("bff", "윤하람", "KakaoTalk_20260818_201109547.png", "byulbit77@gmail.com"),
    ("bff", "조은채", "KakaoTalk_20260818_201116324.png", "onda21@naver.com"),
    ("bff", "최지유", "KakaoTalk_20260818_201122581.png", "dodam58@daum.net"),
    ("bff", "임서율", "KakaoTalk_20260818_201134301.png", "haemi34@kakao.com"),
    ("distant", "오태경", "KakaoTalk_20260818_201200278.png", "yeondu09@gmail.com"),
    # 요청 — "보통의 관계"(가끔 연락)에서 5명을 "아주 친밀한 관계"(베프)로 이동
    # (이후 요청으로 강혁만 다시 "보통의 관계"로 되돌림 — 아래 casual 티어 참고)
    ("bff", "조태윤", "KakaoTalk_20260818_200011207.png", "jjang14@daum.net"),
    ("bff", "문인선", "KakaoTalk_20260818_200014611.png", "nabi21@kakao.com"),
    ("bff", "gracelee92", "KakaoTalk_20260818_200018953.png", "grace.lee@outlook.com"),
    ("bff", "장진우", "KakaoTalk_20260818_200920318.png", "haemi28@hanmail.net"),
    ("distant", "권도은", "7c1a215e5a67cdc5adf70b93d331f7df.png", "poby19@daum.net"),
    ("distant", "안유진", "907d8d01276e79a4e4e0a139208f7e97.png", "onda33@hanmail.net"),
    ("distant", "전세은", "9fee3c0329144b4d41172af062cb508d.png", "riverside47@gmail.com"),
    # 요청 — "나" 프로필 사진과 맞바꿈(원래 내 사진 75bd6be5...를 김지원이 대신 씀)
    ("distant", "김지원", "75bd6be54b7b1e0f050b6b199361d808.png", "coco61@daum.net"),
    ("distant", "mpark0304", "KakaoTalk_20260818_194325435.png", "michael.park@outlook.com"),
    ("distant", "최재현", "KakaoTalk_20260818_194331288.png", "byul82@nate.com"),
    ("distant", "정성희", "KakaoTalk_20260818_194334623.png", "sarang89@gmail.com"),
    # 요청 — 강혁을 "아주 친밀한 관계"(베프)에서 다시 "보통의 관계"(가끔 연락)로 되돌림
    ("casual", "강혁", "KakaoTalk_20260818_195956948.png", "dowon96@naver.com"),
    ("casual", "임아린", "KakaoTalk_20260818_200923187.png", "yeondu35@nate.com"),
    ("casual", "한경아", "KakaoTalk_20260818_200925777.png", "bomnal42@gmail.com"),
    ("casual", "오미소", "KakaoTalk_20260818_200948506.png", "gaeul49@naver.com"),
    ("casual", "서승현", "KakaoTalk_20260818_200950994.png", "sup56@daum.net"),
    ("casual", "Daniel Cho", "KakaoTalk_20260818_201101433.png", "daniel.cho@outlook.com"),
    ("distant", "김민아", "KakaoTalk_20260818_201311699.png", "haeul77@nate.com"),
    ("brand", "무신사", "KakaoTalk_20260818_202011909.png", "newsletter@musinsa.com"),
    ("brand", "예스24", "KakaoTalk_20260818_202033673.png", "info@yes24.com"),
    ("brand", "쿠팡", "KakaoTalk_20260818_202057056.png", "noreply@coupang.com"),
    ("brand", "올리브영", "KakaoTalk_20260818_202115913.png", "marketing@oliveyoung.co.kr"),
    ("brand", "Microsoft 365", "brand-microsoft365.png", "office@microsoft.com"),
    ("brand", "배달의민족", "KakaoTalk_20260818_202151276.png", "service@baemin.com"),
    # 요청 — 광고/브랜드 계정은 사람 사진이 아니라 회사 로고가 나와야 함.
    # 아래 4개는 web/public/images/avatar/ 폴더에 이 파일명 그대로 로고 이미지를
    # 넣어주면 자동으로 반영됨(저작권 있는 로고라 제가 직접 만들어 넣을 수는 없음).
    ("brand", "Apple", "brand-apple.png", "news@apple.com"),
    ("brand", "네이버", "brand-naver.png", "notice@naver.com"),
    ("brand", "토스", "brand-toss.png", "newsletter@toss.im"),
    ("brand", "당근마켓", "brand-daangn.png", "info@daangn.com"),
]

# 요청 — My Time 타임슬라이더를 2017-02-04로 옮겼을 때 2020년 이전 데이터를 가진
# 사람이 13명 정도만 남도록, 아래 13명만 활동 시작 연도를 2017년으로 앞당긴다
# (나머지는 티어 기본값대로 전부 2020년 이후 시작이라 슬라이더가 2020년 아래로
# 내려가면 화면에서 사라짐). 권도은은 상세보기 시연에 쓸 예정이라 반드시 포함.
EARLY_ACTIVITY_EMAILS = {
    "poby19@daum.net",       # 권도은 (필수 포함)
    "sunny10@gmail.com",     # 김민주
    # 이서연(moonlight17@naver.com)은 2024년부터 연락하는 걸로 새로 하드코딩해서
    # 여기서 빼고 대신 박지연을 넣음(13명 유지).
    "blue24@daum.net",       # 박지연
    "haru31@kakao.com",      # 박소정
    "cotton45@nate.com",     # 강세준
    "james.carter@outlook.com",  # j.carter92
    "jelly59@naver.com",     # 윤지민
    "dallae87@nate.com",     # dahun.o
    "yeondu09@gmail.com",    # 오태경
    "onda33@hanmail.net",    # 안유진
    "byul82@nate.com",       # 최재현
    "yeondu35@nate.com",     # 임아린
    "bomnal42@gmail.com",    # 한경아
}
EARLY_ACTIVITY_START_YEAR = 2017


def build_roster():
    people = []
    for tier_key, name, avatar, email in ROSTER_RAW:
        tp = TIER_PARAMS[tier_key]
        email_lower = email.lower()
        years = tp["years"]
        if email_lower in EARLY_ACTIVITY_EMAILS:
            years = (EARLY_ACTIVITY_START_YEAR, years[1])
        people.append({
            "email": email_lower,
            "name": name,
            "tier": tier_key,
            "tier_label": tp["label"],
            "avatar": avatar,
            "balance": tp["balance"],
            "reply": tp["reply"],
            "elapsed": tp["elapsed"],
            "tone": tp["tone"],
            "mails": tp["mails"],
            "years": years,
        })
    return people


MAIL_KEYWORD_POOL = [
    "회의", "프로젝트", "보고서", "마감", "여행", "항공권", "숙소예약", "취업", "이력서", "면접",
    "자격증", "온라인강의", "헬스", "러닝", "다이어트", "재테크", "주식", "적금", "병원", "건강검진",
    "이사", "부동산", "반려동물", "강아지", "쇼핑", "할인", "배송", "결혼식", "생일", "동창회",
    "공연", "티켓", "독서", "스터디", "코딩", "디자인", "사진", "휴가", "캠핑", "맛집",
]

HS_CHATROOM_ID = "64c6eaa5a654c2e3c7948bec2be03b3dbe63fb43"

# "3학년 4반 고등학교 단톡방" 전용 — 실제 채팅 데이터는 2022년(대학 새내기)부터
# 시작하지만(start_year), 고2/고3(2020/2021) 항목도 이름 그대로 참고용으로 남겨둠.
# 연도별 서사 + 그 시기에 맞는 키워드. month별로 살짝 다른 문장이 나오도록
# phrases를 여러 개 두고 월 인덱스로 순환시킨다.
HS_YEAR_THEMES = {
    2020: dict(
        stage="고2",
        keywords=["동아리", "기말고사", "모의고사", "체육대회", "학원", "생기부", "야자", "수행평가"],
        phrases=[
            "다들 고2라 학교, 학원 오가느라 하루가 빡빡하다는 얘기가 많았다",
            "동아리 활동이랑 곧 있을 체육대회 얘기로 단톡방이 시끌시끌했다",
            "모의고사 성적표 나온 날은 다같이 한숨 쉬다가도 서로 다독여줬다",
            "야자 끝나고 편의점에서 잠깐 얼굴 보자는 얘기가 자주 나왔다",
            "생기부 챙기랴 수행평가 챙기랴 다들 정신없다고 투덜댔다",
            "기말고사 끝나고 다같이 노래방 가자는 계획을 세웠다",
        ],
    ),
    2021: dict(
        stage="고3",
        keywords=["수능", "모의고사", "자습", "야자", "원서접수", "입시설명회", "면접준비", "성적표"],
        phrases=[
            "고3이 되면서 다들 부쩍 예민해졌지만 서로 응원하는 말을 많이 남겼다",
            "모의고사 등급 얘기가 나올 때마다 단톡방 분위기가 무거워졌다",
            "자습실, 야자 얘기뿐이라 얼굴 볼 시간이 거의 없다는 하소연이 많았다",
            "수시 원서 몇 개 쓸지 고민하는 글이 자주 올라왔다",
            "수능이 다가오면서 다들 잠 못 잔다는 얘기, 그래도 파이팅하자는 얘기가 오갔다",
            "수능 끝난 날엔 다같이 만나서 펑펑 울고 웃었다는 후기가 올라왔다",
            "정시 원서접수와 면접 준비로 다시 한 번 다들 예민해졌다",
        ],
    ),
    2022: dict(
        stage="대학 새내기",
        keywords=["새내기", "OT", "MT", "수강신청", "학과", "동아리박람회", "대학생활", "미팅"],
        phrases=[
            "다들 대학 배정받고 캠퍼스 사진을 자랑하듯 올렸다",
            "새내기 OT, MT 다녀온 후기랑 사진이 쏟아졌다",
            "수강신청 전쟁 얘기와 시간표 자랑이 이어졌다",
            "동아리박람회 돌아본 얘기, 어느 동아리 들지 고민하는 얘기가 많았다",
            "대학 생활 적응기와 새로 사귄 친구들 얘기가 자주 올라왔다",
            "다들 바빠졌지만 방학 때 꼭 모이자는 약속을 남겼다",
        ],
    ),
    2023: dict(
        stage="전공 수업·알바·군입대",
        keywords=["전공수업", "알바", "군입대", "휴학", "자취", "학점", "조모임", "면회"],
        phrases=[
            "전공 수업이 어려워지면서 다들 학점 걱정을 늘어놓았다",
            "누군가 입대 소식을 전하자 다같이 응원 메시지를 남겼다",
            "알바 시작했다는 얘기, 자취 얘기가 하나둘 올라오기 시작했다",
            "조모임 스트레스와 시험 기간 하소연이 이어졌다",
            "면회 다녀온 후기와 사진이 단톡방에 올라왔다",
            "방학 때 오랜만에 다같이 모여 근황을 나눴다",
        ],
    ),
    2024: dict(
        stage="휴학·복학·인턴",
        keywords=["휴학", "복학", "인턴", "공모전", "자격증", "토익", "포트폴리오", "졸업유예"],
        phrases=[
            "휴학하고 뭐 할지, 복학하면 뭐 들을지 고민을 나눴다",
            "인턴 합격 소식이 올라오자 다같이 축하해줬다",
            "공모전 준비, 자격증 시험 얘기가 자주 오갔다",
            "토익 점수, 포트폴리오 얘기로 다들 진로 고민이 깊어졌다",
            "복학한 친구가 캠퍼스 근황을 전하며 다시 활기를 띠었다",
            "졸업 유예할지 말지 고민하는 글이 올라오기도 했다",
        ],
    ),
    2025: dict(
        stage="자소서·면접·취업준비",
        keywords=["자소서", "면접", "취업준비", "채용공고", "스터디", "포트폴리오", "합격", "불합격"],
        phrases=[
            "자소서 쓰다 막힌다는 하소연이 매달 꾸준히 올라왔다",
            "채용공고 링크를 서로 공유하며 같이 취업 준비를 했다",
            "면접 보러 간다는 소식에 다같이 파이팅을 외쳤다",
            "합격 소식이 올라온 날은 단톡방이 축하로 가득했다",
            "불합격 소식엔 서로 위로하며 다음을 응원했다",
            "취업 스터디, 포트폴리오 얘기로 다들 바쁜 나날을 보냈다",
        ],
    ),
    2026: dict(
        stage="사회초년생",
        keywords=["첫출근", "회사생활", "적응", "월급", "회식", "재테크", "동창회", "안부"],
        phrases=[
            "첫 출근 후기와 회사 생활 적응기가 올라왔다",
            "첫 월급 얘기, 재테크 고민 얘기로 다들 어른이 됐다며 웃었다",
            "회식 후기와 직장 생활의 소소한 에피소드가 이어졌다",
            "오랜만에 동창회로 다같이 모이자는 얘기가 나왔다",
            "다들 바빠졌어도 가끔씩 안부를 챙기며 대화를 이어갔다",
        ],
    ),
}
# (2020/2021 항목은 요청으로 방 데이터 시작 연도를 2022년으로 올리면서 더 이상
# 안 쓰이지만, 참고용으로 남겨둠 — HS_CHATROOM start_year=2022 아래 참고.)

# 요청 — 고등학교 동창 단톡방 멤버를 15명으로 늘림(기존 4명 + 11명 추가).
HS_MEMBERS = [
    "김도현", "이수빈", "박재현", "최유나",
    "정하늘", "오승민", "한지원", "배수아", "임찬우",
    "신예진", "강태오", "문서영", "조은비", "윤도경", "백하은",
]

# 요청 — My Time 2022-09 "주요 연락처"에 마우스를 올렸을 때 뜨는 사람 설명(chatroom_people.
# description)을 아주 간단하게 채워달라는 요청 — 9명만(HS_MONTH_CONTACTS_OVERRIDES[(2022,9)]와
# 동일한 명단). 나머지 멤버는 기존처럼 방 이름 기반 기본 설명을 그대로 씀.
HS_MEMBER_DESCRIPTIONS = {
    "김도현": "성격 좋고 붙임성 있어서 반에서 인기가 많았던 친구입니다.",
    "이수빈": "차분하고 배려심 많아서 다들 편하게 의지하는 친구입니다.",
    "박재현": "운동을 좋아하고 성격이 활발한 친구입니다.",
    "강태오": "유머 감각이 좋아 분위기를 잘 띄우는 친구입니다.",
    "문서영": "그림 그리기를 좋아하는 감성적인 친구입니다.",
    "백하은": "꼼꼼하고 계획적인 성격의 친구입니다.",
    "신예진": "노래를 잘해서 반 행사 때마다 인기였던 친구입니다.",
    "오승민": "게임과 컴퓨터를 좋아하는 친구입니다.",
    "윤도경": "말수는 적지만 정이 많은 친구입니다.",
}

# 요청 — 김도현은 2022년(갓 대학 새내기 때)엔 거의 매번 말할 정도로 활발했지만,
# 그 이후로는 "찔끔찔끔 아주 조금씩만" 말하는 걸로. 총합은 정확히 1382건.
# 요청(후속) — 2023년 1~4월까지는 메신저 통계에 여전히 눈에 띄게 남아있다가, 그
# 뒤로 "점점 내려가는 느낌"으로 서서히 잦아들어야 함 — 그래서 2023년~2026년 구간은
# 연도별 정액이 아니라 매달 지수적으로 줄어드는 하나의 연속 곡선(HS_KIM_TAIL_DECAY)
# 으로 다시 짰다(0으로 뚝 끊기지 않고 2026년까지도 매달 최소 1건은 남도록).
HS_TARGET_MEMBER = "김도현"
HS_KIM_2022_TOTAL = 1250  # 2022년 총량(블록별로 바로 나눔 — 거의 매번 참여)
HS_KIM_TAIL_TOTAL = 132   # 2023-01 ~ 2026-08 총량(매달 지수 감쇠로 나눔)
# 요청 — 2023년 1~2월이 2022년(활발기) 직후 갑자기 뚝 끊긴 것처럼 보이지 않도록,
# floor(매달 최소 1건)+초반에 몰린 감쇠 surplus 방식으로 바꾸면서 decay도 0.94(아주
# 완만함, 초반 surplus가 8건 수준으로 작아짐) → 0.75(초반에 확실히 티나게, 이후 빠르게
# 잦아듦)로 조정. 이제 2023-01≈25건, 02≈18건으로 시작해서 매달 자연스럽게 내려간다.
HS_KIM_TAIL_DECAY = 0.75  # 1보다 작을수록 초반 surplus가 더 빨리 잦아듦
HS_KIM_TOTAL = HS_KIM_2022_TOTAL + HS_KIM_TAIL_TOTAL  # 1382건

# 요청 — 2026-05 한 달만 일반 서사 로직(HS_YEAR_THEMES[2026]="사회초년생" 테마) 대신
# "대학 다니는 서로의 근황" 내용으로 손으로 고정. 키워드는 3-4개만, 각 키워드의 월
# 합계는 전부 5 이하로("언급수 5-6개 아래" 요청) — 대학=5(3+2), 근황=4(3+1), 복학=2,
# 동기=2. (participant, count) — 실제로 그 달 블록에 등장하는 참여자여야 하므로(FK),
# 어느 block_id에 심을지는 아래에서 그 달 실제로 생성된 블록들의 active_members를
# 보고 동적으로 고른다(김도현은 이 방 서사상 "찔끔찔끔"이라 매달 3블록 중 실제로
# 등장하는 블록이 매번 다를 수 있음 — 하드코딩된 block_id 대신 동적 매칭이 필요).
HS_MAY2026_PERIOD = "2026-05"
HS_MAY2026_SUMMARY = (
    "2026년 5월, 대학 다니는 서로의 근황에 대해 대화를 나누고 있습니다. "
    "'대학', '근황' 얘기가 특히 많이 오갔고, 강태오, 김도현, 박재현와(과) 자주 대화했다."
)
HS_MAY2026_KEYWORDS = [
    ("대학", "김도현", 3),
    ("대학", "박재현", 2),
    ("근황", "강태오", 3),
    ("근황", "김도현", 1),
    ("복학", "박재현", 2),
    ("동기", "강태오", 2),
]
# 요청 — "주요 연락처"에서 오승민/한지원/배수아/임찬우/신예진/강태오/문서영/조은비/
# 윤도경/백하은 10명 빼줘. (남는 5명 — HS_MEMBERS에서 저 10명을 제외한 나머지.)
HS_MAY2026_CONTACTS = ["김도현", "이수빈", "박재현", "최유나", "정하늘"]

# 요청 — "3학년 4반 고등학교 단톡방" 타임 슬라이더를 2022-03-08 ~ 2026-05-04로.
# (참고: /messenger-date-range는 인덱싱된 모든 메신저 방을 통틀어 MIN/MAX를 구하는
# 전역 계산이라, 다른 방들의 범위가 더 넓으면 화면에 보이는 슬라이더 자체의 양 끝은
# 이 방 하나만으론 안 움직일 수 있음 — 이 방의 실제 데이터 범위/김도현 통계는 아래
# 값으로 정확히 맞춘다.)
HS_DATE_START = datetime.date(2022, 3, 8)
HS_DATE_END = datetime.date(2026, 5, 4)

# 요청 — "위에서 만든 사람 15명"에 대한 관계가 관계 창에 전부 떠야 함. 이 방은
# 실제로 인덱싱된 적 없는(또는 원래 4명만 있던) 완전 하드코딩 방이라 GraphRAG가
# 뽑은 chatroom_relationship 데이터가 없거나 부족하다 — 그래서 15명 사이 관계를
# 여기서 직접 chatroom_relationship 테이블에 채워 넣는다(15명 전원이 서로 연결되도록
# 105쌍 전부 저장 — 김도현 상세보기 관계 탭에서 나머지 14명이 다 보이도록 하는 게 핵심).
# 요청 — 관계 라벨을 15명 전원 "친구"로 통일(예전엔 단짝친구/친한동창/동창/가끔
# 연락하는 사이 4단계로 순환시켰는데, 그 풀은 이제 안 씀).
HS_RELATION_DESCRIPTIONS = {
    "친구": "3학년 4반 동창이자, 지금도 자주 연락하며 지내는 친구입니다.",
}

# 요청 — 방 분위기가 "다소 사무적인 분위기"로 뜨던 걸 "활발하고 밝은 분위기"로.
# 프론트(mypeople.js moodLabel)는 mood_score가 높을수록 사적·친밀한 분위기로 보므로
# 60~79는 "편안하고 친근한 분위기", 80 이상은 "매우 사적이고 친밀한 분위기" 태그가
# 뜬다 — 이 방은 75~96 사이로 채워서 항상 그 두 단계(밝은 쪽) 안에 들어오게 한다.
HS_MOOD_PHRASES = [
    "다들 반갑게 안부를 물으며 시끌벅적하게 대화가 오갔다",
    "장난 섞인 농담과 이모티콘이 끊이지 않는 활기찬 분위기였다",
    "밝은 얘기들이 오가며 웃음 섞인 대화가 많았다",
    "서로 근황을 나누며 유쾌하고 다정한 분위기가 이어졌다",
    "친근한 말투로 편하게 수다 떠는 느낌이 강했다",
    "다들 텐션이 높아서 대화창이 쉴 새 없이 올라왔다",
]


def hs_mood_score(seed):
    """75~96 사이에서 인덱스 기반으로 들쭉날쭉하게(항상 "편안하고 친근한" 이상)."""
    return 75 + (seed * 7) % 22


def hs_mood_description(seed):
    return HS_MOOD_PHRASES[seed % len(HS_MOOD_PHRASES)]


def hs_month_text(y, m, mi, members):
    theme = HS_YEAR_THEMES[y]
    phrase = theme["phrases"][mi % len(theme["phrases"])]
    kw1 = theme["keywords"][mi % len(theme["keywords"])]
    kw2 = theme["keywords"][(mi + 3) % len(theme["keywords"])]
    who = ", ".join(members[:3])
    return (
        f"{y}년 {m}월, {theme['stage']}였던 그때. {phrase}. "
        f"'{kw1}', '{kw2}' 얘기가 특히 많이 오갔고, {who}와(과) 자주 대화했다."
    ), kw1, kw2


def hs_year_text(y, members):
    theme = HS_YEAR_THEMES[y]
    kws = "', '".join(theme["keywords"][:4])
    who = ", ".join(members[:3])
    return (
        f"{y}년은 다들 {theme['stage']} 시기였다. '{kws}' 같은 이야기가 오간 한 해로, "
        f"{who}와(과) 특히 자주 연락하며 지냈다."
    )


# 요청 — 2022년 9월은 hs_month_text()의 자동 순환 문장 대신, 그 달에 실제로 있었던
# 일(수능/대학 면접 준비 언급 최다, 학교에서 영화 보던 날, 수능이 빨리 끝나길 바람,
# 김도현 연애사 언급 빈도, 주말 호수공원 나들이)을 손으로 채운 요약으로 대체한다.
HS_MONTH_TEXT_OVERRIDES = {
    (2022, 9): (
        "2022년 9월, 고3이었던 그때. 다들 '수능'과 '대학 면접 준비' 얘기를 가장 많이 했고, "
        "하루빨리 수능이 끝났으면 좋겠다는 말이 여기저기서 나왔다. 학교에서 다같이 영화를 "
        "보던 날도 있었고, 주말엔 호수공원에 놀러 갔던 얘기로도 한참 떠들썩했다. 그 와중에 "
        "김도현 연애사 얘기도 빠지지 않고 자주 나왔다. '수능', '대학 면접 준비' 얘기가 특히 "
        "많이 오갔고, 김도현, 이수빈, 박재현와(과) 활발하게 대화했다."
    ),
}

# 요청 — 같은 달의 message_summarize.contacts(주요 연락처)도 방 전체 15명 대신
# 이 9명으로 좁혀서 저장한다.
HS_MONTH_CONTACTS_OVERRIDES = {
    (2022, 9): ["김도현", "이수빈", "박재현", "강태오", "문서영", "백하은", "신예진", "오승민", "윤도경"],
}

# 요청 — 2022년 9월의 message_keyword(My Time 키워드 그래프)는 연도 공용 풀 대신
# 이 달 전용 풀로. '수능'/'대학 면접 준비'를 2번씩 넣어 가장 많이 뽑히게 하고
# (block마다 (인덱스 % 길이)로 순환 선택되는 구조라 등장 횟수를 늘리면 빈도가 높아짐),
# 나머지(정시/원서접수/영화/자습/배달/학교/호수공원)는 1번씩 둬서 그 다음으로 채운다.
HS_MONTH_KEYWORD_OVERRIDES = {
    (2022, 9): [
        "수능", "대학 면접 준비", "수능", "대학 면접 준비",
        "정시", "원서접수", "영화", "자습", "배달", "학교", "호수공원",
    ],
}


CHATROOMS = [
    {
        "chatroom_id": "2398f4c3eeedb255f3841b179fafa4c0c6c1522d",
        "new_name": "가족 단톡방",
        "members": ["엄마", "아빠", "동생"],
        "keywords": ["저녁메뉴", "부모님", "명절", "용돈", "건강", "여행계획", "생신", "안부"],
    },
    {
        "chatroom_id": HS_CHATROOM_ID,
        # 요청 — 방 이름 변경
        "new_name": "3학년 4반 고등학교 단톡방",
        "members": HS_MEMBERS,  # 요청 — 15명으로 확장
        "keywords": ["동창회", "근황", "결혼", "취업", "여행", "술자리", "단체사진", "동기"],
        "narrative": True,
        "start_year": 2022,  # 요청 — 데이터 범위를 2022년~올해로
        "date_start": HS_DATE_START,  # 요청 — 타임 슬라이더 2022-03-08 ~ 2026-05-04
        "date_end": HS_DATE_END,
    },
    {
        "chatroom_id": "8b54e562c9f1ebcf4bb184a891a9311443427af1",
        "new_name": "보컬동아리 VOC 단톡방",
        "members": ["보컬트레이너", "정하람", "윤서준", "강나윤"],
        "keywords": ["합주", "공연", "연습", "곡선정", "보컬트레이닝", "뒷풀이", "정기공연", "발성"],
    },
    {
        "chatroom_id": "a10734ca1a9690cf0d297932348024c8483e2091",
        "new_name": "아파트 재건축 토의방",
        "members": ["PT쌤", "신재원", "황보람"],
        "keywords": ["헬스", "PT", "식단", "단백질", "벌크업", "다이어트", "루틴", "유산소"],
    },
    {
            "chatroom_id": "a8c50ec3269ad4e1e5c60e5e0bb1532ffc830d3e",
            "new_name": "IT 모임 공지방",
            "members": ["신서윤", "정이나", "보람"],
            "keywords": ["공대", "토익", "자료", "강의", "공지사항", "혜택", "비교과", "한성대"],
        },
    
    # 요청 — 위에서 만들었던 "IT 공과대학"(chatroom_id 1c51f4c...)이 이미 있던 진짜
    # 방인 "IT공과대학 공지방"(chatroom_id a8c50ec...)과 메신저 데이터 선택 목록에서
    # 중복으로 떠서, 나중에 만든(=우리가 새로 만든 가짜) 쪽을 지우기로 함. 여기서
    # 목록에서 빼서 재실행해도 다시 안 생기게 하고, DB에 이미 들어간 행은
    # dedupe_chatrooms.py로 따로 지운다.
]


# ────────────────────────────── 2. DB 연결/유틸 ──────────────────────────────

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def month_range(y1, y2):
    """(y1,1) ~ (y2,12) 사이 "YYYY-MM" 목록. 2026년은 8월까지만(오늘 기준)."""
    out = []
    for y in range(y1, y2 + 1):
        last_m = 8 if y == 2026 else 12
        for m in range(1, last_m + 1):
            out.append((y, m))
    return out


def demo_summary_periods():
    """이 스크립트가 message_summarize에 넣는 summary_period 전체 목록.
    ("monthly", "YYYY-MM") / ("yearly", "YYYY") 튜플. cleanup 시 정확히
    이 목록만 지우면 되므로 텍스트 표식 없이도 정리 대상을 특정할 수 있다."""
    periods = [("monthly", f"{y}-{m:02d}") for (y, m) in month_range(2020, 2026)]
    periods += [("yearly", str(y)) for y in range(2020, 2027)]
    return periods


def spread_dates(y1, y2, n):
    """y1~y2 사이에 n개의 날짜를 고르게(월별 순환) 분산 배치."""
    months = month_range(y1, y2)
    if not months:
        months = [(2026, 1)]
    out = []
    for i in range(n):
        y, m = months[i % len(months)]
        day = 1 + (i * 9 + 3) % 27
        hour = 8 + (i * 5) % 14
        minute = (i * 17) % 60
        out.append(datetime.datetime(y, m, day, hour, minute))
    return sorted(out)


def spread_int_total(total, n):
    """total을 n개의 자연스럽게 들쭉날쭉한 음이 아닌 정수로 나눠서 반환(합계는
    정확히 total). 인덱스 기반 가중치로 값들을 흔들어서 다 똑같아 보이지 않게 하고,
    반올림 오차는 마지막에 앞쪽 항목들로 1씩 보정해 합계를 정확히 맞춘다."""
    if n <= 0:
        return []
    if total <= 0:
        return [0] * n
    weights = [1 + (i * 13) % 9 for i in range(n)]  # 1~9 사이로 들쭉날쭉
    wsum = sum(weights)
    raw = [max(0, round(total * w / wsum)) for w in weights]
    diff = total - sum(raw)
    i = 0
    guard = 0
    while diff != 0 and guard < 10000:
        idx = i % n
        if diff > 0:
            raw[idx] += 1
            diff -= 1
        elif raw[idx] > 0:
            raw[idx] -= 1
            diff += 1
        i += 1
        guard += 1
    return raw


def hs_declining_monthly_totals(total, n_months, decay=0.75, floor=1):
    """n_months개월에 걸쳐 total을 "점점 내려가는 느낌"으로 나눠서 반환.
    요청 — 2023년 1~2월이 12월(활발기)에서 바로 8건 수준으로 뚝 끊기면 부자연스러우니,
    모든 달에 최소 floor(=1)건을 깔아둔 뒤, 남는 양(surplus = total - floor*n_months)을
    지수 감쇠(decay^i)로 초반 달들에 몰아준다 — 그래서 초반(2023년 1~2월 등)엔 확실히
    티날 만큼 남아있다가 후반으로 갈수록 서서히 floor로 잦아드는 자연스러운 곡선이 됨.
    반올림 오차는 초반(값이 큰) 달들로 보정해서 합계를 total에 정확히 맞춘다(floor 밑으론
    안 내려가게)."""
    if n_months <= 0:
        return []
    if total <= 0:
        return [0] * n_months
    floor_total = floor * n_months
    if floor_total >= total:
        # 요청 총량이 너무 작아 floor조차 못 채우면 그냥 고르게 나눔
        return spread_int_total(total, n_months)
    surplus = total - floor_total
    ratio_sum = sum(decay ** i for i in range(n_months))
    e0 = surplus / ratio_sum
    raw = [floor + max(0, round(e0 * (decay ** i))) for i in range(n_months)]
    diff = total - sum(raw)
    i = 0
    guard = 0
    while diff != 0 and guard < 10000:
        idx = i % n_months
        if diff > 0:
            raw[idx] += 1
            diff -= 1
        elif raw[idx] > floor:
            raw[idx] -= 1
            diff += 1
        i += 1
        guard += 1
    return raw


# ────────────────────────────── 3. 메일 도메인 시딩 ──────────────────────────────

# 요청 — 시연 영상에 안 어울리는 실제 연락처 카드는 매번 재실행해도 계속 지워지도록
# 여기 추가. (가짜 로스터가 아니라 실제 인덱싱된 person 행이라 mail_keyword/mail도
# 같이 정리한다.)
EXTRA_REMOVE_EMAILS = [
    "beauty777033@gmail.com",
    # 요청 — Google Drive 공유 알림이 실제 인물 이름("최지유")으로 잘못 표시되며
    # 가짜 로스터의 진짜 최지유 카드와 겹쳐 보이는 문제 — 카드 자체를 제거.
    "drive-shares-dm-noreply@google.com",
    # 요청 — My People 패널에 표시 이름 없이 뜨는 실제 연락처 카드 제거.
    "cafucafu@naver.com",
    "csi10186@gmail.com",
    "jjiuu1090@gmail.com",
    # 요청 — My People 패널에 겹쳐 뜨는 실제 최지유 연락처 카드 제거.
    "gpttitti@hansung.ac.kr",
]

# 요청 — "보통의 관계"에서 "아주 친밀한 관계"로 옮긴 5명은 화면 친밀도(EIS 점수,
# calculate_eis() 계산식)가 실제로 90점 이상 나와야 함. EIS는 person.description/
# relation_label이 아니라 mail 테이블의 실제 왕복/답장/톤 패턴으로 계산되므로,
# 이 5명만 메일 생성 로직을 따로 타서 EIS 공식(R·P·T 전부 최대화 + 충분한 메일량 +
# 최근 날짜)을 정확히 겨냥한다. R=0.3, P=0.4, T=0.3 가중치, 볼륨보정 (1-e^-0.05N),
# 시간감쇠 (e^-0.005*delta_days) — 아래 값으로 계산하면 EIS_final ≈ 0.97 (97점).
HIGH_INTIMACY_EMAILS = {
    # 강혁(dowon96@naver.com)은 요청으로 "보통의 관계"로 되돌아가 여기서 제외
    "jjang14@daum.net",      # 조태윤
    "nabi21@kakao.com",      # 문인선(구 윤보람)
    "grace.lee@outlook.com", # Grace Lee
    "haru31@kakao.com",      # 박소정(구 최수아) — 요청으로 장진우와 친밀도 스왑
}

# 요청 — Recap "친밀도" 랭킹에서 90%대 인원끼리 다 99/99/99로 겹쳐 보이는 문제.
# HIGH_INTIMACY_EMAILS 4명은 R·P가 이미 거의 최대치라 T(톤 점수)만 사람마다
# 다르게 주면 EIS가 갈라진다 — 다정한 톤(llm_tone=friendly) 비중만 사람별로
# 다르게 줘서(kg_tone은 그대로 "casual" 고정) 99/96/94/92 스타일로 분산시킨다.
HIGH_INTIMACY_FRIENDLY_FRACTION = {
    "jjang14@daum.net": 0.96,      # 조태윤 → EIS ≈ 99%
    "grace.lee@outlook.com": 0.76, # Grace Lee → EIS ≈ 96%
    "haru31@kakao.com": 0.63,      # 박소정 → EIS ≈ 94%
    "nabi21@kakao.com": 0.49,      # 문인선 → EIS ≈ 92%
}

# 요청 — Recap 친밀도 랭킹에서 90% 미만 구간도 다 87%로 겹쳐 보이는 문제.
# family 티어 중 화면 상위에 뜨는 3명만 톤 비중(과 강세준은 kg_tone 풀도 같이)을
# 사람마다 다르게 줘서 87/82/78 스타일로 분산시킨다. R·P는 건드리지 않는다.
MID_INTIMACY_TONE_OVERRIDE = {
    "yoon38@hanmail.net": {"friendly": 0.50, "kg_pool": None},                          # doheeya → EIS ≈ 87%(기존과 동일)
    "sunny10@gmail.com":  {"friendly": 0.17, "kg_pool": None},                          # 김민주 → EIS ≈ 82%
    "cotton45@nate.com":  {"friendly": 0.05, "kg_pool": ["transactional", "formal", "casual"]},  # 강세준 → EIS ≈ 78%
}


def high_intimacy_dates(index_date, n_recent=20, n_historical=60):
    """EIS의 시간감쇠(delta_t_last = date.today() - 마지막 메일 날짜)를 최소화하려면
    마지막 메일이 '스크립트를 실제로 실행하는 시점'과 가까워야 한다(index_date는
    계정이 마지막으로 인덱싱된 날짜일 뿐, 오늘 날짜와 다를 수 있음). 그래서 index_date가
    아니라 datetime.datetime.now()를 기준으로 최근 n_recent통을 오늘 바로 직전까지
    촘촘히 채우고, 나머지는 2020~2025년에 고르게 분산시켜 히스토리도 채운다."""
    base = datetime.datetime.now()

    historical = spread_dates(2020, 2025, n_historical)
    recent = []
    for i in range(n_recent):
        days_ago = n_recent - 1 - i  # 오래된 것부터 "지금"까지 촘촘히, 마지막은 오늘
        hours_ago = (i * 2) % 20 + 1
        recent.append(base - datetime.timedelta(days=days_ago, hours=hours_ago))
    return sorted(historical + recent)


# ────────────────────────────── 이서연 상세보기 하드코딩 ──────────────────────────────
# 요청 — "상세보기창 하나 하드코딩 -> 이서연". 관계는 "친구"(대학교 웹프로그래밍기초
# 팀프로젝트 동기), 2024년부터 연락, 월별 건수가 균일하지 않고 드문드문(0건인 달도
# 있게) 손으로 짠 일정. 2026년 8월은 보낸 2건·받은 1건으로 딱 맞추고, 8/23일 받은
# 메일 하나만 실제로 눌러보면 진짜 본문(정산서류)이 나오도록 documents.parquet에도
# 같은 mail_id로 심어둔다. description은 "관계/특징/주요 대화 주제"처럼 key: value
# 여러 줄로 써서 설명 탭이 카드 UI(mp-desc-profile-row)로 예쁘게 나오게 한다(한
# 줄짜리 문장은 UI 없이 글자만 나와 보였음). 친밀도는 "보통의 관계"(45~69%)
# 에서 "친밀한 관계"(70~89%)로 올리기 위해 답장 비율/속도/톤을 더 다정하게 튜닝.
# (요청 — "소통 빈도" 줄은 원래 기능이 아니라서 뺌. 이 아래 description에 실제로
# 없는데도 화면에 남아 있다면 DB에 예전 시딩 결과가 캐시돼 있는 것 — 이 스크립트를
# 다시 실행해서 person.description을 덮어써야 사라진다.)
LEE_SEOYEON_EMAIL = "moonlight17@naver.com"

LSY_SETTLE_MAIL_ID = "DEMO-MAIL-LSY-SETTLE-03"  # 2026-08-23, 이서연 → 나 (정산서류)

PERSON_OVERRIDES = {
    LEE_SEOYEON_EMAIL: {
        "relation_label": "친구",
        "description": (
            "관계: 친구\n"
            "특징: 대학교 웹프로그래밍기초 수업에서 만나 팀프로젝트를 함께한 동기\n"
            "주요 대화 주제: 과제, 수업 내용, 팀플 프로젝트 진행상황"
        ),
    },
}

# 월별 (연,월,건수) — 일부러 안 고르게(0건인 달 섞음) 짬. 2026-08은 요청대로
# 보낸 2건 + 받은 1건 = 3건으로 고정.
LSY_MONTHLY_COUNTS = [
    (2024, 1, 0), (2024, 2, 3), (2024, 3, 0), (2024, 4, 5),
    (2024, 5, 0), (2024, 6, 2), (2024, 7, 0), (2024, 8, 4),
    (2024, 9, 0), (2024, 10, 6), (2024, 11, 0), (2024, 12, 3),
    (2025, 1, 0), (2025, 2, 5), (2025, 3, 2), (2025, 4, 0),
    (2025, 5, 7), (2025, 6, 0), (2025, 7, 3), (2025, 8, 0),
    (2025, 9, 4), (2025, 10, 0), (2025, 11, 8), (2025, 12, 0),
    (2026, 1, 2), (2026, 2, 0), (2026, 3, 5), (2026, 4, 0),
    (2026, 5, 3), (2026, 6, 0), (2026, 7, 6), (2026, 8, 3),
]
# (연,월) 안에서 실제 본문이 있는 메일을 심을 (일, 방향, 강제 mail_id).
LSY_SETTLEMENT_SPOTS = {
    (2026, 8, 23): ("received", LSY_SETTLE_MAIL_ID),
}
# 정산서류 자리를 뺀 "나머지" 메일의 방향을 달마다 직접 지정하고 싶을 때만 채움
# (없으면 기존처럼 i%2로 sent/received를 교대로 배치). 2026-08은 정산서류(받은 1건)
# 말고 나머지 2건은 전부 "보낸" 메일이어야 요청한 2:1 비율이 맞는다.
LSY_MONTH_DIRECTION_OVERRIDE = {
    (2026, 8): ["sent", "sent"],
}

# 요청 — 2025년 이전(2024년)엔 과제/수업 관련 키워드 비중을 높이고, 2025년부터는
# 팀플/프로젝트 쪽 키워드 비중을 높인다(진짜 학기 진행에 따라 대화 주제가 옮겨간
# 것처럼 보이도록).
# 요청 — 타임슬라이더를 2025년 아래(2024년)로 내렸을 때 키워드 창이 "수업 내용" 위주로
# 보이도록 재구성. 과제/수업/pdf/팀플 계열로 채우고, 키워드마다 빈도를 다르게 줘서
# 매달 뽑히는 횟수가 다 똑같아 보이지 않게 함(빈도 자체는 아래 LSY_KEYWORD_TOTAL_EARLY
# 에서 고정 — 예전엔 여기 있던 가중치 딕셔너리로 매번 다르게 계산했었는데, 화면
# 합계가 너무 커지는 문제가 있어서 "최종 합계 고정" 방식으로 바꿈).
LSY_KEYWORD_POOL_EARLY = [  # ~2024: 과제/수업 위주
    "수업 내용 정리", "과제 제출", "강의자료 pdf", "웹프로그래밍 실습",
    "강의노트 공유", "출석 확인", "시험 범위", "과제 마감일",
    "수업 필기", "실습 과제 pdf", "조모임 일정", "코드 리뷰", "팀플 회의",
]
LSY_KEYWORD_POOL_LATE = [  # 2025~: 팀플/프로젝트 위주
    "팀플 회의", "발표자료", "정산서류", "프로젝트 기획서", "회의록 정리",
    "깃허브 저장소", "API 연동", "버그 수정", "UI 디자인", "결과보고서",
    "회식비 정산", "발표 PPT", "코드 컨벤션",
]
LSY_KEYWORD_POOL = LSY_KEYWORD_POOL_EARLY + LSY_KEYWORD_POOL_LATE  # 하위호환용 전체 풀

# 요청 — 키워드 창에 뜨는 숫자(선택 기간 안 daily_count 합계)가 다 너무 커서, 키워드별로
# "최종 합계가 몇이 될지"를 아예 여기서 고정해둔다(전부 9 이하, 1~3짜리도 섞음). 아래
# 값은 심을 때 서로 다른 날짜에 daily_count=1로 그 개수만큼만 나눠 심으므로, 화면에
# 뜨는 최종 합계 = 이 숫자 그대로. "정산서류"는 정산 메일 건에서 별도로 심는다(제외).
LSY_KEYWORD_TOTAL_EARLY = {
    "과제 제출": 9, "강의자료 pdf": 8, "수업 내용 정리": 7,
    "과제 마감일": 6, "웹프로그래밍 실습": 6, "수업 필기": 5,
    "강의노트 공유": 4, "실습 과제 pdf": 4,
    "시험 범위": 3, "조모임 일정": 3,
    "출석 확인": 2, "코드 리뷰": 2,
    "팀플 회의": 1,  # 2025년 이전엔 팀플 비중을 낮게(요청)
}
LSY_KEYWORD_TOTAL_LATE = {
    "발표자료": 9, "프로젝트 기획서": 8, "회의록 정리": 7,
    "API 연동": 6, "버그 수정": 6,
    "깃허브 저장소": 5, "UI 디자인": 5,
    "결과보고서": 4, "발표 PPT": 3, "팀플 회의": 3,
    "코드 컨벤션": 2, "회식비 정산": 1,
}


def leeseoyeon_mail_plan():
    """이서연 전용 하드코딩 메일 일정. 각 항목: dt, direction, mail_id_override(있으면)."""
    plan = []
    for (y, m, cnt) in LSY_MONTHLY_COUNTS:
        if cnt == 0:
            continue
        # 이 달에 심어야 할 실제 본문 메일 자리(있으면)부터 예약
        month_spots = {
            day: v for (sy, sm, day), v in LSY_SETTLEMENT_SPOTS.items() if (sy, sm) == (y, m)
        }
        used_days = set(month_spots.keys())
        for day, (direction, forced_id) in month_spots.items():
            hour = 10 + (day % 8)
            minute = (day * 13) % 60
            plan.append({
                "dt": datetime.datetime(y, m, day, hour, minute),
                "direction": direction,
                "mail_id_override": forced_id,
                "is_settlement": True,
            })

        remaining = cnt - len(month_spots)
        dir_override = LSY_MONTH_DIRECTION_OVERRIDE.get((y, m))
        day_cursor = 1
        for i in range(remaining):
            while day_cursor in used_days:
                day_cursor += 1
            if day_cursor > 27:
                day_cursor = 1
                while day_cursor in used_days:
                    day_cursor += 1
            used_days.add(day_cursor)
            hour = 9 + (i * 5) % 11
            minute = (i * 23) % 60
            direction = dir_override[i] if dir_override else ("sent" if i % 2 == 0 else "received")
            plan.append({
                "dt": datetime.datetime(y, m, day_cursor, hour, minute),
                "direction": direction,
                "mail_id_override": None,
                "is_settlement": False,
            })
            day_cursor += 3
    plan.sort(key=lambda x: x["dt"])
    return plan


def cleanup_mail_domain(conn, roster):
    cur = conn.cursor()
    try:
        emails = [p["email"] for p in roster]
        placeholders = ",".join(["%s"] * len(emails))
        cur.execute(
            f"DELETE FROM mail_keyword WHERE user_mail_account_id=%s "
            f"AND person_mail_account_id IN ({placeholders})",
            (MAIL_USER_ID, *emails),
        )
        cur.execute("DELETE FROM mail WHERE user_mail_account_id=%s AND mail_id LIKE %s",
                    (MAIL_USER_ID, DEMO_MAIL_PREFIX + "%"))
        cur.execute(
            f"DELETE FROM person WHERE user_mail_account_id=%s "
            f"AND person_mail_account_id IN ({placeholders})",
            (MAIL_USER_ID, *emails),
        )
        # 예전 3명짜리 테스트 데이터도 정리
        cur.execute(
            "DELETE FROM person WHERE person_mail_account_id IN (%s,%s,%s)",
            ("minjun.kim@example.com", "seoyeon.lee@example.com", "jihoon.park@example.com"),
        )
        # 시연 영상에서 빼기로 한 실제 연락처 카드 정리
        if EXTRA_REMOVE_EMAILS:
            extra_placeholders = ",".join(["%s"] * len(EXTRA_REMOVE_EMAILS))
            cur.execute(
                f"DELETE FROM mail_keyword WHERE user_mail_account_id=%s "
                f"AND person_mail_account_id IN ({extra_placeholders})",
                (MAIL_USER_ID, *EXTRA_REMOVE_EMAILS),
            )
            cur.execute(
                f"DELETE FROM mail WHERE user_mail_account_id=%s AND ("
                + " OR ".join(["sender LIKE %s OR receiver LIKE %s"] * len(EXTRA_REMOVE_EMAILS))
                + ")",
                (MAIL_USER_ID, *[v for e in EXTRA_REMOVE_EMAILS for v in (f"%<{e}>%", f"%<{e}>%")]),
            )
            cur.execute(
                f"DELETE FROM person WHERE user_mail_account_id=%s "
                f"AND person_mail_account_id IN ({extra_placeholders})",
                (MAIL_USER_ID, *EXTRA_REMOVE_EMAILS),
            )
        conn.commit()
    finally:
        cur.close()


def seed_mail_domain(conn, roster, index_date):
    cur = conn.cursor()
    try:
        # mail_folder FK 대상 보장
        cur.execute(
            "INSERT INTO mail_folder (mail_folder_name, user_mail_account_id, index_date, mail_count) "
            "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE mail_count=VALUES(mail_count)",
            (DEMO_FOLDER, MAIL_USER_ID, index_date, len(roster) * 10),
        )

        person_sql = """
            INSERT INTO person (
                person_mail_account_id, user_mail_account_id, index_date, person_name,
                receive_mails, send_mails, friendly_mails, description, relation_label
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                person_name=VALUES(person_name), receive_mails=VALUES(receive_mails),
                send_mails=VALUES(send_mails), friendly_mails=VALUES(friendly_mails),
                description=VALUES(description), relation_label=VALUES(relation_label)
        """
        mail_sql = """
            INSERT INTO mail (
                mail_id, user_mail_account_id, index_date, mail_folder_name, mail_date,
                sender, receiver, direction, kg_tone, llm_tone,
                is_reply, reply_to_mail_id, reply_elapsed_hours
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE mail_date=VALUES(mail_date)
        """
        kw_sql = """
            INSERT INTO mail_keyword (
                keyword_name, user_mail_account_id, index_date, person_mail_account_id,
                mail_date, daily_count
            ) VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE daily_count=VALUES(daily_count)
        """

        mail_counter = 0
        # 요청 — Recap "많이 보낸/받은 사람" 랭킹이 mail_contact_stats.json(실제 메일
        # 인덱싱 파이프라인이 만드는 별도 파일)을 그대로 읽는데, 이 파일엔 로스터
        # 사람들이 아예 없어서(광고/알림 메일만 있음) 랭킹이 죄다 Pinterest/Google
        # 같은 걸로 뜨는 문제 — 여기서 실제로 person 테이블에 넣는 것과 똑같은
        # 이름/수신/발신 수치를 모아뒀다가 아래 apply_mail_contact_stats_overrides()로
        # 그 파일에도 같이 반영한다(파일이 재인덱싱으로 초기화돼도 이 스크립트를
        # 다시 돌리면 항상 다시 채워짐).
        roster_stats = {}
        # 요청 — 이서연(LEE_SEOYEON_EMAIL)은 타임슬라이더를 2025년 이전으로 내렸을 때
        # 과제/수업 위주 전용 키워드(LSY_KEYWORD_POOL_EARLY)만 보여야 하는데, 이서연이
        # active_pool에 섞여 있으면 아래 공용 매달-키워드 루프(2020~2026 전체 범위)가
        # 이서연에게도 병원/스터디/이사 같은 무관한 일반 키워드를 얹어서 전용 풀이
        # 묻혀버렸다. 이서연은 leeseoyeon_mail_plan() 전용 로직으로 키워드를 따로
        # 채우므로 공용 풀에서는 제외한다.
        active_pool = [
            p for p in roster
            if p["tier"] not in ("brand", "distant") and p["email"] != LEE_SEOYEON_EMAIL
        ]

        for idx, p in enumerate(roster):
            is_high_intimacy = p["email"] in HIGH_INTIMACY_EMAILS
            is_leeseoyeon = p["email"] == LEE_SEOYEON_EMAIL
            # 이메일 기반 결정적 해시 — 티어가 같은 사람들끼리도 사람마다 메일 총량/
            # 왕복비율이 조금씩 다르게 흩어지도록(요청: "숫자들이 너무 겹쳐").
            variance_seed = sum(ord(c) for c in p["email"])
            custom_items = None

            if is_leeseoyeon:
                custom_items = leeseoyeon_mail_plan()
                dates = [item["dt"] for item in custom_items]
                total_n = len(custom_items)
                sent_n = sum(1 for item in custom_items if item["direction"] == "sent")
                recv_n = total_n - sent_n
                friendly = round(total_n * 0.65)
            elif is_high_intimacy:
                # EIS 90+ 겨냥 — 완전히 균형잡힌 왕복(R≈1), 전부 빠른 답장(P≈1),
                # 전부 다정한 톤(T≈1), 충분한 메일량(N=80, 볼륨보정≈0.98),
                # 마지막 메일이 오늘 근처(시간감쇠≈1.0). 사람마다 살짝 다른 양/비율로 흩어짐.
                n_recent = 18 + (variance_seed % 5)
                n_historical = 56 + (variance_seed % 9)
                dates = high_intimacy_dates(index_date, n_recent=n_recent, n_historical=n_historical)
                total_n = len(dates)
                sent_n = total_n // 2 + (variance_seed % 2)
                recv_n = total_n - sent_n
                friendly = total_n  # 전부 다정한 톤이므로 friendly_mails도 전량 카운트
            else:
                lo, hi = p["mails"]
                n = lo + (variance_seed * 7 + idx * 3) % max(1, (hi - lo + 1))
                balance_jitter = ((variance_seed % 21) - 10) / 100.0  # ±0.10
                eff_balance = min(0.95, max(0.05, p["balance"] + balance_jitter))
                sent_n = round(n * (0.15 + eff_balance * 0.35))
                recv_n = max(0, n - sent_n)
                total_n = sent_n + recv_n
                friendly = round(total_n * p["reply"] * 0.6)
                dates = spread_dates(p["years"][0], p["years"][1], max(1, total_n))

            roster_stats[p["email"]] = {
                "name": p["name"], "sent": sent_n, "received": recv_n, "friendly_mail": friendly,
            }

            overrides = PERSON_OVERRIDES.get(p["email"], {})
            cur.execute(person_sql, (
                p["email"], MAIL_USER_ID, index_date, p["name"],
                recv_n, sent_n, friendly,
                overrides.get("description", PERSON_DESC_TEMPLATES[p["tier"]]),
                overrides.get("relation_label", p["tier_label"]),
            ))

            tone_pool = TONE_MAP[p["tone"]]
            e_lo, e_hi = p["elapsed"]

            for i, d in enumerate(dates):
                mail_counter += 1
                if custom_items:
                    item = custom_items[i]
                    mail_id = item["mail_id_override"] or f"{DEMO_MAIL_PREFIX}{mail_counter:06d}"
                    direction = item["direction"]
                else:
                    mail_id = f"{DEMO_MAIL_PREFIX}{mail_counter:06d}"
                    direction = "sent" if i < sent_n else "received"

                if direction == "sent":
                    sender = f"나 <{MAIL_USER_ID}>"
                    receiver = f"{p['name']} <{p['email']}>"
                else:
                    sender = f"{p['name']} <{p['email']}>"
                    receiver = f"나 <{MAIL_USER_ID}>"

                if custom_items:
                    item = custom_items[i]
                    if item["is_settlement"]:
                        kg_tone = "transactional"
                        llm_tone = "friendly"
                        is_reply = 0  # 이서연이 먼저 보낸 정산서류 메일 — 답장 아님
                        elapsed = None
                    else:
                        # 요청 — 친밀도를 "보통의 관계"(45~69%)에서 "친밀한 관계"(70~89%)로
                        # 올리기 위해 답장 비율(67%)·답장 속도(1~6시간)·다정한 톤 비중(80%)을
                        # 전부 높임(EIS_final ≈ 76% 검증됨). 그래도 매달 들쭉날쭉한 건수
                        # 자체는 그대로라 그래프 모양은 안 바뀜.
                        kg_tone = "casual" if i % 5 != 0 else "transactional"
                        llm_tone = "friendly" if i % 5 != 4 else "not_friendly"
                        is_reply = 1 if i % 3 != 0 else 0
                        elapsed = round(1 + (i * 3) % 6, 2) if is_reply else None
                elif is_high_intimacy:
                    kg_tone = "casual"       # T의 kg 성분 = 1.0
                    is_reply = 1             # P의 반응비율 = 1.0
                    elapsed = round(0.5 + (i % 3) * 0.3, 2)  # 30분~1시간대 — P의 시간감쇠 ≈ 1.0
                    hi_frac = HIGH_INTIMACY_FRIENDLY_FRACTION.get(p["email"])
                    if hi_frac is not None:
                        llm_tone = "friendly" if i < round(hi_frac * total_n) else "not_friendly"
                    else:
                        llm_tone = "friendly"    # T의 llm 성분 = 1.0
                else:
                    mid_override = MID_INTIMACY_TONE_OVERRIDE.get(p["email"])
                    kg_pool = mid_override["kg_pool"] if (mid_override and mid_override["kg_pool"]) else tone_pool
                    kg_tone = kg_pool[i % len(kg_pool)]
                    is_reply = 1 if (p["reply"] > 0 and i % max(1, round(1 / max(p["reply"], 0.05))) == 0) else 0
                    elapsed = None
                    if is_reply and e_hi > 0:
                        elapsed = round(e_lo + (i * 3) % max(1, (e_hi - e_lo) + 1), 2)
                    if mid_override is not None:
                        llm_tone = "friendly" if i < round(mid_override["friendly"] * total_n) else "not_friendly"
                    else:
                        llm_tone = "friendly" if p["tone"] in ("casual", "mixed") and i % 2 == 0 else "not_friendly"

                cur.execute(mail_sql, (
                    mail_id, MAIL_USER_ID, index_date, DEMO_FOLDER, d,
                    sender, receiver, direction, kg_tone, llm_tone,
                    is_reply, None, elapsed,
                ))

            if mail_counter % 200 == 0:
                conn.commit()

        conn.commit()

        # mail_keyword — 2020-01 ~ 2026-08 매달 여러 날짜에 다양한 키워드
        kw_counter = 0
        for mi, (y, m) in enumerate(month_range(2020, 2026)):
            days_in_month = 27
            for j in range(14):  # 달마다 14개 (키워드,날짜) 로우
                day = 1 + (j * 2 + mi) % days_in_month
                kw = MAIL_KEYWORD_POOL[(mi * 3 + j) % len(MAIL_KEYWORD_POOL)]
                person = active_pool[(mi * 5 + j) % len(active_pool)]
                count = 1 + (mi + j) % 6
                mail_date = datetime.datetime(y, m, day, 10 + j % 10, 0)
                cur.execute(kw_sql, (kw, MAIL_USER_ID, index_date, person["email"], mail_date, count))
                kw_counter += 1
            if kw_counter % 300 == 0:
                conn.commit()
        conn.commit()

        # 요청 — 이서연은 실제로 메일을 주고받은 날짜에만, 과제/수업/프로젝트/코드/서류
        # 등 "정말 다양한" 전용 키워드가 붙도록 위 공용 루프와 별도로 심는다. 2025년
        # 이전(2024년)엔 과제/수업 위주, 2025년부터는 팀플/프로젝트 위주로 풀을 바꿔서
        # 학기가 진행될수록 대화 주제가 옮겨간 것처럼 보이게 한다.
        # 요청 — 키워드 창 숫자가 전부 10 아래(그리고 1~3짜리도 섞이게)가 되도록,
        # 키워드마다 LSY_KEYWORD_TOTAL_EARLY/LATE에 정해둔 "최종 합계"만큼만 서로 다른
        # 날짜에 daily_count=1로 나눠 심는다. 키워드별 총 개수가 그 기간의 날짜 수보다
        # 항상 적어서(최대 9 < 날짜 23~47개) 같은 키워드가 같은 날짜에 겹쳐 심겨
        # (ON DUPLICATE KEY로 합쳐지며) 합계가 깨질 일은 없다.
        lsy_items = leeseoyeon_mail_plan()
        lsy_early_dates = [
            it["dt"] for it in lsy_items if not it["is_settlement"] and it["dt"].year < 2025
        ]
        lsy_late_dates = [
            it["dt"] for it in lsy_items if not it["is_settlement"] and it["dt"].year >= 2025
        ]
        for totals, dates in (
            (LSY_KEYWORD_TOTAL_EARLY, lsy_early_dates),
            (LSY_KEYWORD_TOTAL_LATE, lsy_late_dates),
        ):
            if not dates:
                continue
            cursor = 0
            for kw, total in totals.items():
                for _ in range(total):
                    dt = dates[cursor % len(dates)]
                    cursor += 1
                    cur.execute(kw_sql, (kw, MAIL_USER_ID, index_date, LEE_SEOYEON_EMAIL, dt, 1))
                    kw_counter += 1

        # 정산서류 — 실제로 정산서류 본문이 붙는 그 메일 건에만, 역시 10 아래로.
        for item in lsy_items:
            if item["is_settlement"]:
                cur.execute(
                    kw_sql,
                    ("정산서류", MAIL_USER_ID, index_date, LEE_SEOYEON_EMAIL, item["dt"], 6),
                )
                kw_counter += 1
        conn.commit()

        print(f"[OK] 메일 도메인: person {len(roster)}명, mail {mail_counter}건, mail_keyword {kw_counter}건")
    finally:
        cur.close()
    return roster_stats


# 요청 — My Time(메일) 월별 요약 카드는 DB가 아니라 mail_summaries.json 파일 자체가
# 소스라(app.py의 /mail-summaries가 이 파일을 그대로 읽어 반환) — 다른 하드코딩처럼
# DB에 INSERT하는 방식이 아니라 이 파일을 직접 읽고 덮어쓴다. "하드코딩은 전부
# seed_fake_people.py 하나로 통일" 요청에 따라, 파일을 따로 손으로 고치는 대신 여기서
# 관리한다. contacts/count/threads는 요약 텍스트와 직접 연동되는 필드가 아니라서
# (다른 달들도 요약 주제와 무관하게 그 달 연락처 목록/건수를 담고 있음) 손대지 않고
# summary 텍스트만 바꾼다.
MAIL_SUMMARY_OVERRIDES = {
    "2026-08": (
        "2026년 8월은 '프로젝트'와 '광고' 관련 메일이 많았습니다. 프로젝트 관련 첨부파일 "
        "메일과 함께 업무 및 일정 조율 메일도 꾸준히 오갔습니다. 또한 광고 관련 메일이 많이 "
        "분포합니다."
    ),
}


def apply_mail_summary_overrides(base_dir):
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")
    if not os.path.exists(paths.MAIL_SUMMARIES_PATH):
        print(f"[WARN] {paths.MAIL_SUMMARIES_PATH} 이 없어 mail 요약 오버라이드를 건너뜁니다.")
        return
    with open(paths.MAIL_SUMMARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    monthly = data.get("monthly", {})
    for period, summary in MAIL_SUMMARY_OVERRIDES.items():
        if period not in monthly:
            print(f"[WARN] mail_summaries.json에 {period} 항목이 없어 그 항목은 건너뜁니다.")
            continue
        monthly[period]["summary"] = summary
    with open(paths.MAIL_SUMMARIES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] mail_summaries.json 오버라이드 {len(MAIL_SUMMARY_OVERRIDES)}건 적용 → {paths.MAIL_SUMMARIES_PATH}")


# 요청 — Recap "나에게 많이 보낸 사람"/"내가 많이 보낸 사람"이 실제 로스터 데이터가
# 아니라 mail_contact_stats.json에 남아있던 광고/알림 메일(Pinterest, Google, ChatGPT
# 등)로만 채워져 있던 문제 — mail_summaries.json과 같은 방식으로, DB에 넣은 것과
# 동일한 이름/수신/발신 수치를 이 파일에도 병합해서 Recap이 My People과 같은 실제
# 데이터를 보도록 맞춘다. 기존에 있던 광고/알림 항목은 지우지 않고 그대로 둔다
# (로스터 인원 수치가 훨씬 커서 어차피 랭킹 상위는 로스터 사람들이 차지함).
def apply_mail_contact_stats_overrides(base_dir, roster_stats):
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")
    if not os.path.exists(paths.MAIL_CONTACTS_PATH):
        print(f"[WARN] {paths.MAIL_CONTACTS_PATH} 이 없어 mail_contact_stats 오버라이드를 건너뜁니다.")
        return
    with open(paths.MAIL_CONTACTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for email, stats in roster_stats.items():
        data[email] = {
            "name": stats["name"],
            "sent": stats["sent"],
            "received": stats["received"],
            "friendly_mail": stats["friendly_mail"],
        }
    with open(paths.MAIL_CONTACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] mail_contact_stats.json에 로스터 {len(roster_stats)}명 반영 → {paths.MAIL_CONTACTS_PATH}")


# ────────────────────────────── 4. 메신저(카카오) 도메인 시딩 ──────────────────────────────

def cleanup_messenger_domain(conn, room):
    cur = conn.cursor()
    try:
        chatroom_id = room["chatroom_id"]
        cur.execute(
            "DELETE FROM message_keyword WHERE chatroom_id=%s AND block_id LIKE %s",
            (chatroom_id, DEMO_BLOCK_PREFIX + "%"),
        )
        cur.execute(
            "DELETE FROM participant WHERE chatroom_id=%s AND block_id LIKE %s",
            (chatroom_id, DEMO_BLOCK_PREFIX + "%"),
        )
        cur.execute(
            "DELETE FROM message_block WHERE chatroom_id=%s AND block_id LIKE %s",
            (chatroom_id, DEMO_BLOCK_PREFIX + "%"),
        )
        # 텍스트 표식 없이도 정확히 우리가 넣는 (summarize_unit, summary_period) 조합만 지운다.
        for unit, period in demo_summary_periods():
            cur.execute(
                "DELETE FROM message_summarize WHERE chatroom_id=%s AND summarize_unit=%s AND summary_period=%s",
                (chatroom_id, unit, period),
            )
        conn.commit()
    finally:
        cur.close()


def seed_messenger_domain(conn, room, block_counter_start):
    cur = conn.cursor()
    block_counter = block_counter_start
    try:
        cur.execute(
            "SELECT chatroom_id, index_date, user_id FROM chatroom WHERE chatroom_id=%s "
            "ORDER BY index_date DESC LIMIT 1",
            (room["chatroom_id"],),
        )
        row = cur.fetchone()
        if not row:
            if not room.get("create_if_missing"):
                print(f"[WARN] chatroom {room['chatroom_id']} 이(가) 아직 인덱싱된 적이 없어 건너뜁니다.")
                return block_counter
            # 요청 — 실제로 인덱싱된 적 없는 완전히 새로운 가짜 채팅방을 chatroom
            # 테이블에 직접 INSERT. index_date/user_id는 FK(user 테이블) 제약이 있어
            # 임의값을 못 쓰므로, 이미 인덱싱된 다른 채팅방의 값을 그대로 빌려 쓴다.
            cur.execute(
                "SELECT index_date, user_id FROM chatroom ORDER BY index_date DESC LIMIT 1"
            )
            template = cur.fetchone()
            if not template:
                print(f"[WARN] chatroom {room['chatroom_id']} 생성 실패 — 참고할 기존 chatroom 행이 "
                      f"하나도 없습니다(메신저 계정이 아직 한 번도 인덱싱된 적이 없는 것 같아요).")
                return block_counter
            tmpl_index_date, tmpl_user_id = template
            cur.execute(
                "INSERT INTO chatroom (chatroom_id, index_date, user_id, chatroom_name, "
                "message_platform, message_count) VALUES (%s,%s,%s,%s,%s,%s)",
                (room["chatroom_id"], tmpl_index_date, tmpl_user_id, room["new_name"], "kakao", 0),
            )
            conn.commit()
            chatroom_id, index_date, user_id = room["chatroom_id"], tmpl_index_date, tmpl_user_id
            print(f"[OK] chatroom '{room['new_name']}' 신규 생성 ({chatroom_id[:8]}...)")
        else:
            chatroom_id, index_date, user_id = row
            # 방 이름 변경
            cur.execute(
                "UPDATE chatroom SET chatroom_name=%s WHERE chatroom_id=%s AND index_date=%s AND user_id=%s",
                (room["new_name"], chatroom_id, index_date, user_id),
            )

        # 참여자를 chatroom_people에도 등록(참여자 탭에 이름이 뜨도록 + 주요 연락처
        # 호버 설명용). description도 ON DUPLICATE KEY UPDATE 대상에 넣어야 재실행 시
        # HS_MEMBER_DESCRIPTIONS를 바꿔도 실제로 반영된다(기존엔 message_count만 갱신돼서
        # 이미 있던 행은 최초 생성 당시 설명에 영원히 고정돼 있었음).
        cp_sql = """
            INSERT INTO chatroom_people (
                participant_id, chatroom_id, index_date, user_id, chatroom_people_name,
                message_count, description
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                message_count = VALUES(message_count),
                description = VALUES(description)
        """
        for member in room["members"]:
            description = HS_MEMBER_DESCRIPTIONS.get(member, f"'{room['new_name']}' 멤버입니다.")
            cur.execute(cp_sql, (member, chatroom_id, index_date, user_id, member, 0, description))
        conn.commit()

        # 요청 — "위에서 만든 사람 15명"에 대한 관계가 관계 창에 전부 떠야 함. 이 방은
        # 완전 하드코딩이라 GraphRAG가 뽑은 chatroom_relationship이 없거나(또는 기존
        # 4명분밖에 없어서) 부족하므로, 15명 사이 105쌍 전부를 여기서 직접 채워 넣는다
        # (누구의 상세보기를 열어도 나머지 14명이 다 나오도록).
        if room.get("narrative"):
            rel_sql = """
                INSERT INTO chatroom_relationship (
                    chatroom_id, index_date, user_id,
                    person_a, person_b, relation_label, description
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    relation_label = VALUES(relation_label),
                    description    = VALUES(description)
            """
            # 요청 — 15명 사이 관계 라벨을 전부 "친구"로 통일(기존 4단계 순환 풀 제거).
            pairs = list(itertools.combinations(sorted(room["members"]), 2))
            label = "친구"
            desc = HS_RELATION_DESCRIPTIONS[label]
            for person_a, person_b in pairs:
                cur.execute(rel_sql, (chatroom_id, index_date, user_id, person_a, person_b, label, desc))
            conn.commit()

        block_sql = """
            INSERT INTO message_block (
                block_id, chatroom_id, index_date, user_id, block_date,
                message_count, participant_count, kg_tone, llm_tone, participant
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE message_count=VALUES(message_count)
        """
        part_sql = """
            INSERT INTO participant (
                participant_name, block_id, chatroom_id, index_date, user_id, sent_message
            ) VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE sent_message=VALUES(sent_message)
        """
        kw_sql = """
            INSERT INTO message_keyword (
                keyword_name, participant_name, block_id, chatroom_id, index_date, user_id, mention_count
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE mention_count=VALUES(mention_count)
        """
        summ_sql = """
            INSERT INTO message_summarize (
                summarize_unit, summary_period, chatroom_id, index_date, user_id,
                summarized_context, contacts
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE summarized_context=VALUES(summarized_context), contacts=VALUES(contacts)
        """

        is_narrative = room.get("narrative", False)
        start_year = room.get("start_year", 2020)  # 요청 — 방마다 데이터 시작 연도 다르게
        date_start = room.get("date_start")
        date_end = room.get("date_end")
        if date_start and date_end:
            # 요청 — 이 방만 정확한 날짜 범위(2022-03-08~2026-05-04)로 좁힘
            months = [
                (y, m) for (y, m) in month_range(date_start.year, date_end.year)
                if (date_start.year, date_start.month) <= (y, m) <= (date_end.year, date_end.month)
            ]
        else:
            months = month_range(start_year, 2026)

        # 요청 — 김도현은 2022년엔 사실상 매 블록마다 말할 정도로 활발했다가, 2023년
        # 1~4월까지는 여전히 눈에 띄게 남아있고, 그 뒤로는 "점점 내려가는 느낌"으로
        # 서서히 잦아들도록(0으로 뚝 끊기지 않고 2026년에도 매달 최소 1건은 남게).
        # 2022년은 블록 단위로 바로 나누고(HS_KIM_2022_TOTAL), 2023년~2026년은 먼저
        # 월별로 지수 감쇠 곡선(hs_declining_monthly_totals)을 적용한 뒤 그 달의 3개
        # 블록으로 다시 나눈다.
        kim_block_plan = {}
        if is_narrative:
            months_2022 = [(yy, mm) for (yy, mm) in months if yy == 2022]
            if months_2022:
                # 요청 — My People 김도현 상세보기의 2022년 월별 메신저 통계 그래프가
                # 매달 정확히 125건으로 완전히 평평하게 나오는 문제(스크린샷으로 확인) —
                # 원인은 spread_int_total()의 가중치가 주기 9로 반복되는데, 그걸 블록
                # 30개(달 10개 × 3블록)에 한 번에 적용하면 달 경계(3블록 단위)와 주기가
                # 우연히 맞아떨어져서 달마다 3블록 가중치 합이 항상 똑같아지는 수학적
                # 우연이 있었다. 그래서 2023년 이후(hs_declining_monthly_totals)와 같은
                # 2단계 방식으로 바꿔 — 먼저 "월별 총량"을 따로 흔들어 나눈 뒤, 그 달의
                # 3블록으로 다시 나눈다.
                month_totals_2022 = spread_int_total(HS_KIM_2022_TOTAL, len(months_2022))
                for ym, month_total in zip(months_2022, month_totals_2022):
                    kim_block_plan[ym] = spread_int_total(month_total, 3)

            tail_months = [(yy, mm) for (yy, mm) in months if yy > 2022]
            if tail_months:
                tail_month_totals = hs_declining_monthly_totals(
                    HS_KIM_TAIL_TOTAL, len(tail_months), HS_KIM_TAIL_DECAY
                )
                for ym, month_total in zip(tail_months, tail_month_totals):
                    kim_block_plan[ym] = spread_int_total(month_total, 3)
        kim_block_cursor = {ym: 0 for ym in kim_block_plan}

        # (y, m) -> [(block_id, active_members), ...] — 월별 오버라이드(HS_MAY2026_*)가
        # "이 블록엔 실제로 누가 있었는지"를 나중에 다시 조회하지 않고도 알 수 있도록
        # 블록을 만들 때마다 바로 기록해둔다.
        month_block_participants = {}

        for mi, (y, m) in enumerate(months):
            blocks_this_month = 3
            if is_narrative:
                room_keywords = HS_MONTH_KEYWORD_OVERRIDES.get((y, m), HS_YEAR_THEMES[y]["keywords"])
            else:
                room_keywords = room["keywords"]
            for b in range(blocks_this_month):
                block_counter += 1
                block_id = f"{DEMO_BLOCK_PREFIX}{block_counter:06d}"
                day = 1 + (b * 9 + mi) % 27
                # 요청 — 첫 달/마지막 달은 실제 날짜가 2022-03-08~2026-05-04 범위
                # 밖으로 나가지 않도록 그 달의 day만 잘라준다.
                if date_start and (y, m) == (date_start.year, date_start.month):
                    day = max(day, date_start.day)
                if date_end and (y, m) == (date_end.year, date_end.month):
                    day = min(day, date_end.day)
                block_date = datetime.date(y, m, day)
                kg_tone = "casual" if (mi + b) % 3 else "transactional"
                llm_tone = "friendly" if (mi + b) % 2 == 0 else "not_friendly"

                # 김도현 계획값 — 0(또는 계획 없음)이면 이 블록엔 아예 참여 안 한 걸로
                # (참여자 행 자체를 안 남김 — "찔끔찔끔"이 진짜 뜸한 느낌이 나도록).
                kim_value = None
                if is_narrative and (y, m) in kim_block_plan:
                    idx = kim_block_cursor[(y, m)]
                    kim_value = kim_block_plan[(y, m)][idx]
                    kim_block_cursor[(y, m)] = idx + 1

                base_members = (
                    [mm for mm in room["members"] if mm != HS_TARGET_MEMBER]
                    if is_narrative
                    else room["members"]
                )
                active_base = base_members[: 2 + (mi + b) % len(base_members)]
                if is_narrative and kim_value:
                    active_members = [
                        mm for mm in room["members"] if mm in active_base or mm == HS_TARGET_MEMBER
                    ]
                else:
                    active_members = active_base
                participant_json = json.dumps(active_members, ensure_ascii=False)

                other_count = len(active_base)
                base_msg_count = 5 + (mi + b) % 30
                per_member = max(1, base_msg_count // max(1, other_count))

                # 요청 — 참여패턴이 다 똑같아 보이지 않게(데모 티 안 나게) 멤버마다
                # 이름 기반으로 살짝 다른 값을 준다. msg_count는 실제 개인별 합계와
                # 항상 일치하도록 나중에 합산해서 채운다.
                sent_map = {}
                for member in active_members:
                    if is_narrative and member == HS_TARGET_MEMBER:
                        sent_map[member] = kim_value
                    else:
                        jitter = (sum(ord(c) for c in member) + mi + b) % 5 - 2
                        sent_map[member] = max(1, per_member + jitter)
                msg_count = sum(sent_map.values())

                cur.execute(block_sql, (
                    block_id, chatroom_id, index_date, user_id, block_date,
                    msg_count, len(active_members), kg_tone, llm_tone, participant_json,
                ))
                month_block_participants.setdefault((y, m), []).append((block_id, list(active_members)))

                for member_idx, member in enumerate(active_members):
                    sent = sent_map[member]
                    cur.execute(part_sql, (member, block_id, chatroom_id, index_date, user_id, sent))
                    # 요청 — HS_MEMBERS(와 다른 방 멤버들)가 대부분 이름 길이가 똑같아서
                    # (전부 3글자) len(member)로는 인덱스가 사실상 안 흔들려, 한 달에 블록
                    # 3개뿐이면 키워드 풀 크기와 무관하게 매달 최대 3종류만 뽑히는 버그가
                    # 있었다(예: 2022-09 커스텀 11개 풀 중 3개만 등장). 멤버 이름 대신 블록
                    # 안에서의 순번(member_idx)으로 인덱스를 흔들어 풀 전체가 고르게 뽑히게 함.
                    kw = room_keywords[(mi + b + member_idx) % len(room_keywords)]
                    mention = 1 + (mi + b) % 4
                    cur.execute(kw_sql, (kw, member, block_id, chatroom_id, index_date, user_id, mention))

            if block_counter % 150 == 0:
                conn.commit()

            # 월별 요약(message_summarize, summarize_unit='monthly')
            period = f"{y}-{m:02d}"
            if is_narrative:
                if (y, m) in HS_MONTH_TEXT_OVERRIDES:
                    summary = HS_MONTH_TEXT_OVERRIDES[(y, m)]
                else:
                    summary, _, _ = hs_month_text(y, m, mi, room["members"])
                month_contacts = HS_MONTH_CONTACTS_OVERRIDES.get((y, m), room["members"])
            else:
                kw1 = room["keywords"][mi % len(room["keywords"])]
                kw2 = room["keywords"][(mi + 2) % len(room["keywords"])]
                summary = (
                    f"{y}년 {m}월 '{room['new_name']}'에서는 '{kw1}', '{kw2}' 관련 대화가 "
                    f"많았습니다. {', '.join(room['members'][:3])}와(과) 활발하게 대화했습니다."
                )
                month_contacts = room["members"]
            contacts = json.dumps(month_contacts, ensure_ascii=False)
            cur.execute(summ_sql, ("monthly", period, chatroom_id, index_date, user_id, summary, contacts))

        # 요청 — 2026-05는 위에서 이미 일반 로직(사회초년생 테마)으로 채워진 블록/키워드/
        # 요약을 이 방(HS_CHATROOM_ID)에 한해 손으로 다시 덮어쓴다. 일반 루프가 만든
        # 블록(month_block_participants)은 그대로 재사용하고, 그 블록들에 걸린 키워드만
        # 지운 뒤 HS_MAY2026_KEYWORDS로 다시 심는다 — 참여자는 실제로 그 블록에 있었던
        # 사람 중에서 동적으로 찾으므로(FK: message_keyword -> participant), 김도현처럼
        # "찔끔찔끔"이라 매달 등장 블록이 달라지는 사람도 안전하게 매칭된다.
        if is_narrative and room["chatroom_id"] == HS_CHATROOM_ID:
            may_key = tuple(int(x) for x in HS_MAY2026_PERIOD.split("-"))
            may_blocks = month_block_participants.get(may_key)
            if may_blocks:
                block_ids = [bid for bid, _ in may_blocks]
                placeholders = ",".join(["%s"] * len(block_ids))
                cur.execute(
                    f"DELETE FROM message_keyword WHERE chatroom_id=%s AND index_date=%s "
                    f"AND user_id=%s AND block_id IN ({placeholders})",
                    (chatroom_id, index_date, user_id, *block_ids),
                )
                for kw, participant, count in HS_MAY2026_KEYWORDS:
                    target_block = next(
                        (bid for bid, members in may_blocks if participant in members), None
                    )
                    if target_block is None:
                        print(f"[WARN] HS_MAY2026_KEYWORDS: '{participant}'이(가) "
                              f"{HS_MAY2026_PERIOD} 어느 블록에도 없어 '{kw}' 건너뜀")
                        continue
                    cur.execute(kw_sql, (
                        kw, participant, target_block, chatroom_id, index_date, user_id, count,
                    ))
                cur.execute(summ_sql, (
                    "monthly", HS_MAY2026_PERIOD, chatroom_id, index_date, user_id,
                    HS_MAY2026_SUMMARY, json.dumps(HS_MAY2026_CONTACTS, ensure_ascii=False),
                ))
            else:
                print(f"[WARN] HS_MAY2026_KEYWORDS: {HS_MAY2026_PERIOD}에 해당하는 블록이 "
                      f"없어(날짜 범위 밖) 오버라이드를 건너뜁니다.")

        conn.commit()

        # 연도별 요약 (요청 — 방 데이터 시작 연도(start_year)부터만)
        for y in range(start_year, 2027):
            if is_narrative:
                summary = hs_year_text(y, room["members"])
            else:
                kw = room["keywords"][y % len(room["keywords"])]
                summary = (
                    f"{y}년 '{room['new_name']}'은(는) '{kw}' 등 다양한 주제로 꾸준히 "
                    f"대화가 이어졌습니다."
                )
            contacts = json.dumps(room["members"], ensure_ascii=False)
            cur.execute(summ_sql, ("yearly", str(y), chatroom_id, index_date, user_id, summary, contacts))
        conn.commit()

        # 요청 — "3학년 4반 고등학교 단톡방" 방 분위기를 "활발하고 밝은 분위기"로.
        # message_mood 테이블은 원래 실제 인덱싱(LLM 분위기 분석) 때만 채워지는데, 이
        # 방은 완전 하드코딩이라 옛날에 실제로 인덱싱됐을 때 나온 사무적인 점수가 그대로
        # 남아있었다 — 여기서 월별/연도별로 다시 채워서 덮어쓴다.
        if is_narrative:
            mood_sql = """
                INSERT INTO message_mood (
                    summary_period, summary_unit, chatroom_id, index_date, user_id,
                    mood_description, mood_score
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    mood_description = VALUES(mood_description),
                    mood_score = VALUES(mood_score)
            """
            for mi, (y, m) in enumerate(months):
                period = f"{y}-{m:02d}"
                cur.execute(mood_sql, (
                    period, "monthly", chatroom_id, index_date, user_id,
                    hs_mood_description(mi), hs_mood_score(mi),
                ))
            for yi, y in enumerate(range(start_year, 2027)):
                cur.execute(mood_sql, (
                    str(y), "yearly", chatroom_id, index_date, user_id,
                    hs_mood_description(yi + 3), hs_mood_score(yi + 3),
                ))
            conn.commit()

        print(f"[OK] 메신저 '{room['new_name']}' ({chatroom_id[:8]}...): "
              f"block {block_counter - block_counter_start}건 생성")
        return block_counter
    finally:
        cur.close()


# ────────────────────────────── 5. main ──────────────────────────────

def get_latest_index_date(conn, user_mail_account_id):
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT index_date FROM mail_account WHERE user_mail_account_id=%s "
            "ORDER BY index_date DESC LIMIT 1",
            (user_mail_account_id,),
        )
        row = cur.fetchone()
        return row["index_date"] if row else None
    finally:
        cur.close()


def main():
    roster = build_roster()
    print(f"[INFO] 사람 {len(roster)}명(가족 5 · 베프 18 · 친구 1(이서연) · 가끔연락 5 · "
          f"소원함 9 · 광고 10, 영어 실명은 Daniel Cho 1명만, 이름 중복 없음) 생성")

    conn = get_db_connection()
    try:
        index_date = get_latest_index_date(conn, MAIL_USER_ID)
        if not index_date:
            print(f"[ERROR] mail_account에 {MAIL_USER_ID} 레코드가 없습니다. 먼저 계정을 한 번 인덱싱하세요.")
            return

        print("[STEP] 이전 시연용 데이터 정리 중...")
        cleanup_mail_domain(conn, roster)

        print("[STEP] 메일 도메인(연락처/친밀도/키워드) 채우는 중...")
        roster_stats = seed_mail_domain(conn, roster, index_date)

        print("[STEP] My Time 메일 요약(mail_summaries.json) 오버라이드 적용 중...")
        apply_mail_summary_overrides(BASE_DIR)

        print("[STEP] Recap 연락처 통계(mail_contact_stats.json) 오버라이드 적용 중...")
        apply_mail_contact_stats_overrides(BASE_DIR, roster_stats)

        print("[STEP] 메신저 채팅방 이름/요약/키워드 채우는 중...")
        block_counter = 0
        for room in CHATROOMS:
            cleanup_messenger_domain(conn, room)
            block_counter = seed_messenger_domain(conn, room, block_counter)

    finally:
        conn.close()

    print("완료! My People / My Time 페이지를 새로고침하면 반영됩니다.")
    print("(메일 표시 이메일은 accountPicker.js에서 화면 텍스트만 바꾼 것이라, "
          "이 스크립트가 건드리는 실제 계정 식별자는 그대로 03yeah03@gmail.com / 03yeeun03@naver.com 입니다.)")


if __name__ == "__main__":
    main()
