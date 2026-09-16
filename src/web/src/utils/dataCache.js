/**
 * 사이드바에서 계정/방을 전환하거나, My People ↔ My Time ↔ Recap처럼 페이지를 아예
 * 넘나들거나, 브라우저/탭을 완전히 껐다 켜도 하루(24시간) 동안은 서버에 다시 요청하지
 * 않도록 데이터를 담아두는 캐시.
 *
 * localStorage에 저장한다 — 그래야 페이지 이동/새로고침은 물론 브라우저를 완전히
 * 종료했다 다시 열어도 캐시가 그대로 남아있다(sessionStorage는 탭을 닫으면 사라지므로
 * "다 꺼도 유지" 요구사항엔 안 맞아서 안 씀). 프라이빗 모드 등으로 localStorage를 아예
 * 못 쓰는 상황이면 예외를 삼키고 조용히 메모리 캐시로만 동작한다(캐시가 좀 짧게 사는
 * 것뿐, 페이지 자체가 죽으면 안 되므로).
 */

export const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 하루
const PREFIX = "sv_cache::";

// localStorage 접근 성공 시 매번 JSON.parse 하지 않도록 두는 1차 캐시(같은 페이지 안에서만 유효).
const mem = new Map(); // key -> { timestamp, value }

function detectStorage() {
  try {
    const t = "__sv_cache_probe__";
    window.localStorage.setItem(t, "1");
    window.localStorage.removeItem(t);
    return true;
  } catch (e) {
    return false;
  }
}
const hasStorage = typeof window !== "undefined" && detectStorage();

function isFresh(entry) {
  return !!entry && Date.now() - entry.timestamp < CACHE_TTL_MS;
}

export function getCached(key) {
  const memHit = mem.get(key);
  if (memHit) {
    if (isFresh(memHit)) return memHit.value;
    mem.delete(key);
  }

  if (!hasStorage) return undefined;
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (!raw) return undefined;
    const entry = JSON.parse(raw);
    if (!isFresh(entry)) {
      window.localStorage.removeItem(PREFIX + key);
      return undefined;
    }
    mem.set(key, entry);
    return entry.value;
  } catch (e) {
    return undefined;
  }
}

export function setCached(key, value) {
  const entry = { timestamp: Date.now(), value };
  mem.set(key, entry);
  if (!hasStorage) return;
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(entry));
  } catch (e) {
    // 저장 공간 초과 등 — 이번 값은 메모리 캐시로만 살아있는 걸로 만족한다.
  }
}

export function clearCached(key) {
  mem.delete(key);
  if (!hasStorage) return;
  try {
    window.localStorage.removeItem(PREFIX + key);
  } catch (e) {}
}
