import { useEffect, useState } from 'react';
import {
  fetchSubjectsByRefs,
  findLineIdxBySubject,
  formatAnswer,
  extractUniqueMailRefs,
  loadRecents,
  saveRecent,
  removeRecent,
  clearRecents,
  pollJob,
} from '../../features/graphragSearch.js';

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
          const uniqueMailRefs = extractUniqueMailRefs(domain, sourceIds);
          const subjectsById = await fetchSubjectsByRefs(flaskUrl, uniqueMailRefs);
          const lines = formatAnswer(text).split('\n');
          const inlineRefsByLineIdx = new Map();
          const usedLines = new Set();
          uniqueMailRefs.forEach((ref) => {
            const subject = subjectsById[ref.id] || '';
            let lineIdx = findLineIdxBySubject(lines, subject, usedLines);
            // 제목이 답변 문장 어디와도 안 겹치는 경우(본문 요약형 답변 등) 근거를 그냥
            // 버리면 사용자 입장에선 "근거메일이 아예 안 뜨는" 것으로 보임. 백엔드가 이미
            // 근거로 판단해서 넘겨준 이상, 특정 줄을 못 찾더라도 아직 다른 근거가 안 붙은
            // 마지막 줄에라도 버튼을 붙여서 항상 보이게 함.
            if (lineIdx === -1) {
              lineIdx = lines.length - 1;
              while (lineIdx > 0 && usedLines.has(lineIdx)) lineIdx -= 1;
            }
            usedLines.add(lineIdx);
            if (!inlineRefsByLineIdx.has(lineIdx)) inlineRefsByLineIdx.set(lineIdx, []);
            inlineRefsByLineIdx.get(lineIdx).push(ref);
          });
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
      const res = await fetch(`${flaskUrl}/mail-body-by-ids`, {
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
                                key={ref.id}
                                type="button"
                                className={`gw-view-source-mail-btn${activeMailId === ref.id ? ' active' : ''}`}
                                onClick={() => { loadSourceMail(ref); setDrawerOpen(true); }}
                              >
                                근거메일 보기
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
                          왼쪽의 "근거메일 보기"를 누르면 여기에 메일 본문이 표시됩니다.
                        </div>
                      )}
                      {mailDetail?.loading && (
                        <div className="gw-mail-detail-loading">
                          <div className="gw-spinner"></div>
                          <span>메일을 불러오는 중...</span>
                        </div>
                      )}
                      {mailDetail?.error && (
                        <div className="gw-mail-detail-empty">메일을 불러오지 못했습니다: {mailDetail.error}</div>
                      )}
                      {mailDetail?.data && (
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
