/**
개발 모드에서만 콘솔에 출력하는 로거 래퍼. 프로덕션 빌드에서는 Terser가 이 호출들을 제거한다.

Console logger wrapper that only outputs in development; production builds strip these calls via
Terser.
 */

const isDev = process.env.NODE_ENV === 'development';

// 개발 모드에서만 대응하는 console 메서드를 그대로 호출하는 래퍼 모음
const logger = {
  log: (...args) => {
    if (isDev) {
      console.log(...args);
    }
  },
  warn: (...args) => {
    if (isDev) {
      console.warn(...args);
    }
  },
  error: (...args) => {
    if (isDev) {
      console.error(...args);
    }
  },
  info: (...args) => {
    if (isDev) {
      console.info(...args);
    }
  },
  debug: (...args) => {
    if (isDev) {
      console.debug(...args);
    }
  },
  group: (...args) => {
    if (isDev) {
      console.group(...args);
    }
  },
  groupEnd: () => {
    if (isDev) {
      console.groupEnd();
    }
  }
};

export default logger;
