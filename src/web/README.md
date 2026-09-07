# web — Vite 프론트엔드

Social Visualizer의 웹 UI로, Vite 멀티페이지 앱(MPA)이며 `production/*.html` 각각이 별도 빌드 진입점이다.
실제 기능 페이지 8개는 전부 React 19 컴포넌트(`<PageName>App.jsx`)가 헤더·푸터까지 통째로 그리고, 그래프 시각화만 D3(+ 별도 렌더러 모듈)를 쓴다.
스타일은 Bootstrap 5 + SCSS. 빌드·실행 명령은 [`docs/EXECUTE.md`](../../docs/EXECUTE.md)를 참고. 여기서는 구조와 배선만 설명한다.

## 구성

### `production/*.html` — 페이지별 HTML 엔트리

`vite.config.js`의 빌드 입력에 등록된 8개 + 빌드 대상이 아닌 `imap-start.html`.

- `index.html` — Home
- `mytime.html` — My Time
- `mypeople.html` — My People
- `graphviz.html` — Knowledge Graph
- `recap.html` — Recap
- `search.html` — Search
- `imap-collect.html` — 소셜 데이터 분석(수집)
- `analysishub.html` — 4가지 기능 목록 허브
- `imap-start.html` — 빌드 대상 아님. 주소창으로 직접 들어온 사용자를 `/dashboard/`로 리다이렉트만 함

### `src/pages/*.js` — 각 HTML의 진입 스크립트

세 줄짜리 배선만 담당한다.

- 페이지 전용 SCSS import
- `main-app.js`(공용 초기화) import
- `mount<PageName>App(rootId)` 호출

### `src/main-app.js` — 8개 페이지가 공통으로 쓰는 전역 초기화 진입점

아래 순서로 로드한다.

- Bootstrap을 `window.bootstrap`에 노출
- 전역 스타일(`main.scss`)
- 공통 UI 초기화(`utils/init.js`)
- 리사이즈 디바운스 핸들러(`utils/smartresize.js`)
- 우측 상단 플로팅 검색 위젯

### `src/components/` — 페이지별 React 루트 + 공용 컴포넌트

- `HomeApp`
- `MyPeopleApp`
- `MyTimeApp`
- `RecapApp` — `recap/` 카드 6종 포함: `AffinityDonutCard`, `KeywordCloudCard`, `MailStatsCard`, `MonthlyMessageCard`, `RelationshipDonutCard`, `SyncStatsCard`
- `GraphVizApp`
- `SearchApp` — `search/SearchPanel` 포함
- `ImapCollectApp`
- `AnalysisHubApp`
- `Header` / `Footer` / `HeroContent` — 모든 페이지가 공유
- `appSidebar.js` / `floatingSearch.js` — React가 아닌 순수 JS(DOM 직접 조작) 공용 위젯

### `src/features/` — 페이지별 엔진/로직 모듈

DOM에 직접 손대는 초기화(`init<PageName>Page()`)와 순수 헬퍼가 함께 있다.

- `mypeopleEngine` — My People 페이지 엔진
- `mytimeEngine` — My Time 페이지 엔진
- `graphVizEngine` — 지식그래프 페이지 엔진
- `imapCollectEngine` — 소셜 데이터 수집 페이지 엔진
- `recapStats` — Recap 통계 카드 순수 헬퍼(DOM 직접 조작 없음)
- `graphragSearch` — GraphRAG 검색 순수 헬퍼(검색 페이지 + 플로팅 검색 위젯 공용)
- `accountPicker` — 계정·채팅방 선택 공용 로직

### `src/store/globalStore.js` — 전역 필터 싱글턴

선택된 메일 계정·채팅방 필터를 관리하는 전역 싱글턴. 변경 시 `gwStoreStateChanged` 이벤트로 사이드바·페이지를 동기화한다.

### `src/utils/` — 저수준 공용 유틸

- `apiBase`(백엔드 URL 결정)
- `dom`(jQuery 없는 select/class/event 헬퍼)
- `filterSync`(사이드바 ↔ 페이지 필터 동기화)
- `init`(날짜선택기·모달·탭 등 공통 UI 초기화)
- `logger`(dev 전용, 프로덕션에서 Terser가 제거)
- `smartresize`(디바운스 리사이즈)
- `useScaleToFit`(React 훅 — 창 크기가 바뀌어도 내부 요소 크기는 그대로 두고 고정 크기 캔버스 전체를 `transform:scale()`로 통째로 축소/확대해 비율을 항상 동일하게 유지)

### `src/scss/`, `src/main.scss` — 스타일

- 전역: `_variables`, `_color-schemes`, `_global-overrides`, `custom`, `font-optimization`
- `components/`: `_header`, `_footer`, `_sidebar`, `_floating-search`
- `pages/`: `analysishub`, `graphviz`, `home`, `imap-collect`, `mypeople`, `mytime`, `recap`, `search` (8개, 페이지별 1개씩)

### `public/` — 정적 자산

- `favicon.ico`
- `images/`
- `site.webmanifest`

빌드 시 그대로 복사된다.

### `vite.config.js`, `package.json`, `jsconfig.json` — 빌드·의존성·JS 설정

`manualChunks`로 벤더 라이브러리를 아래 3개 청크로 분리한다.

- `vendor-core`(bootstrap, `@popperjs/core`)
- `vendor-d3`(d3)
- `vendor-react`(react, react-dom)

빌드 후 `dist/stats.html`에 번들 분석 리포트도 생성한다.

## 빌드 & 서빙

- `vite.config.js`의 `build.rollupOptions.input`에 `production/*.html` 8개가 각각 빌드 진입점으로 등록돼 있다 (MPA).
- **개발**: `npm run dev` (포트 3000). API 요청은 `vite.config.js`의 `server.proxy` 목록을 통해 백엔드(`127.0.0.1:80`)로 프록시된다 — 백엔드에 새 라우트를 추가하면 이 목록에도 등록해야 개발 서버에서 404가 안 난다.
- **프로덕션**: 백엔드 [`app.py`](../app.py)의 `/dashboard/<path:path>` 라우트가 `dist/` 산출물을 그대로 서빙한다.
- API 기본 URL은 `utils/apiBase.js`의 `getApiBase()`가 결정한다 — `localStorage['gw_flask_url']`(백엔드 핸드오프 값) → 빌드 env → 현재 페이지 origin 순.
- 코드 검증은 `npm run lint`(ESLint 9 flat config, `eslint.config.js`) / `npm run build`(타입 체크는 없고 Vite 빌드 성공 여부로 검증)로 한다.

## 페이지 구조 패턴

> `src/pages/<name>.js` → `src/components/<Name>App.jsx` → `src/features/<name>Engine.js`

1. **`src/pages/<name>.js`** — 진입 스크립트. 페이지 전용 SCSS·`main-app.js` import 후 `mount<Name>App(rootId)` 호출.
2. **`src/components/<Name>App.jsx`** — React 컴포넌트. `mount<Name>App(rootId)`를 export하고, 마운트 직후 `useEffect`에서 엔진의 `init<Name>Page()`를 한 번 호출한다(엔진이 있는 페이지만).
3. **`src/features/<name>Engine.js`** — 기존(리액트 이전) 로직을 거의 그대로 포팅한 엔진 모듈. `getElementById`로 React가 그려놓은 DOM에 직접 연결해서 카드 정렬·상세 패널·슬라이더 같은 실제 동작을 담당.

> **구조(마크업)는 React, 동작은 엔진 모듈** — 이 둘로 역할이 나뉜다.

- 이 패턴을 따르는 페이지: My People, My Time, GraphViz, Imap-collect
- 엔진 모듈 없이 React 컴포넌트(+ 순수 헬퍼 모듈)만으로 구성된 페이지: Recap, Search

### 창 크기 반응형 — `useScaleToFit`

clamp()/cqw로 요소 하나하나를 따로 줄이는 대신, 요소를 고정 크기 캔버스에 넣고 그 캔버스 전체를 `transform:scale()`한다.

- **효과**: 내부 요소 간 비율·위치가 창 크기와 무관하게 항상 동일하게 유지됨
- **적용 예**: My People 상세 패널/패널 헤더/타임라인, My Time 페이지 헤더/본문

## 주의 — 페이지 파일명 ↔ 백엔드 API 이름

`/dashboard/`는 파일명을 하드코딩하지 않으므로 페이지 HTML 파일명은 대체로 자유롭게 바꿀 수 있다.
단, 같은 이름의 백엔드 API 엔드포인트가 있으면 예외다.
예를 들어 `imap-collect.html`은 `app.py`의 실제 엔드포인트(`POST /imap-collect`, `/imap-collect-status/<job_id>`)와 이름이 겹쳐서, 파일명을 바꾸면 메일 수집 기능이 깨질 수 있다.
페이지명을 바꿀 땐 `app.py`에 동명 라우트가 없는지 먼저 확인할 것.

## 관련

- 실행 방법: [`docs/EXECUTE.md`](../../docs/EXECUTE.md)
- 독립 그래프 렌더러: [`src/json/`](../json) (`graph-render.js`)
- 백엔드 API: [`src/app.py`](../app.py)

---

# web — Vite frontend

Social Visualizer's web UI: a Vite multi-page app (MPA) where each `production/*.html` is its own build entry point.
All 8 real feature pages are fully React 19 components (`<PageName>App.jsx`) — each one renders even the header/footer itself; D3 (plus a separate renderer module) is used only for graph visualization.
Styling is Bootstrap 5 + SCSS. See [`docs/EXECUTE.md`](../../docs/EXECUTE.md) for build/run commands; this file only covers layout and wiring.

## Layout

### `production/*.html` — per-page HTML entries

8 are registered as build inputs in `vite.config.js`, plus `imap-start.html` which is excluded from the build.

- `index.html` — Home
- `mytime.html` — My Time
- `mypeople.html` — My People
- `graphviz.html` — Knowledge Graph
- `recap.html` — Recap
- `search.html` — Search
- `imap-collect.html` — social-data collection
- `analysishub.html` — hub listing the 4 features
- `imap-start.html` — not a build entry. Redirects direct visitors to `/dashboard/`

### `src/pages/*.js` — entry script per HTML

Just three lines of wiring.

- Import the page's own SCSS
- Import `main-app.js` (shared init)
- Call `mount<PageName>App(rootId)`

### `src/main-app.js` — shared global-init entry used by all 8 pages

Loads, in order:

- Bootstrap, exposed on `window.bootstrap`
- Global styles (`main.scss`)
- Common UI init (`utils/init.js`)
- The debounced resize handler (`utils/smartresize.js`)
- The top-right floating search widget

### `src/components/` — per-page React roots + shared components

- `HomeApp`
- `MyPeopleApp`
- `MyTimeApp`
- `RecapApp` — includes 6 `recap/` card components: `AffinityDonutCard`, `KeywordCloudCard`, `MailStatsCard`, `MonthlyMessageCard`, `RelationshipDonutCard`, `SyncStatsCard`
- `GraphVizApp`
- `SearchApp` — includes `search/SearchPanel`
- `ImapCollectApp`
- `AnalysisHubApp`
- `Header` / `Footer` / `HeroContent` — shared by every page
- `appSidebar.js` / `floatingSearch.js` — plain-JS (direct DOM) shared widgets, not React

### `src/features/` — per-page engine/logic modules

A mix of DOM-touching init (`init<PageName>Page()`) and pure helpers.

- `mypeopleEngine` — My People page engine
- `mytimeEngine` — My Time page engine
- `graphVizEngine` — knowledge-graph page engine
- `imapCollectEngine` — social-data collection page engine
- `recapStats` — pure helpers for Recap's stat cards (no direct DOM access)
- `graphragSearch` — pure GraphRAG search helpers (shared by the search page and the floating search widget)
- `accountPicker` — shared account/chatroom picker logic

### `src/store/globalStore.js` — global filter singleton

Global singleton holding the selected mail-account / chatroom filter; emits `gwStoreStateChanged` to sync the sidebar and pages.

### `src/utils/` — low-level shared utils

- `apiBase` (backend URL resolution)
- `dom` (jQuery-free select/class/event helpers)
- `filterSync` (syncs the sidebar with each page's filter)
- `init` (common UI init: date pickers, modals, tabs, …)
- `logger` (dev-only, stripped by Terser in production)
- `smartresize` (debounced resize)
- `useScaleToFit` (React hook — re-measures a ref'd element's natural size against its wrap's available space and applies a uniform `transform:scale()`, keeping every internal ratio identical regardless of window size, instead of shrinking individual elements)

### `src/scss/`, `src/main.scss` — styles

- Globals: `_variables`, `_color-schemes`, `_global-overrides`, `custom`, `font-optimization`
- `components/`: `_header`, `_footer`, `_sidebar`, `_floating-search`
- `pages/`: `analysishub`, `graphviz`, `home`, `imap-collect`, `mypeople`, `mytime`, `recap`, `search` (8 total, one per page)

### `public/` — static assets

- `favicon.ico`
- `images/`
- `site.webmanifest`

Copied verbatim at build.

### `vite.config.js`, `package.json`, `jsconfig.json` — build / deps / JS config

`manualChunks` splits vendor libraries into 3 chunks.

- `vendor-core` (bootstrap, `@popperjs/core`)
- `vendor-d3` (d3)
- `vendor-react` (react, react-dom)

A bundle-analysis report is also generated at `dist/stats.html` after build.

## Build & serving

- `build.rollupOptions.input` in `vite.config.js` registers 8 `production/*.html` files as separate build entry points (MPA).
- **Dev**: `npm run dev` (port 3000). API calls are proxied to the backend (`127.0.0.1:80`) via `server.proxy` in `vite.config.js` — add each new backend route here too, or the dev server returns 404.
- **Production**: the backend's `/dashboard/<path:path>` route in [`app.py`](../app.py) serves the `dist/` output as-is.
- The API base URL is resolved by `getApiBase()` in `utils/apiBase.js` — `localStorage['gw_flask_url']` (backend handoff) → build-time env → current page origin.
- Verification: `npm run lint` (ESLint 9 flat config, `eslint.config.js`) / `npm run build` (no separate type-check step — a successful Vite build is the check).

## Page structure pattern

> `src/pages/<name>.js` → `src/components/<Name>App.jsx` → `src/features/<name>Engine.js`

1. **`src/pages/<name>.js`** — entry script. Imports the page's own SCSS and `main-app.js`, then calls `mount<Name>App(rootId)`.
2. **`src/components/<Name>App.jsx`** — React component. Exports `mount<Name>App(rootId)`, and calls the engine's `init<Name>Page()` once from a `useEffect` right after mount (only for pages that have an engine).
3. **`src/features/<name>Engine.js`** — an engine module largely ported from the original pre-React logic. Wires itself to the DOM React drew via `getElementById`, and owns the actual behavior — card sorting, the detail panel, sliders, and so on.

> **React draws the structure/markup; the engine module owns the behavior.**

- Pages following this pattern: My People, My Time, GraphViz, Imap-collect
- Pages with no engine module — built entirely from React components (plus pure-helper modules): Recap, Search

### Responsive sizing — `useScaleToFit`

Instead of shrinking individual elements via clamp()/cqw, content goes in a fixed-size canvas and the whole canvas gets `transform:scale()`'d.

- **Effect**: every internal ratio and position stays identical regardless of window size
- **Used in**: My People's detail panel/panel header/timeline, My Time's page header/body

## Caveat — page filename ↔ backend API name

`/dashboard/` doesn't hardcode filenames, so page HTML filenames can mostly be renamed freely.
The exception is when a backend API endpoint shares the name: `imap-collect.html` collides with real endpoints (`POST /imap-collect`, `/imap-collect-status/<job_id>`) in `app.py`, so renaming it can break mail collection.
Before renaming a page, check that `app.py` has no route of the same name.

## Related

- How to run: [`docs/EXECUTE.md`](../../docs/EXECUTE.md)
- Standalone graph renderer: [`src/json/`](../json) (`graph-render.js`)
- Backend API: [`src/app.py`](../app.py)
