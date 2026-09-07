import { createRoot } from "react-dom/client";
import { useEffect, useRef } from "react";
import Header from "./Header.jsx";
import Footer from "./Footer.jsx";
import {
  initMyPeoplePage,
  switchDetailTab,
  closeEmailDrawer,
  toggleGraphView,
} from "../features/mypeopleEngine.js";
import { useScaleToFit } from "../utils/useScaleToFit.js";

/**
"My People" 페이지(mypeople.html) 전체를 감싸는 최상위 React 컴포넌트 — 헤더, 사이드바 자리표시자, 카드 그리드/지식그래프/상세 패널/타임라인 마크업, 푸터를 마운트한다.
카드 정렬·상세 패널 열기·미니 지식그래프·타임라인 슬라이더 같은 실제 동작은 mypeopleEngine.js(기존 mypeople.js 로직을 거의 그대로 포팅한 모듈)가 담당하며, 이 컴포넌트는 마운트 직후 딱 한 번 initMyPeoplePage()를 호출해 그 엔진을 이 DOM에 연결해준다(My Time/Recap과 동일한 패턴 — 구조는 React가 그리고, 내부 동작은 useEffect 안에서 기존 엔진이 담당).

Top-level React component wrapping the entire "My People" page (mypeople.html) — mounts the header, sidebar placeholder, card grid/knowledge-graph/detail-panel/timeline markup, and footer.
Actual behavior (card sorting, opening the detail panel, the mini knowledge graph, the timeline slider) is owned by mypeopleEngine.js (a module that ports the original mypeople.js logic almost verbatim); this component just calls initMyPeoplePage() once right after mount to wire that engine up to this DOM (same pattern as My Time/Recap — structure drawn by React, behavior owned by the existing engine inside a useEffect).
 */
function MyPeopleApp() {
  useEffect(() => {
    initMyPeoplePage();
  }, []);

  // 상세보기 패널(.mp-detail)은 아바타·이름·탭 버튼이 서로 다른 기준(가로/세로)으로
  // 따로 줄어들다 보니 창 크기에 따라 요소끼리 겹치거나 위치가 틀어지는 문제가
  // 있었음 — 소셜 데이터 분석 페이지와 같은 방식으로, 안쪽 내용을 고정 크기
  // 캔버스(.mp-detail-canvas)로 두고 그 전체를 통째로 transform:scale()해서
  // 배치·비율이 창 크기와 무관하게 항상 완전히 동일하게 유지되도록 한다.
  const detailCanvasRef = useRef(null);
  useScaleToFit(detailCanvasRef, "top center");

  // 상세보기 캔버스와 같은 이유로, 패널 위쪽 제목/버튼 줄(.mp-panel-header)도
  // clamp() 기반 개별 축소 대신 고정 캔버스+scale로 통일해서, 상세보기 패널이
  // 줄어드는 정도와 이 위쪽 줄이 줄어드는 정도가 항상 완전히 같은 비율로
  // 맞물려 움직이게 한다.
  const panelHeaderCanvasRef = useRef(null);
  // 이 줄은 왼쪽 정렬이라 가운데 기준(top center)으로 줄이면 제목이 오른쪽으로
  // 쏠려 보임 — 왼쪽 위 기준(top left)으로 줄어들게 해서 패널 왼쪽 끝에 계속 붙어있게 함.
  useScaleToFit(panelHeaderCanvasRef, "top left");

  // 하단 타임라인 슬라이더(.mp-timeline)도 같은 이유로 고정 캔버스+scale로 통일 —
  // 트랙 두께/점(thumb) 크기/눈금이 clamp() 범위가 좁아서 창을 줄여도 거의 안
  // 바뀌어 보였는데, 캔버스 전체를 scale()하면 다른 요소들과 똑같은 비율로 같이
  // 줄어들고 커진다.
  const timelineCanvasRef = useRef(null);
  useScaleToFit(timelineCanvasRef, "top center");

  return (
    <>
      <Header activePage="mypeople" />
      <div id="app-sidebar"></div>
      <main className="right_col" role="main">
        <div className="mp-page">
          {/* 헤더: 제목 + 드롭다운 */}
          <div className="mp-panel-header">
            <div className="mp-panel-header-canvas" ref={panelHeaderCanvasRef}>
            <div className="mp-header-left">
              <div className="mp-title-wrap">
                <div className="mp-title">
                  My <span>People</span>
                </div>
                <span className="mp-count" id="mp-count"></span>
              </div>
              <div className="mp-header-controls">
                <button className="mp-brand-filter-btn" id="mp-brand-filter-btn" type="button">
                  <i className="bi bi-megaphone"></i>
                  <span id="mp-brand-filter-label">광고 제거</span>
                </button>
                <div className="mp-dropdown" id="mp-dropdown">
                  <div className="mp-dropdown-btn" id="mp-dropdown-btn">
                    <span id="mp-dropdown-label">친밀도</span>
                    <i className="bi bi-chevron-down mp-dropdown-chevron"></i>
                  </div>
                  <div className="mp-dropdown-menu" id="mp-dropdown-menu">
                    <div className="mp-dropdown-item selected" data-sort="affinity">
                      친밀도
                    </div>
                    <div className="mp-dropdown-item" data-sort="name">
                      이름
                    </div>
                    <div className="mp-dropdown-item" data-sort="total">
                      송수신 횟수
                    </div>
                    <div className="mp-dropdown-item" data-sort="received">
                      받은 메일수
                    </div>
                    <div className="mp-dropdown-item" data-sort="sent">
                      보낸 메일수
                    </div>
                  </div>
                </div>
              </div>
            </div>
            </div>
          </div>

          {/* 콘텐츠 행 */}
          <div className="mp-content">
            <div className="mp-left">
              <div className="mp-panel" id="mp-mail-view">
                <div className="mp-graph-panel" id="mp-graph-panel">
                  <div className="mp-graph-panel-header">
                    <div className="mp-graph-panel-title">
                      <i className="bi bi-diagram-3"></i> 지식 그래프
                    </div>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <button
                        id="mp-graph-fit-btn"
                        className="mp-graph-close"
                        style={{ background: "rgba(38, 185, 154, 0.12)", color: "#1a9e7f" }}
                      >
                        <i className="bi bi-fullscreen"></i> 전체보기
                      </button>
                      <button className="mp-graph-close" onClick={() => toggleGraphView()}>
                        <i className="bi bi-arrow-left"></i> 카드 보기
                      </button>
                    </div>
                  </div>
                  <svg
                    id="graph"
                    width="100%"
                    height="100%"
                    style={{ flex: 1, minHeight: 0, display: "block" }}
                  ></svg>
                  <div
                    id="tooltip"
                    style={{
                      position: "fixed",
                      background: "#fff",
                      color: "#000",
                      border: "1px solid rgba(0, 0, 0, 0.2)",
                      padding: "10px 14px",
                      borderRadius: "10px",
                      fontSize: "13px",
                      fontFamily: "sans-serif",
                      lineHeight: 1.6,
                      pointerEvents: "none",
                      opacity: 0,
                      transition: "opacity 0.15s",
                      maxWidth: "260px",
                      zIndex: 9999,
                      boxShadow: "0 4px 16px rgba(0, 0, 0, 0.12)",
                    }}
                  ></div>
                </div>

                <div className="mp-grid" id="mp-grid">
                  <div className="mp-empty">
                    <i className="bi bi-people"></i>
                    <p>데이터를 불러오는 중...</p>
                  </div>
                </div>
              </div>

              <div className="mp-panel" id="mp-messenger-view" style={{ display: "none" }}>
                <div className="mp-empty" id="mp-messenger-loading">
                  <i className="bi bi-chat-dots"></i>
                  <p>메신저 기능을 불러오는 중...</p>
                </div>
              </div>

              {/* 디테일 패널 */}
              <div className="mp-detail" id="mp-detail">
                {/* 닫기 버튼은 안쪽 캔버스가 줄어들어도 패널 모서리에 그대로 붙어있도록
                    캔버스 밖(.mp-detail 기준)에 둔다 — 캔버스 안에 있으면 다른 요소들과
                    같이 scale되면서 위치가 안쪽으로 밀려 들어와 버림. */}
                <button className="mp-detail-close" id="mp-detail-close">
                  <i className="bi bi-x-lg"></i>
                </button>
                <div className="mp-detail-canvas" ref={detailCanvasRef}>
                <div className="mp-detail-header" style={{ position: "relative" }}>
                  <div className="mp-detail-pair">
                    <div className="mp-detail-self-info">
                      <h2 className="mp-detail-name" id="mp-detail-my-name"></h2>
                      <p className="mp-detail-email" id="mp-detail-my-email"></p>
                    </div>
                    <div
                      className="mp-detail-avatar mp-detail-avatar-self"
                      id="mp-detail-avatar-self"
                    ></div>
                    <div className="mp-detail-relation">
                      {/* 친밀도: 선 위에는 관계, 선 밑에는 친밀도 설명 */}
                      <span
                        className="mp-detail-relation-label"
                        id="mp-detail-relation-label"
                      ></span>
                      <div className="mp-detail-relation-line"></div>
                      <span
                        className="mp-detail-affinity-label"
                        id="mp-detail-affinity-label"
                      ></span>
                    </div>
                    <div className="mp-detail-avatar-ring">
                      <svg className="mp-detail-avatar-ring-svg" viewBox="0 0 100 100">
                        <defs>
                          <linearGradient id="mpRingTrackGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stopColor="#ffffff" />
                            <stop offset="100%" stopColor="#f6d3e6" />
                          </linearGradient>
                          <linearGradient id="mpRingFillGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stopColor="#ffd3ea" />
                            <stop offset="45%" stopColor="#ff6fb0" />
                            <stop offset="100%" stopColor="#e0399b" />
                          </linearGradient>
                          <filter id="mpRingBevel" x="-60%" y="-60%" width="220%" height="220%">
                            <feGaussianBlur in="SourceAlpha" stdDeviation="2.4" result="blur" />
                            <feColorMatrix
                              in="blur"
                              type="matrix"
                              values="0 0 0 0 1  0 0 0 0 0.35  0 0 0 0 0.68  0 0 0 0.55 0"
                              result="glow"
                            />
                            <feDropShadow
                              in="SourceGraphic"
                              dx="0"
                              dy="1"
                              stdDeviation="1"
                              floodColor="#c23a86"
                              floodOpacity="0.4"
                              result="bevel"
                            />
                            <feMerge>
                              <feMergeNode in="glow" />
                              <feMergeNode in="bevel" />
                            </feMerge>
                          </filter>
                        </defs>
                        <circle
                          className="mp-detail-avatar-ring-bg"
                          cx="50"
                          cy="50"
                          r="46"
                        ></circle>
                        <circle
                          className="mp-detail-avatar-ring-fill"
                          id="mp-detail-avatar-ring-fill"
                          cx="50"
                          cy="50"
                          r="46"
                        ></circle>
                      </svg>
                      <div className="mp-detail-avatar" id="mp-detail-avatar"></div>
                      <span
                        className="mp-detail-avatar-ring-label"
                        id="mp-detail-avatar-ring-label"
                      ></span>
                    </div>
                  </div>
                  <div id="mp-detail-namewrap">
                    <div className="mp-detail-nametitle">
                      <h2 className="mp-detail-name" id="mp-detail-name"></h2>
                      <p className="mp-detail-email" id="mp-detail-email"></p>
                    </div>
                    {/* innerHTML로 <div class="mp-msg-desc-line">를 넣는데, <p> 태그
                        안에 블록 요소(div)를 문자열로 넣으면 브라우저가 파싱 규칙상
                        <p>를 자동으로 닫아버려서(div가 형제로 밖으로 튕겨나감) 레이아웃이
                        깨졌었다 — div를 자유롭게 담을 수 있는 div로 바꿔서 해결. */}
                    <div className="mp-detail-messenger-desc" id="mp-detail-messenger-desc"></div>
                  </div>
                  <div className="mp-detail-tab-group">
                    <button
                      className="mp-detail-tab-btn active-stats"
                      id="mp-tab-stats"
                      onClick={() => switchDetailTab("stats")}
                    >
                      메일 통계
                    </button>
                    <button
                      className="mp-detail-tab-btn"
                      id="mp-tab-desc"
                      onClick={() => switchDetailTab("desc")}
                    >
                      설명
                    </button>
                    <button
                      className="mp-detail-tab-btn"
                      id="mp-tab-kw"
                      onClick={() => switchDetailTab("kw")}
                    >
                      키워드
                    </button>
                  </div>
                </div>

                <div className="mp-detail-desc" id="mp-detail-desc">
                  <div id="mp-desc-profile-content">
                    <p className="mp-desc-profile-empty">로딩 중...</p>
                  </div>
                </div>

                <div className="mp-detail-kw" id="mp-detail-kw">
                  <div className="mp-wc-wrap" id="mp-detail-wc">
                    <span style={{ color: "#a0b8b0", fontSize: "1rem" }}>로딩 중...</span>
                  </div>
                </div>

                <div className="mp-detail-body" id="mp-detail-body-stats">
                  <div className="mp-detail-col">
                    <div
                      id="mp-echange-row"
                      style={{ display: "flex", gap: "16px", flex: 1, minHeight: 0 }}
                    >
                      <div
                        id="mp-echange-chartview"
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: "inherit",
                          flex: "1 1 100%",
                          minWidth: 0,
                          minHeight: 0,
                          transition: "flex-basis 0.32s cubic-bezier(0.22, 1, 0.36, 1)",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: "16px",
                            flexShrink: 0,
                            paddingBottom: "14px",
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "baseline", gap: "12px" }}>
                            <div
                              id="mp-stats-title"
                              className="mp-detail-section-title"
                              style={{
                                background: "none",
                                border: "none",
                                borderBottom: "1.5px solid rgba(28, 28, 30, 0.16)",
                                borderRadius: 0,
                                boxShadow: "none",
                                padding: "0 0 5px",
                                fontSize: "1rem",
                                letterSpacing: "-0.01em",
                                textTransform: "none",
                                color: "#1c1c1e",
                              }}
                            >
                              메일 통계
                            </div>
                            <span
                              id="mp-stats-total"
                              style={{
                                fontSize: "1rem",
                                fontWeight: 700,
                                color: "#6b6459",
                                background: "rgba(28, 28, 30, 0.06)",
                                padding: "4px 12px",
                                borderRadius: "20px",
                                whiteSpace: "nowrap",
                              }}
                            ></span>
                          </div>
                          <div
                            id="mp-stats-legend"
                            style={{
                              display: "flex",
                              gap: "18px",
                              alignItems: "center",
                              flexShrink: 0,
                            }}
                          ></div>
                        </div>
                        {/* Y축이 뭘 나타내는지 표시(My Time 일별 키워드 그래프와 같은 방식) */}
                        <div className="mp-vchart-y-title">건수</div>
                        <div className="mp-vchart-wrap">
                          <div className="mp-vchart-y" id="mp-vchart-y">
                            <span>—</span>
                            <span>—</span>
                            <span>0</span>
                          </div>
                          <div className="mp-vchart-area" id="mp-chart">
                            <span style={{ color: "#a0b8b0", fontSize: "1rem" }}>로딩 중...</span>
                          </div>
                        </div>
                      </div>
                      <div
                        id="mp-echange-listview"
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: "inherit",
                          flex: "0 0 0%",
                          width: 0,
                          minHeight: 0,
                          opacity: 0,
                          pointerEvents: "none",
                          paddingLeft: 0,
                          borderLeft: "none",
                          overflow: "hidden",
                          transition:
                            "flex-basis 0.32s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.2s, padding-left 0.32s, border-left 0.32s",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "10px",
                            flexShrink: 0,
                            paddingBottom: "14px",
                          }}
                        >
                          <button
                            id="mp-echange-back"
                            onClick={() => closeEmailDrawer()}
                            style={{
                              width: "26px",
                              height: "26px",
                              borderRadius: "50%",
                              border: "1px solid rgba(28, 28, 30, 0.14)",
                              background: "#fff",
                              color: "#4a4640",
                              cursor: "pointer",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: "0.7rem",
                              flexShrink: 0,
                            }}
                          >
                            <i className="bi bi-arrow-left"></i>
                          </button>
                          <div style={{ minWidth: 0 }}>
                            <div
                              id="mp-echange-list-title"
                              style={{
                                fontSize: "1rem",
                                fontWeight: 700,
                                color: "#1c1c1e",
                                whiteSpace: "nowrap",
                              }}
                            ></div>
                            <div
                              id="mp-echange-list-count"
                              style={{
                                fontSize: "0.82rem",
                                color: "#8a8378",
                                whiteSpace: "nowrap",
                              }}
                            ></div>
                          </div>
                        </div>
                        <div
                          id="mp-echange-list-body"
                          style={{
                            flex: 1,
                            minHeight: 0,
                            overflowY: "auto",
                            display: "flex",
                            flexDirection: "column",
                            gap: "10px",
                          }}
                        ></div>
                      </div>
                    </div>
                  </div>
                </div>
                </div>
              </div>
            </div>
          </div>

          {/* 타임라인 슬라이더 — 고정 캔버스 안에 넣고 통째로 scale() */}
          <div className="mp-timeline">
            <div className="mp-timeline-canvas" ref={timelineCanvasRef}>
            <div className="mp-tl-dates">
              <span className="mp-tl-date-label" id="tl-start-lbl">
                —
              </span>
              <span className="mp-tl-selected" id="tl-selected-text"></span>
              <span className="mp-tl-date-label" id="tl-end-lbl">
                —
              </span>
            </div>
            <div className="mp-tl-track-wrap" id="tl-wrap">
              <div className="mp-tl-track"></div>
              <div className="mp-tl-fill" id="tl-fill"></div>
              <input type="range" id="tl-min" min="0" max="1000" defaultValue="0" step="1" />
              <input type="range" id="tl-max" min="0" max="1000" defaultValue="1000" step="1" />
              <div className="mp-tl-ticks" id="tl-ticks"></div>
            </div>
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}

// #containerId 엘리먼트에 MyPeopleApp을 React 루트로 마운트
export function mountMyPeopleApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<MyPeopleApp />);
}
