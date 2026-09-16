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

import calendar
import datetime
import hashlib
import itertools
import json
import os
import shutil
import sys
import pandas as pd

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

# 요청 — "3학년 4반 고등학교 단톡방" 상세보기 상단에 뜨는 참여 패턴/자주 하는
# 이야기/말투(chatroom_people.description·short_bio) 설명을 15명 전원 가짜
# 데이터로 채워달라는 요청. 단, 김도현은 예시로 보여준 게 실인덱싱 때 실제로 생성된
# 진짜 데이터라서 절대 건드리면 안 됨 — 아래 dict에 김도현은 아예 넣지 않고,
# cp_sql 루프에서도 김도현만 skip해서 그의 기존 DB 값을 그대로 보존한다.
# 한지원은 다른 14명과 달리 급우가 아니라 "선생님"(HS_MEMBER_RELATION_OVERRIDES 참고)
# 이라서, 반말로 재잘거리는 다른 친구들과 다르게 존댓말로 제자들 근황을 챙기는
# 느낌으로 따로 썼다.
HS_MEMBER_DESCRIPTIONS = {
    "이수빈": (
        "참여 패턴: 꾸준히 참여합니다.\n"
        "자주 하는 이야기: 근황과 진로 고민, 서로 다독이는 이야기를 자주 나눕니다.\n"
        "말투: 존댓말과 반말을 섞어 차분하게 이야기하며, 이모티콘은 가끔만 씁니다."
    ),
    "박재현": (
        "참여 패턴: 활발히 참여합니다.\n"
        "자주 하는 이야기: 운동, 헬스, 등산 같은 취미 이야기를 자주 꺼냅니다.\n"
        "말투: 반말로 씩씩하게 얘기하며, 느낌표를 자주 씁니다."
    ),
    "최유나": (
        "참여 패턴: 매우 활발히 참여합니다.\n"
        "자주 하는 이야기: 맛집, 여행, 요즘 유행하는 이야기를 자주 공유합니다.\n"
        "말투: 반말로 발랄하게 얘기하며, 이모티콘과 사진을 자주 올립니다."
    ),
    "정하늘": (
        "참여 패턴: 꾸준히 참여합니다.\n"
        "자주 하는 이야기: 자기계발, 운동, 재테크 같은 이야기를 자주 나눕니다.\n"
        "말투: 반말로 담백하게 얘기하며, 이모티콘은 거의 쓰지 않습니다."
    ),
    "오승민": (
        "참여 패턴: 가끔 참여합니다.\n"
        "자주 하는 이야기: 게임, 신작 소식, 컴퓨터 관련 이야기를 자주 꺼냅니다.\n"
        "말투: 반말로 짧게 얘기하며, 게임 용어를 자주 섞어 씁니다."
    ),
    "한지원": (
        "참여 패턴: 이따금 들어와 근황을 살펴보는 편입니다.\n"
        "자주 하는 이야기: 제자들 취업과 진로, 근황을 챙기며 안부를 묻는 이야기를 주로 합니다.\n"
        "말투: 존댓말로 다정하게 이야기하며, 이모티콘은 거의 쓰지 않습니다."
    ),
    "배수아": (
        "참여 패턴: 꾸준히 참여합니다.\n"
        "자주 하는 이야기: 근황과 연애, 서로 위로하는 이야기를 자주 나눕니다.\n"
        "말투: 반말로 다정하게 얘기하며, 이모티콘을 자주 사용합니다."
    ),
    "임찬우": (
        "참여 패턴: 활발히 참여합니다.\n"
        "자주 하는 이야기: 동창회나 술자리 약속을 주도적으로 잡는 이야기를 자주 합니다.\n"
        "말투: 반말로 유쾌하게 얘기하며, 느낌표와 이모티콘을 자주 씁니다."
    ),
    "신예진": (
        "참여 패턴: 활발히 참여합니다.\n"
        "자주 하는 이야기: 노래방, 최근 들은 음악 이야기를 자주 꺼냅니다.\n"
        "말투: 반말로 밝게 얘기하며, 이모티콘을 자주 사용합니다."
    ),
    "강태오": (
        "참여 패턴: 매우 활발히 참여합니다.\n"
        "자주 하는 이야기: 장난스러운 드립과 근황 얘기로 분위기를 자주 띄웁니다.\n"
        "말투: 반말로 유쾌하게 얘기하며, 이모티콘을 아주 자주 사용합니다."
    ),
    "문서영": (
        "참여 패턴: 가끔 참여합니다.\n"
        "자주 하는 이야기: 그림, 전시회, 감성적인 일상 이야기를 자주 나눕니다.\n"
        "말투: 반말로 차분하게 얘기하며, 감성적인 이모티콘을 종종 사용합니다."
    ),
    "조은비": (
        "참여 패턴: 가끔 참여합니다.\n"
        "자주 하는 이야기: 사진, 카페 나들이 같은 소소한 일상 이야기를 자주 올립니다.\n"
        "말투: 반말로 차분하게 얘기하며, 사진을 자주 첨부합니다."
    ),
    "윤도경": (
        "참여 패턴: 드물게 참여합니다.\n"
        "자주 하는 이야기: 짧게라도 안부를 묻거나 응원하는 말을 남깁니다.\n"
        "말투: 반말로 짧고 담백하게 얘기하며, 이모티콘은 거의 쓰지 않습니다."
    ),
    "백하은": (
        "참여 패턴: 꾸준히 참여합니다.\n"
        "자주 하는 이야기: 약속 일정을 챙기고 동창회 계획을 정리하는 이야기를 자주 합니다.\n"
        "말투: 반말로 또박또박 얘기하며, 이모티콘은 가끔만 씁니다."
    ),
}

# 요청 — My Time "주요 연락처" 툴팁(mytimeEngine.js formatContactTooltip)이 description과
# 똑같은 문장(참여 패턴/자주 하는 이야기/말투 3줄)을 그대로 보여줘서 이상해졌다는 지적 —
# 원래 이 툴팁은 short_bio(한 줄 소개)만 봐야 하는데, 예전엔 이 방(HS_CHATROOM_ID)이
# 실인덱싱 없이 만들어져 short_bio가 채워질 기회가 없어서 description을 그대로
# short_bio에도 복사해 넣었었다(하단 cp_sql 주석 참고) — 그때는 description이 짧아서
# 문제가 안 됐는데, 이번에 description을 3줄 형식으로 새로 채우면서 그대로 같이
# 새어나온 것. description과 별개로, 실제 short_bio 생성 프롬프트(message_statics.py
# generate_chatroom_people_short_bios)와 같은 톤(한 문장, 존댓말 "~습니다./~입니다.",
# 반말·영어·한자 금지)으로 진짜 한 줄 소개를 따로 만들어서 short_bio 컬럼에는 이걸 쓴다.
HS_MEMBER_SHORT_BIOS = {
    "이수빈": "꾸준히 대화에 참여하며 근황과 진로 고민을 서로 다독이는 이야기를 자주 나누는 친구입니다.",
    "박재현": "운동과 등산 같은 취미 이야기를 즐겨 나누며 활발하게 대화에 참여하는 친구입니다.",
    "최유나": "맛집과 여행, 요즘 유행하는 이야기를 발랄하게 공유하며 매우 활발히 참여하는 친구입니다.",
    "정하늘": "자기계발과 재테크 이야기를 담백하게 나누며 꾸준히 대화에 참여하는 친구입니다.",
    "오승민": "게임과 신작 소식 이야기를 즐겨 나누며 가끔 대화에 참여하는 친구입니다.",
    "한지원": "제자들의 취업과 진로, 근황을 다정하게 챙기는 고3 때 담임 선생님입니다.",
    "배수아": "근황과 연애 이야기를 다정하게 나누며 서로 위로해주는 꾸준한 참여자입니다.",
    "임찬우": "동창회와 술자리 약속을 주도적으로 잡으며 유쾌하게 대화를 이끄는 친구입니다.",
    "신예진": "노래방과 최근 들은 음악 이야기를 밝게 나누며 활발히 참여하는 친구입니다.",
    "강태오": "장난스러운 드립으로 분위기를 띄우며 매우 활발하게 대화에 참여하는 친구입니다.",
    "문서영": "그림과 전시회, 감성적인 일상 이야기를 차분하게 나누는 친구입니다.",
    "조은비": "사진과 카페 나들이 같은 소소한 일상을 차분하게 공유하는 친구입니다.",
    "윤도경": "짧게나마 안부를 묻고 응원의 말을 남기는, 드물지만 다정한 참여자입니다.",
    "백하은": "약속 일정과 동창회 계획을 또박또박 잘 챙기는 꾸준한 참여자입니다.",
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

# 요청 — 김도현 메신저 키워드(My Time 키워드 그래프)가 지금은 방 전체 15명이
# 공유하는 연도별 8개짜리 테마 풀(HS_YEAR_THEMES[y]["keywords"])에서 순번만
# 밀려서 뽑히다 보니, 그가 실제로 등장하는 블록 수가 적은 달엔 몇 안 되는 단어만
# 반복돼서 "다양하다"는 느낌이 잘 안 남. 김도현만 따로, 연도별 개인 서사(대학
# 새내기/알바·군입대/휴학·복학·인턴/취업준비/사회초년생)에 맞는 전용 키워드 풀을
# 두고, 그가 실제로 등장한 횟수(연도별 누적)를 기준으로 순환시켜 풀 전체가 고르게
# 다 뽑히게 한다. (다른 14명이 쓰는 room_keywords 로직은 그대로 안 건드림.)
HS_KIM_KEYWORD_POOL_BY_YEAR = {
    2022: ["기말고사", "모의고사", "야자", "수능", "졸업식", "반친구들", "담임쌤", "급식", "체육대회", "방과후"],
    2023: ["전공수업", "알바", "군입대", "훈련소", "자취", "학점", "조모임", "면회", "휴가", "복무"],
    2024: ["휴학", "복학", "인턴", "공모전", "자격증", "토익", "포트폴리오", "졸업유예", "동아리", "학회"],
    2025: ["자소서", "면접", "취업준비", "채용공고", "스터디", "포트폴리오", "합격", "불합격", "최종면접", "인적성"],
    2026: ["첫출근", "회사생활", "적응", "월급", "회식", "재테크", "동창회", "안부", "출장", "야근"],
}

# 요청 — "김도현 메신저 통계에서 대화 본문도 조작해줘 전부 다 채워줘": 지금까지는
# message_block/message_keyword까지만 채웠지, 상세보기에서 그 날짜를 눌렀을 때 실제로
# 뜨는 대화 내용(documents.parquet, get_chatroom_day_messages가 여기서 파싱해서 보여줌)은
# 이 방 전체(HS 단톡방)에 애초에 한 줄도 없었다 — 그래서 그동안 김도현이 등장하는
# 날짜를 눌러도 "그날 대화를 찾지 못했어요" 상태였을 것이다. 김도현이 실제로 참여한
# 블록(위 kim_block_plan으로 등장하는 91개 안팎)에만, 그 블록에 배정된 키워드
# (HS_KIM_KEYWORD_POOL_BY_YEAR, 같은 인덱스)와 짝이 맞는 짧은 대화문을 심는다 —
# 년도별 서사(새내기→알바/군입대→휴학복학/인턴→취업준비→사회초년생) 톤에 맞춘
# 3줄짜리 템플릿을 키워드/상대방 이름만 바꿔 채운다. 다른 14명 몫의 대화 본문은
# 전혀 만들지 않는다(요청 범위가 "김도현"으로 명확히 한정됨 — 다른 사람 몫까지
# 새로 지어내면 안 하기로 한 하드코딩 범위를 넘어서게 된다).
#
# 주의 — chatroom_people.description/short_bio(김도현 실제 인덱싱 데이터, 절대 불가침)는
# 원래 이 documents.parquet 대화 이력을 LLM에 넣어 생성한 것이지만(message_statics.py의
# generate_chatroom_people_descriptions), 그 생성 파이프라인은 현재 app.py 어디에서도
# 자동으로 호출되지 않는다(메일 쪽만 업로드 시 자동 파이프라인이 돎) — 그래도 나중에
# 누군가 그 파이프라인을 이 방에 대해 수동으로 다시 돌리면, 지금 심는 가짜 대화문을
# 근거로 김도현의 description/short_bio가 재생성되며 실제 값을 덮어쓸 수 있으니
# 주의가 필요하다.
#
# 요청 — "하루날짜마다 대화본문내용이 다 똑같아 다다르게 김도현 구성": 연도별로 템플릿이
# 딱 1개뿐이라 키워드/상대방 이름만 바뀌고 문장 골격 자체는 매일 동일했음(똑같은 대사가
# 계속 반복되는 것처럼 보임). 연도마다 여러 개의 "변형(variant)" 템플릿을 두고, 그 블록에
# 배정된 키워드 순번(kim_idx, HS_KIM_KEYWORD_POOL_BY_YEAR와 같은 인덱스)으로 변형을
# 순환시켜 날짜마다 다른 골격의 대화가 나오게 한다.
HS_KIM_CONVO_LINE_TEMPLATES = {
    2022: [
        [
            "{other1}: {kw} 때문에 죽겠다 진짜ㅠㅠ",
            "김도현: 나도ㅋㅋ 근데 그래도 다 같이 하니까 좀 낫다",
            "{other2}: 그러게, 이따 끝나고 매점이나 가자",
        ],
        [
            "김도현: 오늘 {kw} 어땠어? 나는 진짜 정신없었어",
            "{other1}: 나도 똑같아ㅋㅋ 근데 끝나니까 후련하긴 하다",
            "{other2}: 그니까, 우리 이따 반 애들이랑 다 같이 놀자",
        ],
        [
            "{other1}: 야 담임쌤이 {kw} 얘기하시던데 들었어?",
            "김도현: 어 들었어ㅋㅋㅋ 또 잔소리하시겠지 뭐",
            "{other2}: 그래도 우리 반은 무사히 넘어가자ㅠㅠ",
        ],
        [
            "김도현: 아 오늘 {kw} 완전 빡셌다...",
            "{other1}: 헐 진짜? 고생했다ㅠㅠ",
            "{other2}: 끝나고 매점에서 보자, 내가 쏠게",
        ],
        [
            "{other1}: {kw} 끝나고 다들 뭐해?",
            "김도현: 나는 그냥 집 가서 좀 쉬려고",
            "{other2}: 좋다, 나도 오늘은 일찍 자야지",
        ],
    ],
    2023: [
        [
            "{other1}: 요즘 {kw} 때문에 정신없지?",
            "김도현: 어 진짜 하루하루가 빠듯하다ㅠ",
            "{other2}: 그래도 몸 상하지 말고 잘 챙겨 먹어",
        ],
        [
            "김도현: 나 요즘 {kw} 때문에 정신이 하나도 없다ㅋㅋ",
            "{other1}: 헐 고생 많다... 밥은 챙겨 먹고 다니는 거지?",
            "{other2}: 그니까, 너무 무리하지는 마",
        ],
        [
            "{other1}: {kw} 어떻게 돼가? 잘 하고 있어?",
            "김도현: 그럭저럭 버티는 중이야, 적응하는 데 시간 좀 걸리네",
            "{other2}: 화이팅이다, 조만간 얼굴 보자",
        ],
        [
            "김도현: 오늘 {kw} 얘기 나왔는데 다들 비슷한가봐",
            "{other1}: 맞아, 다들 사는 게 다 거기서 거기지 뭐",
            "{other2}: 그래도 서로 있으니까 든든하다",
        ],
    ],
    2024: [
        [
            "{other1}: {kw} 준비는 잘 되고 있어?",
            "김도현: 이제 슬슬 시작하려고, 막막하긴 하다",
            "{other2}: 화이팅! 필요하면 언제든 얘기해",
        ],
        [
            "김도현: 나 요즘 {kw} 때문에 계획 다시 짜는 중이야",
            "{other1}: 오 잘 생각했다, 나도 좀 도와줄까?",
            "{other2}: 좋다, 다 같이 한번 얘기해보자",
        ],
        [
            "{other1}: {kw} 쪽으로 알아봤어?",
            "김도현: 어 몇 군데 찾아보고 있어, 아직 결정은 못했어",
            "{other2}: 천천히 알아봐, 급할 거 없어",
        ],
        [
            "김도현: {kw} 때문에 요즘 좀 바빠졌어",
            "{other1}: 오 진짜? 어떻게 돼가는지 궁금하다",
            "{other2}: 다음에 만나면 자세히 얘기해줘",
        ],
    ],
    2025: [
        [
            "{other1}: {kw} 쪽은 어떻게 돼가?",
            "김도현: 아직 결과 기다리는 중이야ㅠㅠ",
            "{other2}: 좋은 소식 있을 거야, 조금만 기다려보자",
        ],
        [
            "김도현: 오늘 {kw} 때문에 하루 종일 긴장했다",
            "{other1}: 헐 고생했어, 잘 마무리됐어?",
            "{other2}: 결과 나오면 바로 알려줘!",
        ],
        [
            "{other1}: {kw} 준비하느라 힘들지...",
            "김도현: 그니까, 근데 다들 열심히 하니까 나도 힘낸다",
            "{other2}: 우리 다 같이 잘 됐으면 좋겠다",
        ],
        [
            "김도현: {kw} 관련해서 오늘 스터디원들이랑 얘기했어",
            "{other1}: 오 어땠어? 도움 됐어?",
            "{other2}: 다행이다, 우리도 같이 준비하자",
        ],
    ],
    2026: [
        [
            "{other1}: {kw} 얘기 좀 해줘, 궁금하다",
            "김도현: 요즘 적응하느라 바쁘다, 그래도 할 만해",
            "{other2}: 다행이다, 조만간 얼굴 한번 보자",
        ],
        [
            "김도현: 오늘 {kw} 때문에 좀 정신없었어",
            "{other1}: 회사 생활 힘들지... 밥은 챙겨 먹고 다녀",
            "{other2}: 그니까, 우리도 조만간 다 같이 보자",
        ],
        [
            "{other1}: {kw}는 어때, 적응 좀 됐어?",
            "김도현: 조금씩 익숙해지고 있어, 아직 배울 게 많다",
            "{other2}: 화이팅! 힘들면 언제든 얘기해",
        ],
        [
            "김도현: 요즘 {kw} 때문에 정신이 하나도 없다ㅋㅋ",
            "{other1}: 사회생활이 원래 그렇지 뭐, 고생 많다",
            "{other2}: 그래도 잘 하고 있는 거 같아 보기 좋다",
        ],
    ],
}

# 김도현이 실제로 등장한 블록 정보를 모아뒀다가(seed_messenger_domain 루프 안에서
# 채움), 그 방 처리가 끝난 뒤 apply_kim_dohyun_conversation_bodies()가 한 번에
# documents.parquet에 심는다.
KIM_CONVO_ENTRIES = []


def kim_convo_lines(y, keyword, other_members, variant_idx=0):
    """HS_KIM_CONVO_LINE_TEMPLATES[y](변형 템플릿 여러 개의 리스트)에서 variant_idx로
    하나를 골라, 그 블록의 키워드/상대방 이름으로 채워 "HH:MM 발신자: 텍스트" 형식
    (실제 인덱싱 대화와 같은 포맷, message_statics.py의 _MSG_LINE_RE가 파싱하는 형식)의
    줄 목록으로 만든다. variant_idx를 블록마다 다르게 넘기면(kim_idx 등) 매일 같은
    골격의 대사가 반복되지 않고 날짜마다 다른 대화로 보인다."""
    variants = HS_KIM_CONVO_LINE_TEMPLATES.get(y, HS_KIM_CONVO_LINE_TEMPLATES[2026])
    tmpl = variants[variant_idx % len(variants)]
    o1 = other_members[0] if other_members else "이수빈"
    o2 = other_members[1] if len(other_members) > 1 else o1
    lines = []
    for i, raw in enumerate(tmpl):
        sender, _, text = raw.format(kw=keyword, other1=o1, other2=o2).partition(": ")
        lines.append(f"21:{10 + i * 3:02d} {sender.strip()}: {text.strip()}")
    return lines

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
    # 요청 — 한지원만 관계를 "선생님"으로.
    "선생님": "고3 때 담임 선생님이셨는데, 지금도 가끔 안부를 주고받는 사이입니다.",
}
# 요청 — 특정 멤버는 관계 라벨을 "친구"가 아니라 여기 지정한 값으로 덮어쓴다.
HS_MEMBER_RELATION_OVERRIDES = {
    "한지원": "선생님",
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
        # 요청 — 이 chatroom_id가 실제로 인덱싱된 적 없는 계정(DB 초기화 등)에서는
        # 조용히 건너뛰어서(seed_messenger_domain의 [WARN] 분기) My People 사이드바에
        # 아예 안 뜨는 문제가 있었음 — create_if_missing을 켜서, 실인덱싱 없이도
        # 이 chatroom_id로 새 방을 바로 만들도록 함.
        "create_if_missing": True,
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


# 요청 — "이서연 8/23 정산서류 말고 다른 날짜들은 다 밋밋한 템플릿"이라는 지적 —
# leeseoyeon_mail_plan()이 만드는 71건(2024-01~2026-08) 중 정산서류 1건 말고는
# 전부 mail_id_override=None이라 documents.parquet에 본문을 못 심었었다. 아래
# LSY_MAIL_ID_OVERRIDES는 (연,월,일) -> 고정 mail_id 매핑으로, leeseoyeon_mail_plan()의
# "remaining"(정산서류 자리를 뺀 나머지) 루프가 만드는 날짜/방향은 100% 그대로 두고
# mail_id만 예측 가능하게 고정한다(is_settlement은 계속 False라 kg_tone/llm_tone/
# is_reply/elapsed 같은 기존 톤·답장 패턴도 전혀 안 바뀐다 — mail_id만 새로 생김).
# 값은 이 스크립트를 고치기 전 leeseoyeon_mail_plan()이 실제로 만들던 날짜와
# 정확히 동일하게 맞춰서 뽑아뒀다(달력 자체는 바뀌지 않음).
LSY_MAIL_ID_OVERRIDES = {
    (2024, 2, 1): "DEMO-MAIL-LSY-001",
    (2024, 2, 4): "DEMO-MAIL-LSY-002",
    (2024, 2, 7): "DEMO-MAIL-LSY-003",
    (2024, 4, 1): "DEMO-MAIL-LSY-004",
    (2024, 4, 4): "DEMO-MAIL-LSY-005",
    (2024, 4, 7): "DEMO-MAIL-LSY-006",
    (2024, 4, 10): "DEMO-MAIL-LSY-007",
    (2024, 4, 13): "DEMO-MAIL-LSY-008",
    (2024, 6, 1): "DEMO-MAIL-LSY-009",
    (2024, 6, 4): "DEMO-MAIL-LSY-010",
    (2024, 8, 1): "DEMO-MAIL-LSY-011",
    (2024, 8, 4): "DEMO-MAIL-LSY-012",
    (2024, 8, 7): "DEMO-MAIL-LSY-013",
    (2024, 8, 10): "DEMO-MAIL-LSY-014",
    (2024, 10, 1): "DEMO-MAIL-LSY-015",
    (2024, 10, 4): "DEMO-MAIL-LSY-016",
    (2024, 10, 7): "DEMO-MAIL-LSY-017",
    (2024, 10, 10): "DEMO-MAIL-LSY-018",
    (2024, 10, 13): "DEMO-MAIL-LSY-019",
    (2024, 10, 16): "DEMO-MAIL-LSY-020",
    (2024, 12, 1): "DEMO-MAIL-LSY-021",
    (2024, 12, 4): "DEMO-MAIL-LSY-022",
    (2024, 12, 7): "DEMO-MAIL-LSY-023",
    (2025, 2, 1): "DEMO-MAIL-LSY-024",
    (2025, 2, 4): "DEMO-MAIL-LSY-025",
    (2025, 2, 7): "DEMO-MAIL-LSY-026",
    (2025, 2, 10): "DEMO-MAIL-LSY-027",
    (2025, 2, 13): "DEMO-MAIL-LSY-028",
    (2025, 3, 1): "DEMO-MAIL-LSY-029",
    (2025, 3, 4): "DEMO-MAIL-LSY-030",
    (2025, 5, 1): "DEMO-MAIL-LSY-031",
    (2025, 5, 4): "DEMO-MAIL-LSY-032",
    (2025, 5, 7): "DEMO-MAIL-LSY-033",
    (2025, 5, 10): "DEMO-MAIL-LSY-034",
    (2025, 5, 13): "DEMO-MAIL-LSY-035",
    (2025, 5, 16): "DEMO-MAIL-LSY-036",
    (2025, 5, 19): "DEMO-MAIL-LSY-037",
    (2025, 7, 1): "DEMO-MAIL-LSY-038",
    (2025, 7, 4): "DEMO-MAIL-LSY-039",
    (2025, 7, 7): "DEMO-MAIL-LSY-040",
    (2025, 9, 1): "DEMO-MAIL-LSY-041",
    (2025, 9, 4): "DEMO-MAIL-LSY-042",
    (2025, 9, 7): "DEMO-MAIL-LSY-043",
    (2025, 9, 10): "DEMO-MAIL-LSY-044",
    (2025, 11, 1): "DEMO-MAIL-LSY-045",
    (2025, 11, 4): "DEMO-MAIL-LSY-046",
    (2025, 11, 7): "DEMO-MAIL-LSY-047",
    (2025, 11, 10): "DEMO-MAIL-LSY-048",
    (2025, 11, 13): "DEMO-MAIL-LSY-049",
    (2025, 11, 16): "DEMO-MAIL-LSY-050",
    (2025, 11, 19): "DEMO-MAIL-LSY-051",
    (2025, 11, 22): "DEMO-MAIL-LSY-052",
    (2026, 1, 1): "DEMO-MAIL-LSY-053",
    (2026, 1, 4): "DEMO-MAIL-LSY-054",
    (2026, 3, 1): "DEMO-MAIL-LSY-055",
    (2026, 3, 4): "DEMO-MAIL-LSY-056",
    (2026, 3, 7): "DEMO-MAIL-LSY-057",
    (2026, 3, 10): "DEMO-MAIL-LSY-058",
    (2026, 3, 13): "DEMO-MAIL-LSY-059",
    (2026, 5, 1): "DEMO-MAIL-LSY-060",
    (2026, 5, 4): "DEMO-MAIL-LSY-061",
    (2026, 5, 7): "DEMO-MAIL-LSY-062",
    (2026, 7, 1): "DEMO-MAIL-LSY-063",
    (2026, 7, 4): "DEMO-MAIL-LSY-064",
    (2026, 7, 7): "DEMO-MAIL-LSY-065",
    (2026, 7, 10): "DEMO-MAIL-LSY-066",
    (2026, 7, 13): "DEMO-MAIL-LSY-067",
    (2026, 7, 16): "DEMO-MAIL-LSY-068",
    (2026, 8, 1): "DEMO-MAIL-LSY-069",
    (2026, 8, 4): "DEMO-MAIL-LSY-070",
}

# 위 70건 각각의 제목/본문 — 2024년(과제/수업 위주)·2025~2026년(팀플/프로젝트
# 위주) 테마에 맞춰 키워드 풀(LSY_KEYWORD_POOL_EARLY/LATE)을 순환시키고, 방향(수신/
# 발신)에 맞는 말투 템플릿을 돌려썼다. 8/23 정산서류(LSY_SETTLE_SUBJECT/BODY)는
# 별도이고 여기엔 안 들어있다.
LSY_MAIL_BODIES = {
    "DEMO-MAIL-LSY-001": ("수업 내용 정리 확인했어", "네가 보내준 수업 내용 정리 확인했어, 정리 진짜 꼼꼼하게 잘했더라. 고마워!"),
    "DEMO-MAIL-LSY-002": ("과제 제출 다 됐어?", "저번에 얘기했던 과제 제출 어디까지 했어? 나는 거의 다 끝나가는데 너도 진행상황 좀 알려줘."),
    "DEMO-MAIL-LSY-003": ("강의자료 pdf 나도 정리해서 보낼게", "나도 강의자료 pdf 정리 끝났어, 조금 이따 파일로 보낼게. 맞는지 한번 봐줘."),
    "DEMO-MAIL-LSY-004": ("웹프로그래밍 실습 관련해서 물어볼 게 있어", "웹프로그래밍 실습 하다가 막히는 부분이 있는데 혹시 시간 될 때 좀 봐줄 수 있어?"),
    "DEMO-MAIL-LSY-005": ("강의노트 공유 자료 보낼게", "오늘 수업 때 나온 강의노트 공유 정리해서 보내. 혹시 빠진 부분 있으면 얘기해줘!"),
    "DEMO-MAIL-LSY-006": ("출석 확인 같이 하자", "이번 출석 확인 나눠서 하지 말고 그냥 같이 하는 게 나을 것 같은데 어때?"),
    "DEMO-MAIL-LSY-007": ("이번주 시험 범위 언제 할까", "이번 주 시험 범위 시간 맞춰서 정하자. 나는 화요일 오후 아니면 목요일 오전 가능해."),
    "DEMO-MAIL-LSY-008": ("과제 마감일 진행상황 공유", "과제 마감일 지금까지 한 거 정리해서 보내. 이 정도면 얼추 맞는 방향인 것 같아."),
    "DEMO-MAIL-LSY-009": ("수업 필기 오늘까지 끝낼 수 있을까", "수업 필기 오늘까지 끝내야 하는데 시간 괜찮으면 잠깐 같이 볼래?"),
    "DEMO-MAIL-LSY-010": ("실습 과제 pdf 놓친 부분 있어?", "오늘 수업 좀 정신없었는데 실습 과제 pdf 관련해서 놓친 부분 있으면 알려줘. 나도 다시 확인해볼게."),
    "DEMO-MAIL-LSY-011": ("조모임 일정 덕분에 살았다", "조모임 일정 자료 보내준 덕분에 훨씬 수월하게 끝냈어, 진짜 고마워!"),
    "DEMO-MAIL-LSY-012": ("코드 리뷰 마감 얼마 안 남았어", "코드 리뷰 마감이 이번 주까지라 슬슬 서둘러야 할 것 같아. 진행 상황 어때?"),
    "DEMO-MAIL-LSY-013": ("팀플 회의 관련 질문", "혹시 팀플 회의 부분에서 이해 안 되는 거 있으면 나한테 물어봐도 돼, 아까 교수님한테 따로 여쭤봤거든."),
    "DEMO-MAIL-LSY-014": ("혹시 수업 내용 정리 같이 볼래?", "이번 수업 내용 정리 나 혼자 하기 좀 벅찬데, 시간 되면 같이 봐줄 수 있어?"),
    "DEMO-MAIL-LSY-015": ("과제 제출 확인했어", "네가 보내준 과제 제출 확인했어, 정리 진짜 꼼꼼하게 잘했더라. 고마워!"),
    "DEMO-MAIL-LSY-016": ("강의자료 pdf 확인 부탁해", "내가 정리한 강의자료 pdf 확인해줄 수 있어? 이상한 부분 있으면 편하게 말해줘."),
    "DEMO-MAIL-LSY-017": ("웹프로그래밍 실습 나도 정리해서 보낼게", "나도 웹프로그래밍 실습 정리 끝났어, 조금 이따 파일로 보낼게. 맞는지 한번 봐줘."),
    "DEMO-MAIL-LSY-018": ("오늘 강의노트 공유 어땠어?", "오늘 강의노트 공유 너무 어렵지 않았어? 나는 반쯤 이해한 것 같은데 너는 어때?"),
    "DEMO-MAIL-LSY-019": ("출석 확인 관련해서 물어볼 게 있어", "출석 확인 하다가 막히는 부분이 있는데 혹시 시간 될 때 좀 봐줄 수 있어?"),
    "DEMO-MAIL-LSY-020": ("시험 범위 다 됐어?", "저번에 얘기했던 시험 범위 어디까지 했어? 나는 거의 다 끝나가는데 너도 진행상황 좀 알려줘."),
    "DEMO-MAIL-LSY-021": ("과제 마감일 같이 하자", "이번 과제 마감일 나눠서 하지 말고 그냥 같이 하는 게 나을 것 같은데 어때?"),
    "DEMO-MAIL-LSY-022": ("수업 필기 자료 보낼게", "오늘 수업 때 나온 수업 필기 정리해서 보내. 혹시 빠진 부분 있으면 얘기해줘!"),
    "DEMO-MAIL-LSY-023": ("실습 과제 pdf 진행상황 공유", "실습 과제 pdf 지금까지 한 거 정리해서 보내. 이 정도면 얼추 맞는 방향인 것 같아."),
    "DEMO-MAIL-LSY-024": ("팀플 회의 확인했어", "보내준 팀플 회의 확인했어, 잘 정리됐더라. 이대로 진행하면 될 것 같아."),
    "DEMO-MAIL-LSY-025": ("발표자료 관련해서 얘기 좀 하자", "발표자료 이번 주까지는 마무리해야 할 것 같은데 언제 시간 괜찮아?"),
    "DEMO-MAIL-LSY-026": ("프로젝트 기획서 내가 맡을게", "프로젝트 기획서 부분은 내가 맡아서 진행해볼게, 진행되는대로 공유할게."),
    "DEMO-MAIL-LSY-027": ("회의록 정리 초안 보내", "회의록 정리 초안 만들어봤어, 한번 확인하고 의견 줘."),
    "DEMO-MAIL-LSY-028": ("깃허브 저장소 관련해서 의견 있어", "깃허브 저장소 보다가 이 부분은 이렇게 바꾸는 게 나을 것 같은데 어떻게 생각해?"),
    "DEMO-MAIL-LSY-029": ("API 연동 회의 시간 조율", "API 연동 관련 회의 시간 다시 맞춰야 할 것 같은데 이번 주 언제 괜찮아?"),
    "DEMO-MAIL-LSY-030": ("버그 수정 다들 진행 어때?", "팀원들 버그 수정 진행상황 궁금해서 물어보는 건데, 너는 어디까지 했어?"),
    "DEMO-MAIL-LSY-031": ("UI 디자인 마무리했어", "UI 디자인 마무리해서 정리했어, 최종본 확인해보고 이상 없으면 제출할게."),
    "DEMO-MAIL-LSY-032": ("결과보고서 오늘 회의에서 정리하자", "오늘 회의 때 결과보고서 확실히 정리하고 넘어가자. 미리 생각해둔 거 있으면 준비해와."),
    "DEMO-MAIL-LSY-033": ("발표 PPT 다시 확인 부탁", "발표 PPT 수정한 부분 다시 한번 확인해줄 수 있어? 놓친 게 있을까봐 걱정돼서."),
    "DEMO-MAIL-LSY-034": ("코드 컨벤션 급하게 확인 부탁", "코드 컨벤션 관련해서 급하게 확인할 게 있는데 지금 시간 돼?"),
    "DEMO-MAIL-LSY-035": ("팀플 회의 진짜 고생했다", "이번 팀플 회의 준비하느라 진짜 고생 많았어, 덕분에 잘 마무리된 것 같아."),
    "DEMO-MAIL-LSY-036": ("발표자료 수정했어", "얘기했던 발표자료 부분 수정했어, 확인해보고 이상 없으면 그대로 진행할게."),
    "DEMO-MAIL-LSY-037": ("프로젝트 기획서 다음 단계 얘기하자", "프로젝트 기획서 끝났으니까 다음 단계는 어떻게 진행할지 다음 회의 때 얘기하자."),
    "DEMO-MAIL-LSY-038": ("회의록 정리 확인했어", "보내준 회의록 정리 확인했어, 잘 정리됐더라. 이대로 진행하면 될 것 같아."),
    "DEMO-MAIL-LSY-039": ("깃허브 저장소 발표 전에 리허설 하자", "발표 전에 깃허브 저장소 한번 맞춰보는 게 좋을 것 같은데 이번 주 중에 시간 되는 날 있어?"),
    "DEMO-MAIL-LSY-040": ("API 연동 내가 맡을게", "API 연동 부분은 내가 맡아서 진행해볼게, 진행되는대로 공유할게."),
    "DEMO-MAIL-LSY-041": ("버그 수정 관련해서 의견 있어", "버그 수정 보다가 이 부분은 이렇게 바꾸는 게 나을 것 같은데 어떻게 생각해?"),
    "DEMO-MAIL-LSY-042": ("UI 디자인 관련 자료 첨부", "UI 디자인 관련 자료 첨부해서 보내, 확인하고 필요하면 더 추가할게."),
    "DEMO-MAIL-LSY-043": ("결과보고서 회의 시간 조율", "결과보고서 관련 회의 시간 다시 맞춰야 할 것 같은데 이번 주 언제 괜찮아?"),
    "DEMO-MAIL-LSY-044": ("발표 PPT 관련해서 얘기 좀 하자", "발표 PPT 이번 주까지는 마무리해야 할 것 같은데 언제 시간 괜찮아?"),
    "DEMO-MAIL-LSY-045": ("코드 컨벤션 마무리했어", "코드 컨벤션 마무리해서 정리했어, 최종본 확인해보고 이상 없으면 제출할게."),
    "DEMO-MAIL-LSY-046": ("팀플 회의 초안 보내", "팀플 회의 초안 만들어봤어, 한번 확인하고 의견 줘."),
    "DEMO-MAIL-LSY-047": ("발표자료 다시 확인 부탁", "발표자료 수정한 부분 다시 한번 확인해줄 수 있어? 놓친 게 있을까봐 걱정돼서."),
    "DEMO-MAIL-LSY-048": ("프로젝트 기획서 다들 진행 어때?", "팀원들 프로젝트 기획서 진행상황 궁금해서 물어보는 건데, 너는 어디까지 했어?"),
    "DEMO-MAIL-LSY-049": ("회의록 정리 진짜 고생했다", "이번 회의록 정리 준비하느라 진짜 고생 많았어, 덕분에 잘 마무리된 것 같아."),
    "DEMO-MAIL-LSY-050": ("깃허브 저장소 오늘 회의에서 정리하자", "오늘 회의 때 깃허브 저장소 확실히 정리하고 넘어가자. 미리 생각해둔 거 있으면 준비해와."),
    "DEMO-MAIL-LSY-051": ("API 연동 다음 단계 얘기하자", "API 연동 끝났으니까 다음 단계는 어떻게 진행할지 다음 회의 때 얘기하자."),
    "DEMO-MAIL-LSY-052": ("버그 수정 급하게 확인 부탁", "버그 수정 관련해서 급하게 확인할 게 있는데 지금 시간 돼?"),
    "DEMO-MAIL-LSY-053": ("UI 디자인 확인했어", "보내준 UI 디자인 확인했어, 잘 정리됐더라. 이대로 진행하면 될 것 같아."),
    "DEMO-MAIL-LSY-054": ("결과보고서 수정했어", "얘기했던 결과보고서 부분 수정했어, 확인해보고 이상 없으면 그대로 진행할게."),
    "DEMO-MAIL-LSY-055": ("발표 PPT 내가 맡을게", "발표 PPT 부분은 내가 맡아서 진행해볼게, 진행되는대로 공유할게."),
    "DEMO-MAIL-LSY-056": ("코드 컨벤션 발표 전에 리허설 하자", "발표 전에 코드 컨벤션 한번 맞춰보는 게 좋을 것 같은데 이번 주 중에 시간 되는 날 있어?"),
    "DEMO-MAIL-LSY-057": ("팀플 회의 관련해서 의견 있어", "팀플 회의 보다가 이 부분은 이렇게 바꾸는 게 나을 것 같은데 어떻게 생각해?"),
    "DEMO-MAIL-LSY-058": ("발표자료 관련 자료 첨부", "발표자료 관련 자료 첨부해서 보내, 확인하고 필요하면 더 추가할게."),
    "DEMO-MAIL-LSY-059": ("프로젝트 기획서 회의 시간 조율", "프로젝트 기획서 관련 회의 시간 다시 맞춰야 할 것 같은데 이번 주 언제 괜찮아?"),
    "DEMO-MAIL-LSY-060": ("회의록 정리 마무리했어", "회의록 정리 마무리해서 정리했어, 최종본 확인해보고 이상 없으면 제출할게."),
    "DEMO-MAIL-LSY-061": ("깃허브 저장소 관련해서 얘기 좀 하자", "깃허브 저장소 이번 주까지는 마무리해야 할 것 같은데 언제 시간 괜찮아?"),
    "DEMO-MAIL-LSY-062": ("API 연동 다시 확인 부탁", "API 연동 수정한 부분 다시 한번 확인해줄 수 있어? 놓친 게 있을까봐 걱정돼서."),
    "DEMO-MAIL-LSY-063": ("버그 수정 진짜 고생했다", "이번 버그 수정 준비하느라 진짜 고생 많았어, 덕분에 잘 마무리된 것 같아."),
    "DEMO-MAIL-LSY-064": ("UI 디자인 초안 보내", "UI 디자인 초안 만들어봤어, 한번 확인하고 의견 줘."),
    "DEMO-MAIL-LSY-065": ("결과보고서 다음 단계 얘기하자", "결과보고서 끝났으니까 다음 단계는 어떻게 진행할지 다음 회의 때 얘기하자."),
    "DEMO-MAIL-LSY-066": ("발표 PPT 다들 진행 어때?", "팀원들 발표 PPT 진행상황 궁금해서 물어보는 건데, 너는 어디까지 했어?"),
    "DEMO-MAIL-LSY-067": ("코드 컨벤션 확인했어", "보내준 코드 컨벤션 확인했어, 잘 정리됐더라. 이대로 진행하면 될 것 같아."),
    "DEMO-MAIL-LSY-068": ("팀플 회의 오늘 회의에서 정리하자", "오늘 회의 때 팀플 회의 확실히 정리하고 넘어가자. 미리 생각해둔 거 있으면 준비해와."),
    "DEMO-MAIL-LSY-069": ("발표자료 내가 맡을게", "발표자료 부분은 내가 맡아서 진행해볼게, 진행되는대로 공유할게."),
    "DEMO-MAIL-LSY-070": ("프로젝트 기획서 관련해서 의견 있어", "프로젝트 기획서 보다가 이 부분은 이렇게 바꾸는 게 나을 것 같은데 어떻게 생각해?"),
}


# 이서연의 정산서류 말고 "나머지" 70건 본문도 documents.parquet에 심는다.
# apply_leeseoyeon_settlement_document()와 완전히 같은 포맷/원리를 재사용하되,
# 여러 건을 한꺼번에 처리한다는 점만 다르다. 정산서류 자체는 이 함수가 건드리지 않는다.
def apply_leeseoyeon_other_mail_bodies(base_dir):
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")
    documents_path = os.path.join(paths.PARQUET_DIR, "documents.parquet")
    if not os.path.exists(documents_path):
        print(f"[WARN] documents.parquet이 없어 이서연 나머지 메일 본문을 못 심음: {documents_path}")
        return

    plan = leeseoyeon_mail_plan()
    new_rows = []
    for item in plan:
        if item["is_settlement"]:
            continue
        mail_id = item["mail_id_override"]
        if not mail_id or mail_id not in LSY_MAIL_BODIES:
            continue
        subject, body = LSY_MAIL_BODIES[mail_id]
        dt = item["dt"]
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        if item["direction"] == "received":
            sender = f"이서연 <{LEE_SEOYEON_EMAIL}>"
            receiver = f"나 <{MAIL_USER_ID}>"
            gubun = "수신"
        else:
            sender = f"나 <{MAIL_USER_ID}>"
            receiver = f"이서연 <{LEE_SEOYEON_EMAIL}>"
            gubun = "발신"

        text = (
            f"[메일 1]\n\n"
            f"[ID] {mail_id}\n"
            f"[제목] {subject}\n"
            f"[구분] {gubun}\n"
            f"[날짜] {date_str}\n"
            f"[발신인] {sender}\n"
            f"[수신인] {receiver}\n"
            f"[참조(CC)] 없음\n"
            f"[폴더 정보] {DEMO_FOLDER}\n\n"
            f"[메일 본문]\n{body}\n\n"
            f"[첨부파일 정보]\n없음"
        )
        new_rows.append({
            "id": mail_id,
            "title": "이서연 이벤트 데모 메일",
            "text": text,
            "text_unit_ids": [],
            "creation_date": date_str + " +0900",
            "raw_data": {"id": mail_id, "text": text},
        })

    if not new_rows:
        print("[WARN] 이서연 나머지 메일 본문으로 심을 항목이 없음")
        return

    df = pd.read_parquet(documents_path)
    ids_to_add = {r["id"] for r in new_rows}
    df = df[~df["id"].isin(ids_to_add)]  # 재실행 시 중복 방지 — 있으면 지우고 새로 심음
    next_hrid = int(df["human_readable_id"].max()) + 1 if len(df) else 0
    for r in new_rows:
        r["human_readable_id"] = next_hrid
        next_hrid += 1
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    df.to_parquet(documents_path, index=False)
    print(f"[OK] documents.parquet에 이서연 나머지 메일 본문 {len(new_rows)}건 심음 → {documents_path}")


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
                "mail_id_override": LSY_MAIL_ID_OVERRIDES.get((y, m, day_cursor)),
                "is_settlement": False,
            })
            day_cursor += 3
    plan.sort(key=lambda x: x["dt"])
    return plan


# 요청 — 이서연 상세보기에서 2026-08-23 정산서류 메일을 실제로 눌러보면 본문이 나와야
# 하는데, 지금까지 DB(mail 테이블)에는 참조 행만 심고 실제 본문을 documents.parquet에
# 심는 코드가 아예 없었다(주석에만 "심어둔다"고 적혀 있고 구현이 빠져 있었음). 그래서
# 그 날짜를 열면 참조(mail 테이블 행)는 있는데 본문이 없어 프론트가 "그날 주고받은
# 메일을 찾지 못했어요"로 표시했다. get_mail_bodies_by_ids()가 documents.parquet의
# id/text 컬럼만 보고 [제목]/[날짜]/[발신인]/[수신인]/[메일 본문] 태그를 정규식으로
# 파싱하므로, 실제 인덱싱된 메일과 똑같은 포맷으로 한 행을 만들어 심어준다.
# 요청 — 원래 하드코딩된 실제 내용(사용자가 스크린샷으로 다시 알려줌)으로 정정.
LSY_SETTLE_SUBJECT = "[세미콜론 소모임] 정산서류 보내드려요"
LSY_SETTLE_BODY = (
    "안녕! 저번에 얘기했던 팀플 정산서류 정리해서 보내.\n"
    "발표자료 인쇄비랑 서버 호스팅비 영수증 모아서 엑셀로 정리했어, 총 4명이서 나눠서 계산해봤는데 확인해보고 이상 없으면 알려줘!\n"
    "다음 주 초까지 조교님한테 제출해야 해서 좀 서둘러야 할 것 같아. 첨부한 정산서류 한번만 봐줘 ㅠㅠ 고마워!"
)


# 이서연의 정산서류 메일 본문을 documents.parquet에 실제 인덱싱된 메일과 같은
# 포맷(구분자·태그)으로 심는다(재실행 시 같은 mail_id 행을 지우고 새로 심어 중복 방지).
def apply_leeseoyeon_settlement_document(base_dir):
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")
    documents_path = os.path.join(paths.PARQUET_DIR, "documents.parquet")
    if not os.path.exists(documents_path):
        print(f"[WARN] documents.parquet이 없어 이서연 정산서류 본문을 못 심음: {documents_path}")
        return

    dt = None
    for (y, m, d), (direction, forced_id) in LSY_SETTLEMENT_SPOTS.items():
        if forced_id == LSY_SETTLE_MAIL_ID:
            hour = 10 + (d % 8)
            minute = (d * 13) % 60
            dt = datetime.datetime(y, m, d, hour, minute)
            break
    if dt is None:
        return
    date_str = dt.strftime("%Y-%m-%d %H:%M:%S")

    text = (
        f"[메일 1]\n\n"
        f"[ID] {LSY_SETTLE_MAIL_ID}\n"
        f"[제목] {LSY_SETTLE_SUBJECT}\n"
        f"[구분] 수신\n"
        f"[날짜] {date_str}\n"
        f"[발신인] 이서연 <{LEE_SEOYEON_EMAIL}>\n"
        f"[수신인] 나 <{MAIL_USER_ID}>\n"
        f"[참조(CC)] 없음\n"
        f"[폴더 정보] INBOX\n\n"
        f"[메일 본문]\n{LSY_SETTLE_BODY}\n\n"
        f"[첨부파일 정보]\n정산내역.xlsx"
    )

    df = pd.read_parquet(documents_path)
    df = df[df["id"] != LSY_SETTLE_MAIL_ID]  # 재실행 시 중복 방지 — 있으면 지우고 새로 심음
    next_hrid = int(df["human_readable_id"].max()) + 1 if len(df) else 0
    new_row = {
        "id": LSY_SETTLE_MAIL_ID,
        "human_readable_id": next_hrid,
        "title": "이서연 정산서류 데모 메일",
        "text": text,
        "text_unit_ids": [],
        "creation_date": dt.strftime("%Y-%m-%d %H:%M:%S +0900"),
        "raw_data": {"id": LSY_SETTLE_MAIL_ID, "text": text},
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_parquet(documents_path, index=False)
    print(f"[OK] documents.parquet에 이서연 정산서류 본문 심음(id={LSY_SETTLE_MAIL_ID}) → {documents_path}")


# 요청 — 처음엔 "비용 지불 관련 메일 있어?" 검색 답변의 근거메일 3건(전기요금 청구서
# 도착/신용카드 발급 완료/Apple App Store Gift Card)을 이 스크립트로 별도 가짜 계정
# (billsearch.demo@mailgrapher.local) 폴더의 documents.parquet에 심었었다.
#
# 요청(후속) — "계정을 따로 만들지 말고 그냥 바로 뜨게 해달라"는 요청으로, 이제 그
# 근거메일 3건의 본문은 app.py의 BILL_SEARCH_HARDCODED_MAILS 딕셔너리에 파이썬 값으로
# 직접 들어있고, /mail-body-by-ids·/mail-subjects-by-ids 라우트가 디스크를 전혀
# 건드리지 않고 바로 반환한다. 그래서 이 스크립트가 만들던 별도 계정 폴더는 더 이상
# 필요 없어 관련 상수/함수를 제거했다 — 근거메일 내용을 바꾸려면 이제 app.py 쪽만
# 고치면 된다.


# 요청 — "로스터 68명 전체가 친밀도 티어별 왕복 메일만 자동 생성되고, 이서연 한 명만
# '8/23 정산서류' 같은 구체적 사건이 있다"는 지적 — 이서연을 제외한 나머지(가족 5·
# 베프 17·가끔연락 6·소원함 9 = 37명, 광고 10명은 제외)에게도 상세보기에서 밋밋한
# 템플릿이 아니라 "그 사람과 실제로 있었던 구체적인 일"이 하나씩 뜨도록, 사람마다
# 특정 날짜에 특정 사건(메일 제목+본문)을 추가한다. 기존 seed_mail_domain()의 왕복
# 메일 생성 루프는 전혀 안 건드리고, 그 위에 "이벤트성 메일 한 통씩"을 추가로 심는
# 방식 — mail_id도 기존 카운터 방식(DEMO-MAIL-000123)과 안 겹치게 별도 네임스페이스
# (DEMO-MAIL-EVT0001)를 쓴다. leeseoyeon_mail_plan()/apply_leeseoyeon_settlement_document()
# 랑 같은 원리(실제 인덱싱 메일과 같은 포맷으로 documents.parquet에 본문을 심어야
# 상세보기에서 읽힘)를 재사용하되, 37명 전원에 대해 일반화했다.
ROSTER_MAIL_EVENTS = {
    # ── 가족(5) ──
    "sunny10@gmail.com": dict(  # 김민주
        date=(2025, 9, 5), direction="received",
        subject="추석에 내려올 때 뭐 필요한 거 없어?",
        body="이번 추석에 내려올 때 기차표 미리 끊어놔, 명절 연휴라 금방 매진되더라. 내려오는 날 저녁은 다같이 전 부쳐 먹기로 했으니까 늦지 않게 와!",
        keyword="명절",
    ),
    "blue24@daum.net": dict(  # 박지연
        date=(2024, 11, 12), direction="received",
        subject="엄마 건강검진 결과 나왔어",
        body="어제 건강검진 결과 나왔는데 다행히 별 이상 없대, 너무 걱정하지 마. 그래도 정기적으로 검진은 계속 받으시라고 했어.",
        keyword="건강검진",
    ),
    "haru31@kakao.com": dict(  # 박소정
        date=(2025, 3, 20), direction="received",
        subject="조카 돌잔치 날짜 잡혔어",
        body="조카 돌잔치가 다음 달 셋째 주 토요일로 잡혔어. 선물은 다 같이 돈 모아서 하나 크게 하는 게 어떨까 싶은데 의견 줘!",
        keyword="돌잔치",
    ),
    "yoon38@hanmail.net": dict(  # doheeya
        date=(2023, 6, 15), direction="sent",
        subject="이사 도와줘서 진짜 고마워",
        body="지난 주말에 이삿짐 옮기는 거 도와줘서 진짜 고마웠어, 덕분에 훨씬 수월했다. 집 정리 다 끝나면 집들이 한번 부를게!",
        keyword="이사",
    ),
    "cotton45@nate.com": dict(  # 강세준
        date=(2025, 1, 10), direction="received",
        subject="아빠 생신 언제 모일까?",
        body="다음 달 아빠 생신인데 다들 시간 맞춰서 언제 모일지 정하자. 케이크는 내가 예약해둘 테니까 장소만 정해줘.",
        keyword="생신",
    ),

    # ── 베프/절친(17) ──
    "james.carter@outlook.com": dict(  # j.carter92
        date=(2025, 7, 8), direction="received",
        subject="이번 여름휴가 같이 갈래?",
        body="이번 여름휴가에 바다 쪽으로 며칠 놀러갈까 생각 중인데 같이 갈래? 숙소랑 일정은 내가 대충 짜볼게.",
        keyword="여행",
    ),
    "jelly59@naver.com": dict(  # 윤지민
        date=(2024, 5, 22), direction="received",
        subject="나 이직했어!!",
        body="나 드디어 이직 확정됐어, 다음 달부터 새 회사 출근이야! 조만간 축하 겸 밥 한번 사줘.",
        keyword="이직",
    ),
    "milkyway66@daum.net": dict(  # 장은우
        date=(2025, 10, 2), direction="sent",
        subject="생일 축하한다 진짜",
        body="생일 진짜 축하해! 이번 주말에 시간 맞춰서 선물 주면서 저녁 같이 먹자.",
        keyword="생일",
    ),
    "cloud973@kakao.com": dict(  # 임예은
        date=(2023, 9, 14), direction="received",
        subject="요즘 너무 힘들어서 그런데 시간 돼?",
        body="요즘 회사일 때문에 너무 힘들어서 그런데 이번 주에 시간 좀 내줄 수 있어? 그냥 얘기라도 하고 싶어서.",
        keyword="고민상담",
    ),
    "emily.chen@outlook.com": dict(  # emilychen_
        date=(2024, 12, 1), direction="received",
        subject="연말에 한번 보자!",
        body="벌써 연말이네, 올해 가기 전에 한번 봐야지! 다음 주 중에 시간 되는 날 알려줘.",
        keyword="연말모임",
    ),
    "greenlight80@hanmail.net": dict(  # 한희우
        date=(2025, 2, 14), direction="received",
        subject="결혼한다!!! 청첩장 줄게",
        body="나 드디어 결혼해! 날짜는 5월 셋째 주 토요일이고, 청첩장은 다음 주에 만나서 직접 줄게.",
        keyword="청첩장",
    ),
    "dallae87@nate.com": dict(  # dahun.o
        date=(2023, 11, 3), direction="sent",
        subject="합격 축하해!!",
        body="취업 합격했다는 소식 들었어, 진짜 축하해! 언제 시간 되는지 알려주면 내가 저녁 살게.",
        keyword="취업축하",
    ),
    "dodam94@gmail.com": dict(  # 서주희
        date=(2024, 8, 19), direction="received",
        subject="같이 운동할래? 요즘 헬스 다녀",
        body="나 요즘 집 근처 헬스장 다니는데 같이 다닐래? 혼자 하는 것보다 같이 하면 꾸준히 할 수 있을 것 같아서.",
        keyword="헬스",
    ),
    "hodu12@naver.com": dict(  # 신서윤
        date=(2022, 4, 11), direction="received",
        subject="새 집 구했어, 집들이 올래?",
        body="드디어 새 집으로 이사했어! 다음 주말에 집들이 할 건데 놀러 와.",
        keyword="집들이",
    ),
    "byulbit77@gmail.com": dict(  # 윤하람
        date=(2025, 5, 30), direction="sent",
        subject="그때 빌려준 돈 고마웠어",
        body="지난달에 급하게 빌려준 돈 정말 고마웠어, 덕분에 잘 해결했다. 이번 주에 갚으면서 저녁도 같이 먹자.",
        keyword="약속",
    ),
    "onda21@naver.com": dict(  # 조은채
        date=(2024, 3, 8), direction="received",
        subject="우리 여행 사진 좀 보내줘",
        body="지난번 여행 때 찍은 사진들 나한테도 좀 보내줄래? 앨범으로 만들어두고 싶어서.",
        keyword="여행사진",
    ),
    "dodam58@daum.net": dict(  # 최지유
        date=(2025, 8, 16), direction="received",
        subject="생일 파티 장소 정했어!",
        body="내 생일 파티 장소 예약 끝났어, 이번 주 금요일 저녁 7시야. 시간 꼭 비워둬!",
        keyword="생일파티",
    ),
    "haemi34@kakao.com": dict(  # 임서율
        date=(2023, 7, 25), direction="received",
        subject="너 요즘 바빠? 오랜만에 보자",
        body="요즘 통 연락이 없길래, 많이 바쁜가 해서 연락해봤어. 오랜만에 얼굴 좀 보자!",
        keyword="약속",
    ),
    "jjang14@daum.net": dict(  # 조태윤
        date=(2026, 2, 9), direction="received",
        subject="이번 주말 등산 콜?",
        body="날씨도 풀렸는데 이번 주말에 등산 갈래? 오랜만에 산 공기 좀 쐬자.",
        keyword="등산",
    ),
    "nabi21@kakao.com": dict(  # 문인선
        date=(2025, 11, 21), direction="received",
        subject="너한테 할 말 있어, 통화 가능해?",
        body="너한테 할 얘기가 좀 있는데 오늘 저녁에 통화 가능해? 별일은 아니고 그냥 상의하고 싶은 게 있어서.",
        keyword="통화",
    ),
    "grace.lee@outlook.com": dict(  # gracelee92
        date=(2024, 6, 4), direction="received",
        subject="이번에 유학 가게 됐어",
        body="나 이번 학기부터 유학 가게 됐어! 출국 전에 다같이 모여서 송별회 한번 하자.",
        keyword="유학",
    ),
    "haemi28@hanmail.net": dict(  # 장진우
        date=(2023, 12, 25), direction="received",
        subject="메리크리스마스! 새해에 보자",
        body="메리크리스마스! 올해도 얼마 안 남았네, 새해 되면 다같이 한번 모이자.",
        keyword="크리스마스",
    ),

    # ── 가끔 연락(6) ──
    "dowon96@naver.com": dict(  # 강혁
        date=(2023, 4, 18), direction="received",
        subject="너 그 동네로 이사갔다며?",
        body="얼마 전에 얘기 들었는데 이사갔다며? 어느 동네로 갔는지 궁금해서 연락해봤어.",
        keyword="이사소식",
    ),
    "yeondu35@nate.com": dict(  # 임아린
        date=(2024, 2, 27), direction="received",
        subject="오랜만에 동창들 모임 있대",
        body="다음 달에 동창들끼리 오랜만에 모이는 자리가 있다고 하더라. 너도 시간 되면 같이 가자.",
        keyword="동창모임",
    ),
    "bomnal42@gmail.com": dict(  # 한경아
        date=(2023, 8, 11), direction="received",
        subject="너 결혼식에 못 가서 미안해",
        body="그때 결혼식에 일정이 겹쳐서 못 가서 정말 미안했어. 늦었지만 청첩장 사진 보고 축하 인사 전한다!",
        keyword="결혼식",
    ),
    "gaeul49@naver.com": dict(  # 오미소
        date=(2024, 9, 23), direction="received",
        subject="우리 회사 근처인데 밥 한번 먹자",
        body="나 요즘 너희 회사 근처로 출퇴근하는데 언제 한번 점심이라도 같이 먹자.",
        keyword="점심약속",
    ),
    "sup56@daum.net": dict(  # 서승현
        date=(2022, 7, 7), direction="received",
        subject="그때 부탁했던 거 고마웠어",
        body="지난번에 부탁했던 자료 챙겨줘서 정말 고마웠어. 덕분에 잘 마무리했다.",
        keyword="감사인사",
    ),
    "daniel.cho@outlook.com": dict(  # Daniel Cho
        date=(2024, 4, 30), direction="received",
        subject="한국 여행 계획 중인데 시간 돼?",
        body="이번 여름에 한국 여행 계획 중인데 그때 시간 맞으면 얼굴 한번 보자.",
        keyword="여행계획",
    ),

    # ── 소원함(9) ──
    "yeondu09@gmail.com": dict(  # 오태경
        date=(2021, 5, 14), direction="received",
        subject="오랜만이다, 잘 지내지?",
        body="진짜 오랜만이다. 연락 못 한 사이에 잘 지냈어? 문득 생각나서 연락해봤어.",
        keyword="안부",
    ),
    "poby19@daum.net": dict(  # 권도은
        date=(2020, 8, 9), direction="received",
        subject="너 얘기 듣고 연락해봤어",
        body="얼마 전에 지나가다 네 얘기 듣고 오랜만에 연락해봤어. 잘 지내고 있는지 궁금해서.",
        keyword="안부",
    ),
    "onda33@hanmail.net": dict(  # 안유진
        date=(2022, 1, 17), direction="received",
        subject="새해 복 많이 받아",
        body="새해 복 많이 받아! 올해는 좀 더 자주 연락하고 지내자.",
        keyword="새해인사",
    ),
    "riverside47@gmail.com": dict(  # 전세은
        date=(2021, 9, 30), direction="received",
        subject="동창회 온다고 들었는데 진짜야?",
        body="이번 동창회에 너도 온다는 얘기 들었는데 진짜야? 진짜면 진짜 오랜만에 보겠다.",
        keyword="동창회",
    ),
    "coco61@daum.net": dict(  # 김지원
        date=(2020, 11, 11), direction="received",
        subject="잘 지내? 문득 생각나서 연락했어",
        body="요즘 어떻게 지내는지 문득 궁금해서 연락해봤어. 별일 없으면 다행이고.",
        keyword="안부",
    ),
    "michael.park@outlook.com": dict(  # mpark0304
        date=(2021, 3, 3), direction="received",
        subject="한국 들어왔다는 소식 들었어",
        body="너 한국 들어왔다는 소식 들었어. 시간 되면 오랜만에 한번 보자.",
        keyword="귀국소식",
    ),
    "byul82@nate.com": dict(  # 최재현
        date=(2020, 6, 20), direction="received",
        subject="그때 얘기했던 책 다 읽었어?",
        body="예전에 추천해줬던 책 나 다 읽었어, 진짜 재밌더라. 그때 얘기 좀 더 들려줘.",
        keyword="독서",
    ),
    "sarang89@gmail.com": dict(  # 정성희
        date=(2022, 10, 5), direction="received",
        subject="오랜만이야, 잘 지내?",
        body="정말 오랜만이다. 요즘 바쁘게 지내고 있는지, 한번 안부 물어보고 싶어서 연락했어.",
        keyword="안부",
    ),
    "haeul77@nate.com": dict(  # 김민아
        date=(2021, 12, 19), direction="received",
        subject="연말인데 얼굴 한번 보자",
        body="벌써 연말이네, 올해 가기 전에 얼굴 한번 보자. 시간 괜찮은 날 알려줘.",
        keyword="연말",
    ),
}


# 위 ROSTER_MAIL_EVENTS를 실제 mail/mail_keyword 행 + documents.parquet 본문으로 심는다.
# 기존 seed_mail_domain()의 왕복 메일 생성 루프는 전혀 건드리지 않고, 그 결과 위에
# "사람마다 이벤트성 메일 한 통씩"을 추가하는 완전히 별도의 단계다.
def apply_roster_mail_events(base_dir, conn, index_date, roster):
    roster_by_email = {p["email"]: p for p in roster}
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")
    documents_path = os.path.join(paths.PARQUET_DIR, "documents.parquet")

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

    df = pd.read_parquet(documents_path) if os.path.exists(documents_path) else None
    if df is None:
        print(f"[WARN] documents.parquet이 없어 로스터 이벤트 메일 본문을 못 심음: {documents_path}")

    cur = conn.cursor()
    applied = 0
    new_rows = []
    try:
        for i, (email, ev) in enumerate(ROSTER_MAIL_EVENTS.items(), start=1):
            p = roster_by_email.get(email)
            if not p:
                print(f"[WARN] 로스터에 없는 이메일이라 건너뜀: {email}")
                continue

            mail_id = f"{DEMO_MAIL_PREFIX}EVT{i:04d}"
            y, m, d = ev["date"]
            hour = 10 + (d % 8)
            minute = (d * 13) % 60
            dt = datetime.datetime(y, m, d, hour, minute)

            if ev["direction"] == "received":
                sender = f"{p['name']} <{email}>"
                receiver = f"나 <{MAIL_USER_ID}>"
                gubun = "수신"
            else:
                sender = f"나 <{MAIL_USER_ID}>"
                receiver = f"{p['name']} <{email}>"
                gubun = "발신"

            cur.execute(mail_sql, (
                mail_id, MAIL_USER_ID, index_date, DEMO_FOLDER, dt,
                sender, receiver, ev["direction"], "casual", "friendly",
                0, None, None,
            ))
            cur.execute(kw_sql, (ev["keyword"], MAIL_USER_ID, index_date, email, dt, 4))
            applied += 1

            if df is not None:
                date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                text = (
                    f"[메일 1]\n\n"
                    f"[ID] {mail_id}\n"
                    f"[제목] {ev['subject']}\n"
                    f"[구분] {gubun}\n"
                    f"[날짜] {date_str}\n"
                    f"[발신인] {sender}\n"
                    f"[수신인] {receiver}\n"
                    f"[참조(CC)] 없음\n"
                    f"[폴더 정보] {DEMO_FOLDER}\n\n"
                    f"[메일 본문]\n{ev['body']}\n\n"
                    f"[첨부파일 정보]\n없음"
                )
                new_rows.append({
                    "id": mail_id,
                    "title": f"{p['name']} 이벤트 데모 메일",
                    "text": text,
                    "text_unit_ids": [],
                    "creation_date": date_str + " +0900",
                    "raw_data": {"id": mail_id, "text": text},
                })

        conn.commit()
    finally:
        cur.close()

    if df is not None and new_rows:
        ids_to_add = {r["id"] for r in new_rows}
        df = df[~df["id"].isin(ids_to_add)]  # 재실행 시 중복 방지 — 있으면 지우고 새로 심음
        next_hrid = int(df["human_readable_id"].max()) + 1 if len(df) else 0
        for r in new_rows:
            r["human_readable_id"] = next_hrid
            next_hrid += 1
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        df.to_parquet(documents_path, index=False)

    print(f"[OK] 로스터 이벤트 메일 {applied}건 추가(mail/mail_keyword/documents.parquet)")


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

        # 요청 — My Time 뱃지 범위를 2017년까지 넓혔는데(MAIL_MONTH_PLACEHOLDER_PERIODS)
        # 정작 2017~2019년은 mail_keyword 자체가 없어서 그 구간 슬라이더에선 키워드
        # 일별 그래프가 텅 비어 보인다. 위 2020~2026 루프는 절대 건들지 않고(이미 보여준
        # 적 있는 달들의 키워드 배정이 흔들리면 안 되므로), 2017-01~2019-12 전용으로
        # 완전히 독립된 인덱스(mi2)를 쓰는 별도 루프를 추가한다.
        for mi2, (y, m) in enumerate(month_range(2017, 2019)):
            days_in_month = 27
            for j in range(14):
                day = 1 + (j * 2 + mi2) % days_in_month
                kw = MAIL_KEYWORD_POOL[(mi2 * 3 + j) % len(MAIL_KEYWORD_POOL)]
                person = active_pool[(mi2 * 5 + j) % len(active_pool)]
                count = 1 + (mi2 + j) % 6
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


def apply_mail_summary_overrides(base_dir, conn, index_date):
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")
    if not os.path.exists(paths.MAIL_SUMMARIES_PATH):
        print(f"[WARN] {paths.MAIL_SUMMARIES_PATH} 이 없어 mail 요약 오버라이드를 건너뜁니다.")
        return
    with open(paths.MAIL_SUMMARIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    monthly = data.get("monthly", {})

    # 요청 — 화면(My Time 요약 카드)은 이 JSON 파일이 아니라 DB mail_summarize
    # 테이블(get_mail_summaries, db_reader.py)을 읽는다는 걸 뒤늦게 확인 — JSON만
    # 고쳐서는 화면에 절대 반영 안 되고, 실제 인덱싱이 만든 원본 텍스트가 계속 떴었음.
    # 그래서 이제 JSON과 DB를 같이 맞춘다(계정/기간 매칭은 PK 그대로 사용, contacts는
    # JSON에 있는 값을 그대로 같이 넣어 JSON=DB로 완전히 일치시킴).
    cur = conn.cursor()
    applied = 0
    try:
        for period, summary in MAIL_SUMMARY_OVERRIDES.items():
            if period not in monthly:
                print(f"[WARN] mail_summaries.json에 {period} 항목이 없어 그 항목은 건너뜁니다.")
                continue
            monthly[period]["summary"] = summary
            contacts_json = json.dumps(monthly[period].get("contacts", []), ensure_ascii=False)
            cur.execute(
                """
                INSERT INTO mail_summarize (
                    user_mail_account_id, index_date, summarize_unit, summary_period,
                    summarized_context, contacts
                ) VALUES (%s, %s, 'monthly', %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    summarized_context = VALUES(summarized_context),
                    contacts = VALUES(contacts)
                """,
                (MAIL_USER_ID, index_date, period, summary, contacts_json),
            )
            applied += 1
        conn.commit()
    finally:
        cur.close()

    with open(paths.MAIL_SUMMARIES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] mail_summaries.json + DB mail_summarize 오버라이드 {applied}건 적용")


# 요청 — My Time 연도 슬라이더에 2026년만 찍히지 말고 2017년부터 쭉 나오게 해달라는
# 요청. "버튼만 있으면 되고 안에 실제 데이터를 채울 필요는 없다"는 요청이라, 진짜
# 연도별 요약을 만드는 대신 mail_summarize(summarize_unit='yearly')에 빈 자리표시
# 행만 넣는다 — 프론트(mytimeEngine.js)는 /mail-summaries(type=yearly) 응답의
# summary_period 키 개수만큼 연도 점을 찍으므로, 내용이 비어 있어도 버튼은 뜬다.
# 2026년은 이미 실제 인덱싱으로 값이 있으니 건드리지 않는다(ON DUPLICATE KEY UPDATE로
# 기존 값 보존).
MAIL_YEAR_BUTTON_RANGE = range(2017, 2026)  # 2017~2025 (2026은 이미 실제 데이터 있음)

# 요청 — My Time 상단 "YYYY.MM ~ YYYY.MM 데이터" 뱃지(My People과 범위를 맞춰달라는
# 요청)도 연도 버튼과 같은 원리다 — mytimeEngine.js의 이 뱃지는 ALL_KEYS(=DB
# mail_summarize의 월별 행이 실제로 존재하는 달들)의 첫/마지막 값으로 계산되는데,
# 이 계정은 실인덱싱된 달(대략 2026년 상반기 몇 달)+우리가 덮어쓴 2026-08 말고는
# 월별 행 자체가 없어서 범위가 좁게 잡혔다. My People 쪽 범위(2017~2026)에 맞추려고
# "버튼(뱃지 범위)만 넓히고 실제 요약 내용은 안 채운다"는 연도 자리표시와 완전히
# 같은 방식으로, 2017-01~2019-12 + 2026-09 구간에 빈 월별 mail_summarize 행만
# 추가한다 — 2020-01~2026-08 사이 기존 실제/하드코딩된 월별 요약은 ON DUPLICATE
# KEY UPDATE 자기참조(no-op)로 절대 건드리지 않는다.
#
# 요청(후속) — "My Time 요약/키워드 그래프 등 전체적으로 안 되어있는 거 다 넣어줘":
# 위 방식(뱃지 양 끝만 자리표시)만으로는 타임 슬라이더를 2017~2025년 쪽으로 옮기면
# "요약이 없습니다"만 뜨는 빈 달이 훨씬 많이 남아있었다(2020-01~2025-12도 실제로는
# 월별 mail_summarize 행 자체가 없었음 — 위 주석의 "실인덱싱된 2026년 상반기 몇 달
# +2026-08" 말고는 전부 비어 있었다). 그래서 이제 2017-01~2025-12 전체(2026년은
# 실인덱싱/2026-08 오버라이드로 이미 채워져 있으니 제외)에도 HS 단톡방의
# hs_month_text()와 같은 방식(연도 무관 공용 키워드 풀을 달마다 순환)으로 만든
# 짧은 자동 요약 텍스트 + 그 달의 로스터 연락처 3명을 채운다. 2026-09는 여전히
# "아직 실인덱싱이 도달하지 않은 다음 달"을 보여주는 자리이므로(MAIL_DEMO_CUTOFF_
# PERIOD 참고 — 재실행마다 그 이후 데이터가 트림됨) 일부러 비워둔다.
MAIL_MONTH_PLACEHOLDER_PERIODS = (
    [f"{y}-{m:02d}" for y in range(2017, 2026) for m in range(1, 13)]
    + ["2026-09"]
)

# 2026-09는 항상 빈 채로 두는 유일한 기간(위 주석 참고).
MAIL_MONTH_PLACEHOLDER_KEEP_EMPTY = {"2026-09"}


def mail_month_text(y, m, mi):
    """2017-01~2025-12처럼 월별 mail_summarize 행 자체가 없던 달을 채우는 짧은
    자동 요약 텍스트. HS 단톡방 hs_month_text()와 같은 원리(연도 무관 공용 키워드
    풀 MAIL_KEYWORD_POOL을 달마다 순환)로, 손으로 쓴 이서연/2026-08 오버라이드와
    겹치지 않게 완전히 별도 함수로 둔다."""
    kw1 = MAIL_KEYWORD_POOL[(mi * 3) % len(MAIL_KEYWORD_POOL)]
    kw2 = MAIL_KEYWORD_POOL[(mi * 3 + 5) % len(MAIL_KEYWORD_POOL)]
    return (
        f"{y}년 {m}월에는 '{kw1}', '{kw2}' 관련 메일이 많이 오갔습니다. "
        "그 밖에도 다양한 연락처와 크고 작은 메일을 주고받았습니다."
    )


def apply_mail_month_placeholders(conn, index_date, roster):
    contact_pool = [p["name"] for p in roster if p["tier"] not in ("brand", "distant")]
    cur = conn.cursor()
    applied = 0
    try:
        # 요청(후속) — 이 스크립트를 예전에 이미 한 번 돌려서 2017-2019/2026-09에
        # 빈 문자열("") placeholder 행이 이미 들어가 있는 경우까지 감안한다. 예전
        # "자기참조 no-op"(summarized_context = summarized_context) 그대로 두면
        # "이미 있던 행"으로 취급돼 우리가 새로 만든 자동 요약 텍스트로 절대 안
        # 바뀐다 — 그런데 그 값이 진짜 실인덱싱 데이터가 아니라 우리가 예전에 넣은
        # 빈 자리표시일 뿐이라 채워도 안전하다. 그래서 "기존 값이 빈 문자열일 때만
        # 새 값으로 덮어쓰고, 뭔가 실제 내용이 있으면(=실인덱싱/기존 하드코딩)
        # 절대 안 건드린다"로 바꾼다(IF(...)의 summarized_context는 MySQL에서 항상
        # UPDATE 시작 시점의 '기존' 값을 가리키므로 두 컬럼 다 안전하게 같은 조건을
        # 쓸 수 있다).
        sql = """
            INSERT INTO mail_summarize (
                user_mail_account_id, index_date, summarize_unit, summary_period,
                summarized_context, contacts
            ) VALUES (%s, %s, 'monthly', %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                contacts = IF(summarized_context = '', VALUES(contacts), contacts),
                summarized_context = IF(summarized_context = '', VALUES(summarized_context), summarized_context)
        """
        for mi, period in enumerate(MAIL_MONTH_PLACEHOLDER_PERIODS):
            if period in MAIL_MONTH_PLACEHOLDER_KEEP_EMPTY:
                summary, contacts = "", []
            else:
                y, m = (int(x) for x in period.split("-"))
                summary = mail_month_text(y, m, mi)
                contacts = [contact_pool[(mi * 5 + k) % len(contact_pool)] for k in range(3)]
            cur.execute(sql, (MAIL_USER_ID, index_date, period, summary, json.dumps(contacts, ensure_ascii=False)))
            applied += 1
        conn.commit()
    finally:
        cur.close()
    print(f"[OK] mail_summarize에 My Time 뱃지 범위용 월별 자리표시/자동 요약 {applied}개 추가"
          f"(2017-01~2025-12 자동 요약, 2026-09만 계속 빈 채로)")



def apply_mail_year_button_placeholders(conn, index_date):
    cur = conn.cursor()
    applied = 0
    try:
        sql = """
            INSERT INTO mail_summarize (
                user_mail_account_id, index_date, summarize_unit, summary_period,
                summarized_context, contacts
            ) VALUES (%s, %s, 'yearly', %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                summarized_context = summarized_context
        """
        for y in MAIL_YEAR_BUTTON_RANGE:
            cur.execute(sql, (MAIL_USER_ID, index_date, str(y), "", json.dumps([], ensure_ascii=False)))
            applied += 1
        conn.commit()
    finally:
        cur.close()
    print(f"[OK] mail_summarize에 연도 버튼용 자리표시 {applied}개 추가(2017~2025)")



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


# 요청 — My People 로스터 사람들 사진이 화면에 하나도 안 뜨는 문제. 실제 아바타 표시는
# FLUX로 매번 새로 생성해 person_avatars.json(이메일→URL 캐시)에 저장하는 구조라서
# (avatar_generator.py generate_person_avatars_batch), ROSTER_RAW에 avatar 파일명을
# 적어놓는 것만으로는 화면에 전혀 반영되지 않았다 — AVATAR_DIR/AVATAR_FILES는 지금까지
# 어디에서도 읽어서 쓰이질 않는 죽은 값이었음. 그래서 ROSTER_RAW가 지정한 avatar 파일을
# 직접 person_avatars.json이 기대하는 위치(<이메일 md5 해시>.png)로 복사해 넣고,
# person_avatars.json에도 그 URL을 바로 기록해서 FLUX 생성을 건너뛰고 이 사진이
# 그대로 쓰이게 한다.
def apply_person_avatars(base_dir, roster):
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")
    os.makedirs(paths.AVATAR_IMAGES_DIR, exist_ok=True)

    avatar_map = {}
    if os.path.exists(paths.MAIL_AVATARS_PATH):
        with open(paths.MAIL_AVATARS_PATH, "r", encoding="utf-8") as f:
            avatar_map = json.load(f)

    applied = 0
    missing_src = []
    for person in roster:
        email = person["email"]
        src_path = os.path.join(base_dir, AVATAR_DIR, person["avatar"])
        if not os.path.exists(src_path):
            missing_src.append(person["avatar"])
            continue
        filename = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest() + ".png"
        dst_path = os.path.join(paths.AVATAR_IMAGES_DIR, filename)
        shutil.copyfile(src_path, dst_path)
        avatar_map[email] = f"/person-avatar-image/{MAIL_USER_ID}/{filename}"
        applied += 1

    with open(paths.MAIL_AVATARS_PATH, "w", encoding="utf-8") as f:
        json.dump(avatar_map, f, ensure_ascii=False, indent=2)

    if missing_src:
        print(f"[WARN] avatar 원본 파일을 못 찾아 건너뜀: {sorted(set(missing_src))}")
    print(f"[OK] person_avatars.json에 로스터 아바타 {applied}명 반영 → {paths.MAIL_AVATARS_PATH}")


# 요청 — "3학년 4반 고등학교 단톡방" 참여자(HS_MEMBERS) 이미지가 하나도 안 뜨는 문제.
# short_bio 문제와 원인이 같다 — 이 방은 실인덱싱 없이 create_if_missing으로 새로 만든
# 방이라, 실인덱싱 때만 돌아가는 generate_chatroom_people_avatars_batch()(FLUX 아바타
# 생성)가 한 번도 실행된 적이 없어서 chatroom_people_avatars.json이 비어있었다.
# My People 로스터 사진(apply_person_avatars)과 똑같은 방식으로, avatar_stock 사진을
# 직접 chatroom_avatars/ 캐시에 복사해 넣고 chatroom_people_avatars.json에 매핑을
# 심어준다(성별은 avatar_stock 썸네일을 직접 눈으로 확인해서 이름과 맞춰 배정함).
HS_MEMBER_AVATARS = {
    "김도현": "001_송빈하_66315354.png",
    "이수빈": "003_류아빈_71639823.png",
    "박재현": "008_이진_41004722.png",
    "최유나": "005_정민_58613979.png",
    "정하늘": "009_안민_67902677.png",
    "오승민": "012_최우_92259074.png",
    "한지원": "010_정하수_74104806.png",
    "배수아": "015_강재_57167054.png",
    "임찬우": "014_한훈훈_27540406.png",
    "신예진": "018_장서환_74937666.png",
    "강태오": "020_서지_26059123.png",
    "문서영": "021_신영빈_11982417.png",
    "조은비": "023_한윤태_41507540.png",
    "윤도경": "024_서은태_55896841.png",
    "백하은": "025_이서규_75532064.png",
}
HS_AVATAR_STOCK_DIR = "avatar_stock"  # 위 파일들은 전부 이 폴더(repo 루트) 안에 있음


# 채팅방 참여자(participant_id)→아바타 파일 매핑을 chatroom_avatars/ 캐시에 복사하고
# chatroom_people_avatars.json에 반영한다(avatar_generator._chatroom_avatar_filename과
# 동일하게 md5(participant_id).png 파일명 규칙을 그대로 따른다).
def apply_chatroom_people_avatars(base_dir, chatroom_id, member_avatars):
    paths = UserPaths(base_dir, chatroom_id, "messenger")
    os.makedirs(paths.MESSAGE_AVATAR_IMAGES_DIR, exist_ok=True)

    avatar_map = {}
    if os.path.exists(paths.MESSAGE_AVATARS_PATH):
        with open(paths.MESSAGE_AVATARS_PATH, "r", encoding="utf-8") as f:
            avatar_map = json.load(f)

    applied = 0
    missing_src = []
    for participant_id, filename_src in member_avatars.items():
        src_path = os.path.join(base_dir, HS_AVATAR_STOCK_DIR, filename_src)
        if not os.path.exists(src_path):
            missing_src.append(filename_src)
            continue
        filename = hashlib.md5(participant_id.strip().encode("utf-8")).hexdigest() + ".png"
        dst_path = os.path.join(paths.MESSAGE_AVATAR_IMAGES_DIR, filename)
        shutil.copyfile(src_path, dst_path)
        avatar_map[participant_id] = f"/chatroom-person-avatar-image/{chatroom_id}/{filename}"
        applied += 1

    with open(paths.MESSAGE_AVATARS_PATH, "w", encoding="utf-8") as f:
        json.dump(avatar_map, f, ensure_ascii=False, indent=2)

    if missing_src:
        print(f"[WARN] chatroom avatar 원본 파일을 못 찾아 건너뜀: {sorted(set(missing_src))}")
    print(f"[OK] chatroom_people_avatars.json({chatroom_id})에 아바타 {applied}명 반영 → {paths.MESSAGE_AVATARS_PATH}")



# ────────────────────────────── 4. 메신저(카카오) 도메인 시딩 ──────────────────────────────


# 요청 — My Time이 "처음 뜰 때" 항상 최신 달을 보여주는데, 실제 인덱싱이 계속 진행되면서
# 하드코딩해둔 2026-08 이후로 실제 달(예: 2026-09)의 진짜 메일 요약/키워드가 쌓이면
# 데모용 8월 요약 대신 밋밋한 실제 요약이 최신으로 떠버리는 문제. 시연 때마다 손으로
# 지우지 않아도 되게, 재실행할 때마다 이 컷오프 이후로 쌓인 데이터를 이 계정에 한해
# 통째로 지워서 "8월이 최신"인 상태를 계속 유지한다.
MAIL_DEMO_CUTOFF_PERIOD = "2026-08"


def trim_mail_data_after_cutoff(base_dir, conn, index_date):
    paths = UserPaths(base_dir, MAIL_USER_ID, "mail")

    # 1) mail_summaries.json에서 컷오프 이후 월 제거
    if os.path.exists(paths.MAIL_SUMMARIES_PATH):
        with open(paths.MAIL_SUMMARIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        monthly = data.get("monthly", {})
        removed = sorted(p for p in monthly if p > MAIL_DEMO_CUTOFF_PERIOD)
        for p in removed:
            del monthly[p]
        if removed:
            with open(paths.MAIL_SUMMARIES_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[OK] mail_summaries.json에서 {MAIL_DEMO_CUTOFF_PERIOD} 이후 "
                  f"{len(removed)}개월 제거: {removed}")

    # 2) DB(mail_summarize, mail_keyword)에서도 같은 기준으로 제거
    year, mon = (int(x) for x in MAIL_DEMO_CUTOFF_PERIOD.split("-"))
    cutoff_date_end = f"{MAIL_DEMO_CUTOFF_PERIOD}-{calendar.monthrange(year, mon)[1]:02d} 23:59:59"

    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM mail_summarize WHERE user_mail_account_id=%s AND index_date=%s "
            "AND summarize_unit='monthly' AND summary_period > %s",
            (MAIL_USER_ID, index_date, MAIL_DEMO_CUTOFF_PERIOD),
        )
        deleted_summaries = cur.rowcount

        cur.execute(
            "DELETE FROM mail_keyword WHERE user_mail_account_id=%s AND index_date=%s "
            "AND mail_date > %s",
            (MAIL_USER_ID, index_date, cutoff_date_end),
        )
        deleted_keywords = cur.rowcount

        conn.commit()
        print(f"[OK] DB에서 {MAIL_DEMO_CUTOFF_PERIOD} 이후 데이터 정리: "
              f"mail_summarize {deleted_summaries}건, mail_keyword {deleted_keywords}건 삭제")
    finally:
        cur.close()


# seed_messenger_domain()이 KIM_CONVO_ENTRIES에 모아둔 "김도현이 등장한 블록" 정보를
# 실제 documents.parquet 행(get_chatroom_day_messages가 파싱하는 포맷)으로 심는다.
# 재실행 시 같은 block_id 행은 지우고 새로 심어 중복을 방지한다.
def apply_kim_dohyun_conversation_bodies(base_dir, chatroom_id, entries):
    paths = UserPaths(base_dir, chatroom_id, "messenger")
    documents_path = os.path.join(paths.PARQUET_DIR, "documents.parquet")
    if not entries:
        print("[WARN] 김도현이 등장한 블록이 없어 대화 본문을 심지 않았습니다.")
        return

    # 요청(후속) — "김도현 대화 본문이 하나도 안 채워졌다" 확인해보니, 이 방
    # (3학년 4반 고등학교 단톡방)은 message_block/participant/message_keyword/
    # message_summarize 같은 DB 테이블만 하드코딩으로 채워져 있을 뿐, 실제로 GraphRAG
    # 인덱싱을 한 번도 거친 적이 없어서 documents.parquet 파일 자체가 애초에 없었다
    # (다른 진짜로 인덱싱된 방들은 communities.parquet 등과 함께 documents.parquet도
    # 있는데, 이 방 폴더엔 stats.json/아바타만 있고 parquet 산출물이 하나도 없었음).
    # 그래서 예전 코드처럼 "없으면 WARN만 찍고 조용히 건너뛰기"로는 절대 안 채워진다
    # — 파일이 없으면 실제 인덱싱 결과물과 같은 스키마(다른 방의 documents.parquet에서
    # 확인한 7개 컬럼: id/human_readable_id/title/text/text_unit_ids/creation_date/
    # raw_data)로 새로 만든다.
    if os.path.exists(documents_path):
        df = pd.read_parquet(documents_path)
    else:
        os.makedirs(os.path.dirname(documents_path), exist_ok=True)
        df = pd.DataFrame(columns=[
            "id", "human_readable_id", "title", "text", "text_unit_ids",
            "creation_date", "raw_data",
        ])
        print(f"[INFO] documents.parquet이 없어 새로 만듭니다: {documents_path}")

    ids = {e["block_id"] for e in entries}
    df = df[~df["id"].isin(ids)]  # 재실행 시 중복 방지 — 있으면 지우고 새로 심음
    next_hrid = int(df["human_readable_id"].max()) + 1 if len(df) else 0

    new_rows = []
    for i, e in enumerate(entries):
        lines = kim_convo_lines(e["year"], e["keyword"], e["others"], e.get("variant_idx", 0))
        body = "\n".join(lines)
        participants_str = ", ".join(e["participants"])
        text = (
            f"[대화 {i + 1}]\n\n"
            f"ID: {e['block_id']}\n"
            f"채팅방: {e['chatroom_name']}\n"
            f"날짜: {e['block_date']}\n"
            f"참여자: {participants_str}\n\n"
            f"[대화 내용]\n{body}\n"
            f"====="
        )
        new_rows.append({
            "id": e["block_id"],
            "human_readable_id": next_hrid,
            "title": f"{e['block_date']} {e['chatroom_name']} 대화",
            "text": text,
            "text_unit_ids": [],
            "creation_date": f"{e['block_date']} 00:00:00 +0900",
            "raw_data": {"id": e["block_id"], "text": text},
        })
        next_hrid += 1

    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    df.to_parquet(documents_path, index=False)
    print(f"[OK] documents.parquet에 김도현 대화 본문 {len(new_rows)}건 심음 → {documents_path}")


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
        # 요청 — My Time "주요 연락처" 툴팁(mytimeEngine.js formatContactTooltip)은
        # description이 아니라 short_bio 컬럼을 보는데, 이 방은 실인덱싱 없이 새로
        # 만든 방이라 short_bio가 채워질 기회(실인덱싱 2차 LLM 호출)가 없어서 전원
        # "등록된 설명이 없습니다"로 떴다 — description과 같은 문장을 short_bio에도
        # 같이 넣어서 툴팁이 뜨게 한다.
        cp_sql = """
            INSERT INTO chatroom_people (
                participant_id, chatroom_id, index_date, user_id, chatroom_people_name,
                message_count, description, short_bio
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                message_count = VALUES(message_count),
                description = VALUES(description),
                short_bio = VALUES(short_bio)
        """
        for member in room["members"]:
            # 요청 — 김도현은 실인덱싱으로 실제 생성된 진짜 description/short_bio가
            # 있으니 절대 건드리지 말 것 — 이 방(HS_CHATROOM_ID)의 김도현만 UPSERT 자체를
            # 스킵해서 기존 DB 값을 그대로 보존한다(message_count도 갱신 안 함).
            if member == "김도현" and chatroom_id == HS_CHATROOM_ID:
                continue
            description = HS_MEMBER_DESCRIPTIONS.get(member, f"'{room['new_name']}' 멤버입니다.")
            short_bio = HS_MEMBER_SHORT_BIOS.get(member, description)
            cur.execute(cp_sql, (member, chatroom_id, index_date, user_id, member, 0, description, short_bio))
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
            # 요청 — 15명 사이 관계 라벨을 기본 "친구"로 통일(기존 4단계 순환 풀 제거)하되,
            # HS_MEMBER_RELATION_OVERRIDES에 지정된 멤버가 낀 쌍은 그 라벨로 덮어쓴다.
            pairs = list(itertools.combinations(sorted(room["members"]), 2))
            for person_a, person_b in pairs:
                label = (
                    HS_MEMBER_RELATION_OVERRIDES.get(person_a)
                    or HS_MEMBER_RELATION_OVERRIDES.get(person_b)
                    or "친구"
                )
                desc = HS_RELATION_DESCRIPTIONS[label]
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
        # 요청 — 김도현 전용 키워드 풀(HS_KIM_KEYWORD_POOL_BY_YEAR)을 연도별로 몇 번째까지
        # 뽑았는지 추적(연도가 바뀌면 그 해 풀 처음부터 다시 순환).
        kim_kw_idx = {}

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
                    if is_narrative and member == HS_TARGET_MEMBER:
                        kim_pool = HS_KIM_KEYWORD_POOL_BY_YEAR.get(y, room_keywords)
                        kim_idx = kim_kw_idx.get(y, 0)
                        kw = kim_pool[kim_idx % len(kim_pool)]
                        kim_kw_idx[y] = kim_idx + 1
                        # 요청 — 김도현이 등장한 이 블록에, 방금 뽑은 키워드와 짝이 맞는
                        # 대화 본문도 같이 심을 수 있도록 정보를 모아둔다(실제 parquet
                        # 쓰기는 이 방 처리가 다 끝난 뒤 apply_kim_dohyun_conversation_
                        # bodies()에서 한 번에 처리 — DB 커밋 루프 안에서 매번 parquet
                        # 파일을 열고 쓰면 너무 느려짐).
                        KIM_CONVO_ENTRIES.append({
                            "block_id": block_id,
                            "chatroom_name": room["new_name"],
                            "block_date": block_date.strftime("%Y-%m-%d"),
                            "participants": list(active_members),
                            "year": y,
                            "keyword": kw,
                            "variant_idx": kim_idx,
                            "others": [mm for mm in active_members if mm != HS_TARGET_MEMBER],
                        })
                    else:
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

        # 요청 — Recap "가장 많이 말한 사람" 카드가 이 방(등 하드코딩 채팅방)에서
        # 전부 "데이터가 없습니다"로 뜨는 버그 — 위 chatroom_people UPSERT(2단계
        # 앞부분)가 message_count를 항상 리터럴 0으로 써넣고 있어서(각 블록의 실제
        # 발화량 합계를 반영한 적이 없음), rankChatPeople()이 count>0 조건으로 전원을
        # 걸러내 빈 배열이 됐다. participant 테이블(각 블록별 sent_message, 위 블록
        # 루프에서 실제로 채워짐)을 참여자별로 합산해 chatroom_people.message_count를
        # 실제 값으로 채운다. 김도현은 이 방(HS_CHATROOM_ID)에 한해 실인덱싱 당시의
        # 진짜 message_count를 보존해야 하므로(위 UPSERT 루프와 동일한 보호 규칙) 이
        # 갱신에서 제외한다.
        cur.execute(
            """
            SELECT participant_name, SUM(sent_message) AS total
            FROM participant
            WHERE chatroom_id=%s AND index_date=%s AND user_id=%s
            GROUP BY participant_name
            """,
            (chatroom_id, index_date, user_id),
        )
        sent_totals = {row[0]: int(row[1] or 0) for row in cur.fetchall()}
        updated_count = 0
        for member, total in sent_totals.items():
            if member == "김도현" and chatroom_id == HS_CHATROOM_ID:
                continue
            cur.execute(
                "UPDATE chatroom_people SET message_count=%s "
                "WHERE participant_id=%s AND chatroom_id=%s AND index_date=%s AND user_id=%s",
                (total, member, chatroom_id, index_date, user_id),
            )
            updated_count += 1
        conn.commit()
        print(f"[OK] chatroom_people.message_count {updated_count}명 실제 발화량으로 갱신 → {room['new_name']}")

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

        # 요청(후속) — "김도현 메신저 대화 본문이 계속 안 채워진다"는 게 최우선
        # 순위라서, 메신저 관련 스텝(방 채우기 + 아바타 + 김도현 대화 본문)을
        # 스크립트 맨 뒤(메일 쪽 나머지 스텝들 다음)에서 여기 메일 도메인 직후로
        # 끌어올렸다 — 메일 쪽 뒷부분 스텝(요약 오버라이드/연도·월별 자리표시 등)
        # 중 하나가 실패해서 스크립트가 중간에 죽더라도, 메신저/김도현 데이터는
        # 이미 커밋된 뒤라 영향을 안 받는다.
        print("[STEP] 메신저 채팅방 이름/요약/키워드 채우는 중...")
        block_counter = 0
        for room in CHATROOMS:
            cleanup_messenger_domain(conn, room)
            block_counter = seed_messenger_domain(conn, room, block_counter)

        print("[STEP] '3학년 4반 고등학교 단톡방' 참여자 아바타(chatroom_people_avatars.json) 반영 중...")
        apply_chatroom_people_avatars(BASE_DIR, HS_CHATROOM_ID, HS_MEMBER_AVATARS)

        print("[STEP] 김도현 메신저 대화 본문(documents.parquet) 심는 중...")
        apply_kim_dohyun_conversation_bodies(BASE_DIR, HS_CHATROOM_ID, KIM_CONVO_ENTRIES)

        print("[STEP] 이서연 정산서류 메일 본문(documents.parquet) 심는 중...")
        apply_leeseoyeon_settlement_document(BASE_DIR)

        print("[STEP] 이서연 나머지 70건 메일 본문(documents.parquet) 심는 중...")
        apply_leeseoyeon_other_mail_bodies(BASE_DIR)

        print("[STEP] 로스터 37명 이벤트성 메일(mail/mail_keyword/documents.parquet) 추가 중...")
        apply_roster_mail_events(BASE_DIR, conn, index_date, roster)

        print("[STEP] My Time 메일 요약(mail_summaries.json) 오버라이드 적용 중...")
        apply_mail_summary_overrides(BASE_DIR, conn, index_date)

        print("[STEP] My Time 연도 슬라이더 버튼용 자리표시(2017~2025) 추가 중...")
        apply_mail_year_button_placeholders(conn, index_date)

        print(f"[STEP] {MAIL_DEMO_CUTOFF_PERIOD} 이후 실제 데이터 정리 중...")
        trim_mail_data_after_cutoff(BASE_DIR, conn, index_date)

        print("[STEP] My Time 뱃지 범위(2017~2026.09)용 월별 자리표시/자동 요약 추가 중...")
        apply_mail_month_placeholders(conn, index_date, roster)

        print("[STEP] Recap 연락처 통계(mail_contact_stats.json) 오버라이드 적용 중...")
        apply_mail_contact_stats_overrides(BASE_DIR, roster_stats)

        print("[STEP] My People 로스터 아바타(person_avatars.json) 반영 중...")
        apply_person_avatars(BASE_DIR, roster)

    finally:
        conn.close()

    print("완료! My People / My Time 페이지를 새로고침하면 반영됩니다.")
    print("(메일 표시 이메일은 accountPicker.js에서 화면 텍스트만 바꾼 것이라, "
          "이 스크립트가 건드리는 실제 계정 식별자는 그대로 03yeah03@gmail.com / 03yeeun03@naver.com 입니다.)")


if __name__ == "__main__":
    main()