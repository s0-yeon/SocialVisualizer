/**
지식그래프 시각화 페이지 엔진 — 계정/도메인 전환, d3 + graph-render.js 동적 로드, /graph-data 조회, SVG 렌더링을 담당한다.
순수 헬퍼(_loadScript)와 데이터 로드/렌더링 함수(loadGraphData, loadDomain)는 모듈 스코프에 두고, DOM에 직접 손을 대는 URL 파라미터 처리·이벤트 바인딩·최초 로드는 initGraphVizPage()로 묶어 React 마운트 후 한 번 호출한다.

Engine module for the knowledge-graph page — handles account/domain switching, dynamically loading d3 + graph-render.js, fetching /graph-data, and SVG rendering.
The pure helper (_loadScript) and the load/render functions (loadGraphData, loadDomain) live at module scope; the URL-param handling, event bindings, and initial load are wrapped into initGraphVizPage(), called once after the React component mounts.
 */
import { initAccountPicker } from "./accountPicker.js";

// My People/My Time/Recap이 공유하는 'gw_user_id'와는 별도의 저장키를 써서, 이 페이지에서 고른 계정이 다른 페이지의 계정 선택에 영향을 주지 않게 한다.
// URL에 gmail_id가 명시된 경우엔 그걸 그대로 우선한다.
var GRAPH_MAIL_STORAGE_KEY = "gw_graph_mail_user_id";

// user_id로 해당 계정(또는 카카오 대화방)의 그래프 데이터를 불러와 그린다.
// 계정/도메인 전환 시에도 페이지 새로고침 없이 이 함수만 다시 호출해 그 자리에서 다시 그린다.
var currentDomain = "mail";

// d3 + graph-render.js는 계정 목록 조회와 병렬로 미리 로드해두고, 렌더링 직전에만 대기한다.
// initGraphVizPage()에서 실제로 로드를 시작하고 이 변수에 할당한다(모듈 스코프에 미리 선언해둬야 loadGraphData()가 클로저로 참조할 수 있다).
var rendererReady;

// 외부 <script> 태그를 동적으로 로드하고 완료되면 resolve하는 헬퍼
function _loadScript(src) {
  return new Promise(function (resolve, reject) {
    var s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

// userId(+ currentDomain)로 그래프 데이터를 조회해 #graph SVG에 렌더링
function loadGraphData(userId) {
  var svg = document.getElementById("graph");
  if (!userId) {
    console.warn("[graph] user_id 없음 → 그래프 로드 생략");
    svg.innerHTML = "";
    return Promise.resolve();
  }
  return fetch(
    "/graph-data?user_id=" +
      encodeURIComponent(userId) +
      "&domain=" +
      encodeURIComponent(currentDomain)
  )
    .then(function (res) {
      return res.json();
    })
    .then(function (data) {
      if (!data || !Array.isArray(data.nodes)) {
        console.warn("[graph] 그래프 데이터 없음:", data && data.error);
        svg.innerHTML = "";
        return;
      }
      return rendererReady.then(function () {
        svg.innerHTML = "";
        renderGraph(svg, data);
      });
    })
    .catch(function (err) {
      console.error("[graph] 로드 실패:", err);
    });
}

// 메일/메신저 토글에 맞춰 계정 선택기를 그 도메인 목록으로 다시 초기화하고 그래프를 새로 불러온다.
// 메일과 카카오는 "마지막 선택"을 서로 다른 localStorage 키에 각자 기억한다.
// 메일/메신저 도메인 전환 — 토글 버튼 상태 갱신, 해당 도메인 계정 선택기 재초기화, 그래프 재조회
function loadDomain(domain) {
  currentDomain = domain;
  document.getElementById("domain-btn-mail").classList.toggle("active", domain === "mail");
  document
    .getElementById("domain-btn-mail")
    .setAttribute("aria-selected", String(domain === "mail"));
  document.getElementById("domain-btn-message").classList.toggle("active", domain === "messenger");
  document
    .getElementById("domain-btn-message")
    .setAttribute("aria-selected", String(domain === "messenger"));

  var storageKey = domain === "mail" ? GRAPH_MAIL_STORAGE_KEY : "gw_message_room_id";
  return initAccountPicker(document.getElementById("account-picker-mount"), loadGraphData, {
    domain,
    storageKey,
  }).then(function (effectiveUserId) {
    return loadGraphData(effectiveUserId);
  });
}

export function initGraphVizPage() {
  // 이름/gmail_id 처리
  const params = new URLSearchParams(window.location.search);
  const nameParam = params.get("name");
  const name = nameParam
    ? decodeURIComponent(nameParam)
    : sessionStorage.getItem("gw_user_name") || "-";
  if (nameParam) sessionStorage.setItem("gw_user_name", decodeURIComponent(nameParam));

  const gmailIdParam = params.get("gmail_id");
  if (gmailIdParam) localStorage.setItem("gw_user_id", decodeURIComponent(gmailIdParam));
  const flaskUrlParam = params.get("flask_url");
  if (flaskUrlParam) localStorage.setItem("gw_flask_url", decodeURIComponent(flaskUrlParam));

  if (gmailIdParam) {
    localStorage.setItem(GRAPH_MAIL_STORAGE_KEY, decodeURIComponent(gmailIdParam));
  }

  const profileNameEl = document.getElementById("google-profile-name");
  if (profileNameEl) profileNameEl.textContent = name;

  rendererReady = _loadScript("https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js").then(
    function () {
      return _loadScript("/graph-render.js");
    }
  );

  document.getElementById("domain-btn-mail").addEventListener("click", function () {
    loadDomain("mail");
  });
  document.getElementById("domain-btn-message").addEventListener("click", function () {
    loadDomain("messenger");
  });

  window.addEventListener("load", function () {
    loadDomain("mail");
  });
}
