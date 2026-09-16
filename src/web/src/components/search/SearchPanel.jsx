import { useEffect, useState } from 'react';
import {
  fetchSubjectsByRefs,
  findLineIdxBySubject,
  assignStructuredItemLines,
  formatAnswer,
  extractUniqueRefs,
  messengerRefSearchKey,
  loadRecents,
  saveRecent,
  removeRecent,
  clearRecents,
  pollJob,
} from '../../features/graphragSearch.js';

const SOURCE_BTN_LABEL = { mail: '근거메일 보기', messenger: '근거메신저 보기' };
const SOURCE_BODY_ENDPOINT = { mail: '/mail-body-by-ids', messenger: '/messenger-body-by-ids' };

/**
검색 탭(메일/메신저) 하나의 전체 UI — 입력창, 최근 검색어, GraphRAG 질의 실행, 결과(답변 줄 +
근거메일 보기 버튼), 근거 메일 본문 서랍까지 포함한다. 메일/메신저 탭이 각자 독립된 상태(입력값,
최근 검색어, 결과)를 갖도록 props로만 구분되는 재사용 컴포넌트.

Full UI for one search tab (mail or messenger) — input, recent searches, running the GraphRAG
query, rendering the answer (with inline "view source mail" buttons), and the source-mail detail
drawer. A single reusable component; the mail and messenger tabs each get independent state via
props only.
 */
export default function SearchPanel({
  active,
  domain,
  recentKey,
  getUserId,
  flaskUrl,
  loadingText,
  placeholder,
  emptyIcon,
  emptyText,
  initialQuery,
}) {
  const [query, setQuery] = useState('');
  const [recents, setRecents] = useState(() => loadRecents(recentKey));
  const [result, setResult] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeMailId, setActiveMailId] = useState(null);
  const [mailDetail, setMailDetail] = useState(null);

  async function runSearch(q) {
    setResult({ query: q, status: 'loading' });
    setDrawerOpen(false);
    setActiveMailId(null);
    setMailDetail(null);
    saveRecent(recentKey, q);
    setRecents(loadRecents(recentKey));

    const userId = getUserId();
    try {
      const res = await fetch(`${flaskUrl}/run-query-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: q, resType: 'structed', user_id: userId, domain }),
      });
      const data = await res.json();
      if (!data.jobId) {
        setResult({ query: q, status: 'error', message: '검색 요청에 실패했습니다.' });
        return;
      }
      await pollJob(
        flaskUrl,
        data.jobId,
        async (text, sourceIds) => {
          const lines = formatAnswer(text).split('\n');
          const inlineRefsByLineIdx = new Map();

          // 목표 구조화 형식(번호 매김 5필드)이면 백엔드가 이미 'ID:' 줄은 지워서 보내고
          // (그건 화면에 보일 텍스트가 아니라 "근거보기" 버튼으로 들어가는 값이라서),
          // source_ids를 답변에 남은 항목과 같은 순서로 보내준다 — 그래서 항목이 몇 번째로
          // 나왔는지만 세어서 순서대로 그대로 짝지으면 된다. 제목/날짜 문자열로 어림짐작하는
          // 것보다 훨씬 정확함.
          const itemLineIdxs = assignStructuredItemLines(lines);
          const isStructured = itemLineIdxs.length > 0 && itemLineIdxs.length === sourceIds.length;

          if (isStructured) {
            sourceIds.forEach((src, i) => {
              const ref = { id: src.id, account: src.account };
              const lineIdx = itemLineIdxs[i];
              if (!inlineRefsByLineIdx.has(lineIdx)) inlineRefsByLineIdx.set(lineIdx, []);
              inlineRefsByLineIdx.get(lineIdx).push(ref);
            });
          } else {
            // 폴백: 모델이 목표 형식을 못 지킨 옛 자유 서술형 답변 — 제목/날짜 기반 매칭
            const uniqueRefs = extractUniqueRefs(sourceIds);
            const subjectsById = domain === 'mail'
              ? await fetchSubjectsByRefs(flaskUrl, uniqueRefs)
              : Object.fromEntries(uniqueRefs.map((ref) => [ref.id, messengerRefSearchKey(ref)]));
            const usedLines = new Set();
            uniqueRefs.forEach((ref) => {
              const subject = subjectsById[ref.id] || '';
              let lineIdx = findLineIdxBySubject(lines, subject, usedLines);
              // 어떤 방식으로도 못 찾은 경우(본문 요약형 답변 등) 근거를 그냥 버리면 사용자
              // 입장에선 "근거메일이 아예 안 뜨는" 것으로 보임. 백엔드가 이미 근거로 판단해서
              // 넘겨준 이상, 특정 줄을 못 찾더라도 아직 다른 근거가 안 붙은 마지막 줄에라도
              // 버튼을 붙여서 항상 보이게 함.
              if (lineIdx === -1) {
                lineIdx = lines.length - 1;
                while (lineIdx > 0 && usedLines.has(lineIdx)) lineIdx -= 1;
              }
              usedLines.add(lineIdx);
              if (!inlineRefsByLineIdx.has(lineIdx)) inlineRefsByLineIdx.set(lineIdx, []);
              inlineRefsByLineIdx.get(lineIdx).push(ref);
            });
          }

          setResult({ query: q, status: 'done', lines, inlineRefsByLineIdx });
        },
        (msg) => setResult({ query: q, status: 'error', message: msg }),
      );
    } catch (e) {
      setResult({ query: q, status: 'error', message: '서버에 연결할 수 없습니다. Flask 서버가 실행 중인지 확인하세요.' });
    }
  }

  // 페이지 URL에 ?q=가 있으면(메일 탭 기준 — 기존 동작 유지) 진입 시 자동으로 그 검색어를 실행
  useEffect(() => {
    if (initialQuery) {
      setQuery(initialQuery);
      runSearch(initialQuery);
    }
  }, []);

  async function loadSourceMail(ref) {
    setActiveMailId(ref.id);
    setMailDetail({ loading: true });
    try {
      const endpoint = SOURCE_BODY_ENDPOINT[domain] || SOURCE_BODY_ENDPOINT.mail;
      const res = await fetch(`${flaskUrl}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: ref.account, mail_id: ref.id }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setMailDetail({ loading: false, error: data.error || '알 수 없는 오류' });
        return;
      }
      setMailDetail({ loading: false, data });
    } catch (e) {
      setMailDetail({ loading: false, error: '서버에 연결할 수 없습니다.' });
    }
  }

  function handleSubmit() {
    const q = query.trim();
    if (!q) return;
    runSearch(q);
  }

  return (
    <div className={`gw-tab-panel${active ? ' active' : ''}`} role="tabpanel">
      <div className="gw-search-top">
        <div className="gw-search-box">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(); }}
            placeholder={placeholder}
            autoComplete="off"
          />
          <button type="button" onClick={handleSubmit}>
            <i className="fas fa-search"></i>
          </button>
        </div>
        {recents.length > 0 && (
          <div className="gw-recent-searches" style={{ display: 'flex' }}>
            <span className="gw-recent-label">
              <i className="fas fa-history me-1"></i>최근 검색:
            </span>
            <div>
              {recents.map((r) => (
                <span key={r} className="gw-recent-tag" onClick={() => { setQuery(r); runSearch(r); }}>
                  <i className="fas fa-history" style={{ fontSize: '0.72rem', color: '#aaa' }}></i>
                  {r}
                  <span
                    className="gw-tag-del"
                    title="삭제"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeRecent(recentKey, r);
                      setRecents(loadRecents(recentKey));
                    }}
                  >
                    ×
                  </span>
                </span>
              ))}
            </div>
            <span
              className="gw-recent-clear"
              onClick={() => { clearRecents(recentKey); setRecents([]); }}
            >
              전체 삭제
            </span>
          </div>
        )}
      </div>

      <div className="gw-result-wrapper">
        {!result && (
          <div className="gw-empty">
            <i className={emptyIcon}></i>
            <p>{emptyText}</p>
          </div>
        )}

        {result && (
          <>
            <div className="gw-query-label">
              검색어: <strong>{result.query}</strong>
            </div>

            {result.status === 'loading' && (
              <div className="gw-loading">
                <div className="gw-spinner"></div>
                <span>{loadingText}</span>
              </div>
            )}

            {result.status === 'error' && (
              <div className="gw-error">
                <i className="fas fa-exclamation-circle me-2"></i>
                {result.message}
              </div>
            )}

            {result.status === 'done' && (
              <div className="gw-answer-frame">
                <div className="gw-answer-main">
                  <div className="gw-result-card">
                    {result.lines.map((line, idx) => {
                      const inlineRefs = result.inlineRefsByLineIdx.get(idx);
                      if (inlineRefs) {
                        return (
                          <div className="gw-answer-line-with-source" key={idx}>
                            <span className="gw-answer-line-text">{line}</span>
                            {inlineRefs.map((ref) => (
                              <button
                                key={`${ref.account || ''}-${ref.id}`}
                                type="button"
                                className={`gw-view-source-mail-btn${activeMailId === ref.id ? ' active' : ''}`}
                                onClick={() => { loadSourceMail(ref); setDrawerOpen(true); }}
                              >
                                {SOURCE_BTN_LABEL[domain] || SOURCE_BTN_LABEL.mail}
                              </button>
                            ))}
                          </div>
                        );
                      }
                      return (
                        <div className="gw-answer-line" key={idx}>
                          {line || ' '}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {result.inlineRefsByLineIdx.size > 0 && (
                  <div className={`gw-mail-drawer${drawerOpen ? ' is-open' : ''}`}>
                    <button
                      type="button"
                      className="gw-mail-drawer-close"
                      title="닫기"
                      onClick={() => { setDrawerOpen(false); setActiveMailId(null); }}
                    >
                      <i className="fas fa-times"></i>
                    </button>
                    <div className="gw-mail-detail-panel">
                      {!mailDetail && (
                        <div className="gw-mail-detail-empty">
                          왼쪽의 "{SOURCE_BTN_LABEL[domain] || SOURCE_BTN_LABEL.mail}"를 누르면 여기에 {domain === 'mail' ? '메일 본문이' : '대화 원문이'} 표시됩니다.
                        </div>
                      )}
                      {mailDetail?.loading && (
                        <div className="gw-mail-detail-loading">
                          <div className="gw-spinner"></div>
                          <span>{domain === 'mail' ? '메일을' : '대화를'} 불러오는 중...</span>
                        </div>
                      )}
                      {mailDetail?.error && (
                        <div className="gw-mail-detail-empty">{domain === 'mail' ? '메일을' : '대화를'} 불러오지 못했습니다: {mailDetail.error}</div>
                      )}
                      {mailDetail?.data && domain === 'mail' && (
                        <>
                          <div className="gw-mail-detail-subject">{mailDetail.data.subject || '(제목 없음)'}</div>
                          <div className="gw-mail-detail-meta">
                            <div><strong>날짜</strong> {mailDetail.data.date || '-'}</div>
                            <div><strong>발신</strong> {mailDetail.data.sender || '-'}</div>
                            <div><strong>수신</strong> {mailDetail.data.receiver || '-'}</div>
                          </div>
                          <div className="gw-mail-detail-body">{mailDetail.data.body || '(본문 없음)'}</div>
                        </>
                      )}
                      {mailDetail?.data && domain === 'messenger' && (
                        <>
                          <div className="gw-mail-detail-subject">{mailDetail.data.room_name || '(채팅방 이름 없음)'}</div>
                          <div className="gw-mail-detail-meta">
                            <div><strong>날짜</strong> {mailDetail.data.date || '-'}</div>
                          </div>
                          <div className="gw-mail-detail-body">
                            {(mailDetail.data.messages || []).length === 0 && '(대화 내용 없음)'}
                            {(mailDetail.data.messages || []).map((m, i) => (
                              <div key={i} style={{ marginBottom: '0.4em' }}>
                                <span style={{ color: '#999', marginRight: '0.5em' }}>{m.time}</span>
                                {m.is_system
                                  ? <span style={{ color: '#999' }}>{m.text}</span>
                                  : <><strong>{m.sender}</strong>: {m.text}</>}
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
