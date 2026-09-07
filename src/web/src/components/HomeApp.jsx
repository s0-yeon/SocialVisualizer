import { createRoot } from "react-dom/client";
import Header from "./Header.jsx";
import Footer from "./Footer.jsx";
import HeroContent from "./HeroContent.jsx";

/**
홈 화면(index.html) 전체를 감싸는 최상위 React 컴포넌트 — Header/HeroContent/Footer 세 영역을 한 번에 그려서 마운트한다.

Top-level React component wrapping the entire home page (index.html) — renders Header, HeroContent, and Footer together in one mount.
 */
function HomeApp() {
  return (
    <>
      <Header activePage="home" />
      <main className="right_col" role="main" aria-label="Main content">
        <HeroContent />
      </main>
      <Footer />
    </>
  );
}

// #containerId 엘리먼트에 HomeApp을 React 루트로 마운트
export function mountHomeApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<HomeApp />);
}
