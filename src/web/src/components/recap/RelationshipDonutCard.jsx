import { useState } from "react";
import { rankRelationships, RANK_LABELS } from "../../features/recapStats.js";

/**
"채팅방 관계" 카드 — 메일 Recap의 친밀도 도넛(AffinityDonutCard)과 같은 시각 언어(.rc-af-*)를
그대로 쓰되, 데이터 소스만 /chatroom-relationship-stats(관계 라벨별 건수)로 바꾼 버전.
범례/세그먼트에 마우스를 올리면 양쪽이 함께 강조된다.

"Chatroom relationships" card — reuses the mail Recap affinity donut's visual language (.rc-af-*),
but sourced from /chatroom-relationship-stats (per-label relationship counts).
 */
export default function RelationshipDonutCard({ state }) {
  const { status, data, error } = state;
  const [hoverIdx, setHoverIdx] = useState(-1);

  const { sorted, circumference, segments, total } =
    status === "done" && data
      ? rankRelationships(data)
      : { sorted: [], circumference: 0, segments: [], total: 0 };

  return (
    <div className="rc-card">
      <div className="rc-card-header">
        <div className="rc-card-title">
          <div className="rc-card-title-icon" style={{ background: "#eef6f0" }}>
            🤝
          </div>
          채팅방 관계
        </div>
        {status === "done" && sorted.length > 0 && (
          <span className="rc-card-badge">{sorted.length}종</span>
        )}
      </div>

      {status === "loading" && (
        <div className="rc-loading">
          <div className="rc-spinner"></div>관계 분석 중…
        </div>
      )}

      {(status === "error" || (status === "done" && sorted.length === 0)) && (
        <div className="rc-error">{error || "데이터가 없습니다."}</div>
      )}

      {status === "done" && sorted.length > 0 && (
        <div className="rc-af-donut-wrap">
          <div className="rc-af-chart-container">
            <svg className="rc-af-donut-svg" viewBox="0 0 200 200">
              <circle className="rc-af-donut-bg" cx="100" cy="100" r="82.5"></circle>
              {segments.map((seg, i) => (
                <circle
                  key={seg.item.label || i}
                  className="rc-af-donut-segment"
                  cx="100"
                  cy="100"
                  r="82.5"
                  stroke={seg.color}
                  strokeDasharray={`${seg.length} ${circumference}`}
                  strokeDashoffset={seg.dashOffset}
                  style={{
                    transition: "all 0.8s cubic-bezier(0.22, 1, 0.36, 1)",
                    strokeWidth: hoverIdx === i ? 40 : 35,
                    filter: hoverIdx === i ? "brightness(1.1)" : "none",
                    opacity: hoverIdx === -1 || hoverIdx === i ? 1 : 0.4,
                  }}
                  onMouseEnter={() => setHoverIdx(i)}
                  onMouseLeave={() => setHoverIdx(-1)}
                />
              ))}
            </svg>
            <div className="rc-af-center-info">
              <div className="rc-af-center-num">{total}</div>
              <div className="rc-af-center-label">총 관계</div>
            </div>
          </div>
          <div className="rc-af-legend">
            {segments.map((seg, i) => {
              const segTotal = segments.reduce((s, x) => s + x.count, 0);
              const percentage = segTotal > 0 ? Math.round((seg.count / segTotal) * 100) : 0;
              const rankLabel = i < 3 ? RANK_LABELS[i] : i + 1;
              const isHovered = hoverIdx === i;
              return (
                <div
                  key={seg.item.label || i}
                  className="rc-af-legend-item"
                  style={{
                    background: isHovered ? "rgba(240, 240, 244, 0.8)" : "rgba(240, 240, 244, 0.3)",
                    transform: isHovered ? "translateX(6px) scale(1.02)" : "translateX(0) scale(1)",
                    opacity: hoverIdx === -1 || isHovered ? 1 : 0.5,
                  }}
                  onMouseEnter={() => setHoverIdx(i)}
                  onMouseLeave={() => setHoverIdx(-1)}
                >
                  <div className="rc-af-legend-rank">{rankLabel}</div>
                  <div className="rc-af-legend-color" style={{ background: seg.color }}></div>
                  <div className="rc-af-legend-info">
                    <div className="rc-af-legend-name">{seg.item.label}</div>
                    <div className="rc-af-legend-email">{seg.count}건</div>
                  </div>
                  <div className="rc-af-legend-score" style={{ color: seg.color }}>
                    {percentage}%
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
