/**
"My Time" 페이지(mytime.html) 진입점 — MyTimeApp(React)을 마운트한다. 사이드바 선택 동기화, 타임라인·키워드 패널 로직은 전부 MyTimeApp.jsx와 features/mytimeEngine.js가 담당한다.

Entry point for the "My Time" page (mytime.html) — mounts MyTimeApp (React). Sidebar selection sync and all timeline/keyword-panel logic are handled by MyTimeApp.jsx and features/mytimeEngine.js.
 */
import "../scss/components/_sidebar.scss";
import "../scss/pages/mytime.scss";

import "../main-app.js";
import { mountMyTimeApp } from "../components/MyTimeApp.jsx";

mountMyTimeApp("mytime-app-root");
