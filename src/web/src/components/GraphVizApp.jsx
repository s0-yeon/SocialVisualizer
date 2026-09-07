import { createRoot } from "react-dom/client";
import { useEffect } from "react";
import Header from "./Header.jsx";
import Footer from "./Footer.jsx";
import { initGraphVizPage } from "../features/graphVizEngine.js";

/**
지식그래프 시각화 페이지(graphviz.html) 전체를 감싸는 최상위 React 컴포넌트 — 헤더, 메일/메신저 도메인 토글 + 계정 선택기, 그래프 SVG, 툴팁, 푸터를 마운트한다.
계정 선택기 재초기화, /graph-data 조회, d3 기반 graph-render.js 렌더링 같은 실제 동작은 graphVizEngine.js(기존 로직을 거의 그대로 포팅한 모듈)가 담당하며, 이 컴포넌트는 마운트 직후 딱 한 번 initGraphVizPage()를 호출해 그 엔진을 이 DOM에 연결해준다(다른 변환 페이지들과 동일한 패턴 — 구조는 React가 그리고, 내부 동작은 useEffect 안에서 기존 엔진이 담당).

참고: 이 페이지는 사이드바(#app-sidebar) 없이 헤더+푸터만 쓴다.
계정 선택기도 다른 페이지들처럼 헤드리스가 아니라 실제로 화면에 그려지는(#account-picker-mount) 유일한 변환 페이지다 — 원본 그대로 유지했다.

Top-level React component wrapping the entire knowledge-graph page (graphviz.html) — mounts the header, the mail/messenger domain toggle + account picker, the graph SVG, the tooltip, and the footer.
Actual behavior (re-initializing the account picker, fetching /graph-data, rendering with the d3-based graph-render.js) is owned by graphVizEngine.js (a module that ports the original logic nearly verbatim); this component just calls initGraphVizPage() once right after mount to wire that engine up to this DOM (same pattern as the other converted pages — structure drawn by React, behavior owned by the existing engine inside a useEffect).

Note: this page uses only header + footer, no sidebar (#app-sidebar). It's also the one converted page where the account picker actually renders on screen (#account-picker-mount), rather than running headless like on the other pages — kept as in the original.
 */
function GraphVizApp() {
  useEffect(() => {
    initGraphVizPage();
  }, []);

  return (
    <>
      <Header activePage="graph-viz" />
      <main className="right_col" role="main" style={{ padding: 0 }}>
        <div id="graph-section">
          <div className="gv-picker-panel">
            <div className="gv-domain-toggle" role="tablist">
              <button
                type="button"
                className="gv-domain-btn active"
                id="domain-btn-mail"
                role="tab"
                aria-selected="true"
              >
                <i className="bi bi-envelope"></i> 메일
              </button>
              <button
                type="button"
                className="gv-domain-btn"
                id="domain-btn-message"
                role="tab"
                aria-selected="false"
              >
                <i className="bi bi-chat-dots"></i> 메신저
              </button>
            </div>
            <div id="account-picker-mount" className="gv-account-picker-wrap"></div>
          </div>
          <svg id="graph" width="100%" height="100%"></svg>
          <div id="tooltip"></div>
        </div>
      </main>
      <Footer />
    </>
  );
}

// #containerId 엘리먼트에 GraphVizApp을 React 루트로 마운트
export function mountGraphVizApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<GraphVizApp />);
}
