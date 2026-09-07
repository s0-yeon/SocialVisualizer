import { useEffect, useState } from "react";
import { rankKeywords, keywordFontSize, WC_COLORS } from "../../features/recapStats.js";

/**
"메일 속 주요 키워드" 카드 — 상위 10개 키워드를 빈도에 비례한 크기의 태그 클라우드로 렌더링한다.
각 단어는 순서대로 살짝 지연시켜 페이드인한다(기존 requestAnimationFrame + show 클래스 트릭과 동일).

"Top keywords" card — renders the top-10 keywords as a tag cloud sized by frequency. Each word fades in with a staggered delay (same requestAnimationFrame + "show" class trick as the original).
 */
export default function KeywordCloudCard({
  state,
  title = "메일 속 주요 키워드",
  icon = "✦",
  iconBg = "#f0faf4",
}) {
  const { status, data, error } = state;
  const keywords = data ? rankKeywords(data) : [];
  const [shown, setShown] = useState(false);

  useEffect(() => {
    setShown(false);
    if (status !== "done" || keywords.length === 0) return;
    let raf1, raf2;
    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setShown(true));
    });
    return () => {
      cancelAnimationFrame(raf1);
      if (raf2) cancelAnimationFrame(raf2);
    };
  }, [status, data]);

  const max = keywords[0]?.count;
  const min = keywords[keywords.length - 1]?.count;

  return (
    <div className="rc-card">
      <div className="rc-card-header">
        <div className="rc-card-title">
          <div className="rc-card-title-icon" style={{ background: iconBg }}>
            {icon}
          </div>
          {title}
        </div>
        {status === "done" && keywords.length > 0 && (
          <span className="rc-card-badge">{keywords.length}개 키워드</span>
        )}
      </div>

      {status === "loading" && (
        <div className="rc-loading">
          <div className="rc-spinner"></div>키워드 분석 중…
        </div>
      )}

      {(status === "error" || (status === "done" && keywords.length === 0)) && (
        <div className="rc-error">{error || "데이터가 없습니다."}</div>
      )}

      {status === "done" && keywords.length > 0 && (
        <div className="rc-wc-wrap">
          {keywords.map((kw, idx) => (
            <span
              key={kw.word}
              className={`rc-wc-word${shown ? " show" : ""}`}
              style={{
                fontSize: `${keywordFontSize(kw.count, min, max)}px`,
                color: WC_COLORS[idx % WC_COLORS.length],
                transitionDelay: `${(idx * 0.06).toFixed(2)}s`,
              }}
              title={`${kw.word}: ${kw.count}회`}
            >
              {kw.word}
              <sup className="rc-wc-count">{kw.count}</sup>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
