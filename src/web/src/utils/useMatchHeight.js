import { useEffect } from "react";

/**
 * source로 넘긴 요소의 실제 렌더링 높이를 측정해서 target 요소의 max-height로 그대로
 * 적용한다(ResizeObserver로 계속 동기화). CSS Grid/Flexbox의 auto 높이 계산은
 * overflow:auto인 자식의 "최소" 기여만 0으로 취급할 뿐 콘텐츠 높이 자체를 기준으로
 * 트랙을 키우기 때문에, target 쪽에 overflow:auto만 걸어서는 source 높이에 맞춰
 * 상한을 걸 수 없다 — useScaleToFit.js와 같은 방식으로 직접 측정해서 명시적인 px
 * 값을 강제해야 실제로 캡이 걸리고 넘치는 내용만 스크롤된다.
 *
 * source가 display:none 등으로 보이지 않으면(예: 비활성 탭) 높이가 0으로 보고되는데,
 * 이때는 target에 반영하지 않고 이전 값을 유지한다 — 다시 보일 때 ResizeObserver가
 * 실제 높이로 재통지하면 그때 갱신된다.
 */
export function useMatchHeight(pairs) {
  useEffect(() => {
    const observers = pairs
      .map(([sourceRef, targetRef]) => {
        const source = sourceRef.current;
        const target = targetRef.current;
        if (!source || !target) return null;
        const ro = new ResizeObserver((entries) => {
          const height = entries[0]?.contentRect.height;
          if (height) target.style.maxHeight = `${height}px`;
        });
        ro.observe(source);
        return ro;
      })
      .filter(Boolean);

    return () => observers.forEach((ro) => ro.disconnect());
  }, []);
}
