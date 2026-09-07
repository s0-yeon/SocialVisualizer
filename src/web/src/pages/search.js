/**
자연어 검색 페이지(search.html) 진입점 — SearchApp(React)을 마운트하고, URL 파라미터
(name/gmail_id/flask_url/q)를 세션·로컬 스토리지에 반영해 로그인 핸드오프와 초기 검색어 실행을 처리한다.

Entry point for the natural-language search page. Mounts SearchApp (React) and persists URL
params (name/gmail_id/flask_url/q) to session/local storage to complete the login handoff and
run the initial search query.
 */
import '../main-app.js';
import { mountSearchApp } from '../components/SearchApp.jsx';
import '../scss/pages/search.scss';

// URL 파라미터 처리
const params = new URLSearchParams(window.location.search);
const nameParam = params.get('name');
const name = nameParam
  ? decodeURIComponent(nameParam)
  : (sessionStorage.getItem('gw_user_name') || '-');
if (nameParam) sessionStorage.setItem('gw_user_name', decodeURIComponent(nameParam));

const gmailIdParam = params.get('gmail_id');
if (gmailIdParam) localStorage.setItem('gw_user_id', decodeURIComponent(gmailIdParam));
const flaskUrlParam = params.get('flask_url');
if (flaskUrlParam) localStorage.setItem('gw_flask_url', decodeURIComponent(flaskUrlParam));

const profileNameEl = document.getElementById('google-profile-name');
if (profileNameEl) profileNameEl.textContent = name;
window.currentUserName = name;

// 검색어 URL 파라미터 (메일 탭 기준 — 기존 동작 유지)
const urlQuery = params.get('q');
const initialMailQuery = urlQuery && urlQuery.trim() ? decodeURIComponent(urlQuery) : undefined;

mountSearchApp('search-app-root', { initialMailQuery });
