/**
GraphRAG 자연어 검색 공통 로직 — 잡 폴링, 답변 텍스트 후처리, 근거메일 제목으로 답변 줄 매칭,
최근 검색어 저장. DOM을 직접 건드리지 않는 순수 함수만 모아서 검색 페이지의 React 컴포넌트에서
재사용한다.

Shared GraphRAG search logic — job polling, answer post-processing, matching source-mail subjects
to answer lines, and recent-search persistence. Pure functions with no direct DOM access, reused by
the search page's React components.
 */

export const MAX_RECENTS = 8;

// 목표 구조화 답변 형식(번호 매김 5필드)인지 판단한다. 1번째/3번째 필드 라벨은 도메인마다
// 다르므로(메신저: 메시지/채팅방, 메일: 제목/계정) 라벨 이름 대신 "N. ...' 다음 줄에 들여쓴
// '날짜:' 필드가 오는" 구조 자체로 판별한다. 이 형식일 때는 백엔드가 이미 줄바꿈/들여쓰기를
// 정확히 맞춰서 보내주므로 아래 문장부호 기반 강제 줄바꿈 안전망을 적용하면 오히려 "내용:"
// 필드 안의 문장 두 개가 멋대로 갈라지는 등 형식이 깨진다 — 그래서 이 형식일 땐 안전망을
// 건너뛴다.
const STRUCTURED_ANSWER_RE = /^\d+\.[^\n]*\n[ \t]*날짜:/m;

// 라마 응답이 " - " 불릿 외의 형식으로 줄바꿈 없이 나오는 경우를 대비해 문장이 끝나는
// 지점마다 줄바꿈을 넣는 안전망(구조화 형식이 아닌 예전 방식의 자유 서술형 답변에만 적용).
// "다./요." 뒤가 이미 줄바꿈(단락 구분용 빈 줄 포함)이면 손대지 않고, 공백으로만 이어붙은
// 경우에만 줄바꿈을 넣음 — \s+는 뒤따르는 개행까지 다 먹어치워서, 답변 문단 사이의 빈 줄
// (단락 구분)까지 한 줄로 뭉개 가독성을 해치는 문제가 있었음.
export function formatAnswer(text) {
  const s = String(text || '').trim();
  if (STRUCTURED_ANSWER_RE.test(s)) return s;
  return s.replace(/([다요])\.[ \t]+(?=\S)/g, '$1.\n');
}

// jobId 처리 상태를 폴링하다 완료/실패 시 콜백 호출
export async function pollJob(flaskUrl, jobId, onDone, onError, interval = 2000, maxTries = 60) {
  for (let i = 0; i < maxTries; i++) {
    await new Promise((r) => setTimeout(r, interval));
    try {
      const res = await fetch(`${flaskUrl}/job-status/${jobId}`);
      const data = await res.json();
      if (data.status === 'done') { onDone(data.result || '결과가 없습니다.', data.source_ids || []); return; }
      if (data.status === 'error') { onError(data.result || '오류가 발생했습니다.'); return; }
    } catch (e) {
      onError('서버 연결에 실패했습니다.');
      return;
    }
  }
  onError('응답 시간이 초과되었습니다. 다시 시도해주세요.');
}

// 근거로 인용된 메일 id 목록의 제목을 조회
export async function fetchSubjectsByRefs(flaskUrl, refs) {
  if (!refs.length) return {};
  try {
    const res = await fetch(`${flaskUrl}/mail-subjects-by-ids`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refs: refs.map((r) => ({ id: r.id, account: r.account })) }),
    });
    if (!res.ok) return {};
    const data = await res.json();
    return data.subjects || {};
  } catch (e) {
    return {};
  }
}

// 제목 앞의 회신/전달 표시(RE:, FW:, 회신:, 전달: 등)를 반복해서 제거
function _stripReplyForwardPrefix(subject) {
  let s = subject;
  for (;;) {
    const next = s.replace(/^\s*(re|fw|fwd|회신|전달)\s*[:：]\s*/i, '');
    if (next === s) return s.trim();
    s = next;
  }
}

// 두 문자열 사이 최장 연속 공통 부분문자열의 길이를 계산 (동적 계획법)
function _longestCommonSubstringLen(a, b) {
  if (!a || !b) return 0;
  let prevRow = new Array(b.length + 1).fill(0);
  let best = 0;
  for (let i = 1; i <= a.length; i++) {
    const currRow = new Array(b.length + 1).fill(0);
    for (let j = 1; j <= b.length; j++) {
      if (a[i - 1] === b[j - 1]) {
        currRow[j] = prevRow[j - 1] + 1;
        if (currRow[j] > best) best = currRow[j];
      }
    }
    prevRow = currRow;
  }
  return best;
}

// 답변 줄 하나에 제목이 "언급됐다"고 볼 수 있는지 판단. 원래는 제목 전체가 그대로 포함된
// 줄만 찾았는데, 답변이 요약형이면(예: "한국정보통신학회 춘계 종합학술대회 초록 보내드립니다."
// 같은 원제목을 "한국정보통신학회 춘계 종합학술대회 초록과 관련된 안내를 전달하는
// 메일입니다."처럼 풀어 쓰는 경우) 제목 전체가 그대로 안 걸려 버튼이 통째로 사라졌음.
// 1) 제목 전체가 그대로 포함된 줄을 최우선으로 찾음.
// 2) 못 찾으면 RE/FW/회신/전달 접두사를 뗀 제목으로 다시 찾음(원제목을 요약하며 접두사만
//    빠지는 경우 대비).
// 3) 그래도 못 찾으면, 제목과 줄 사이에 "충분히 길게" 겹치는 연속 문자열이 있는 줄을 찾음.
//    겹치는 길이는 제목 길이의 절반 이상이면서 최소 5자 이상이어야 인정 — 예전에 있었던
//    "첫 단어만 일치해도 매칭"하던 fallback은 같은 단어로 시작하는 제목이 여럿일 때 버튼이
//    엉뚱한 줄에 몰리는 문제가 있어 제거된 적이 있는데, 이 기준은 그보다 훨씬 엄격해서
//    같은 문제를 재현하지 않음.
// "- 제목: ..." 처럼 메일 하나하나를 나열하는 불릿 줄인지 판단. 답변 맨 앞의 소개
// 문장("보안 알림 메일들이 있습니다")도 제목 단어를 그대로 포함하는 경우가 많아서, 구분
// 없이 첫 일치를 쓰면 그 소개 문장이 실제 목록 줄 자리를 가로채 버리는 문제가 있었음
// (제목이 같은 메일 여러 건일 때 특히 두드러짐 — 첫 건이 소개 문장에 붙어버리고 나머지만
// 목록 줄에 배정됨). 그래서 불릿 줄을 항상 먼저 찾고, 불릿 줄 중에 없을 때만 일반 문장도
// 후보로 봄.
function _isBulletLine(line) {
  return /^\s*[-*]\s/.test(line);
}

export function findLineIdxBySubject(lines, subject, excludeIdx) {
  const raw = String(subject || '').trim();
  if (!raw) return -1;
  const skip = excludeIdx || new Set();
  const notExcluded = (line, i) => !skip.has(i);

  // 후보를 찾는 조건(matches)이 주어지면, 불릿 줄 중에서 먼저 찾고 없으면 전체에서 찾는다.
  const findPreferBullet = (matches) => {
    let idx = lines.findIndex((line, i) => notExcluded(line, i) && _isBulletLine(line) && matches(line));
    if (idx !== -1) return idx;
    return lines.findIndex((line, i) => notExcluded(line, i) && matches(line));
  };

  let idx = findPreferBullet((line) => line.includes(raw));
  if (idx !== -1) return idx;

  const cleaned = _stripReplyForwardPrefix(raw).replace(/\s+/g, ' ');
  if (cleaned && cleaned !== raw) {
    idx = findPreferBullet((line) => line.includes(cleaned));
    if (idx !== -1) return idx;
  }

  const base = cleaned || raw;
  const minLen = Math.max(5, Math.ceil(base.length * 0.5));
  return findPreferBullet((line) => _longestCommonSubstringLen(base, line.replace(/\s+/g, ' ')) >= minLen);
}

// source_ids({id, account} 배열)에서 중복을 제거해서 뽑는다. 메일/메신저 도메인 공통 —
// 예전엔 domain !== 'mail'이면 항상 빈 배열을 반환해서 메신저 탭엔 "근거메신저 보기"
// 버튼 자체가 뜬 적이 없었음(도메인 분기가 아예 미구현 상태로 남아 있었음).
// 중복 판정 키는 "계정:블록ID" 조합 — 메신저 블록 ID는 "날짜_순번" 형태라 서로 다른
// 계정(채팅방)에서 같은 날짜에 같은 순번의 블록이 우연히 겹칠 수 있는데, id만으로
// 중복 판정하면 그중 한 계정의 근거가 통째로 사라져 버튼이 엉뚱한 계정을 가리키게 된다.
export function extractUniqueRefs(sourceIds) {
  const refs = [];
  if (!sourceIds || !sourceIds.length) return refs;
  const seen = new Set();
  sourceIds.forEach((src) => {
    const id = typeof src === 'string' ? src : src && src.id;
    const account = typeof src === 'string' ? null : src && src.account;
    if (!id) return;
    const key = `${account || ''}:${id}`;
    if (seen.has(key)) return;
    seen.add(key);
    refs.push({ id, account });
  });
  return refs;
}

// 목표 구조화 답변(번호 매김 5필드)의 각 항목이 몇 번째 줄에서 시작하는지 찾아, 그 항목의
// '내용:' 줄(들여쓴 4번째 줄) 인덱스를 항목이 나온 순서대로 배열로 반환한다.
// 'ID:' 줄은 사용자 설명대로 "근거메일/근거메신저 보기" 버튼으로 들어가는 값일 뿐 화면에
// 노출할 텍스트가 아니라서 — 백엔드가 이미 그 줄을 지우고 보내준다(graphrag_query.py의
// _format_structured_answer 참고). 그래서 텍스트로 ID를 찾아 매칭하는 대신, 답변에 남은 항목
// 순서와 백엔드가 같은 순서로 보내주는 source_ids 배열을 그대로 짝지어 버튼을 붙인다 —
// 이쪽이 제목/날짜 문자열로 어림짐작하는 것보다 훨씬 정확하고 안전하다.
export function assignStructuredItemLines(lines) {
  const indices = [];
  for (let i = 0; i < lines.length; i++) {
    if (!/^\d+\.\s*[^\n:]+:/.test(lines[i])) continue;
    const contentIdx = i + 3; // N.제목줄, 날짜, 채팅방|계정, 내용 순 — 내용은 4번째(0-index +3)
    if (contentIdx < lines.length && /^[ \t]*내용:/.test(lines[contentIdx])) {
      indices.push(contentIdx);
    }
  }
  return indices;
}

// 메신저 블록 ID("2022-08-21_01" 형태, 날짜_순번)에서 날짜만 뽑아 답변 줄 매칭용
// 검색어로 쓴다 — 메일의 "제목"에 해당하는 역할. 실제 federated_local 답변에는
// system_prompt 지시에 따라 LLM이 "날짜: 2022-08-21에 ..."처럼 날짜를 그대로
// 문장에 적는 경우가 많아 findLineIdxBySubject의 부분일치 로직을 그대로 재사용할 수 있다.
export function messengerRefSearchKey(ref) {
  const m = String((ref && ref.id) || '').match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : '';
}

export function loadRecents(key) {
  try { return JSON.parse(localStorage.getItem(key)) || []; } catch { return []; }
}

export function saveRecent(key, q) {
  let recents = loadRecents(key).filter((r) => r !== q);
  recents.unshift(q);
  if (recents.length > MAX_RECENTS) recents = recents.slice(0, MAX_RECENTS);
  localStorage.setItem(key, JSON.stringify(recents));
}

export function removeRecent(key, q) {
  localStorage.setItem(key, JSON.stringify(loadRecents(key).filter((r) => r !== q)));
}

export function clearRecents(key) {
  localStorage.removeItem(key);
}
