// floatingSearch.js
/**
모든 페이지 우측 상단에 떠 있는 플로팅 검색 버튼 + 팝업 .
search.js와 동일한 GraphRAG 질의 (/run-query-async → /job-status 폴링)를 재사용해서 어느 페이지에서든 같은 검색 결과를 즉시 보여준다.
main-app.js에서 side-effect import되어 이 파일을 불러오는 모든 페이지에 자동으로 뜬다.

Floating search button + popup shown on every page.
Reuses the same GraphRAG query flow as search.js (/run-query-async then polling /job-status) so results match the dedicated search page.
Auto-mounted on every page that imports main-app.js, via that file's side-effect import.
 */
import { getApiBase } from "../utils/apiBase.js";

// XSS 방지용 최소 HTML 이스케이프
function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
// XSS 방지용 최소 속성값 이스케이프
function escapeAttr(str) {
  return String(str || "")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// jobId의 처리 상태를 일정 간격으로 폴링하다 완료/실패 시 콜백 호출(최대 maxTries회)
async function pollJob(FLASK_URL, jobId, onDone, onError, interval = 2000, maxTries = 60) {
  for (let i = 0; i < maxTries; i++) {
    await new Promise((r) => setTimeout(r, interval));
    try {
      const res = await fetch(`${FLASK_URL}/job-status/${jobId}`);
      const data = await res.json();
      if (data.status === "done") {
        onDone(data.result || "결과가 없습니다.", data.source_ids || []);
        return;
      }
      if (data.status === "error") {
        onError(data.result || "오류가 발생했습니다.");
        return;
      }
    } catch (e) {
      onError("서버 연결에 실패했습니다.");
      return;
    }
  }
  onError("응답 시간이 초과되었습니다. 다시 시도해주세요.");
}

const TABS = [
  {
    key: "mail",
    label: "메일",
    icon: "fas fa-envelope",
    domain: "mail",
    recentKey: "gw_recent_searches", // search.js와 동일한 키 — 최근 검색어를 실제 검색 페이지와 공유
    loadingText: "메일을 분석하고 있습니다...",
    getUserId: () => localStorage.getItem("gw_user_id") || "",
    placeholder: "메일에서 검색...",
  },
  {
    key: "message",
    label: "메신저",
    icon: "bi bi-chat-dots",
    domain: "messenger",
    recentKey: "gw_recent_searches_message",
    loadingText: "카카오톡 대화를 분석하고 있습니다...",
    getUserId: () => "message",
    placeholder: "메신저 대화에서 검색...",
  },
];

// search.html처럼 메일/메신저 탭이 입력창·최근검색·결과영역을 각자 독립적으로 갖는다 (하나를 공유하면 두 탭의 이벤트 리스너가 같은 input/버튼에 겹쳐 붙어서 검색이 동시에 두 번 실행되는 문제가 생김 — 그래서 탭마다 완전히 별도의 서브패널을 둔다).
// 검색 팝업(탭 + 입력창 + 결과 영역)의 HTML 마크업 문자열 생성
function buildPanelHtml() {
  const tabBtns = TABS.map(
    (t, i) => `
      <button type="button" class="gwfs-tab-btn${i === 0 ? " active" : ""}" data-tab="${t.key}">
        <i class="${t.icon}"></i><span>${t.label}</span>
      </button>`
  ).join("");

  const tabPanels = TABS.map(
    (t, i) => `
      <div class="gwfs-tab-panel${i === 0 ? " active" : ""}" data-tab-panel="${t.key}">
        <!-- 버튼 삐져나옴 방지를 위해 컨테이너에 flex, input에 flex: 1, button에 flex-shrink: 0 적용 -->
        <div class="gwfs-search-box" style="display: flex; align-items: center; box-sizing: border-box; overflow: hidden;">
          <input type="text" class="gwfs-input" placeholder="${t.placeholder}" autocomplete="off" style="flex: 1; min-width: 0; box-sizing: border-box;">
          <button type="button" class="gwfs-search-btn" aria-label="검색" style="flex-shrink: 0; box-sizing: border-box;"><i class="fas fa-search"></i></button>
        </div>
        <div class="gwfs-recent"></div>
        <div class="gwfs-result"></div>
      </div>`
  ).join("");

  return `
    <div class="gwfs-panel-head">
      <div class="gwfs-tabs">${tabBtns}</div>
      <button type="button" class="gwfs-close-btn" aria-label="닫기"><i class="bi bi-x-lg"></i></button>
    </div>
    ${tabPanels}
  `;
}

// 검색창 하나(메일/메신저 탭)의 입력 제출, 질의 요청, 폴링, 결과 렌더링을 담당하는 컨트롤러 생성
function createTabController(tab, root, FLASK_URL) {
  const panelEl = root.querySelector(`.gwfs-tab-panel[data-tab-panel="${tab.key}"]`);
  const inputEl = panelEl.querySelector(".gwfs-input");
  const btnEl = panelEl.querySelector(".gwfs-search-btn");
  const recentEl = panelEl.querySelector(".gwfs-recent");
  const resultEl = panelEl.querySelector(".gwfs-result");

  function getRecents() {
    try {
      return JSON.parse(localStorage.getItem(tab.recentKey)) || [];
    } catch {
      return [];
    }
  }
  function saveRecent(q) {
    let recents = getRecents().filter((r) => r !== q);
    recents.unshift(q);
    if (recents.length > 6) recents = recents.slice(0, 6);
    localStorage.setItem(tab.recentKey, JSON.stringify(recents));
  }
  function removeRecent(q) {
    localStorage.setItem(tab.recentKey, JSON.stringify(getRecents().filter((r) => r !== q)));
    renderRecents();
  }

  function renderRecents() {
    const recents = getRecents();
    if (!recents.length) {
      recentEl.innerHTML = "";
      return;
    }
    recentEl.innerHTML = recents
      .map(
        (r) => `
        <span class="gwfs-recent-tag" data-q="${escapeAttr(r)}">
          <i class="fas fa-history"></i>${escapeHtml(r)}
          <span class="gwfs-tag-del" data-del="${escapeAttr(r)}">×</span>
        </span>`
      )
      .join("");
    recentEl.querySelectorAll(".gwfs-recent-tag").forEach((tagEl) => {
      tagEl.addEventListener("click", (e) => {
        if (e.target.classList.contains("gwfs-tag-del")) return;
        inputEl.value = tagEl.dataset.q;
        runSearch(tagEl.dataset.q);
      });
    });
    recentEl.querySelectorAll(".gwfs-tag-del").forEach((delEl) => {
      delEl.addEventListener("click", (e) => {
        e.stopPropagation();
        removeRecent(delEl.dataset.del);
      });
    });
  }

  function showLoading(q) {
    resultEl.innerHTML = `
      <div class="gwfs-query-label">검색어: <strong>${escapeHtml(q)}</strong></div>
      <div class="gwfs-loading"><div class="gwfs-spinner"></div><span>${tab.loadingText}</span></div>
    `;
  }
  function showResult(q, text, sourceIds) {
    let sourceHtml = "";
    resultEl.innerHTML = `
      <div class="gwfs-query-label">검색어: <strong>${escapeHtml(q)}</strong></div>
      <div class="gwfs-result-card">${escapeHtml(text)}</div>
      ${sourceHtml}
    `;
  }
  function showError(q, msg) {
    resultEl.innerHTML = `
      <div class="gwfs-query-label">검색어: <strong>${escapeHtml(q)}</strong></div>
      <div class="gwfs-error"><i class="fas fa-exclamation-circle"></i>${escapeHtml(msg)}</div>
    `;
  }

  async function runSearch(q) {
    showLoading(q);
    saveRecent(q);
    renderRecents();

    const userId = tab.getUserId();
    try {
      const res = await fetch(`${FLASK_URL}/run-query-async`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: q,
          resType: "structed",
          user_id: userId,
          domain: tab.domain,
        }),
      });
      const data = await res.json();
      if (!data.jobId) {
        showError(q, "검색 요청에 실패했습니다.");
        return;
      }
      await pollJob(
        FLASK_URL,
        data.jobId,
        (text, sourceIds) => showResult(q, text, sourceIds),
        (msg) => showError(q, msg)
      );
    } catch (e) {
      showError(q, "서버에 연결할 수 없습니다.");
    }
  }

  function doSearch() {
    const q = inputEl.value.trim();
    if (!q) return;
    runSearch(q);
  }

  // stopPropagation: 이 클릭/엔터가 document까지 버블링되면 아래 outside-click 닫기 로직과 맞물릴 수 있어서(검색 버튼을 눌렀는데 패널이 닫혀버리는 문제), 패널 안에서 일어나는 검색 액션은 버블링 자체를 여기서 끊어버린다.
  btnEl.addEventListener("click", (e) => {
    e.stopPropagation();
    doSearch();
  });
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
      doSearch();
    }
  });
  renderRecents();

  return { inputEl, placeholder: tab.placeholder };
}

// 플로팅 버튼 + 팝업 DOM을 body에 주입하고 열기/닫기, 탭 전환 이벤트를 바인딩
function mountFloatingSearch() {
  // main-app.js를 안 쓰는 페이지는 애초에 이 모듈이 로드되지 않으므로, 중복 마운트 방지만 체크.
  if (document.getElementById("gwfs-btn")) return; // 중복 마운트 방지

  const FLASK_URL = getApiBase();

  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "gwfs-btn";
  btn.className = "gwfs-btn";
  btn.setAttribute("aria-label", "검색 열기");

  // 마우스 오버 시 툴팁 추가
  btn.setAttribute("data-tooltip", "궁금한 것을 언제든지 질문해주세요.");

  // 돋보기 아이콘을 키움 (font-size 속성 추가)
  btn.innerHTML = '<i class="fas fa-search" style="font-size: 1.5rem; line-height: 1;"></i>';

  document.body.appendChild(btn);

  const panel = document.createElement("div");
  panel.id = "gwfs-panel";
  panel.className = "gwfs-panel";
  panel.innerHTML = buildPanelHtml();
  document.body.appendChild(panel);

  const controllers = {};
  TABS.forEach((tab) => {
    controllers[tab.key] = createTabController(tab, panel, FLASK_URL);
  });

  function switchTab(key) {
    panel.querySelectorAll(".gwfs-tab-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === key);
    });
    panel.querySelectorAll(".gwfs-tab-panel").forEach((p) => {
      p.classList.toggle("active", p.dataset.tabPanel === key);
    });
    controllers[key]?.inputEl.focus();
  }
  panel.querySelectorAll(".gwfs-tab-btn").forEach((b) => {
    b.addEventListener("click", () => switchTab(b.dataset.tab));
  });

  function openPanel() {
    panel.classList.add("open");
    btn.classList.add("open");
    setTimeout(() => panel.querySelector(".gwfs-tab-panel.active .gwfs-input")?.focus(), 50);
  }
  function closePanel() {
    panel.classList.remove("open");
    btn.classList.remove("open");
  }
  btn.addEventListener("click", () => {
    panel.classList.contains("open") ? closePanel() : openPanel();
  });
  panel.querySelector(".gwfs-close-btn").addEventListener("click", closePanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePanel();
  });
  // 패널 내부에서 일어나는 클릭은 무엇이든(검색 버튼, 탭, 최근검색 태그 등) 절대 document까지 버블링되지 않게 원천 차단 — 개별 버튼마다 stopPropagation을 빠짐없이 챙기는 대신 여기 한 곳에서 확실하게 막는다(검색 버튼을 눌렀는데 곧바로 패널이 닫혀버리던 문제의 근본 원인).
  panel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", (e) => {
    if (!panel.classList.contains("open")) return;
    if (panel.contains(e.target) || btn.contains(e.target)) return;
    closePanel();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountFloatingSearch);
} else {
  mountFloatingSearch();
}
