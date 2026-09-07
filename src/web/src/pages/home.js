/**
홈 화면(index.html) 진입점 — HomeApp(React)을 마운트하고, URL 파라미터(name/gmail_id/ flask_url)를 세션·로컬 스토리지에 저장해 로그인 핸드오프를 처리한다.

Entry point for the home page (index.html) — mounts HomeApp (React) and persists URL params (name/gmail_id/flask_url) to session/local storage to complete the login handoff.
 */

// bootstrap JS, main.scss, security 등 전역 세팅은 그대로 재사용 (side-effect import).
import "../main-app.js";
import { mountHomeApp } from "../components/HomeApp.jsx";
import "../scss/pages/home.scss";

mountHomeApp("home-app-root");

/* URL 파라미터로 넘어온 사용자 이름/계정/백엔드 주소를 저장소에 반영 */
(function () {
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
  // Flask에서 직접 열릴 때 자동으로 ngrok URL 저장
  if (!window.location.origin.includes("script.google.com")) {
    localStorage.setItem("gw_flask_url", window.location.origin);
  }
  window.currentUserName = name;
  const pnEl = document.getElementById("google-profile-name");
  if (pnEl) pnEl.textContent = name;
})();
