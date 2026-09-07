/**
jQuery 없이 쓰는 DOM 조작 유틸 모음(select/class/style/이벤트 등). window/global에도 노출되며, 코드베이스 전반에서 실제로 쓰이는
select, selectAll, on, find, closest, hasClass, addClass, removeClass만 남겨뒀다.

jQuery-free DOM utility collection (selection/class/event helpers), exposed on window/global; 
trimmed down to only the methods actually called anywhere in the codebase today: select, selectAll, on, find, closest, hasClass, addClass, removeClass.
 */

const DOM = {
  // 요소 선택
  select: (selector) => document.querySelector(selector),
  selectAll: (selector) => [...document.querySelectorAll(selector)],

  // 이벤트 바인딩
  on: (element, event, handler) => element.addEventListener(event, handler),

  // DOM 탐색
  find: (element, selector) => element.querySelector(selector),
  closest: (element, selector) => element.closest(selector),

  // 클래스 조작
  hasClass: (element, className) => element.classList.contains(className),
  addClass: (element, className) => element.classList.add(className),
  removeClass: (element, className) => element.classList.remove(className),
};

// 전역에도 노출 (레거시 코드/콘솔 디버깅용)
window.DOM = DOM;
globalThis.DOM = DOM;

// Export for module usage
export default DOM;
