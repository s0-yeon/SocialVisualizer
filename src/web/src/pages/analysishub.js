/**
"분석 결과 보기" 허브 페이지(analysishub.html) 진입점 — AnalysisHubApp(React)을 마운트한다.
이 페이지는 정적 바로가기 카드뿐이라 별도 features/*Engine.js 없이 AnalysisHubApp.jsx가 콘텐츠를 전부 담당한다.

Entry point for the "view results" hub page (analysishub.html) — mounts AnalysisHubApp (React).
Since this page is just static shortcut cards, AnalysisHubApp.jsx owns all the content with no separate features/*Engine.js needed.
 */
import "../scss/pages/analysishub.scss";

import "../main-app.js";
import { mountAnalysisHubApp } from "../components/AnalysisHubApp.jsx";

mountAnalysisHubApp("analysis-hub-app-root");
