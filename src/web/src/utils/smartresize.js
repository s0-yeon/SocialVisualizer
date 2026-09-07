/**
 jQuery 없이 구현한 디바운스 리사이즈 핸들러. window.smartResize로 노출되어 여러 곳에서 resize 콜백을 등록/해제할 수 있게 한다.
 
 jQuery-free debounced window-resize handler, exposed as window.smartResize so multiple callers can register/unregister resize callbacks.
 */

// 개발용 로거
import logger from "./logger.js";

// 지정한 대기시간(wait) 동안 호출이 더 없을 때만 func을 실행하는 디바운스 함수
function debounce(func, wait = 250, immediate = false) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      timeout = null;
      if (!immediate) {
        func(...args);
      }
    };
    const callNow = immediate && !timeout;
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
    if (callNow) {
      func(...args);
    }
  };
}

// 핸들러 등록/해제를 관리하는 리사이즈 매니저
const smartResize = {
  handlers: new Set(),

  // 리사이즈 핸들러 등록
  add(handler, wait = 250) {
    const debouncedHandler = debounce(handler, wait);
    this.handlers.add(debouncedHandler);
    window.addEventListener("resize", debouncedHandler);
    return debouncedHandler;
  },

  // 리사이즈 핸들러 해제
  remove(handler) {
    window.removeEventListener("resize", handler);
    this.handlers.delete(handler);
  },

  // 모든 핸들러 제거
  clear() {
    this.handlers.forEach((handler) => {
      window.removeEventListener("resize", handler);
    });
    this.handlers.clear();
  },
};

// jQuery 스타일 API처럼 쓸 수 있도록 window에 노출
if (!window.smartResize) {
  window.smartResize = smartResize;
}

// 직접 호출용 간단한 함수도 함께 제공
window.addSmartResize = (handler, wait) => smartResize.add(handler, wait);
window.removeSmartResize = (handler) => smartResize.remove(handler);

logger.log("Modern smart resize initialized (jQuery-free)");

export default smartResize;
