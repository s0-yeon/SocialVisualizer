/**
"My Time" 페이지의 타임라인/키워드 패널 렌더링을 담당하는 엔진 모듈. 슬라이더 드래그, 연도 점 배치, 일별 막대그래프 등 D3 없이 직접 구현한 커스텀 위젯을 포함한다.
React가 그리는 DOM(#mt-mail-view 등)에 getElementById 기반으로 직접 접근해 동작하며, React 마운트 후 useEffect에서 initMyTimePage()를 한 번 호출하면 초기화된다.

Engine module for the "My Time" page — renders the timeline and keyword panel, including a custom slider-drag, year-dot layout, and daily bar chart built without D3.
It operates directly on the DOM via getElementById rather than through React state, and is initialized by a single call to initMyTimePage() from a useEffect once React has mounted the page (e.g. #mt-mail-view).
 */
import { initAccountPicker } from "../features/accountPicker.js";
import { store } from "../store/globalStore.js";
import { refreshSidebarList } from "../components/appSidebar.js";
import { initGlobalFilter } from "../utils/filterSync.js";

/* 공통 fetch 헬퍼 */
// JSON POST 요청 공통 헬퍼
async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.json();
}

/* 공용 툴팁(주요 연락처 설명 / 키워드 언급자) */
let mtTooltipEl = null;
// 공용 툴팁 엘리먼트를 최초 1회 생성해 body에 붙이고 재사용
function ensureTooltip() {
  if (mtTooltipEl) return mtTooltipEl;
  mtTooltipEl = document.createElement("div");
  mtTooltipEl.className = "mt-tooltip";
  document.body.appendChild(mtTooltipEl);
  return mtTooltipEl;
}
// XSS 방지용 최소 HTML 이스케이프
function escHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
// 주요 연락처 카드 hover 설명 — 상세 설명(description) 대신 short_bio(한줄 소개)만 보여준다.
function formatContactTooltip(shortBio) {
  return shortBio ? escHtml(shortBio) : "등록된 설명이 없습니다.";
}
// anchorEl 위치를 기준으로 공용 툴팁을 표시(placement로 위/아래 결정)
function showTooltip(anchorEl, html, placement = "top") {
  const t = ensureTooltip();
  t.innerHTML = html;
  const rect = anchorEl.getBoundingClientRect();
  const left = Math.max(8, Math.min(window.innerWidth - 280, rect.left));
  t.style.left = `${left}px`;
  // 주요 연락처(placement="bottom")에 뜨는 설명 창은, 그 연락처 요소가 hover 시 변하는 주황색과 맞추되 더 연한 톤(mt-tooltip-contact)을 쓴다.
  t.classList.toggle("mt-tooltip-contact", placement === "bottom");
  if (placement === "bottom") {
    // 주요 연락처 카드용 — 위가 아니라 카드 밑으로 상세 설명 창이 뜨도록
    t.style.top = `${rect.bottom + 8}px`;
    t.style.transform = "translateY(0)";
  } else {
    t.style.top = `${rect.top - 8}px`;
    t.style.transform = "translateY(-100%)";
  }
  requestAnimationFrame(() => t.classList.add("show"));
}
// 공용 툴팁 숨김
function hideTooltip() {
  if (mtTooltipEl) mtTooltipEl.classList.remove("show");
}

/* 타임라인 컨트롤러 */
// 좌측 월/연도 슬라이더 타임라인 전체(렌더링, 포인터/커서, 기간 고정, 데이터 주입)를 관리하는 컨트롤러 팩토리 — 메일/메신저 화면이 각자 하나씩 만들어 쓴다.
function createTimeline(ids) {
  let MONTH_DATA = {};
  let YEAR_DATA = {};
  let ALL_KEYS = [];
  let YEAR_KEYS = [];
  let FIRST_NUM = 0;
  let TOTAL = 1;
  let mode = "month";
  let centerIdx = 2;
  let pinnedKey = null;
  // 제목 옆 뱃지("2020.11 ~ 2026.08 데이터")로 옮겨진 전체 기간 텍스트 — buildPointer()에서 계산해두고, 지금 보고 있는 채널(메일/메신저)일 때만 공용 뱃지(#mtDataRangeLbl)에 반영한다(updateSharedRangeBadge 참고).
  let fullRangeText = "";
  // 상단 타임슬라이더 — 연도별 모드는 한 화면에 5개씩 슬라이딩 윈도우로 보여줌.
  // 월별 모드는 슬라이딩 윈도우가 아니라 "지금 선택된 연도에 속한 달"만 모아서 보여준다(getWindowKeys 참고) — 그래서 여기엔 year 값만 남는다.
  const WIN = { year: 5 };

  // "YYYY-MM" 키를 정렬/거리 계산용 정수(연*12+월)로 변환
  function monthToNum(k) {
    const [y, m] = k.split("-").map(Number);
    return y * 12 + m;
  }
  // 월 키를 전체 기간 대비 위치(0~1 비율)로 변환
  function monthToPct(k) {
    return (monthToNum(k) - FIRST_NUM) / TOTAL;
  }
  // 연도를 전체 기간 대비 위치(0~1 비율)로 변환
  function yearToPct(y) {
    return (Number(y) * 12 + 1 - FIRST_NUM) / TOTAL;
  }
  const YEAR_DOT_INSET = 0;
  // 연도 점들을 실제 시간 간격이 아닌 균등 간격으로 배치하기 위한 인덱스 기반 위치 계산
  function yearIdxPct(i) {
    if (YEAR_KEYS.length <= 1) return 0.5;
    const clamped = Math.max(0, Math.min(YEAR_KEYS.length - 1, i));
    return YEAR_DOT_INSET + (clamped / (YEAR_KEYS.length - 1)) * (1 - YEAR_DOT_INSET * 2);
  }
  function getWindowKeys() {
    if (mode === "month") {
      const k = ALL_KEYS[Math.max(0, Math.min(ALL_KEYS.length - 1, centerIdx))];
      if (!k) return [];
      const year = k.split("-")[0];
      return ALL_KEYS.filter((mk) => mk.split("-")[0] === year);
    }
    const win = WIN.year;
    let start = Math.max(0, centerIdx - Math.floor(win / 2));
    start = Math.min(start, YEAR_KEYS.length - win);
    start = Math.max(0, start);
    return YEAR_KEYS.slice(start, start + win);
  }

  // 현재 모드/윈도우에 맞는 기간 열(점+라벨)을 다시 그리고 이벤트를 바인딩
  function render() {
    const keys = getWindowKeys();
    const data = mode === "month" ? MONTH_DATA : YEAR_DATA;
    const track = document.getElementById(ids.track);
    track.innerHTML = "";
    pinnedKey = null;
    document.getElementById(ids.panel).classList.remove("pinned");
    hidePanel();

    keys.forEach((k) => {
      const d = data[k];
      if (!d) return;

      const col = document.createElement("div");
      col.className = "mt-node-col";
      col.dataset.key = k;

      const dot = document.createElement("div");
      dot.className = "mt-dot";

      const lbl = document.createElement("div");
      lbl.className = "mt-node-label";
      lbl.textContent = mode === "month" ? `${parseInt(k.slice(5), 10)}월` : `${k}년`;

      col.appendChild(dot);
      col.appendChild(lbl);
      track.appendChild(col);

      col.addEventListener("mouseenter", () => {
        if (!pinnedKey) showPanel(col, k, d);
      });
      col.addEventListener("mouseleave", () => {
        if (!pinnedKey) hidePanel();
      });
      col.addEventListener("click", () => {
        if (pinnedKey === k) {
          pinnedKey = null;
          col.classList.remove("pinned");
          document.getElementById(ids.panel).classList.remove("pinned");
          hidePanel();
        } else {
          pinKey(col, k, d);
        }
      });
    });

    updatePointerWindow();
  }

  // 특정 기간 열에 대한 요약/주요 연락처 패널을 표시
  function showPanel(col, key, d) {
    document
      .getElementById(ids.track)
      .querySelectorAll(".mt-node-col")
      .forEach((c) => c.classList.toggle("active", c === col));

    document.getElementById(ids.panelPeriod).textContent =
      mode === "month" ? `${key.slice(0, 4)}년 ${key.slice(5)}월` : `${key}년`;
    if (ids.panelCount) {
      document.getElementById(ids.panelCount).innerHTML = d.count
        ? `<strong>${d.count.toLocaleString()}</strong>건 &nbsp;·&nbsp; ${d.threads}개 대화`
        : "";
    }
    document.getElementById(ids.panelSummary).textContent = d.summary || "";

    const cc = document.getElementById(ids.panelContacts);
    cc.innerHTML = "";
    // person_name이 없는 항목.
    (d.contacts || [])
      .filter((c) => c.person_name)
      .forEach((c) => {
        const el = document.createElement("div");
        el.className = "mt-panel-contact";
        el.textContent = c.person_name;
        el.addEventListener("mouseenter", () => {
          showTooltip(el, formatContactTooltip(c.short_bio), "bottom");
        });
        el.addEventListener("mouseleave", hideTooltip);
        cc.appendChild(el);
      });
    // 필터링 후 하나도 안 남으면(전부 이름 없는 연락처였던 경우) 빈 칸 대신 안내 문구를 보여준다.
    if (!cc.children.length) {
      cc.innerHTML = '<p class="mt-panel-contacts-empty">표시할 주요 연락처가 없습니다.</p>';
    }

    document.getElementById(ids.panel).classList.add("show");
  }

  // 오른쪽 "월별 키워드" 창에 지금 왼쪽에서 보고 있는 기간을 알려준다.
  function notifyPeriod(key) {
    if (ids.onPeriod && key) ids.onPeriod(mode, key);
  }

  function hidePanel() {
    document.getElementById(ids.panel).classList.remove("show");
    document
      .getElementById(ids.track)
      .querySelectorAll(".mt-node-col")
      .forEach((c) => c.classList.remove("active"));
  }

  // 슬라이더에서 기간 하나를 "고정(pin)" — 클릭했을 때와, 페이지 로드 시 가장 최근 달을 기본으로 띄울 때 둘 다 이 함수를 쓴다.
  function pinKey(col, k, d) {
    pinnedKey = k;
    document
      .getElementById(ids.track)
      .querySelectorAll(".mt-node-col")
      .forEach((c) => c.classList.remove("pinned"));
    col.classList.add("pinned");
    showPanel(col, k, d);
    document.getElementById(ids.panel).classList.add("pinned");
    centerIdx = (mode === "month" ? ALL_KEYS : YEAR_KEYS).indexOf(k);
    updatePointerCursor();
    notifyPeriod(k);
  }

  // 페이지를 처음 열었을 때 가장 최근 달을 기본으로 고정해서 보여준다.
  function pinDefaultLast() {
    if (!ALL_KEYS.length) return;
    const key = ALL_KEYS[ALL_KEYS.length - 1];
    const d = MONTH_DATA[key];
    const col = document.getElementById(ids.track).querySelector(`.mt-node-col[data-key="${key}"]`);
    if (!col || !d) {
      notifyPeriod(key);
      return;
    }
    pinKey(col, key, d);
  }

  // 하단 연도 포인터 트랙(점들 + 커서 + 활성 구간 바)을 새로 생성
  function buildPointer() {
    const pointerTrack = document.getElementById(ids.pointerTrack);
    pointerTrack.querySelectorAll(".mt-pm").forEach((el) => el.remove());

    YEAR_KEYS.forEach((y, i) => {
      const pm = document.createElement("div");
      pm.className = "mt-pm";
      pm.dataset.year = y;
      if (YEAR_KEYS.length === 1) pm.classList.add("is-only");
      pm.style.left = `${yearIdxPct(i) * 100}%`;
      pm.addEventListener("click", (e) => {
        e.stopPropagation();
        if (mode === "year") {
          centerIdx = Math.max(0, YEAR_KEYS.indexOf(y));
        } else {
          const idx = ALL_KEYS.findIndex((k) => k.startsWith(`${y}-`));
          centerIdx = Math.max(0, idx === -1 ? 0 : idx);
        }
        updatePointerCursor();
        render();
      });
      pointerTrack.insertBefore(pm, document.getElementById(ids.pointerWindow));
    });

    const fmtYm = (k) => `${k.slice(0, 4)}.${k.slice(5)}`;
    fullRangeText =
      ALL_KEYS.length > 1
        ? `${fmtYm(ALL_KEYS[0])} ~ ${fmtYm(ALL_KEYS[ALL_KEYS.length - 1])} 데이터`
        : ALL_KEYS.length
          ? `${fmtYm(ALL_KEYS[0])} 데이터`
          : "";
    if (ids.channel === mtActiveChannel) updateSharedRangeBadge(fullRangeText);

    const axis = document.getElementById(ids.pointerAxis);
    axis.innerHTML = "";

    const MIN_GAP_PX = 64;
    const axisWidth = axis.offsetWidth || axis.getBoundingClientRect().width || 0;
    const withPct = YEAR_KEYS.map((y, i) => ({
      y,
      pct: yearIdxPct(i) * 100,
    }));

    let filtered = withPct.length ? [withPct[0]] : [];
    for (let i = 1; i < withPct.length; i++) {
      const prev = filtered[filtered.length - 1];
      const gapPx = ((withPct[i].pct - prev.pct) / 100) * axisWidth;
      if (gapPx >= MIN_GAP_PX || i === withPct.length - 1) {
        filtered.push(withPct[i]);
      }
    }
    if (filtered.length >= 2) {
      const last = filtered[filtered.length - 1];
      const beforeLast = filtered[filtered.length - 2];
      const gapPx = ((last.pct - beforeLast.pct) / 100) * axisWidth;
      if (gapPx < MIN_GAP_PX) {
        filtered.splice(filtered.length - 2, 1);
      }
    }

    filtered.forEach(({ y, pct }) => {
      const tick = document.createElement("div");
      tick.className = "mt-pa-tick";
      tick.style.left = pct + "%";
      const line = document.createElement("div");
      line.className = "mt-pa-tick-line";
      const lbl = document.createElement("div");
      lbl.className = "mt-pa-lbl";
      lbl.textContent = y;
      tick.appendChild(line);
      tick.appendChild(lbl);
      axis.appendChild(tick);
    });

    updatePointerCursor();
    updatePointerWindow();
  }

  // 선택된 연도 점 위에 화살표를 띄우기 위한 표시 갱신
  function updateYearDotSelection() {
    const track = document.getElementById(ids.pointerTrack);
    if (!track) return;
    let selectedYear = null;
    if (mode === "year") {
      selectedYear = YEAR_KEYS[Math.max(0, Math.min(YEAR_KEYS.length - 1, centerIdx))];
    } else {
      const mk = ALL_KEYS[Math.max(0, Math.min(ALL_KEYS.length - 1, centerIdx))];
      selectedYear = mk ? mk.split("-")[0] : null;
    }
    track.querySelectorAll(".mt-pm").forEach((el) => {
      el.classList.toggle("selected", !!selectedYear && el.dataset.year === selectedYear);
    });

    const rangeLbl = document.getElementById(ids.rangeLbl);
    if (rangeLbl) {
      rangeLbl.textContent = selectedYear ? `선택된 연도는 ${selectedYear}년도 입니다.` : "—";
    }
  }

  // 현재 선택된 기간에 맞춰 포인터 커서(나 아바타) 위치를 갱신
  function updatePointerCursor() {
    const keys = mode === "month" ? ALL_KEYS : YEAR_KEYS;
    const k = keys[Math.max(0, Math.min(keys.length - 1, centerIdx))];
    let pct;
    if (mode === "month") {
      const y = k.split("-")[0];
      const yIdx = YEAR_KEYS.indexOf(y);
      pct = (yIdx === -1 ? monthToPct(k) : yearIdxPct(yIdx)) * 100;
    } else {
      pct = yearIdxPct(YEAR_KEYS.indexOf(k)) * 100;
    }
    document.getElementById(ids.pointerCursor).style.left = Math.max(0, Math.min(100, pct)) + "%";
    updateYearDotSelection();
  }

  // 지금 화면에 보이는 기간 범위를 포인터 트랙 위 활성 구간 바로 표시
  function updatePointerWindow() {
    const wKeys = getWindowKeys();
    if (!wKeys.length) return;
    let s, e;
    if (mode === "month") {
      s = monthToPct(wKeys[0]);
      e = monthToPct(wKeys[wKeys.length - 1]);
    } else {
      const startIdx = YEAR_KEYS.indexOf(wKeys[0]);
      const endIdx = YEAR_KEYS.indexOf(wKeys[wKeys.length - 1]);
      const step = YEAR_KEYS.length > 1 ? (1 - YEAR_DOT_INSET * 2) / (YEAR_KEYS.length - 1) : 0;
      s = yearIdxPct(startIdx);
      e = yearIdxPct(endIdx) + step * 0.6;
    }
    const win = document.getElementById(ids.pointerWindow);
    win.style.left = `${Math.max(0, s * 100)}%`;
    win.style.width = `${Math.min(100, (e - s) * 100)}%`;
  }

  document.getElementById(ids.pointerTrack).addEventListener("click", (e) => {
    if (e.target.classList.contains("mt-pm")) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    if (mode === "month") {
      const totalIdx = Math.round(pct * ALL_KEYS.length);
      centerIdx = Math.max(0, Math.min(ALL_KEYS.length - 1, totalIdx));
    } else {
      const rawIdx =
        YEAR_KEYS.length > 1
          ? ((pct - YEAR_DOT_INSET) / (1 - YEAR_DOT_INSET * 2)) * (YEAR_KEYS.length - 1)
          : 0;
      centerIdx = Math.max(0, Math.min(YEAR_KEYS.length - 1, Math.round(rawIdx)));
    }
    updatePointerCursor();
    render();
  });

  // 새 계정/채팅방의 월별·연도별 데이터를 주입하고 타임라인을 초기 상태로 다시 그림
  function setData(monthData, yearData, emptyMessage) {
    MONTH_DATA = monthData || {};
    YEAR_DATA = yearData || {};
    ALL_KEYS = Object.keys(MONTH_DATA).sort();
    YEAR_KEYS = Object.keys(YEAR_DATA).sort();

    const track = document.getElementById(ids.track);
    if (!ALL_KEYS.length) {
      track.innerHTML = `<div style="color:#a8a8a8;font-size:.78rem;padding:20px 0;">${emptyMessage}</div>`;
      return false;
    }

    FIRST_NUM = monthToNum(ALL_KEYS[0]);
    const LAST_NUM = monthToNum(ALL_KEYS[ALL_KEYS.length - 1]);
    TOTAL = LAST_NUM - FIRST_NUM || 1;
    centerIdx = ALL_KEYS.length - 1;

    buildPointer();
    render();
    pinDefaultLast();
    return true;
  }

  // 월별/연도별 보기 모드 전환
  function setMode(m) {
    mode = m;
    centerIdx = mode === "month" ? Math.min(3, ALL_KEYS.length - 1) : 0;
    render();
    updatePointerCursor();
    const keys = mode === "month" ? ALL_KEYS : YEAR_KEYS;
    notifyPeriod(keys[Math.max(0, Math.min(keys.length - 1, centerIdx))]);
  }

  return { setData, setMode, getRangeText: () => fullRangeText };
}

/* 오른쪽 "월별 키워드" 창 컨트롤러
   ids: { body, hint, backBtn } — DOM id 문자열
   api: { monthlyUrl, dailyUrl, mentionersUrl, idField } — 메일/메신저별로 다른
        엔드포인트·요청 필드명(user_id vs chatroom_id)을 여기서 갈아끼운다. */
// 우측 "월별 키워드" 패널 전체(목록 보기 ↔ 일별 그래프 보기 전환 포함)를 관리하는 컨트롤러 팩토리
function createKeywordPanel(ids, api) {
  let idValue = "";
  let monthlyMap = {};
  const dailyCache = {}; // monthKey -> {date: [{word,count}]}
  const mentionersCache = {}; // "date|word" -> data[]
  let view = "list"; // 'list' | 'daily'
  let currentMonthKey = null;
  let currentYear = null;
  let currentKeyword = null;

  const bodyEl = () => document.getElementById(ids.body);
  const hintEl = () => document.getElementById(ids.hint);
  const backBtnEl = () => document.getElementById(ids.backBtn);
  const titleEl = () => (ids.title ? document.getElementById(ids.title) : null);

  // "월별 키워드"라는 고정 문구 대신, 지금 왼쪽에서 선택된 기간에 맞춰 제목을 매번 바꿔준다.
  function updateTitle(mode, key) {
    const el = titleEl();
    if (!el || !key) return;
    el.textContent =
      mode === "year" ? `${key}년 키워드` : `${key.slice(0, 4)}년 ${key.slice(5)}월 키워드`;
  }

  // "YYYY-MM" 월의 마지막 날짜(일 수) 계산
  function daysInMonth(key) {
    const [y, m] = key.split("-").map(Number);
    return new Date(y, m, 0).getDate();
  }

  // 계정/채팅방이 바뀔 때(초기 로드 포함) 호출 — 그 기간의 월별 키워드 통계를 통째로 한 번만 받아둔다.
  async function init(newIdValue) {
    idValue = newIdValue || "";
    monthlyMap = {};
    Object.keys(dailyCache).forEach((k) => delete dailyCache[k]);
    Object.keys(mentionersCache).forEach((k) => delete mentionersCache[k]);
    view = "list";
    currentMonthKey = null;
    currentYear = null;
    currentKeyword = null;
    if (backBtnEl()) backBtnEl().style.display = "none";
    if (titleEl()) titleEl().textContent = "키워드";

    if (!idValue) {
      renderEmpty("연결된 계정이 없습니다.");
      return;
    }
    try {
      const j = await postJSON(api.monthlyUrl, { [api.idField]: idValue });
      monthlyMap = j.data || {};
    } catch (e) {
      console.error("keyword-monthly-stats 오류:", e);
      monthlyMap = {};
    }
  }

  // 키워드 패널을 빈 상태 메시지로 표시
  function renderEmpty(msg) {
    if (hintEl()) hintEl().textContent = "";
    if (bodyEl())
      bodyEl().innerHTML = `<div class="mt-empty"><i class="bi bi-chat-square-text"></i><p>${escHtml(msg)}</p></div>`;
  }

  // 현재 선택된 기간의 키워드 랭킹 목록을 렌더링(연도 보기는 그 해 전체 합산)
  function renderList() {
    view = "list";
    currentKeyword = null;
    if (backBtnEl()) backBtnEl().style.display = "none";
    if (!bodyEl()) return;

    let keywords = [];
    const yearMode = !!currentYear;
    if (yearMode) {
      const merged = {};
      Object.keys(monthlyMap).forEach((mk) => {
        if (!mk.startsWith(`${currentYear}-`)) return;
        (monthlyMap[mk] || []).forEach((kw) => {
          merged[kw.word] = (merged[kw.word] || 0) + kw.count;
        });
      });
      keywords = Object.entries(merged).map(([word, count]) => ({
        word,
        count,
      }));
    } else if (currentMonthKey) {
      keywords = monthlyMap[currentMonthKey] || [];
    }

    keywords = keywords
      .slice()
      .sort((a, b) => b.count - a.count)
      .slice(0, 15);

    if (hintEl()) {
      hintEl().textContent = yearMode
        ? "연도별 보기에서는 키워드 집계만 볼 수 있어요 — 일별 그래프는 월별 보기에서 확인해보세요."
        : "키워드를 클릭하시면 일별 그래프가 나타납니다.";
    }

    if (!keywords.length) {
      bodyEl().innerHTML = `<div class="mt-empty"><i class="bi bi-chat-square-text"></i><p>이 기간에는 추출된 키워드가 없습니다.</p></div>`;
      return;
    }

    const max = keywords[0].count || 1;
    const list = document.createElement("div");
    list.className = "mt-kw-list";
    keywords.forEach((kw) => {
      const row = document.createElement("div");
      row.className = "mt-kw-row";
      row.innerHTML = `
        <div class="mt-kw-row-word" title="${escHtml(kw.word)}">${escHtml(kw.word)}</div>
        <div class="mt-kw-row-track"><div class="mt-kw-row-fill" style="width:0%"></div></div>
        <div class="mt-kw-row-count">${kw.count.toLocaleString()}</div>`;
      if (!yearMode) {
        row.addEventListener("click", () => showDaily(kw.word));
      } else {
        row.style.cursor = "default";
      }
      list.appendChild(row);
    });
    bodyEl().innerHTML = "";
    bodyEl().appendChild(list);

    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        list.querySelectorAll(".mt-kw-row-fill").forEach((el, i) => {
          el.style.width = Math.max(4, Math.round((keywords[i].count / max) * 100)) + "%";
        });
      })
    );
  }

  // 특정 키워드의 해당 월 일별 언급 횟수를 막대그래프로 렌더링
  async function showDaily(word) {
    if (!currentMonthKey || !bodyEl()) return;
    view = "daily";
    currentKeyword = word;
    if (backBtnEl()) backBtnEl().style.display = "";
    if (hintEl())
      hintEl().textContent = "막대에 마우스를 올리면 그 날 이 키워드를 언급한 사람을 볼 수 있어요.";
    bodyEl().innerHTML = `<div class="mt-empty"><i class="bi bi-hourglass-split"></i><p>불러오는 중...</p></div>`;

    const monthKey = currentMonthKey;
    let dayData = dailyCache[monthKey];
    if (!dayData) {
      try {
        const j = await postJSON(api.dailyUrl, {
          [api.idField]: idValue,
          month: monthKey,
        });
        dayData = j.data || {};
        dailyCache[monthKey] = dayData;
      } catch (e) {
        console.error("keyword-daily-stats 오류:", e);
        dayData = {};
      }
    }
    if (view !== "daily" || currentKeyword !== word || !bodyEl()) return;

    const total = daysInMonth(monthKey);
    const allCounts = [];
    for (let d = 1; d <= total; d++) {
      const dateKey = `${monthKey}-${String(d).padStart(2, "0")}`;
      const found = (dayData[dateKey] || []).find((x) => x.word === word);
      allCounts.push({ date: dateKey, day: d, count: found ? found.count : 0 });
    }
    const counts = allCounts.filter((c) => c.count > 0);
    const max = Math.max(1, ...counts.map((c) => c.count));

    const wrap = document.createElement("div");
    wrap.className = "mt-kw-daily-box";
    wrap.innerHTML = `<div class="mt-kw-daily-title"><span class="mt-kw-daily-swatch"></span>"${escHtml(word)}" 일별 언급 횟수 — ${escHtml(monthKey)}</div>`;

    if (!counts.length) {
      wrap.innerHTML += `<p class="mt-kw-daily-empty">이 달에는 "${escHtml(word)}"가 언급된 날짜가 없습니다.</p>`;
      bodyEl().innerHTML = "";
      bodyEl().appendChild(wrap);
      return;
    }

    const chartWrap = document.createElement("div");
    chartWrap.className = "mt-kw-daily-chart-wrap";
    const yAxis = document.createElement("div");
    yAxis.className = "mt-kw-daily-y";
    yAxis.innerHTML = `<span>${max.toLocaleString()}</span><span>${Math.round(max / 2).toLocaleString()}</span><span>0</span>`;
    const yAxisTitle = document.createElement("div");
    yAxisTitle.className = "mt-kw-daily-y-title";
    yAxisTitle.textContent = "언급 횟수";

    const scrollArea = document.createElement("div");
    scrollArea.className = "mt-kw-daily-scroll";
    const chart = document.createElement("div");
    chart.className = "mt-kw-daily-chart";
    const daysRow = document.createElement("div");
    daysRow.className = "mt-kw-daily-days";

    counts.forEach((c) => {
      const bar = document.createElement("div");
      bar.className = "mt-kw-daily-bar" + (c.count > 0 ? " has-count" : "");
      bar.title = `${c.date}: ${c.count}건`;
      const fill = document.createElement("div");
      fill.className = "mt-kw-daily-bar-fill";
      fill.style.height =
        c.count > 0 ? Math.max(8, Math.round((c.count / max) * 100)) + "%" : "1px";
      bar.appendChild(fill);

      if (c.count > 0) {
        bar.addEventListener("mouseenter", () => showMentioners(bar, c.date, word));
        bar.addEventListener("mouseleave", hideTooltip);
      }
      chart.appendChild(bar);

      const dayLbl = document.createElement("div");
      dayLbl.className = "mt-kw-daily-day";
      dayLbl.textContent = c.day;
      daysRow.appendChild(dayLbl);
    });

    scrollArea.appendChild(chart);
    scrollArea.appendChild(daysRow);
    chartWrap.appendChild(yAxis);
    chartWrap.appendChild(scrollArea);
    wrap.appendChild(yAxisTitle);
    wrap.appendChild(chartWrap);
    const xAxisTitle = document.createElement("div");
    xAxisTitle.className = "mt-kw-daily-x-title";
    xAxisTitle.textContent = "날짜(언급 있는 날만 표시)";
    wrap.appendChild(xAxisTitle);
    bodyEl().innerHTML = "";
    bodyEl().appendChild(wrap);
  }

  // 막대 hover 시 그 날짜에 해당 키워드를 언급한 사람 목록을 캐시 조회/조회 후 툴팁으로 표시
  async function showMentioners(anchorEl, date, word) {
    const cacheKey = `${date}|${word}`;
    if (mentionersCache[cacheKey]) {
      renderMentionersTooltip(anchorEl, mentionersCache[cacheKey]);
      return;
    }
    showTooltip(anchorEl, `<div class="mt-tooltip-row">불러오는 중...</div>`);
    try {
      const j = await postJSON(api.mentionersUrl, {
        [api.idField]: idValue,
        date,
        keyword: word,
      });
      const data = j.data || [];
      mentionersCache[cacheKey] = data;
      renderMentionersTooltip(anchorEl, data);
    } catch (e) {
      console.error("keyword-mentioners 오류:", e);
    }
  }

  // 언급자 목록 데이터를 툴팁 HTML로 그려서 표시
  function renderMentionersTooltip(anchorEl, data) {
    if (!data.length) {
      showTooltip(anchorEl, `<div class="mt-tooltip-row">이 날 언급한 사람이 없어요.</div>`);
      return;
    }
    const html = data
      .map((p) => {
        const name = p.name || p.person_id || p.participant_id || "";
        const avatarHtml = p.avatar_url
          ? `<img src="${escHtml(p.avatar_url)}" alt="">`
          : escHtml((name || "?").slice(0, 1));
        return `<div class="mt-tooltip-row">
          <span class="mt-tooltip-avatar">${avatarHtml}</span>
          <span>${escHtml(name)} · ${p.count}회</span>
        </div>`;
      })
      .join("");
    showTooltip(anchorEl, html);
  }

  // createTimeline의 notifyPeriod가 호출해주는 진입점 — mode는 'month'|'year'.
  function setPeriod(mode, key) {
    if (!idValue) return;
    if (mode === "year") {
      currentYear = key;
      currentMonthKey = null;
    } else {
      currentMonthKey = key;
      currentYear = null;
    }
    updateTitle(mode, key);
    renderList();
  }

  if (backBtnEl()) {
    backBtnEl().addEventListener("click", () => renderList());
  }

  return { init, setPeriod };
}

/* 모듈 상태 — DOM 접근이 필요 없는 것들만 여기서 바로 초기화하고, DOM 접근이 필요한
   초기화(계정 picker, 타임라인/키워드 패널 인스턴스 생성 등)는 전부 initMyTimePage()
   안에서 한다. */
let currentChatroomId = "";
let chatroomIdPromise = null;
let userIdPromise = null;
let mailKwPanel, msgKwPanel, mailTimeline, msgTimeline;
let mtMailView, mtMessengerView;
let mtMessengerLoaded = false;
let mtActiveChannel = "mail";

// My Time 제목 옆 전체 기간 뱃지 — 지금 보고 있는 채널의 타임라인이 갖고 있는 기간 텍스트로 채운다.
function updateSharedRangeBadge(text) {
  const el = document.getElementById("mtDataRangeLbl");
  if (el) el.textContent = text || "";
}

// 계정이 바뀔 때(사이드바에서 다른 메일 계정 선택) 새로고침 없이 다시 호출할 수 있는 이름 있는 함수다.
async function initMail(gmailId) {
  // /mail-summaries는 { type, data: { summaries: [...] } } 형태로 응답하므로,
  // 메신저 쪽(loadMsgSummaries)과 동일하게 summariesToMap으로 period 기준 맵으로 변환한다.
  async function fetchSummaries(type) {
    try {
      const j = await postJSON("/mail-summaries", { user_id: gmailId, type });
      return summariesToMap((j.data && j.data.summaries) || []);
    } catch (e) {
      console.error(`mail-summaries(${type}) 오류:`, e);
      return {};
    }
  }

  const [MONTH_DATA, YEAR_DATA] = await Promise.all([
    fetchSummaries("monthly"),
    fetchSummaries("yearly"),
  ]);
  // mailTimeline.setData()가 끝나자마자 가장 최근 달을 오른쪽 키워드 창에 자동으로 띄우므로(notifyPeriod), 그보다 먼저 키워드 데이터를 받아둬야 한다.
  await mailKwPanel.init(gmailId);
  mailTimeline.setData(
    MONTH_DATA,
    YEAR_DATA,
    "아직 생성된 요약이 없습니다. 데이터 분석하기를 먼저 실행해주세요."
  );
}

// "나" 커서 아이콘(pointerCursor/msgPointerCursor)에 내 아바타를 적용 — 채널과 무관하게 한 번만 불러온다.
async function initSelfAvatar(gmailId) {
  if (!gmailId) return;
  const applyAvatar = (url) => {
    if (!url) return;
    const cursorEl = document.getElementById("pointerCursor");
    const msgCursorEl = document.getElementById("msgPointerCursor");
    if (cursorEl) cursorEl.innerHTML = `<img src="${url}" alt="나">`;
    if (msgCursorEl) msgCursorEl.innerHTML = `<img src="${url}" alt="나">`;
  };
  try {
    const cache = await postJSON("/self-avatar", { user_id: gmailId });
    if (cache.url) {
      applyAvatar(cache.url);
      return;
    }
    const myName = sessionStorage.getItem("gw_user_name") || "나";
    const gen = await postJSON("/generate-self-avatar", {
      user_id: gmailId,
      name: myName,
    });
    if (gen.url) applyAvatar(gen.url);
  } catch (e) {
    console.error("내 아바타 로드 오류:", e);
  }
}

// 요약 배열을 기간(summary_period) 키의 맵으로 변환
function summariesToMap(summaries) {
  const map = {};
  (summaries || []).forEach((s) => {
    map[s.summary_period] = {
      summary: s.summarized_context,
      contacts: s.contacts || [],
      image_url: s.image_url || null,
    };
  });
  return map;
}

// 채팅방의 월별/연도별 요약을 조회해 기간별 맵으로 반환
async function fetchChatroomSummaries(chatroomId, unit) {
  const j = await postJSON("/chatroom-summaries", {
    chatroom_id: chatroomId,
    summarize_unit: unit,
  });
  return summariesToMap(j.data.summaries);
}

async function loadMtMessengerData() {
  const chatroomId = currentChatroomId || (await chatroomIdPromise) || "";
  if (!chatroomId) {
    await msgKwPanel.init("");
    return msgTimeline.setData({}, {}, "연결된 채팅방이 없습니다. 채팅방을 먼저 선택해주세요.");
  }
  try {
    const [monthData, yearData] = await Promise.all([
      fetchChatroomSummaries(chatroomId, "monthly"),
      fetchChatroomSummaries(chatroomId, "yearly"),
    ]);
    await msgKwPanel.init(chatroomId);
    return msgTimeline.setData(monthData, yearData, "아직 생성된 메신저 요약이 없습니다.");
  } catch (e) {
    console.error("chatroom-summaries 오류:", e);
    await msgKwPanel.init("");
    return msgTimeline.setData(
      {},
      {},
      "메신저 요약을 불러오지 못했습니다. 잠시 후 다시 시도해주세요."
    );
  }
}

// 메일/메신저 뷰 전환 — 해당 뷰만 보이게 하고 공유 기간 뱃지를 그 채널 타임라인 값으로 갱신
function setMtChannel(channel) {
  // 툴팁을 띄운 엘리먼트(막대그래프, 연락처 카드)가 데이터 교체로 DOM에서 통째로 사라지면 mouseleave가 발생하지 않아 hideTooltip()이 불릴 기회가 없으므로, 선택이 바뀌는 시점(=이 함수가 호출되는 시점)에 공용 툴팁을 무조건 한 번 닫아준다.
  hideTooltip();
  mtActiveChannel = channel;
  const isMail = channel === "mail";
  mtMailView.style.display = isMail ? "" : "none";
  mtMessengerView.style.display = isMail ? "none" : "";
  const active = isMail ? mailTimeline : msgTimeline;
  updateSharedRangeBadge(active.getRangeText());
}

// React가 #mt-mail-view 등 DOM을 마운트한 뒤(useEffect) 한 번만 호출한다.
// 이 페이지는 마운트당 한 번만 불리는 걸 전제하므로(다른 전환 페이지들과 동일), 언마운트 정리 로직은 없다.
export function initMyTimePage() {
  mtMailView = document.getElementById("mt-mail-view");
  mtMessengerView = document.getElementById("mt-messenger-view");

  /* 메일 뷰 */
  mailKwPanel = createKeywordPanel(
    { body: "mtKwBody", hint: "mtKwHint", backBtn: "mtKwBackBtn", title: "mtKwTitle" },
    {
      monthlyUrl: "/mail-keyword-monthly-stats",
      dailyUrl: "/mail-keyword-daily-stats",
      mentionersUrl: "/mail-keyword-mentioners",
      idField: "user_id",
    }
  );

  mailTimeline = createTimeline({
    track: "track",
    panel: "infoPanel",
    panelPeriod: "panelPeriod",
    panelCount: "panelCount",
    panelSummary: "panelSummary",
    panelContacts: "panelContacts",
    pointerTrack: "pointerTrack",
    pointerWindow: "pointerWindow",
    pointerCursor: "pointerCursor",
    pointerAxis: "pointerAxis",
    rangeLbl: "mtPointerRangeLbl",
    channel: "mail",
    onPeriod: (mode, key) => mailKwPanel.setPeriod(mode, key),
  });

  /* 메신저 뷰 */
  msgKwPanel = createKeywordPanel(
    { body: "msgKwBody", hint: "msgKwHint", backBtn: "msgKwBackBtn", title: "msgKwTitle" },
    {
      monthlyUrl: "/chatroom-keyword-monthly-stats",
      dailyUrl: "/chatroom-keyword-daily-stats",
      mentionersUrl: "/chatroom-keyword-mentioners",
      idField: "chatroom_id",
    }
  );

  msgTimeline = createTimeline({
    track: "msgTrack",
    panel: "msgInfoPanel",
    panelPeriod: "msgPanelPeriod",
    panelCount: null,
    panelSummary: "msgPanelSummary",
    panelContacts: "msgPanelContacts",
    pointerTrack: "msgPointerTrack",
    pointerWindow: "msgPointerWindow",
    pointerCursor: "msgPointerCursor",
    pointerAxis: "msgPointerAxis",
    rangeLbl: "msgPointerRangeLbl",
    channel: "messenger",
    onPeriod: (mode, key) => msgKwPanel.setPeriod(mode, key),
  });

  userIdPromise = initAccountPicker(
    document.getElementById("account-picker-mount"),
    (selectedMail) => {
      if (selectedMail) {
        store.setFilter("mail", selectedMail);
        refreshSidebarList();
      }
    }
  );

  /* 메신저 뷰용 채팅방 선택 토글 */
  chatroomIdPromise = initAccountPicker(
    document.getElementById("chatroom-picker-mount"),
    (chatroomId) => {
      currentChatroomId = chatroomId;
      mtMessengerLoaded = true;
      loadMtMessengerData();
    },
    { domain: "messenger", storageKey: "gw_chatroom_id" }
  );
  chatroomIdPromise.then((id) => {
    currentChatroomId = id || "";
  });

  userIdPromise.then((gmailId) => initSelfAvatar(gmailId || ""));

  /* 사이드바 선택 ↔ 화면 렌더링 파이프라인 */
  initGlobalFilter((filterState) => {
    if (filterState.mail) {
      setMtChannel("mail");
      initMail(filterState.mail);
    } else if (filterState.room) {
      setMtChannel("messenger");
      currentChatroomId = filterState.room;
      mtMessengerLoaded = true;
      loadMtMessengerData();
    }
  });
}
