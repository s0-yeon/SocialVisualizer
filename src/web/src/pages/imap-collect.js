/**
"소셜 데이터 수집" 페이지(imap-collect.html) 진입점 — ImapCollectApp(React)을 마운트한다. IMAP 수집, 카카오톡 업로드, SSE 진행상황 추적 로직은 전부 ImapCollectApp.jsx와 features/imapCollectEngine.js가 담당한다.

Entry point for the social-data collection page (imap-collect.html) — mounts ImapCollectApp(React). IMAP collection, KakaoTalk upload, and SSE progress-tracking logic are all handled by ImapCollectApp.jsx and features/imapCollectEngine.js.
 */
import "../scss/pages/imap-collect.scss";

import "../main-app.js";
import { mountImapCollectApp } from "../components/ImapCollectApp.jsx";

mountImapCollectApp("imap-collect-app-root");
