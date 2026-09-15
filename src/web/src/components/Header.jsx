/**
공통 상단 헤더 React 컴포넌트 — 상단 네비게이션(NAV_ITEMS)을 렌더링하며 8개 페이지 전부가 activePage prop만 바꿔서 공유하는, 사이트 전체의 유일한 헤더 구현이다.
좁은 화면(≤1180px)에서는 _mobile.scss가 .gw-top-links를 숨기므로 햄버거 버튼(.gw-nav-toggle)으로 펼침/접힘을 토글한다.

Shared top header React component — renders the top nav (NAV_ITEMS) and is reused by all 8 pages via the activePage prop; the site's single header implementation.
On narrow screens (≤1180px) _mobile.scss hides .gw-top-links, so a hamburger button (.gw-nav-toggle) toggles it open.
 */

import { useState } from "react";

// 상단 네비게이션 메뉴 항목 정의 — 이 배열만 고치면 메뉴 항목이 늘거나 줄어도 화면이 자동으로 갱신된다.
// 메뉴 순서: Social data analysis → View results → Knowledge graph.
// 홈은 로고 클릭으로 이동 가능하므로 메뉴에서 제외.
// Recap은 빌드 대상에서 제외됨(vite.config.js 참고).
const NAV_ITEMS = [
  {
    page: "imap-collect",
    href: "imap-collect.html",
    label: "Social data analysis",
  },
  {
    page: "analysis-hub",
    href: "analysishub.html",
    label: "View results",
    children: [
      { page: "mypeople", href: "mypeople.html", label: "My People" },
      { page: "mytime", href: "mytime.html", label: "My Time" },
      { page: "recap", href: "recap.html", label: "Recap" },
      { page: "search", href: "search.html", label: "Natural language search" },
    ],
  },
  { page: "graph-viz", href: "graphviz.html", label: "Knowledge graph" },
];

// 메뉴 항목 하나를 렌더링 — children이 있으면 드롭다운 그룹으로 표시
function NavItem({ item, activePage }) {
  if (item.children) {
    const groupActive =
      item.page === activePage || item.children.some((c) => c.page === activePage);
    return (
      <div className="gw-tl-dropdown">
        <a href={item.href} className={`gw-tl gw-tl-dd-btn${groupActive ? " active" : ""}`}>
          {item.label}{" "}
          <i className="bi bi-chevron-down" style={{ fontSize: ".65rem", marginLeft: "2px" }}></i>
        </a>
        <div className="gw-tl-dd-menu">
          {item.children.map((c) => (
            <a key={c.page} href={c.href} className={c.page === activePage ? "active" : ""}>
              {c.label}
            </a>
          ))}
        </div>
      </div>
    );
  }
  return (
    <a href={item.href} className={`gw-tl${item.page === activePage ? " active" : ""}`}>
      {item.label}
    </a>
  );
}

// 상단 헤더 전체(로고 + 네비게이션) 렌더링
export default function Header({ activePage }) {
  // 좁은 화면에서 햄버거로 펼치는 네비 패널의 열림 상태. 데스크톱에서는 CSS가
  // .gw-nav-toggle 자체를 숨기므로 이 상태값은 화면에 영향을 주지 않는다.
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="top_nav">
      <div className="nav_menu d-flex align-items-center justify-content-between">
        <div className="d-flex align-items-center">
          <a href="index.html" className="gw-brand-logo">
            <img src="/images/logos/socialvisualizer.png" className="gw-brand-logo-icon" alt="" />
            <span className="gw-brand-logo-text">Social Visualizer</span>
          </a>
          <nav className={`gw-top-links${navOpen ? " is-open" : ""}`}>
            {NAV_ITEMS.map((item) => (
              <NavItem key={item.page} item={item} activePage={activePage} />
            ))}
          </nav>
        </div>
        <button
          type="button"
          className="gw-nav-toggle"
          aria-label="메뉴 열기/닫기"
          aria-expanded={navOpen}
          onClick={() => setNavOpen((v) => !v)}
        >
          <i className={`bi ${navOpen ? "bi-x-lg" : "bi-list"}`}></i>
        </button>
        {navOpen && (
          <div
            className="gw-nav-backdrop"
            aria-hidden="true"
            onClick={() => setNavOpen(false)}
          ></div>
        )}
        <nav className="nav navbar-nav ms-auto">
          <ul className="navbar-right d-flex align-items-center gap-3 pe-3"></ul>
        </nav>
      </div>
    </div>
  );
}
