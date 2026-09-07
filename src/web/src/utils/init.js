/**
 jQuery를 걷어낸 공통 UI 초기화 모듈 — 날짜 선택기, 패널 접기/펼치기, 프로그레스바, 폼 검증, 탭/아코디언, 모달, 드래그앤드롭, 검색 필터, 단축키, 헤더 스크롤 그림자 등을 DOMContentLoaded 시점에 한 번에 초기화한다.
 
 jQuery-free shared UI initializer — sets up date pickers, panel collapse, progress bars, form validation, tabs/accordions, modals, drag-and-drop, search filtering, keyboard shortcuts, and the header scroll shadow, all on DOMContentLoaded.
 */

// 공통 DOM 유틸리티
import DOM from "./dom.js";

// 개발용 로거
import logger from "./logger.js";

// DataTables 초기화는 modules/tables.js에서 담당한다(jQuery 없이 DataTables 2.x 네이티브 API 사용).

// 날짜 선택기(.datepicker 등)를 TempusDominus로 초기화한다.
async function initializeDatePickers() {
  // TempusDominus 로드 여부 확인
  const TempusDominus = window.TempusDominus;
  if (typeof TempusDominus === "undefined") {
    return;
  }

  // 기본 날짜 선택기(.datepicker, [data-datepicker]) 초기화
  const datePickerElements = DOM.selectAll(".datepicker, [data-datepicker]");
  datePickerElements.forEach((element) => {
    try {
      new TempusDominus(element, {
        display: {
          components: {
            clock: false,
            seconds: false,
          },
        },
        localization: {
          format: "MM/dd/yyyy",
        },
      });
    } catch (error) {
      logger.error("Failed to initialize date picker:", error);
    }
  });

  // data-td-target 속성이 붙은 날짜 선택기 초기화
  const tdDatePickers = DOM.selectAll('[data-td-target-input="nearest"]');
  tdDatePickers.forEach((element) => {
    // 이미 초기화된 경우 건너뜀
    if (element._tempusDominus) return;

    try {
      const picker = new TempusDominus(element, {
        display: {
          components: {
            clock: false,
            seconds: false,
          },
          buttons: {
            today: true,
            clear: true,
            close: true,
          },
        },
        localization: {
          format: "MM/dd/yyyy",
        },
      });
      element._tempusDominus = picker;
    } catch (error) {
      logger.error("Failed to initialize Tempus Dominus date picker:", error);
    }
  });
}

// 패널 접기/펼치기, 닫기 버튼을 Bootstrap 5 Collapse API로 초기화한다.
function initializePanelToolbox() {
  // 접기/펼치기 — Bootstrap Collapse API 사용
  DOM.selectAll(".collapse-link").forEach((link, index) => {
    const panel = DOM.closest(link, ".x_panel");
    const content = DOM.find(panel, ".x_content");

    if (!panel || !content) {
      return;
    }

    // Bootstrap Collapse에 필요한 고유 id가 없으면 부여
    if (!content.id) {
      content.id = `panel-content-${index}`;
    }

    // collapse 클래스가 없으면 추가
    if (!DOM.hasClass(content, "collapse")) {
      DOM.addClass(content, "collapse");
      DOM.addClass(content, "show"); // 처음엔 펼친 상태로 시작
    }

    // 토글에 필요한 속성 설정
    link.setAttribute("data-bs-toggle", "collapse");
    link.setAttribute("data-bs-target", `#${content.id}`);
    link.setAttribute("aria-expanded", "true");
    link.setAttribute("aria-controls", content.id);

    // Bootstrap collapse 이벤트에 맞춰 아이콘 회전 처리
    content.addEventListener("hide.bs.collapse", () => {
      const icon = DOM.find(link, "i");
      if (icon) {
        DOM.removeClass(icon, "fa-chevron-up");
        DOM.addClass(icon, "fa-chevron-down");
      }
    });

    content.addEventListener("show.bs.collapse", () => {
      const icon = DOM.find(link, "i");
      if (icon) {
        DOM.removeClass(icon, "fa-chevron-down");
        DOM.addClass(icon, "fa-chevron-up");
      }
    });
  });

  // 패널 닫기 — CSS 트랜지션 사용
  DOM.selectAll(".close-link").forEach((link) => {
    DOM.on(link, "click", function (event) {
      event.preventDefault();

      const panel = DOM.closest(link, ".x_panel");
      if (panel) {
        // 서서히 사라지게 한 뒤 패널 제거
        panel.style.transition = "opacity 0.3s ease";
        panel.style.opacity = "0";
        setTimeout(() => {
          panel.remove();
        }, 300);
      }
    });
  });
}

// data-transitiongoal 속성이 있는 프로그레스바를 채워지는 애니메이션으로 표시한다.
function initializeProgressBars() {
  DOM.selectAll(".progress-bar[data-transitiongoal]").forEach((bar) => {
    const goal = bar.getAttribute("data-transitiongoal");
    if (goal) {
      // 0%에서 시작해 목표치까지 애니메이션
      bar.style.width = "0%";
      bar.style.transition = "width 1.5s ease-in-out";

      // 트랜지션이 확실히 걸리도록 setTimeout으로 지연
      setTimeout(() => {
        bar.style.width = goal + "%";
      }, 100);
    }
  });

  // 일반 프로그레스바는 페이지 로드시 애니메이션(자체 스타일을 쓰는 .sales-progress 내부는 제외)
  DOM.selectAll(".progress-bar:not([data-transitiongoal])").forEach((bar) => {
    // .sales-progress 위젯 안의 프로그레스바는 인라인 width를 그대로 유지
    if (bar.closest(".sales-progress")) {
      return;
    }

    const currentWidth = bar.style.width;
    if (currentWidth) {
      bar.style.width = "0%";
      bar.style.transition = "width 1.2s ease-out";
      setTimeout(() => {
        bar.style.width = currentWidth;
      }, 200);
    }
  });
}

// HTML5 검증 API로 폼 유효성 검사를 초기화한다.
function initializeFormValidation() {
  DOM.selectAll("form[data-validate], .needs-validation").forEach((form) => {
    DOM.on(form, "submit", function (event) {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();

        // 유효하지 않은 필드에 시각적 표시 추가
        DOM.selectAll(":invalid", form).forEach((field) => {
          DOM.addClass(field, "is-invalid");

          // 지정된 에러 메시지가 있으면 표시
          const errorMsg = field.getAttribute("data-error-message");
          if (errorMsg) {
            let errorDiv = DOM.find(field.parentNode, ".invalid-feedback");
            if (!errorDiv) {
              errorDiv = document.createElement("div");
              errorDiv.className = "invalid-feedback";
              field.parentNode.appendChild(errorDiv);
            }
            errorDiv.textContent = errorMsg;
          }
        });
      }

      DOM.addClass(form, "was-validated");
    });

    // 필드가 유효해지면 에러 스타일 제거
    DOM.selectAll("input, select, textarea", form).forEach((field) => {
      DOM.on(field, "input", function () {
        if (field.checkValidity()) {
          DOM.removeClass(field, "is-invalid");
          DOM.addClass(field, "is-valid");
        }
      });
    });
  });
}

// 탭/아코디언을 초기화한다. Bootstrap 5 기본 탭은 데이터 속성만으로 자동 동작하며, .custom-tabs는 아래에서 별도로 처리한다.
function initializeTabsAndAccordions() {
  DOM.selectAll(".custom-tabs").forEach((tabContainer) => {
    const tabButtons = DOM.selectAll(".tab-button", tabContainer);
    const tabPanes = DOM.selectAll(".tab-pane", tabContainer);

    tabButtons.forEach((button) => {
      DOM.on(button, "click", function () {
        const targetId = this.getAttribute("data-target");
        const targetPane = DOM.select(targetId);

        if (targetPane) {
          // 모든 탭 패널 숨김
          tabPanes.forEach((pane) => {
            DOM.removeClass(pane, "active");
            pane.style.display = "none";
          });

          // 모든 버튼에서 active 클래스 제거
          tabButtons.forEach((btn) => DOM.removeClass(btn, "active"));

          // 대상 패널을 보이고 버튼 활성화
          DOM.addClass(targetPane, "active");
          targetPane.style.display = "block";
          DOM.addClass(this, "active");
        }
      });
    });
  });
}

// Bootstrap 5 Modal API로 모달을 초기화하고, 열릴 때 첫 입력 필드에 자동 포커스한다.
function initializeModals() {
  DOM.selectAll(".modal").forEach((modalElement) => {
    if (typeof bootstrap !== "undefined" && bootstrap.Modal) {
      const modal = new bootstrap.Modal(modalElement);

      // 외부에서 접근할 수 있도록 모달 인스턴스 저장
      modalElement.modalInstance = modal;

      modalElement.addEventListener("shown.bs.modal", function () {
        // 모달의 첫 입력 필드에 자동 포커스
        const firstInput = DOM.select("input, textarea, select", this);
        if (firstInput) {
          firstInput.focus();
        }
      });
    }
  });
}

// 네이티브 HTML5 드래그앤드롭으로 정렬 가능한 목록(.sortable)을 초기화한다.
function initializeDragAndDrop() {
  DOM.selectAll(".sortable, [data-sortable]").forEach((container) => {
    const items = DOM.selectAll(".sortable-item, [data-sortable-item]", container);

    items.forEach((item) => {
      item.draggable = true;

      DOM.on(item, "dragstart", function (e) {
        e.dataTransfer.setData("text/plain", "");
        DOM.addClass(this, "dragging");
      });

      DOM.on(item, "dragend", function () {
        DOM.removeClass(this, "dragging");
      });
    });

    DOM.on(container, "dragover", function (e) {
      e.preventDefault();
      const dragging = DOM.select(".dragging", this);
      const siblings = [...DOM.selectAll(".sortable-item:not(.dragging)", this)];

      const nextSibling = siblings.find((sibling) => {
        return e.clientY <= sibling.getBoundingClientRect().top + sibling.offsetHeight / 2;
      });

      this.insertBefore(dragging, nextSibling);
    });
  });
}

// 검색어 입력에 따라 대상 요소를 필터링하고 일치 개수를 표시한다.
function initializeSearchAndFilter() {
  DOM.selectAll(".search-input, [data-search]").forEach((searchInput) => {
    const targetSelector = searchInput.getAttribute("data-target") || ".searchable-item";
    const targetElements = DOM.selectAll(targetSelector);

    DOM.on(searchInput, "input", function () {
      const query = this.value.toLowerCase().trim();

      targetElements.forEach((element) => {
        const text = element.textContent.toLowerCase();
        const matches = text.includes(query);

        element.style.display = matches ? "" : "none";

        // 일치 항목에 강조 클래스 추가/제거
        if (matches && query) {
          DOM.addClass(element, "search-match");
        } else {
          DOM.removeClass(element, "search-match");
        }
      });

      // 보이는 항목 개수 표시
      const visibleCount = targetElements.filter((el) => el.style.display !== "none").length;
      const countElement = DOM.select(".search-count");
      if (countElement) {
        countElement.textContent = `${visibleCount} items found`;
      }
    });
  });
}

// Ctrl+/ 검색 포커스, Escape 모달 닫기/검색 초기화 등 키보드 단축키를 등록한다.
function initializeKeyboardShortcuts() {
  const shortcuts = {
    "Ctrl+/": () => DOM.select(".search-input")?.focus(),
    Escape: () => {
      // 열린 모달 닫기
      DOM.selectAll(".modal.show").forEach((modal) => {
        if (modal.modalInstance) {
          modal.modalInstance.hide();
        }
      });

      // 검색어 초기화
      DOM.selectAll(".search-input").forEach((input) => {
        input.value = "";
        input.dispatchEvent(new Event("input"));
      });
    },
  };

  document.addEventListener("keydown", function (e) {
    const key =
      (e.ctrlKey ? "Ctrl+" : "") +
      (e.altKey ? "Alt+" : "") +
      (e.shiftKey ? "Shift+" : "") +
      (e.key === " " ? "Space" : e.key);

    if (shortcuts[key]) {
      e.preventDefault();
      shortcuts[key]();
    }
  });
}

/**
헤더 스크롤 그림자 — 페이지 맨 위에서는 그림자가 안 보이다가 스크롤하면 자연스럽게 나타나도록 함 (_header.scss의 .top_nav.gw-header-scrolled 참고). 모든 페이지가 결국 같은 React Header.jsx를 마운트해 동일한 .top_nav 요소를 쓰므로, scroll 이벤트마다 lazy하게 querySelector로 찾아서 여기 한 곳에서만 처리하면 됨.
 */
function initializeHeaderScrollShadow() {
  const SCROLL_THRESHOLD = 4;
  const getScrollTop = () =>
    window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  const onScroll = () => {
    const header = document.querySelector(".top_nav");
    if (!header) return;
    header.classList.toggle("gw-header-scrolled", getScrollTop() > SCROLL_THRESHOLD);
  };
  window.addEventListener("scroll", onScroll, { passive: true, capture: true });
  document.addEventListener("scroll", onScroll, {
    passive: true,
    capture: true,
  });
  onScroll(); // 새로고침 시 이미 스크롤된 채로 들어오는 경우 대비, 최초 1회 즉시 실행
}

// 위 초기화 함수들을 모아서 순서대로 실행하는 진입점.
async function initializeModernComponents() {
  try {
    await initializeDatePickers();
    initializePanelToolbox();
    initializeProgressBars();
    initializeFormValidation();
    initializeTabsAndAccordions();
    initializeModals();
    initializeDragAndDrop();
    initializeSearchAndFilter();
    initializeKeyboardShortcuts();
    initializeHeaderScrollShadow();

    // DataTables는 modules/tables.js에서 별도로 초기화한다.
  } catch (error) {
    logger.error("Failed to initialize modern components:", error);
  }
}

// 모듈 로딩 완료를 알리는 작은 배지를 우측 상단에 잠깐 띄운다.
function showLoadingStatus() {
  const statusElement = document.createElement("div");
  statusElement.id = "module-loading-status";
  statusElement.style.cssText = `
    position: fixed;
    top: 10px;
    right: 10px;
    background: #8a8a8a;
    color: white;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 12px;
    z-index: 9999;
    transition: opacity 0.3s;
  `;
  statusElement.textContent = "✅ Modern components loaded";
  document.body.appendChild(statusElement);

  // 3초 후 자동으로 사라짐
  setTimeout(() => {
    statusElement.style.opacity = "0";
    setTimeout(() => statusElement.remove(), 300);
  }, 3000);
}

// DOM 준비되면 초기화 실행
if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", async () => {
    await initializeModernComponents();
  });
}
