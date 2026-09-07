/**
npm run format/format:check가 설정 파일 없이 Prettier 기본값으로만 돌고 있던 걸 명시적으로
고정. 코드베이스에 이미 섞여있는 큰따옴표 위주 스타일에 맞췄다.

Pins the style npm run format/format:check were previously running against implicitly (no
config file, just Prettier's own defaults). Matches the double-quote-leaning style already
prevalent across the codebase.
 */

/** @type {import("prettier").Config} */
export default {
  semi: true,
  singleQuote: false,
  trailingComma: "es5",
  printWidth: 100,
  tabWidth: 2,
};
