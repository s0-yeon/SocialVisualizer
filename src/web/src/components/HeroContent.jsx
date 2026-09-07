/**
홈 화면 히어로 섹션 — 헤드라인/설명/CTA와 My People·My Time 미리보기 카드, 글로우 SVG 필터를 렌더링한다.
미리보기는 정적 이미지(기본) 또는 실제 페이지를 담은 축소 iframe 중 하나로 전환 가능하다(USE_STATIC_HERO_PREVIEWS). CSS 클래스 접두사(gw-orbit-hero 등)는 예전 디자인의 흔적으로 이름만 남아있을 뿐, 지금 마크업은 2컬럼(문구 + 미리보기 카드) 레이아웃이다.

Home page hero section — renders the headline/description/CTA, My People & My Time preview cards, and a glow SVG filter.
Previews can switch between static images (default) and a scaled-down live iframe of the actual page (USE_STATIC_HERO_PREVIEWS). The gw-orbit-hero CSS class prefix is a naming leftover from an earlier design; the current markup is the two-column (copy + preview cards) layout.
 */
import { useEffect, useRef } from "react";

// 미니 프리뷰 카드
const FRAME_W = 1600;
const FRAME_H = 1020;

/* 히어로 미리보기 카드를 "실제 페이지 iframe 축소판" 대신 미리 찍어둔 정적 이미지로
   보여줄지 여부. true면 아래 My People/My Time 카드에 public/images/hero/의
   MyPeople.png, MyTime.png를 그대로 띄운다. 원래대로(iframe 라이브 미리보기)
   되돌리려면 이 값을 false로만 바꾸면 된다 — 원본 iframe 코드는 그대로 남아있음. */
const USE_STATIC_HERO_PREVIEWS = true;

// 실제 페이지를 iframe으로 불러와 CSS로 축소해 보여주는 라이브 미리보기 카드
function PagePreviewFrame({ src }) {
  return (
    <div className="gw-preview-frame">
      <iframe
        src={src}
        title={src}
        tabIndex={-1}
        scrolling="no"
        style={{ width: FRAME_W, height: FRAME_H }}
      />
    </div>
  );
}

// 히어로 전체 렌더링
export default function HeroContent() {
  const heroRef = useRef(null);

  // React가 화면을 다 그린 "다음"에 실행됨 — 그래서 .gw-anim 요소들이 실제로 DOM에 존재하는 시점에 안전하게 .visible 클래스를 붙일 수 있음
  useEffect(() => {
    const els = document.querySelectorAll(".gw-orbit-hero .gw-anim");
    requestAnimationFrame(() => {
      els.forEach((el) => el.classList.add("visible"));
    });
  }, []);

  // 창 크기가 바뀌어도 .gw-orbit-hero 안의 요소·크기 값(폰트, 여백, 카드 크기 등)은
  // 전혀 건드리지 않고, 원래 크기 그대로 렌더링된 상태를 매번 다시 측정해서 그 비율만큼
  // transform:scale()로 통째로 줄이거나 키운다. 크기를 한 번만 재서 고정해두면(freeze)
  // 이미지가 아직 로딩되지 않았거나 레이아웃이 자리잡기 전 타이밍에 잘못된 값으로
  // 굳어버릴 수 있어서, 매번 스케일을 잠깐 풀고 "원본 크기"를 다시 잰 뒤 재적용한다.
  useEffect(() => {
    const hero = heroRef.current;
    const wrap = hero?.parentElement;
    if (!hero || !wrap) return undefined;

    let frame = null;

    function measureAndScale() {
      // 측정 직전엔 스케일을 잠깐 초기화해서, 이전에 적용된 scale 값이 원본 크기
      // 측정에 영향을 주지 않도록 한다.
      hero.style.transform = "none";
      const naturalW = hero.offsetWidth;
      const naturalH = hero.offsetHeight;
      const availW = wrap.clientWidth;
      const availH = wrap.clientHeight;
      if (!naturalW || !naturalH || !availW || !availH) return;
      const scale = Math.min(availW / naturalW, availH / naturalH);
      hero.style.transformOrigin = "top center";
      hero.style.transform = `scale(${scale})`;
    }

    function schedule() {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measureAndScale);
    }

    schedule();
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    ro.observe(wrap);
    // 정적 미리보기 이미지가 늦게 로딩되며 자연 크기가 바뀌는 경우도 다시 재는다
    const imgs = hero.querySelectorAll("img");
    imgs.forEach((img) => {
      if (!img.complete) img.addEventListener("load", schedule, { once: true });
    });

    return () => {
      window.removeEventListener("resize", schedule);
      ro.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="gw-hero-scale-wrap">
      <div className="gw-orbit-hero" ref={heroRef}>
        <div className="gw-orbit-left">
          <h1 className="gw-hero-headline gw-anim" style={{ transitionDelay: "0.05s" }}>
            Social Visualizer
          </h1>
          <svg className="absolute -z-1 h-0 w-0" width="0" height="0" aria-hidden="true">
            <defs>
              <filter
                id="glow-4"
                colorInterpolationFilters="sRGB"
                x="-50%"
                y="-200%"
                width="200%"
                height="500%"
              >
                <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur4" />
                <feGaussianBlur in="SourceGraphic" stdDeviation="19" result="blur19" />
                <feGaussianBlur in="SourceGraphic" stdDeviation="9" result="blur9" />
                <feGaussianBlur in="SourceGraphic" stdDeviation="30" result="blur30" />
                <feColorMatrix
                  in="blur4"
                  result="color-0-blur"
                  type="matrix"
                  values="1 0 0 0 0
                        0 0.9803921568627451 0 0 0
                        0 0 0.9647058823529412 0 0
                        0 0 0 0.3 0"
                />
                <feOffset in="color-0-blur" result="layer-0-offsetted" dx="0" dy="0" />
                <feColorMatrix
                  in="blur19"
                  result="color-1-blur"
                  type="matrix"
                  values="0.8156862745098039 0 0 0 0
                        0 0.49411764705882355 0 0 0
                        0 0 0.2627450980392157 0 0
                        0 0 0 0.2 0"
                />
                <feOffset in="color-1-blur" result="layer-1-offsetted" dx="0" dy="2" />
                <feColorMatrix
                  in="blur9"
                  result="color-2-blur"
                  type="matrix"
                  values="1 0 0 0 0
                        0 0.6666666666666666 0 0 0
                        0 0 0.36470588235294116 0 0
                        0 0 0 0.15 0"
                />
                <feOffset in="color-2-blur" result="layer-2-offsetted" dx="0" dy="2" />
                <feColorMatrix
                  in="blur30"
                  result="color-3-blur"
                  type="matrix"
                  values="1 0 0 0 0
                        0 0.611764705882353 0 0 0
                        0 0 0.39215686274509803 0 0
                        0 0 0 0.12 0"
                />
                <feOffset in="color-3-blur" result="layer-3-offsetted" dx="0" dy="2" />
                <feColorMatrix
                  in="blur30"
                  result="color-4-blur"
                  type="matrix"
                  values="0.4549019607843137 0 0 0 0
                        0 0.16470588235294117 0 0 0
                        0 0 0 0 0
                        0 0 0 0.08 0"
                />
                <feOffset in="color-4-blur" result="layer-4-offsetted" dx="0" dy="16" />
                <feColorMatrix
                  in="blur30"
                  result="color-5-blur"
                  type="matrix"
                  values="0.4235294117647059 0 0 0 0
                        0 0.19607843137254902 0 0 0
                        0 0 0.11372549019607843 0 0
                        0 0 0 0.06 0"
                />
                <feOffset in="color-5-blur" result="layer-5-offsetted" dx="0" dy="64" />
                <feColorMatrix
                  in="blur30"
                  result="color-6-blur"
                  type="matrix"
                  values="0.21176470588235294 0 0 0 0
                        0 0.10980392156862745 0 0 0
                        0 0 0.07450980392156863 0 0
                        0 0 0 0.05 0"
                />
                <feOffset in="color-6-blur" result="layer-6-offsetted" dx="0" dy="64" />
                <feMerge>
                  <feMergeNode in="layer-0-offsetted" />
                  <feMergeNode in="layer-1-offsetted" />
                  <feMergeNode in="layer-2-offsetted" />
                  <feMergeNode in="layer-3-offsetted" />
                  <feMergeNode in="layer-4-offsetted" />
                  <feMergeNode in="layer-5-offsetted" />
                  <feMergeNode in="layer-6-offsetted" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
          </svg>
          <p className="gw-hero-desc gw-anim" style={{ transitionDelay: "0.15s" }}>
            Social Visualizer는 메일, 메신저를 연결하여 당신의 인간관계와 삶의 흐름을 시각화합니다.
          </p>
          <div className="gw-hero-cta gw-anim" style={{ transitionDelay: "0.22s" }}>
            <a href="imap-collect.html" className="gw-hero-cta-primary">
              시작하기
            </a>
          </div>
        </div>

        <div className="gw-hero-previews gw-anim" style={{ transitionDelay: "0.28s" }}>
          <a
            href="mypeople.html"
            className={`gw-preview-card${USE_STATIC_HERO_PREVIEWS ? " gw-preview-card--static" : ""}`}
          >
            {USE_STATIC_HERO_PREVIEWS ? (
              <img
                src="/images/hero/MyPeople.png"
                alt="My People"
                className="gw-preview-static-img"
              />
            ) : (
              <PagePreviewFrame src="mypeople.html" />
            )}
            <div className="gw-preview-overlay">
              <span>My People 바로가기</span>
              <i className="bi bi-arrow-right-short"></i>
            </div>
          </a>
          <a
            href="mytime.html"
            className={`gw-preview-card${USE_STATIC_HERO_PREVIEWS ? " gw-preview-card--static" : ""}`}
          >
            {USE_STATIC_HERO_PREVIEWS ? (
              <img src="/images/hero/MyTime.png" alt="My Time" className="gw-preview-static-img" />
            ) : (
              <PagePreviewFrame src="mytime.html" />
            )}
            <div className="gw-preview-overlay">
              <span>My Time 바로가기</span>
              <i className="bi bi-arrow-right-short"></i>
            </div>
          </a>
        </div>
      </div>
    </div>
  );
}
