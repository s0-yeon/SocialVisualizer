/**

 * Vite 빌드 설정 — production/*.html 8개를 각각 별도 진입점으로 빌드하는 멀티페이지 앱 구성, React 플러그인, 청크

 * 분리(vendor-core/d3/react), 개발 서버의 백엔드(80번 포트) API 프록시 목록을 정의한다.

 

 * Vite build config — sets up a multi-page app with 8 separate production/*.html entry points, the

 * React plugin, vendor chunk splitting, and the dev server's proxy list to the backend on

 * port 80.

 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: __dirname,
  base: "/",
  publicDir: "public",
  logLevel: "info",
  clearScreen: false,
  plugins: [react()],
  // 빌드 산출물 설정 — dist/ 출력, 소스맵은 프로덕션에서만 hidden(생성하되 배포물엔 참조 안 남김)
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    sourcemap: process.env.NODE_ENV === "production" ? "hidden" : true,
    target: "es2022",
    rollupOptions: {
      plugins: [
        // 빌드 후 번들 크기 분석 리포트 생성(dist/stats.html)
        visualizer({
          filename: "dist/stats.html",
          open: false,
          gzipSize: true,
          brotliSize: true,
          template: "treemap",
        }),
      ],
      output: {
        // 벤더 라이브러리를 그룹별 청크로 분리해 캐싱 효율을 높임
        manualChunks: {
          "vendor-core": ["bootstrap", "@popperjs/core"],
          "vendor-d3": ["d3"],
          "vendor-react": ["react", "react-dom"],
        },
        // 확장자별로 정적 자산을 images/fonts/assets 하위 폴더로 분류해 출력
        assetFileNames: (assetInfo) => {
          const originalName = assetInfo.names?.[0] ?? "";
          if (/\.(png|jpe?g|svg|gif|tiff|bmp|ico)$/i.test(originalName)) {
            return `images/[name]-[hash][extname]`;
          }
          if (/\.(woff2?|eot|ttf|otf)$/i.test(originalName)) {
            return `fonts/[name]-[hash][extname]`;
          }
          return `assets/[name]-[hash][extname]`;
        },
        chunkFileNames: "js/[name]-[hash].js",
        entryFileNames: "js/[name]-[hash].js",
      },
      // 프로덕션 페이지별 빌드 진입점 — 페이지 추가/삭제 시 여기도 같이 수정
      input: {
        home: "production/index.html",
        mytime: "production/mytime.html",
        mypeople: "production/mypeople.html",
        graphviz: "production/graphviz.html",
        recap: "production/recap.html",
        search: "production/search.html",
        imap_collect: "production/imap-collect.html",
        analysishub: "production/analysishub.html",
      },
    },
    minify: "terser",
    // 프로덕션 압축 설정 — console/debugger 제거, 데드코드 정리, safari10 호환 mangle, 주석 제거
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
        unsafe_comps: true,
        passes: 3,
        pure_getters: true,
        reduce_vars: true,
        collapse_vars: true,
        dead_code: true,
        unused: true,
      },
      mangle: {
        safari10: true,
      },
      format: {
        comments: false,
      },
    },
  },
  esbuild: {
    target: "es2022",
  },
  // 개발 서버 설정 — 기본 진입 페이지, 포트, 백엔드(Flask, 80번 포트) API 프록시
  server: {
    open: "/production/index.html",
    port: 3000,
    host: true,
    proxy: {
      "/graph-data": "http://127.0.0.1:80",
      "/graph-render.js": "http://127.0.0.1:80",
      "/run-query-async": "http://127.0.0.1:80",
      "/job-status": "http://127.0.0.1:80",
      "/high_affinity_person_stats": "http://127.0.0.1:80",
      "/mail-date-range": "http://127.0.0.1:80",
      "/mail-exchange-stats": "http://127.0.0.1:80",
      "/keyword-stats": "http://127.0.0.1:80",
      "/keyword-by-person-date": "http://127.0.0.1:80",
      "/mail-stats": "http://127.0.0.1:80",
      "/mail_sync_stats": "http://127.0.0.1:80",
      "/mail-summaries": "http://127.0.0.1:80",
      "/mail-person-emails": "http://127.0.0.1:80",
      "/mail-person-sent-stats": "http://127.0.0.1:80",
      "/mail-person-received-stats": "http://127.0.0.1:80",
      "/user_rating_stats": "http://127.0.0.1:80",
      "/person-descriptions": "http://127.0.0.1:80",
      "/contact-photos": "http://127.0.0.1:80",
      "/person-avatars": "http://127.0.0.1:80",
      "/self-avatar": "http://127.0.0.1:80",
      "/generate-self-avatar": "http://127.0.0.1:80",
      "/indexing-history": "http://127.0.0.1:80",
      "/indexing-stream": "http://127.0.0.1:80",

      // 백엔드에 라우트 추가할 때마다 여기도 같이 등록해야 함 — /intimacy,
      // /person-avatar-image 누락으로 개발 서버에서 아바타 이미지가 404 났던 적 있음
      "/intimacy": "http://127.0.0.1:80",
      "/person-avatar-image": "http://127.0.0.1:80",

      // 메신저 Recap 통계
      "/chatroom-people": "http://127.0.0.1:80",
      "/chatroom-keyword-stats": "http://127.0.0.1:80",
      "/chatroom-relationship-stats": "http://127.0.0.1:80",
      "/chatroom-monthly-message-stats": "http://127.0.0.1:80",
      "/chatroom-sync-stats": "http://127.0.0.1:80",
    },
    watch: {
      usePolling: false,
      interval: 100,
      ignored: ["**/node_modules/**", "**/dist/**"],
    },
    hmr: {
      overlay: false,
    },
  },
  // 사전 번들링 대상 명시 — 콜드 스타트 시 재번들 방지
  optimizeDeps: {
    include: ["bootstrap", "@popperjs/core", "d3", "react", "react-dom"],
    force: false,
  },
  css: {
    devSourcemap: process.env.NODE_ENV !== "production",
    preprocessorOptions: {
      scss: {
        // Dart Sass 마이그레이션 경고 숨김(legacy API/import 등), node_modules에서 파샬 탐색 허용
        silenceDeprecations: [
          "legacy-js-api",
          "import",
          "global-builtin",
          "color-functions",
        ],
        includePaths: ["node_modules"],
        sourceMap: process.env.NODE_ENV !== "production",
        sourceMapContents: process.env.NODE_ENV !== "production",
      },
    },
  },

  // 브라우저 번들에서 라이브러리가 참조하는 process.env를 정적으로 주입(process 객체가 없는 브라우저 환경 대응)
  define: {
    global: "globalThis",
    process: JSON.stringify({
      env: {
        NODE_ENV: "production",
      },
    }),
    "process.env": JSON.stringify({
      NODE_ENV: "production",
    }),
    "process.env.NODE_ENV": '"production"',
  },
});
