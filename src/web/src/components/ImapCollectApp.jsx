import { createRoot } from "react-dom/client";
import { useEffect, useRef } from "react";
import Header from "./Header.jsx";
import { initImapCollectPage } from "../features/imapCollectEngine.js";
import { useScaleToFit } from "../utils/useScaleToFit.js";

/**
"소셜 데이터 분석" 페이지(imap-collect.html) 전체를 감싸는 최상위 React 컴포넌트 — 헤더와 메일/메신저 탭 폼, job 로그 패널 마크업을 마운트한다.
IMAP 로그인, 폴더 조회, 수집 시작, SSE로 진행상황 추적, 카카오톡 대화 업로드 같은 실제 동작은 imapCollectEngine.js(기존 로직을 거의 그대로 포팅한 모듈)가 담당하며, 이 컴포넌트는 마운트 직후 딱 한 번 initImapCollectPage()를 호출해 그 엔진을 이 DOM에 연결해준다(My Time/My People과 동일한 패턴 — 구조는 React가 그리고, 내부 동작은 useEffect 안에서 기존 엔진이 담당).

참고: 원본 HTML에는 사이드바(#app-sidebar)와 푸터(#app-footer)가 없다 — 이 페이지는 헤더만 쓴다.
그대로 유지했다.

Top-level React component wrapping the entire "social data collection" page (imap-collect.html) — mounts the header and the mail/messenger tab forms + job log panel markup.
Actual behavior (IMAP login, folder listing, starting a collection, SSE progress tracking, KakaoTalk chat upload) is owned by imapCollectEngine.js (a module that ports the original logic nearly verbatim); this component just calls initImapCollectPage() once right after mount to wire that engine up to this DOM (same pattern as My Time/My People — structure drawn by React, behavior owned by the existing engine inside a useEffect).

Note: the original HTML has no sidebar (#app-sidebar) or footer (#app-footer) — this page only uses the header.
Kept as-is.
 */
function ImapCollectApp() {
  const contentRef = useRef(null);

  useEffect(() => {
    initImapCollectPage();
  }, []);

  // 창 크기가 바뀌어도 이 페이지 안의 요소·크기 값(카드 크기, 6:4 분할 비율, 구분선 위치 등)은
  // 전혀 건드리지 않고, 원래 크기 그대로 렌더링된 상태를 매번 다시 측정해서 그 비율만큼
  // transform:scale()로 통째로 줄이거나 키운다(home.scss의 히어로와 같은 방식).
  useScaleToFit(contentRef);

  return (
    <>
      <Header activePage="imap-collect" />
      <main className="right_col" role="main" aria-label="Main content">
        <div className="ic-scale-wrap">
        <div className="gw-collect-wrap" ref={contentRef}>
          {/* 반반 분할 레이아웃 컨테이너 */}
          <div className="gw-split-grid-wrapper">
            {/* 왼쪽 헤더: 데이터 수집 + 메일/메신저 탭 */}
            <div className="gw-split-header-left">
              <h3 className="gw-split-title">
                <span className="gw-step-badge">1</span> 소셜 데이터 수집
              </h3>
              <div className="gw-tabs" role="tablist">
                <button
                  type="button"
                  className="gw-tab-btn active"
                  id="tab-btn-mail"
                  role="tab"
                  aria-selected="true"
                >
                  <i className="bi bi-envelope"></i> 메일
                </button>
                <button
                  type="button"
                  className="gw-tab-btn"
                  id="tab-btn-message"
                  role="tab"
                  aria-selected="false"
                >
                  <i className="bi bi-chat-dots"></i> 메신저
                </button>
              </div>
            </div>

            {/* 오른쪽 헤더: 분석 데이터 만들기 */}
            <div className="gw-split-header-right">
              <h3 className="gw-split-title">
                <span className="gw-step-badge">2</span> 지식그래프 만들기 및 분석
              </h3>
            </div>

            {/* 메일 탭 콘텐츠 */}
            <div className="gw-tab-panel active" id="tab-panel-mail" role="tabpanel">
              {/* 메일 왼쪽: 폼 카드 */}
              <div className="gw-split-left-content">
                <div className="gw-collect-cards-column">
                  {/* 카드 1: IMAP 서버 설정 */}
                  <div className="gw-card">
                    <div className="gw-card-title">
                      <i className="bi bi-server"></i> 메일 계정 로그인
                    </div>

                    <div className="gw-presets">
                      <div
                        className="gw-preset-chip active"
                        data-host="imap.gmail.com"
                        data-port="993"
                        data-domain="gmail.com"
                      >
                        <i className="bi bi-google"></i> Gmail
                      </div>
                      <div
                        className="gw-preset-chip"
                        data-host="imap.naver.com"
                        data-port="993"
                        data-domain="naver.com"
                      >
                        <svg
                          className="gw-brand-icon"
                          viewBox="0 0 20 20"
                          width="14"
                          height="14"
                          aria-hidden="true"
                        >
                          <rect width="20" height="20" rx="5" fill="#03C75A" />
                          <path
                            d="M12.6 11.14 7.28 3.6H3.6v12.8h4.12V9.2l5.32 7.2H16.4V3.6h-3.8z"
                            fill="#fff"
                          />
                        </svg>
                        NAVER
                      </div>
                      <div
                        className="gw-preset-chip"
                        data-host="imap.mail.me.com"
                        data-port="993"
                        data-domain="icloud.com"
                      >
                        <i className="bi bi-apple"></i> iCloud
                      </div>
                      <div className="gw-preset-chip" data-host="" data-port="993" data-domain="">
                        <i className="bi bi-gear"></i> 직접 입력
                      </div>
                    </div>

                    <div className="gw-form-grid gw-uniform-grid" id="imap-server-grid">
                      <div className="gw-form-group">
                        <label className="gw-label">메일 주소</label>
                        <input
                          id="imap-user"
                          className="gw-input"
                          type="text"
                          placeholder="you@example.com"
                          defaultValue="@gmail.com"
                        />
                      </div>
                      <div className="gw-form-group">
                        <label className="gw-label">앱 비밀번호</label>
                        <input
                          id="imap-pass"
                          className="gw-input"
                          type="password"
                          placeholder="앱 전용 비밀번호"
                        />
                      </div>
                    </div>

                    {/* 숨김 필드 */}
                    <div className="gw-hidden-fields" style={{ display: "none" }}>
                      <div className="gw-form-group">
                        <label className="gw-label">IMAP 호스트</label>
                        <input
                          id="imap-host"
                          className="gw-input"
                          type="text"
                          defaultValue="imap.gmail.com"
                        />
                      </div>
                      <div className="gw-form-group">
                        <label className="gw-label">포트</label>
                        <input
                          id="imap-port"
                          className="gw-input"
                          type="number"
                          defaultValue="993"
                        />
                      </div>
                      <div className="gw-form-group">
                        <label className="gw-label">SSL</label>
                        <select id="imap-ssl" className="gw-select" defaultValue="true">
                          <option value="true">사용 (993)</option>
                          <option value="false">미사용 (143)</option>
                        </select>
                      </div>
                    </div>

                    <div
                      style={{
                        marginTop: "16px",
                        display: "flex",
                        alignItems: "center",
                        gap: "12px",
                      }}
                    >
                      <button
                        type="button"
                        className="gw-preset-chip"
                        id="list-folders-btn"
                        style={{ cursor: "pointer" }}
                      >
                        <i className="bi bi-arrow-clockwise"></i> 폴더 불러오기
                      </button>
                      <span
                        id="folder-list-hint"
                        style={{ fontSize: "1rem", color: "#73879c" }}
                      ></span>
                    </div>
                  </div>

                  {/* 카드 2: 옵션 */}
                  <div className="gw-card">
                    <div className="gw-card-title">
                      <i className="bi bi-sliders"></i> 옵션
                    </div>
                    <div className="gw-form-group" style={{ marginBottom: "18px" }}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          marginBottom: "10px",
                        }}
                      >
                        <label className="gw-label" style={{ marginBottom: 0 }}>
                          불러온 폴더
                        </label>
                        <button
                          type="button"
                          className="gw-select-all-btn"
                          id="select-all-btn"
                          style={{ display: "none" }}
                        >
                          전체 선택
                        </button>
                      </div>
                      <div className="gw-folder-list" id="folder-list">
                        <span className="gw-folder-empty">
                          "폴더 불러오기"를 눌러 수집할 폴더를 선택하세요.
                        </span>
                      </div>
                    </div>

                    <div className="gw-form-grid gw-uniform-grid" id="imap-collect-grid">
                      <div className="gw-form-group">
                        <label className="gw-label">수집 개수 (폴더당)</label>
                        <select id="collect-limit" className="gw-select" defaultValue="0">
                          <option value="50">50개</option>
                          <option value="100">100개</option>
                          <option value="200">200개</option>
                          <option value="500">500개</option>
                          <option value="0">전체</option>
                          <option value="custom">사용자 지정</option>
                        </select>
                        <input
                          type="number"
                          id="collect-limit-custom"
                          className="gw-input"
                          placeholder="개수 입력"
                          min="1"
                          style={{ display: "none", marginTop: "8px" }}
                        />
                      </div>
                      <div className="gw-form-group">
                        <label className="gw-label">모드</label>
                        <select id="sync-mode" className="gw-select" defaultValue="rewrite">
                          <option value="append">업데이트 안 된 메일만</option>
                          <option value="rewrite">전체 업데이트</option>
                        </select>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 메일 수집 시작 버튼 */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "14px",
                    flexWrap: "wrap",
                    marginTop: "15px",
                    marginBottom: "20px",
                  }}
                >
                  <button className="gw-collect-btn" id="collect-btn">
                    <div className="gw-spinner" id="collect-spinner"></div>
                    <i className="bi bi-download" id="collect-icon"></i> 메일 수집 시작
                  </button>
                  <span id="collect-hint" style={{ fontSize: "1rem", color: "#73879c" }}></span>
                </div>
              </div>

              {/* 메일 오른쪽: 로그 */}
              <div className="gw-split-right-content">
                <div className="gw-jobs-list" id="jobs-list">
                  <div className="gw-log-empty" id="jobs-list-empty">
                    <i className="bi bi-clock-history" style={{ fontSize: "1.2rem" }}></i>
                    수집을 시작하면 이곳에 로그가 표시됩니다.
                  </div>
                </div>
              </div>
            </div>

            {/* 메시지 탭 콘텐츠 */}
            <div className="gw-tab-panel" id="tab-panel-message" role="tabpanel">
              {/* 메시지 왼쪽: 폼 카드 */}
              <div className="gw-split-left-content">
                <div className="gw-card">
                  <div className="gw-card-title">
                    <i className="bi bi-file-earmark-text"></i> 메신저 파일
                  </div>
                  <label className="gw-dropzone" id="message-dropzone" htmlFor="message-file-input">
                    <i className="bi bi-cloud-arrow-up"></i>
                    <div className="gw-dropzone-text">
                      txt 파일을 여기로 끌어다 놓거나 클릭해서 선택하세요.
                    </div>
                    <div className="gw-dropzone-sub">
                      카카오톡은 채팅방에서 대화 내보내기가 가능합니다.
                    </div>
                    <div
                      className="gw-dropzone-file"
                      id="message-file-name"
                      style={{ display: "none" }}
                    ></div>
                  </label>
                  <input
                    type="file"
                    id="message-file-input"
                    accept=".txt"
                    style={{ display: "none" }}
                  />

                  <div className="gw-form-grid" style={{ marginTop: "18px" }}>
                    <div className="gw-form-group">
                      <label className="gw-label">대화방 이름</label>
                      <input
                        id="message-room-name"
                        className="gw-input"
                        type="text"
                        placeholder="예: 가족톡"
                      />
                    </div>
                    <div className="gw-form-group">
                      <label className="gw-label">모드</label>
                      <select id="message-sync-mode" className="gw-select" defaultValue="rewrite">
                        <option value="append">업데이트 안 된 메일만</option>
                        <option value="rewrite">전체 업데이트</option>
                      </select>
                    </div>
                  </div>
                </div>

                {/* 메신저 수집 시작 버튼 */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "14px",
                    flexWrap: "wrap",
                    marginTop: "15px",
                    marginBottom: "20px",
                  }}
                >
                  <button className="gw-collect-btn" id="message-upload-btn">
                    <div className="gw-spinner" id="message-upload-spinner"></div>
                    <i className="bi bi-upload" id="message-upload-icon"></i>
                    메신저 수집 시작
                  </button>
                  <span
                    id="message-upload-hint"
                    style={{ fontSize: "1rem", color: "#73879c" }}
                  ></span>
                </div>
              </div>

              {/* 메시지 오른쪽: 로그 */}
              <div className="gw-split-right-content">
                <div className="gw-jobs-list" id="message-jobs-list">
                  <div className="gw-log-empty" id="message-jobs-list-empty">
                    <i className="bi bi-clock-history" style={{ fontSize: "1.2rem" }}></i>
                    수집을 시작하면 이곳에 로그가 표시됩니다.
                  </div>
                </div>
              </div>
            </div>
          </div>
          {/* /.gw-split-grid-wrapper */}
        </div>
        {/* /.gw-collect-wrap */}
        </div>
      </main>
    </>
  );
}

// #containerId 엘리먼트에 ImapCollectApp을 React 루트로 마운트
export function mountImapCollectApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<ImapCollectApp />);
}
