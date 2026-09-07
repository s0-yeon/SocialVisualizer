import { useEffect, useRef } from "react";
import { fmtSyncTime, fmtSyncDate } from "../../features/recapStats.js";

/**
"메일 동기화 현황" 카드 — 동기화된 메일 수를 0에서부터 카운트업 애니메이션으로 보여준다. 60fps로 계속 텍스트를 갱신하는 연속 애니메이션이라 리렌더 대신 ref로 DOM을 직접 갱신한다(기존 로직과 동일한 requestAnimationFrame 기반 easing).

"Sync status" card — animates the synced mail count counting up from 0. Since it's a continuous 60fps text update, the DOM node is updated directly via a ref instead of re-rendering (same requestAnimationFrame easing as the original).
 */
export default function SyncStatsCard({
  state,
  title = "메일 동기화 현황",
  countField = "mail_count",
  countLabel = "동기화된 메일",
  countUnit = "통",
}) {
  const { status, data, error } = state;
  const countRef = useRef(null);

  useEffect(() => {
    if (status !== "done" || !data || !countRef.current) return;
    const el = countRef.current;
    const target = data[countField] || 0;
    const duration = 900;
    const start = performance.now();
    let raf;
    function tick(now) {
      const p = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(ease * target).toLocaleString();
      if (p < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    const finalTimer = setTimeout(() => {
      el.textContent = target.toLocaleString() + countUnit;
    }, 940);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(finalTimer);
    };
  }, [status, data, countField, countUnit]);

  return (
    <div className="rc-grid2">
      <div className="rc-card rc-sync-card">
        <div className="rc-card-header">
          <div className="rc-card-title">
            <div className="rc-card-title-icon" style={{ background: "#eff6ff" }}>
              🔄
            </div>
            {title}
          </div>
        </div>

        {status === "loading" && (
          <div className="rc-loading">
            <div className="rc-spinner"></div>동기화 정보 불러오는 중…
          </div>
        )}

        {status === "error" && <div className="rc-error">{error || "데이터가 없습니다."}</div>}

        {status === "done" && data && (
          <div className="rc-sync-tiles">
            <div className="rc-sync-tile rc-sync-tile--blue">
              <div className="rc-sync-tile-icon">📬</div>
              <div className="rc-sync-tile-num" ref={countRef}>
                —
              </div>
              <div className="rc-sync-tile-label">{countLabel}</div>
            </div>
            <div className="rc-sync-tile rc-sync-tile--violet">
              <div className="rc-sync-tile-icon">⏱</div>
              <div className="rc-sync-tile-num">{fmtSyncTime(data.sync_time)}</div>
              <div className="rc-sync-tile-label">동기화 소요</div>
            </div>
            <div className="rc-sync-tile rc-sync-tile--teal">
              <div className="rc-sync-tile-icon">📅</div>
              <div className="rc-sync-tile-num rc-sync-date">
                {fmtSyncDate(data.sync_update_date)}
              </div>
              <div className="rc-sync-tile-label">마지막 동기화</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
