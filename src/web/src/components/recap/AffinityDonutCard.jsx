import { useState } from 'react';
import { rankAffinity, RANK_LABELS } from '../../features/recapStats.js';

/**
"친밀도" 카드 — SVG 도넛 차트 + 범례. 범례 항목이나 도넛 세그먼트에 마우스를 올리면 서로 강조되도록 양방향으로 연동한다(기존엔 addEventListener로 형제 엘리먼트 스타일을 직접 바꿨는데, 여기선 hover 중인 인덱스 하나를 state로 두고 두 쪽 다 그 값을 보고 스타일을 계산한다).

"Affinity" card — SVG donut chart + legend. Hovering a legend row or a donut segment highlights both in sync (the original mutated sibling element styles via addEventListener; here a single hovered-index state drives both sides' styles).
 */
export default function AffinityDonutCard({ state }) {
  const { status, data, error } = state;
  const [hoverIdx, setHoverIdx] = useState(-1);

  const { sorted, circumference, segments } =
    status === 'done' && Array.isArray(data) ? rankAffinity(data) : { sorted: [], circumference: 0, segments: [] };

  const topScore = sorted[0]?.affinity ?? 0;

  return (
    <div className="rc-card">
      <div className="rc-card-header">
        <div className="rc-card-title">
          <div className="rc-card-title-icon" style={{ background: '#fff0f6' }}>💌</div>
          친밀도
        </div>
        {status === 'done' && sorted.length > 0 && (
          <span className="rc-card-badge">{sorted.length}명</span>
        )}
      </div>

      {status === 'loading' && (
        <div className="rc-loading"><div className="rc-spinner"></div>친밀도 분석 중…</div>
      )}

      {(status === 'error' || (status === 'done' && sorted.length === 0)) && (
        <div className="rc-error">{error || '데이터가 없습니다.'}</div>
      )}

      {status === 'done' && sorted.length > 0 && (
        <div className="rc-af-donut-wrap">
          <div className="rc-af-chart-container">
            <svg className="rc-af-donut-svg" viewBox="0 0 200 200">
              <circle className="rc-af-donut-bg" cx="100" cy="100" r="82.5"></circle>
              {segments.map((seg, i) => (
                <circle
                  key={seg.item.email || i}
                  className="rc-af-donut-segment"
                  cx="100"
                  cy="100"
                  r="82.5"
                  stroke={seg.color}
                  strokeDasharray={`${seg.length} ${circumference}`}
                  strokeDashoffset={seg.dashOffset}
                  style={{
                    transition: 'all 0.8s cubic-bezier(0.22, 1, 0.36, 1)',
                    strokeWidth: hoverIdx === i ? 40 : 35,
                    filter: hoverIdx === i ? 'brightness(1.1)' : 'none',
                    opacity: hoverIdx === -1 || hoverIdx === i ? 1 : 0.4,
                  }}
                  onMouseEnter={() => setHoverIdx(i)}
                  onMouseLeave={() => setHoverIdx(-1)}
                />
              ))}
            </svg>
            <div className="rc-af-center-info">
              <div className="rc-af-center-num">{Math.round(topScore * 100)}%</div>
              <div className="rc-af-center-label">TOP 친밀도</div>
            </div>
          </div>
          <div className="rc-af-legend">
            {segments.map((seg, i) => {
              const percentage = Math.round(seg.score * 100);
              const rankLabel = i < 3 ? RANK_LABELS[i] : i + 1;
              const isHovered = hoverIdx === i;
              return (
                <div
                  key={seg.item.email || i}
                  className="rc-af-legend-item"
                  style={{
                    background: isHovered ? 'rgba(240, 240, 244, 0.8)' : 'rgba(240, 240, 244, 0.3)',
                    transform: isHovered ? 'translateX(6px) scale(1.02)' : 'translateX(0) scale(1)',
                    opacity: hoverIdx === -1 || isHovered ? 1 : 0.5,
                  }}
                  onMouseEnter={() => setHoverIdx(i)}
                  onMouseLeave={() => setHoverIdx(-1)}
                >
                  <div className="rc-af-legend-rank">{rankLabel}</div>
                  <div className="rc-af-legend-color" style={{ background: seg.color }}></div>
                  <div className="rc-af-legend-info">
                    <div className="rc-af-legend-name">{seg.item.name || seg.item.email}</div>
                    <div className="rc-af-legend-email">{seg.item.email || ''}</div>
                  </div>
                  <div className="rc-af-legend-score" style={{ color: seg.color }}>{percentage}%</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
