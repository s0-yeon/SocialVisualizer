import { useEffect } from "react";

/**
 * 창 크기가 바뀌어도 ref로 넘긴 요소 내부의 크기 값(카드 크기, 간격, 폰트 등)은 전혀
 * 건드리지 않고, 매번 다시 측정해서 그 비율만큼 transform:scale()로 통째로 줄이거나
 * 키운다 — 홈 화면 히어로/소셜 데이터 분석 페이지에서 쓰던 것과 같은 방식이다.
 *
 * ref로 넘긴 요소의 직계 부모(parentElement)가 "사용 가능한 공간" 역할을 하는
 * 스케일 wrap이어야 한다(예: display:flex; overflow:hidden;인 컨테이너). wrap의
 * clientWidth/clientHeight가 가용 공간, 요소 자신의 offsetWidth/offsetHeight가
 * (스케일이 적용되지 않은) 원본 크기가 된다.
 *
 * Re-measures the ref'd element's natural size against its scale-wrap parent's
 * available space on every resize/ResizeObserver tick/late image load, and applies
 * a uniform transform:scale() — never permanently freezing dimensions. This keeps
 * every internal ratio identical across all window sizes; the trade-off is
 * letterboxing (empty margin) when the window's aspect ratio doesn't match the
 * content's, which is expected and fine.
 */
export function useScaleToFit(ref, origin = "top center") {
  useEffect(() => {
    const content = ref.current;
    const wrap = content?.parentElement;
    if (!content || !wrap) return undefined;

    let frame = null;

    function measureAndScale() {
      content.style.transform = "none";
      const naturalW = content.offsetWidth;
      const naturalH = content.offsetHeight;
      const availW = wrap.clientWidth;
      const availH = wrap.clientHeight;
      if (!naturalW || !naturalH || !availW || !availH) return;
      const scale = Math.min(availW / naturalW, availH / naturalH);
      content.style.transformOrigin = origin;
      content.style.transform = `scale(${scale})`;
    }

    function schedule() {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measureAndScale);
    }

    schedule();
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    ro.observe(wrap);

    const imgs = content.querySelectorAll("img");
    imgs.forEach((img) => {
      if (!img.complete) img.addEventListener("load", schedule, { once: true });
    });

    return () => {
      window.removeEventListener("resize", schedule);
      ro.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
}
