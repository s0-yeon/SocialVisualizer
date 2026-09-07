import { createRoot } from "react-dom/client";
import Header from "./Header.jsx";

/**
"분석 결과 보기" 허브 페이지(analysishub.html) 전체를 감싸는 최상위 React 컴포넌트 — 헤더와 My People/My Time/Recap/검색으로 이동하는 4개의 정적 바로가기 카드를 렌더링한다.
원본 페이지가 이미 순수 정적 HTML(공통 헤더 초기화 외에 자체 JS 로직이 없음)이었기 때문에, 다른 변환 페이지들과 달리 별도의 features/*Engine.js가 필요 없다 — 마크업을 그대로 JSX로 옮기기만 하면 된다.

Top-level React component wrapping the entire "view results" hub page (analysishub.html) — renders the header and the four static shortcut cards linking to My People/My Time/Recap/Search.
Since the original page was already pure static HTML (no JS logic beyond the shared header init), unlike the other converted pages this one needs no separate features/*Engine.js — the markup is simply carried over into JSX as-is.
 */
function AnalysisHubApp() {
  return (
    <>
      <Header activePage="analysis-hub" />
      <main className="right_col page-analysishub" role="main" aria-label="Main content">
        <div className="gw-collect-wrap">
          {/* 상단 타이틀 영역 */}
          <div className="gw-page-header-row">
            <div className="gw-page-header-left">
              <div className="gw-page-title">
                <i className="bi bi-grid-fill"></i>
                View results
              </div>
              <p className="gw-page-subtitle">
                원하시는 분석 항목을 선택하여 상세 결과를 확인하세요.
              </p>
            </div>
          </div>

          {/* 4개의 버튼 카드 (그리드 레이아웃) */}
          <div className="gw-hub-grid">
            {/* 메뉴 1: My People */}
            <a href="mypeople.html" className="gw-hub-card">
              <div className="gw-hub-title">My People</div>
              <div className="gw-hub-desc">사람 중심의 관계망을 시각화합니다.</div>
              <div className="gw-hub-img-wrap">
                <img
                  src="/images/hero/MyPeople.png"
                  alt="My People"
                  onError={(e) => {
                    e.currentTarget.src = "https://via.placeholder.com/600x300?text=My+People";
                  }}
                />
              </div>
            </a>

            {/* 메뉴 2: My Time */}
            <a href="mytime.html" className="gw-hub-card">
              <div className="gw-hub-title">My Time</div>
              <div className="gw-hub-desc">시간 중심의 정보를 시각화합니다.</div>
              <div className="gw-hub-img-wrap">
                <img
                  src="/images/hero/MyTime.png"
                  alt="My Time"
                  onError={(e) => {
                    e.currentTarget.src = "https://via.placeholder.com/600x300?text=My+Time";
                  }}
                />
              </div>
            </a>

            {/* 메뉴 3: Recap */}
            <a href="recap.html" className="gw-hub-card">
              <div className="gw-hub-title">Recap</div>
              <div className="gw-hub-desc">데이터의 전체 통계를 제공합니다.</div>
              <div className="gw-hub-img-wrap">
                <img
                  src="/images/hero/Recap.png"
                  alt="Recap"
                  onError={(e) => {
                    e.currentTarget.src = "https://via.placeholder.com/600x300?text=Recap";
                  }}
                />
              </div>
            </a>

            {/* 메뉴 4: Natural Language Search */}
            <a href="search.html" className="gw-hub-card">
              <div className="gw-hub-title">Natural language search</div>
              <div className="gw-hub-desc">데이터에서 원하는 정보를 자연어로 검색합니다.</div>
              <div className="gw-hub-img-wrap">
                <img
                  src="/images/hero/NaturalLanguageSearch.png"
                  alt="Search"
                  onError={(e) => {
                    e.currentTarget.src = "https://via.placeholder.com/600x300?text=Search";
                  }}
                />
              </div>
            </a>
          </div>
        </div>
      </main>
    </>
  );
}

// #containerId 엘리먼트에 AnalysisHubApp을 React 루트로 마운트
export function mountAnalysisHubApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<AnalysisHubApp />);
}
