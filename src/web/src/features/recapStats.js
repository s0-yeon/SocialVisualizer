/**
Recap 페이지 통계 카드들이 공유하는 순수 헬퍼 — 통계 API 호출, 발신자 랭킹 정렬, 아바타 이니셜/색상, 워드클라우드 폰트 크기, 동기화 시간/날짜 포맷. DOM을 직접 건드리지 않는 순수 함수만 모아서 React 컴포넌트에서 재사용한다.

Shared pure helpers for the Recap page's stat cards — stat API calls, sender ranking, avatar initials/colors, word-cloud font sizing, sync time/date formatting. No direct DOM access, reused across the Recap React components.
 */

// user_id를 POST 바디에 담아 통계 API 호출 (공통 헬퍼)
export async function postStat(endpoint, gmailId) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: gmailId }),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// chatroom_id를 POST 바디에 담아 메신저 통계 API 호출 (postStat의 메신저 버전)
export async function postRoomStat(endpoint, chatroomId) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chatroom_id: chatroomId }),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// 아바타에 표시할 이니셜(이름 앞글자 1~2자) 추출
export function initials(nameStr) {
  const parts = nameStr.trim().split(/\s+/);
  return parts.length >= 2
    ? (parts[0][0] + parts[1][0]).toUpperCase()
    : nameStr.slice(0, 2).toUpperCase();
}

export const AVATAR_COLORS = [
  ["#fcd34d", "#f59e0b"],
  ["#a5b4fc", "#818cf8"],
  ["#c8c8c8", "#a7a7a7"],
  ["#f9a8d4", "#ec4899"],
  ["#67e8f9", "#06b6d4"],
  ["#fca5a5", "#ef4444"],
];

export const WC_COLORS = [
  "#353535",
  "#555555",
  "#757575",
  "#e63946",
  "#457b9d",
  "#e07b39",
  "#7b2d8b",
  "#1d6fa0",
  "#b5451b",
  "#565656",
];

export const AF_COLORS = [
  "#ec4899",
  "#a78bfa",
  "#f97316",
  "#06b6d4",
  "#808080",
  "#f59e0b",
  "#ef4444",
];
export const RANK_LABELS = ["🥇", "🥈", "🥉"];

// field: 'received' | 'sent' — 발신자/수신자 통계 데이터를 카운트 내림차순 상위 10명으로 가공
export function rankMailStats(data, field) {
  return Object.entries(data)
    .map(([email, v]) => ({ email, name: v.name || email, count: v[field] || 0 }))
    .filter((x) => x.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
}

// 상위 10개 키워드를 카운트 내림차순으로 추출
export function rankKeywords(data) {
  return (data.keywords || [])
    .slice()
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
}

// 키워드 카운트를 로그 스케일로 정규화해 폰트 크기(px)로 변환
export function keywordFontSize(count, min, max) {
  const norm = max === min ? 1 : Math.log1p(count - min) / Math.log1p(max - min);
  return Math.round(14 + norm * 32);
}

// 친밀도 상위 7명을 점수 내림차순 정렬 + 도넛 세그먼트용 누적 offset 계산
export function rankAffinity(data) {
  const list = (Array.isArray(data) ? data : []).slice(0, 7);
  const sorted = [...list].sort((a, b) => (b.affinity ?? 0) - (a.affinity ?? 0));
  const total = sorted.reduce((sum, item) => sum + (item.affinity ?? 0), 0);
  const radius = 82.5;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = sorted.map((item, i) => {
    const score = item.affinity ?? 0;
    const percentage = total > 0 ? score / total : 0;
    const length = circumference * percentage;
    const seg = {
      item,
      score,
      color: AF_COLORS[i % AF_COLORS.length],
      length,
      dashOffset: -offset,
    };
    offset += length;
    return seg;
  });
  return { sorted, circumference, segments };
}

// 메신저: 참여자별 메시지 수를 내림차순 상위 10명으로 가공.
// MailStatsCard가 기대하는 {email, name, count} 스키마에 맞추되,
// email 자리에는 participant_id를, bio에는 short_bio/description을 넣는다.
export function rankChatPeople(data) {
  const people = (data && data.people) || [];
  return people
    .map((p) => ({
      email: p.participant_id || "",
      name: p.name || p.participant_id || "-",
      count: p.message_count || 0,
      bio: p.short_bio || p.description || "",
    }))
    .filter((x) => x.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
}

// 메신저: 관계 라벨별 건수를 rankAffinity와 동일한 방식으로 도넛 세그먼트화(상위 7개).
export function rankRelationships(data) {
  const rows = (data && data.relationships) || [];
  const sorted = [...rows]
    .map((r) => ({ label: r.relation_label || "-", count: r.count || 0 }))
    .filter((r) => r.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 7);
  const total = (data && data.total) || sorted.reduce((s, r) => s + r.count, 0);
  const radius = 82.5;
  const circumference = 2 * Math.PI * radius;
  const segTotal = sorted.reduce((s, r) => s + r.count, 0);
  let offset = 0;
  const segments = sorted.map((item, i) => {
    const percentage = segTotal > 0 ? item.count / segTotal : 0;
    const length = circumference * percentage;
    const seg = {
      item,
      count: item.count,
      color: AF_COLORS[i % AF_COLORS.length],
      length,
      dashOffset: -offset,
    };
    offset += length;
    return seg;
  });
  return { sorted, circumference, segments, total };
}

// 메신저: 월별 메시지 수를 month 오름차순 정렬 + 최근 N개월로 제한, 막대차트용 가공.
export function prepMonthlyMessages(data, limit = 12) {
  const rows = (data && data.monthly) || [];
  return rows
    .map((r) => ({ month: r.month, count: r.count || 0 }))
    .filter((r) => r.month)
    .sort((a, b) => (a.month < b.month ? -1 : a.month > b.month ? 1 : 0))
    .slice(-limit)
    .map((r) => {
      const parts = String(r.month).split("-");
      const label = parts.length === 2 ? parts[0].slice(2) + "." + parts[1] : r.month;
      return { ...r, label };
    });
}

export function fmtSyncTime(t) {
  if (!t) return "—";
  const [h, m] = String(t).split("-");
  if (m === undefined) return h;
  return (parseInt(h) ? h + "시간 " : "") + (parseInt(m) ? m : "");
}

export function fmtSyncDate(d) {
  if (!d) return "—";
  const parts = String(d).split("-");
  if (parts.length === 3) return parts[0].slice(2) + "." + parts[1] + "." + parts[2];
  return d;
}
