import { createRoot } from "react-dom/client";
import Header from "./Header.jsx";
import Footer from "./Footer.jsx";
import SearchPanel from "./search/SearchPanel.jsx";
import { useState } from "react";
import { getApiBase } from "../utils/apiBase.js";

/**
자연어 검색 페이지(search.html) 전체를 감싸는 최상위 React 컴포넌트 — 헤더, 메일/메신저 탭 전환, 두 개의 독립된 SearchPanel(메일/메신저), 푸터까지 한 번에 그려서 마운트한다.

Top-level React component wrapping the entire search page (search.html) — renders the header, the mail/messenger tab switcher, two independent SearchPanel instances, and the footer in one mount.
 */
function SearchApp({ initialMailQuery }) {
  const [activeTab, setActiveTab] = useState("mail");
  const flaskUrl = getApiBase();

  return (
    <>
      <Header activePage="search" />
      <main className="right_col" role="main" aria-label="Main content" style={{ padding: 0 }}>
        <div className="gw-tabs" role="tablist">
          <button
            type="button"
            className={`gw-tab-btn${activeTab === "mail" ? " active" : ""}`}
            role="tab"
            aria-selected={activeTab === "mail"}
            onClick={() => setActiveTab("mail")}
          >
            <i className="bi bi-envelope"></i> 메일
          </button>
          <button
            type="button"
            className={`gw-tab-btn${activeTab === "message" ? " active" : ""}`}
            role="tab"
            aria-selected={activeTab === "message"}
            onClick={() => setActiveTab("message")}
          >
            <i className="bi bi-chat-dots"></i> 메신저
          </button>
        </div>

        <SearchPanel
          active={activeTab === "mail"}
          domain="mail"
          recentKey="gw_recent_searches"
          getUserId={() => localStorage.getItem("gw_user_id") || ""}
          flaskUrl={flaskUrl}
          loadingText="메일을 분석하고 있습니다..."
          placeholder="메일에 대해 궁금한 것을 검색하세요..."
          emptyIcon="bi bi-search"
          emptyText="검색어를 입력해 메일을 분석하세요."
          initialQuery={initialMailQuery}
        />

        <SearchPanel
          active={activeTab === "message"}
          domain="messenger"
          recentKey="gw_recent_searches_message"
          // 카카오는 검색 화면에 계정 선택기가 없음 — 연합 검색이 인덱싱된 대화방 전체를 자동으로 대상으로 하므로, user_id는 서버 쪽 유효성 검사를 통과시키기 위한 자리표시자면 충분함
          getUserId={() => "message"}
          flaskUrl={flaskUrl}
          loadingText="카카오톡 대화를 분석하고 있습니다..."
          placeholder="카카오톡 대화에 대해 궁금한 것을 검색하세요..."
          emptyIcon="bi bi-chat-dots"
          emptyText="검색어를 입력해 카카오톡 대화를 분석하세요."
        />
      </main>
      <Footer />
    </>
  );
}

// #containerId 엘리먼트에 SearchApp을 React 루트로 마운트
export function mountSearchApp(containerId, options = {}) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<SearchApp {...options} />);
}
