/**
"Recap" 페이지(recap.html) 진입점 — RecapApp(React)을 마운트한다. 사이드바 선택 동기화, 통계 API 호출, 카드 렌더링은 전부 RecapApp.jsx와 그 하위 컴포넌트가 담당한다.

Entry point for the "Recap" page (recap.html) — mounts RecapApp (React). Sidebar selection sync, stat API calls, and card rendering are all handled by RecapApp.jsx and its child components.
 */
import "../scss/components/_sidebar.scss";
import "../scss/pages/recap.scss";

import "../main-app.js";
import { mountRecapApp } from "../components/RecapApp.jsx";

mountRecapApp("recap-app-root");
