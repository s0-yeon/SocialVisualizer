import { useEffect, useState } from "react";
import { prepMonthlyMessages } from "../../features/recapStats.js";

/**
"월별 대화량" 카드 — /chatroom-monthly-message-stats 의 월별 총 메시지 수를 세로 막대차트로 보여준다.
그룹채팅은 송/수신 구분이 없어 월별 총량만 표시한다. 막대는 0 높이로 그렸다가 다음 프레임에
실제 높이로 늘려 CSS 트랜지션이 보이게 한다(MailStatsCard의 더블 rAF reveal 패턴과 동일).

"Monthly volume" card — renders per-month total message counts as a vertical bar chart.
Group chats have no sent/received split, so only the monthly total is shown.
 */
export default function MonthlyMessageCard({ state }) {
  const { status, data, error } = state;
  const months = status === "done" && data ? prepMonthlyMessages(data) : [];
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    setRevealed(false);
    if (status !== "done" || months.length === 0) return;
    let raf1, raf2;
    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setRevealed(true));
    });
    return () => {
      cancelAnimationFrame(raf1);
      if (raf2) cancelAnimationFrame(raf2);
    };
  }, [status, data]);

  const max = months.reduce((m, x) => Math.max(m, x.count), 0);

  return (
    <div className="rc-card">
      <div className="rc-card-header">
        <div className="rc-card-title">
          <div className="rc-card-title-icon" style={{ background: "#eff6ff" }}>
            📅
          </div>
          월별 대화량
        </div>
        {status === "done" && months.length > 0 && (
          <span className="rc-card-badge">최근 {months.length}개월</span>
        )}
      </div>

      {status === "loading" && (
        <div className="rc-loading">
          <div className="rc-spinner"></div>월별 통계 불러오는 중…
        </div>
      )}

      {(status === "error" || (status === "done" && months.length === 0)) && (
        <div className="rc-error">{error || "데이터가 없습니다."}</div>
      )}

      {status === "done" && months.length > 0 && (
        <div className="rc-mm-wrap">
          {months.map((m) => {
            const pct = max > 0 ? Math.round((m.count / max) * 100) : 0;
            return (
              <div className="rc-mm-col" key={m.month} title={`${m.month}: ${m.count}개`}>
                <div className="rc-mm-count">{m.count}</div>
                <div className="rc-mm-track">
                  <div className="rc-mm-bar" style={{ height: revealed ? `${pct}%` : "0%" }}></div>
                </div>
                <div className="rc-mm-label">{m.label}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
