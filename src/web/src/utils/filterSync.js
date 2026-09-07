// src/utils/filterSync.js
/**
사이드바(계정/채널 필터) 상태와 각 페이지를 동기화하는 모듈.
사이드바를 렌더링하고, 전역 스토어 변경 이벤트를 구독해 페이지에 필터 변경을 전달하며, 인덱싱 미완료 계정이 있으면 주기적으로 목록을 다시 불러온다.

Keeps the sidebar (account/channel filter) in sync with each page — renders the sidebar, listens for global store change events to notify pages of filter changes, and polls for accounts still being indexed.
 */
import { renderAppSidebar, refreshSidebarList } from "../components/appSidebar.js";
import { store } from "../store/globalStore.js";

let indexingPollTimer = null;

// 아직 인덱싱이 끝나지 않은 계정이 있으면 주기적으로 목록을 다시 불러와서 "(생성 중)" 배지가 실제 인덱싱 완료 시점에 맞춰 사라지게 한다.
// 전부 인덱싱 완료되면 폴링을 멈춘다.
function scheduleIndexingPoll() {
  if (indexingPollTimer) return;
  const { mails = [] } = store.getCollectedLists() || {};
  if (!mails.some((m) => !m.indexed)) return;
  indexingPollTimer = setInterval(async () => {
    await store.fetchCollectedLists();
    const { mails: refreshed = [] } = store.getCollectedLists() || {};
    if (!refreshed.some((m) => !m.indexed)) {
      clearInterval(indexingPollTimer);
      indexingPollTimer = null;
    }
  }, 8000);
}

export async function initGlobalFilter(onFilterChangeCallback) {
  // 1. 공통 사이드바 HTML 렌더링
  renderAppSidebar("app-sidebar");

  // 2. 스토어 상태 변경 감지 — refreshSidebarList()보다 먼저 등록해야 한다.
  // 리스너를 먼저 등록해두면 이 초기 이벤트도 절대 안 놓친다.
  window.addEventListener("gwStoreStateChanged", (e) => {
    refreshSidebarList();
    onFilterChangeCallback(e.detail, { isInitial: false });
  });

  // 3. 백엔드 DB에서 수집 목록 가져오기 후 사이드바 갱신
  await store.fetchCollectedLists();
  refreshSidebarList();
  scheduleIndexingPoll();

  // 4. 지금 사이드바가 실제로 선택하고 있는 상태를 페이지에 무조건 한 번 더 알려준다.
  onFilterChangeCallback(store.getFilterState(), { isInitial: false });
}
