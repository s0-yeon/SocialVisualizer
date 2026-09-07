/**
지식그래프 시각화 페이지(graphviz.html) 진입점 — GraphVizApp(React)을 마운트한다. 계정/도메인 전환, 그래프 데이터 조회·렌더링 로직은 전부 GraphVizApp.jsx와 features/graphVizEngine.js가 담당한다.

Entry point for the knowledge-graph page (graphviz.html) — mounts GraphVizApp (React). Account/domain switching and graph data fetching/rendering are all handled by GraphVizApp.jsx and features/graphVizEngine.js.
 */
import "../scss/pages/graphviz.scss";

import "../main-app.js";
import { mountGraphVizApp } from "../components/GraphVizApp.jsx";

mountGraphVizApp("graph-viz-app-root");
