/**
"My People" 페이지(mypeople.html) 진입점 — MyPeopleApp(React)을 마운트한다. 카드 정렬, 상세 패널, 미니 지식그래프, 타임라인 슬라이더 로직은 전부 MyPeopleApp.jsx와 features/mypeopleEngine.js가 담당한다.

Entry point for the "My People" page (mypeople.html) — mounts MyPeopleApp (React). Card sorting, the detail panel, the mini knowledge graph, and the timeline slider are all handled by MyPeopleApp.jsx and features/mypeopleEngine.js.
 */
import "../scss/components/_sidebar.scss";
import "../scss/pages/mypeople.scss";

import "../main-app.js";
import { mountMyPeopleApp } from "../components/MyPeopleApp.jsx";

mountMyPeopleApp("mypeople-app-root");
