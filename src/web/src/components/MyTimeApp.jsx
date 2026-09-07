import { createRoot } from "react-dom/client";
import { useEffect, useRef } from "react";
import Header from "./Header.jsx";
import Footer from "./Footer.jsx";
import { initMyTimePage } from "../features/mytimeEngine.js";
import { useScaleToFit } from "../utils/useScaleToFit.js";

/**
"My Time" 페이지(mytime.html) 전체를 감싸는 최상위 React 컴포넌트 — 헤더, 사이드바 자리표시자, 메일/메신저 타임라인 마크업, 푸터를 마운트한다.
타임라인 슬라이더·키워드 패널 자체의 동작은 mytimeEngine.js(기존 로직을 그대로 포팅한 모듈)가 담당하며, 이 컴포넌트는 마운트 직후 딱 한 번 initMyTimePage()를 호출해 그 엔진을 이 DOM에 연결해준다(D3 같은 명령형 라이브러리를 React에 붙일 때 쓰는 표준 패턴과 동일 — 구조는 React가 그리고, 내부 동작은 useEffect 안에서 기존 엔진이 담당).

Top-level React component wrapping the entire "My Time" page (mytime.html) — mounts the header, sidebar placeholder, mail/messenger timeline markup, and footer.
The timeline slider and keyword panel behavior themselves are owned by mytimeEngine.js (a module that ports the original logic unchanged); this component just calls initMyTimePage() once right after mount to wire that engine up to this DOM (the same pattern used to integrate an imperative library like D3 into React — structure is drawn by React, behavior is owned by the existing engine inside a useEffect).
 */
function MyTimeApp() {
  useEffect(() => {
    initMyTimePage();
  }, []);

  // 제목 줄(My People의 .mp-panel-header와 같은 역할)도 고정 캔버스+scale로 —
  // 창이 좁아지면 이 줄과 나머지 페이지가 항상 같은 비율로 같이 줄어들게 함.
  const pageHeaderCanvasRef = useRef(null);
  useScaleToFit(pageHeaderCanvasRef, "top left");

  // 연도 슬라이더(.mt-pointer-wrap)와 그 아래 두 창(.mt-two-col)을 따로따로 캔버스로
  // 나누면 각자 반올림이 달라져서 서로 위치가 어긋나는 문제가 있었음 — 그래서 뷰(메일/
  // 메신저) 하나당 슬라이더+두 창 전체를 하나의 고정 캔버스로 묶어서, My People의
  // 상세보기 패널처럼 항상 정확히 같은 비율로 같이 줄어들고 커지게 한다.
  const mailViewCanvasRef = useRef(null);
  useScaleToFit(mailViewCanvasRef, "top center");
  const msgViewCanvasRef = useRef(null);
  useScaleToFit(msgViewCanvasRef, "top center");

  return (
    <>
      <Header activePage="mytime" />
      <div id="app-sidebar"></div>
      <main className="right_col" role="main">
        <div className="mt-page">
          <div className="mt-page-header">
            <div className="mt-page-header-canvas" ref={pageHeaderCanvasRef}>
            <div className="mt-title-group">
              <div className="mt-title">
                My <span>Time</span>
              </div>
              <span className="mt-count" id="mtDataRangeLbl"></span>
            </div>
            </div>
          </div>

          {/* 메일 뷰 (기본 표시) */}
          <div className="mt-view" id="mt-mail-view">
            <div className="mt-view-canvas" ref={mailViewCanvasRef}>
            <div className="mt-pointer-wrap">
              <div className="mt-pointer-dates">
                <span className="mt-pointer-date-label" id="mtPointerRangeLbl">
                  —
                </span>
              </div>
              <div className="mt-pointer-track" id="pointerTrack">
                <div className="mt-pointer-bg"></div>
                <div className="mt-pointer-window" id="pointerWindow"></div>
                <div className="mt-pointer-cursor" id="pointerCursor">
                  <span className="mt-pointer-cursor-fallback">나</span>
                </div>
              </div>
              <div className="mt-pointer-axis" id="pointerAxis"></div>
            </div>

            <div className="mt-two-col">
              <div className="mt-col-main">
                <div className="mt-main" id="mainCard">
                  <div className="mt-track" id="track"></div>
                  <div className="mt-info-area">
                    <div className="mt-panel" id="infoPanel">
                      <div className="mt-panel-top">
                        <div className="mt-panel-period" id="panelPeriod"></div>
                        <div className="mt-panel-count" id="panelCount"></div>
                      </div>
                      <div className="mt-panel-summary" id="panelSummary"></div>
                      <div className="mt-panel-contacts-title">주요 연락처</div>
                      <div className="mt-panel-contacts" id="panelContacts"></div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-kw-panel mt-card" id="mtKwPanel">
                <div className="mt-kw-header">
                  <div className="mt-kw-title" id="mtKwTitle">
                    키워드
                  </div>
                  <button
                    type="button"
                    className="mt-kw-back-btn"
                    id="mtKwBackBtn"
                    style={{ display: "none" }}
                  >
                    <i className="bi bi-arrow-left"></i>
                    <span>키워드 목록으로</span>
                  </button>
                </div>
                <div className="mt-kw-hint" id="mtKwHint">
                  키워드를 클릭하시면 일별 그래프가 나타납니다.
                </div>
                <div className="mt-kw-body" id="mtKwBody"></div>
              </div>
            </div>
            </div>
          </div>

          {/* 메신저 뷰: 첫 클릭 시 mytimeEngine.js가 /chatroom-summaries를 불러와 채움, 기본은 숨김 */}
          <div className="mt-view" id="mt-messenger-view" style={{ display: "none" }}>
            <div className="mt-view-canvas" ref={msgViewCanvasRef}>
            <div className="mt-pointer-wrap">
              <div className="mt-pointer-dates">
                <span className="mt-pointer-date-label" id="msgPointerRangeLbl">
                  —
                </span>
              </div>
              <div className="mt-pointer-track" id="msgPointerTrack">
                <div className="mt-pointer-bg"></div>
                <div className="mt-pointer-window" id="msgPointerWindow"></div>
                <div className="mt-pointer-cursor" id="msgPointerCursor">
                  <span className="mt-pointer-cursor-fallback">나</span>
                </div>
              </div>
              <div className="mt-pointer-axis" id="msgPointerAxis"></div>
            </div>

            <div className="mt-two-col">
              <div className="mt-col-main">
                <div className="mt-main" id="msgMainCard">
                  <div className="mt-track" id="msgTrack"></div>
                  <div className="mt-info-area">
                    <div className="mt-panel" id="msgInfoPanel">
                      <div className="mt-panel-top">
                        <div className="mt-panel-period" id="msgPanelPeriod"></div>
                      </div>
                      <div className="mt-panel-summary" id="msgPanelSummary"></div>
                      <div className="mt-panel-contacts-title">주요 연락처</div>
                      <div className="mt-panel-contacts" id="msgPanelContacts"></div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-kw-panel mt-card" id="msgKwPanel">
                <div className="mt-kw-header">
                  <div className="mt-kw-title" id="msgKwTitle">
                    키워드
                  </div>
                  <button
                    type="button"
                    className="mt-kw-back-btn"
                    id="msgKwBackBtn"
                    style={{ display: "none" }}
                  >
                    <i className="bi bi-arrow-left"></i>
                    <span>키워드 목록으로</span>
                  </button>
                </div>
                <div className="mt-kw-hint" id="msgKwHint">
                  키워드를 클릭하시면 일별 그래프가 나타납니다.
                </div>
                <div className="mt-kw-body" id="msgKwBody"></div>
              </div>
            </div>
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}

// #containerId 엘리먼트에 MyTimeApp을 React 루트로 마운트
export function mountMyTimeApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<MyTimeApp />);
}
