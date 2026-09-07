/**
실제 기능 페이지 8개가 공통으로 쓰는 전역 초기화를 모아둔 공용 진입점 — 각 페이지는 `import "../main-app.js"` 한 줄만으로 이 파일의 side-effect 초기화를 그대로 받는다. 
부트스트랩/팝퍼를 전역(window.bootstrap)에 노출하고, 전역 스타일(main.scss)과 날짜선택기·모달 등 공통 UI 초기화(utils/init.js), 리사이즈 디바운스 핸들러, 우측 상단 플로팅 검색 위젯을 순서대로 로드한다. 
헤더/푸터는 각 페이지의 `<PageName>App.jsx`가 React 컴포넌트로 직접 그리므로 이 파일은 관여하지 않는다.

Shared entry point for global initialization used by all 8 feature pages — each page pulls in this
file's side-effect init with a single `import "../main-app.js"`. It exposes bootstrap/popper on
window.bootstrap, and loads global styles (main.scss), common UI init such as date pickers/modals
(utils/init.js), the debounced resize handler, and the top-right floating search widget in that
order. Header/footer are rendered directly by each page's `<PageName>App.jsx` React component, so
this file has no involvement there.
 */

import * as bootstrap from "bootstrap";
window.bootstrap = bootstrap;
globalThis.bootstrap = bootstrap;

import "./main.scss";

import "./utils/smartresize.js";
import "./utils/init.js";

// 우측 상단 떠 있는 검색 버튼 — side-effect import라 main-app.js를 쓰는 모든 페이지에
// 자동으로 뜬다(main-app.js를 쓰지 않는 페이지는 애초에 이 모듈이 로드되지 않는다).
import "./components/floatingSearch.js";
