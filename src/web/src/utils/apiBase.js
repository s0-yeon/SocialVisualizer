/**
백엔드 API의 기본 URL을 결정하는 유틸. localStorage에 저장된 flask_url(백엔드 핸드오프 값) → 빌드 타임 env 변수 → 현재 페이지 origin 순으로 우선순위를 적용한다.

Resolves the backend API base URL, preferring a stored flask_url handoff value, then a build-time env var, then falling back to the current page origin.
 */

// 저장된 flask_url(ngrok 등 백엔드 주소 핸드오프) > 빌드 시 env > 현재 페이지 origin
export function getApiBase() {
  return (
    localStorage.getItem("gw_flask_url") ||
    import.meta.env.VITE_API_BASE_URL ||
    window.location.origin
  );
}
