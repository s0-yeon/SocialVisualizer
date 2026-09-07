/**
공통 React 푸터 — 브랜드명을 표시하는 최소 컴포넌트로, React로 전환된 페이지들이 함께 쓴다.
스타일은 scss/components/_footer.scss의 gw-footer 클래스가 담당하며, 화면 폭 전체에 걸친 조용한 placeholder 영역으로 렌더링된다.

Shared React footer — a minimal component that displays the brand name, reused by every React-converted page.
Styling comes from the gw-footer class in scss/components/_footer.scss, rendering as a quiet, full-width placeholder bar.
 */
export default function Footer({ brand = "Social Visualizer" }) {
  return (
    <footer id="app-footer" className="gw-footer">
      <span className="gw-footer-brand">{brand}</span>
    </footer>
  );
}
