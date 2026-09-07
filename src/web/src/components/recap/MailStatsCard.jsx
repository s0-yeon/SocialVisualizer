import { useEffect, useState } from "react";
import { initials, AVATAR_COLORS } from "../../features/recapStats.js";

/**
"나에게 많이 보낸 사람" / "내가 많이 보낸 사람" 카드 — 1위 하이라이트와 상위 10명 막대그래프를
렌더링한다. 막대는 처음엔 0폭으로 그렸다가 다음 프레임에 실제 비율로 늘려서 CSS 트랜지션이
보이게 한다(기존 requestAnimationFrame 두 번 트릭과 동일).

"Top senders to me" / "Top people I sent to" card — renders the #1 highlight plus a top-10 bar list. Bars render at 0 width first, then grow to their real percentage on the next frame so the CSS transition is visible (same double-requestAnimationFrame trick as the original).
 */
export default function MailStatsCard({
  icon,
  iconBg,
  title,
  tag,
  unit,
  state,
  secondary = "email",
  barUnit = "통",
}) {
  const { status, ranked = [], error } = state;
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    setRevealed(false);
    if (status !== "done" || ranked.length === 0) return;
    let raf1, raf2;
    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setRevealed(true));
    });
    return () => {
      cancelAnimationFrame(raf1);
      if (raf2) cancelAnimationFrame(raf2);
    };
  }, [status, ranked]);

  const max = ranked[0]?.count || 0;
  const top = ranked[0];
  const [c1, c2] = AVATAR_COLORS[0];

  // 1위/바 리스트의 보조 텍스트(이름 아래 줄). "email"=이메일, "bio"=한줄소개, "none"=숨김
  const secondaryText = (item) =>
    secondary === "email" ? item.email : secondary === "bio" ? item.bio || "" : "";

  return (
    <div className="rc-card">
      <div className="rc-card-header">
        <div className="rc-card-title">
          <div className="rc-card-title-icon" style={{ background: iconBg }}>
            {icon}
          </div>
          {title}
        </div>
        {status === "done" && ranked.length > 0 && (
          <span className="rc-card-badge">{ranked.length}명</span>
        )}
      </div>

      {status === "loading" && (
        <div className="rc-loading">
          <div className="rc-spinner"></div>데이터를 불러오는 중…
        </div>
      )}

      {(status === "error" || (status === "done" && ranked.length === 0)) && (
        <div className="rc-error">{error || "데이터가 없습니다."}</div>
      )}

      {status === "done" && ranked.length > 0 && (
        <div>
          <div className="rc-rank1-card">
            <div
              className="rc-rank1-avatar"
              style={{ background: `linear-gradient(135deg,${c1},${c2})` }}
            >
              {initials(top.name)}
            </div>
            <div className="rc-rank1-info">
              <div className="rc-rank1-tag">🏆 {tag}</div>
              <div className="rc-rank1-name">{top.name}</div>
              {secondaryText(top) && (
                <div className="rc-rank1-email">{secondaryText(top)}</div>
              )}
            </div>
            <div className="rc-rank1-count">
              <div className="rc-rank1-num">{top.count}</div>
              <div className="rc-rank1-unit">{unit}</div>
            </div>
          </div>
          <ul className="rc-bar-list">
            {ranked.map((item, i) => {
              const rankClass = i === 0 ? "rank1" : i === 1 ? "rank2" : i === 2 ? "rank3" : "";
              const rankLabel = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : i + 1;
              const pct = max > 0 ? Math.round((item.count / max) * 100) : 0;
              return (
                <li className="rc-bar-item" key={item.email || item.name}>
                  <div className={`rc-bar-rank${i < 3 ? " top" : ""}`}>{rankLabel}</div>
                  <div className="rc-bar-inner">
                    <div className="rc-bar-name" title={secondaryText(item) || item.name}>
                      {item.name}
                    </div>
                    <div className="rc-bar-track">
                      <div
                        className={`rc-bar-fill ${rankClass}`}
                        style={{ width: revealed ? `${pct}%` : "0%" }}
                      ></div>
                    </div>
                  </div>
                  <div className="rc-bar-count">
                    {item.count}
                    {barUnit}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
