/**
package.json에 eslint 관련 의존성만 있고 정작 이 설정 파일이 없어서 npm run lint가 실행 전부터
에러 나던 상태를 고친 최소 구성. TypeScript 전용 lint 플러그인은 설치돼 있지 않아서 문법 파싱만
지원하고, React는 JSX에서만 값이 쓰이는 import/함수를 no-unused-vars가 오탐하는 문제 때문에
eslint-plugin-react를 최소 설정(jsx-uses-vars, jsx-uses-react)으로만 붙였다.

Minimum ESLint 9 flat config filling in what was missing — eslint deps existed in package.json
but with no config file `npm run lint` failed before it could even start. No TypeScript plugin is
installed, so that part is parsing-only. eslint-plugin-react is included with just enough rules
(jsx-uses-vars, jsx-uses-react) so no-unused-vars stops false-flagging imports/components that are
only referenced inside JSX.
 */
import js from "@eslint/js";
import react from "eslint-plugin-react";
import prettierConfig from "eslint-config-prettier";

const browserGlobals = {
  window: "readonly",
  document: "readonly",
  navigator: "readonly",
  location: "readonly",
  localStorage: "readonly",
  sessionStorage: "readonly",
  fetch: "readonly",
  console: "readonly",
  alert: "readonly",
  setTimeout: "readonly",
  clearTimeout: "readonly",
  setInterval: "readonly",
  clearInterval: "readonly",
  URLSearchParams: "readonly",
  FormData: "readonly",
  Image: "readonly",
  Event: "readonly",
  CustomEvent: "readonly",
  EventSource: "readonly",
  TextDecoder: "readonly",
  FileReader: "readonly",
  requestAnimationFrame: "readonly",
  cancelAnimationFrame: "readonly",
  ResizeObserver: "readonly",
  DOMPurify: "readonly",
  bootstrap: "readonly", // main-app.js가 window.bootstrap으로 노출
  process: "readonly", // vite.config.js가 define으로 정적 주입(process.env.NODE_ENV)
  performance: "readonly",
  renderGraph: "readonly", // graphVizEngine.js/mypeopleEngine.js가 동적 로드하는 /graph-render.js가 전역으로 노출
};

export default [
  { ignores: ["dist/**", "node_modules/**", "**/_to_delete/**"] },
  js.configs.recommended,
  {
    files: ["src/**/*.{js,jsx}"],
    plugins: { react },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: browserGlobals,
    },
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "no-empty": ["error", { allowEmptyCatch: true }], // 의도적인 무시용 빈 catch 블록 허용
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "error",
    },
  },
  prettierConfig,
];
