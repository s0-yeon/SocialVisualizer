import { createRoot } from "react-dom/client";
import { useEffect, useRef, useState } from "react";
import Header from "./Header.jsx";
import Footer from "./Footer.jsx";
import MailStatsCard from "./recap/MailStatsCard.jsx";
import KeywordCloudCard from "./recap/KeywordCloudCard.jsx";
import AffinityDonutCard from "./recap/AffinityDonutCard.jsx";
import RelationshipDonutCard from "./recap/RelationshipDonutCard.jsx";
import MonthlyMessageCard from "./recap/MonthlyMessageCard.jsx";
import SyncStatsCard from "./recap/SyncStatsCard.jsx";
import { initAccountPicker } from "../features/accountPicker.js";
import { store } from "../store/globalStore.js";
import { refreshSidebarList } from "./appSidebar.js";
import { initGlobalFilter } from "../utils/filterSync.js";
import { postStat, postRoomStat, rankMailStats, rankChatPeople } from "../features/recapStats.js";

/**
"Recap" 페이지(recap.html) 전체를 감싸는 최상위 React 컴포넌트 — 히어로, 통계 카드, 사이드바(공용 vanilla 모듈)까지 한 번에 마운트한다.
사이드바에서 메일 계정을 고르면 메일 통계 5종을, 메신저 채팅방을 고르면 chatroom 통계 5종을 병렬로 불러와 각각의 카드 세트를 렌더링한다.
선택이 또 바뀌면 늦게 도착한 결과는 화면에 반영하지 않는다(React 이펙트의 표준 ignore-flag 패턴).

Top-level React component wrapping the entire Recap page. Selecting a mail account loads the 5 mail stats; selecting a messenger chatroom loads the 5 chatroom stats, each with its own card set. Stale responses are ignored via the standard effect ignore-flag pattern.
 */

const CACHE_TTL_MS = 5 * 60 * 1000; // 캐시 유효시간(5분)

const LOADING_STATE = { status: "loading" };
const NO_ACCOUNT_ERROR = "인덱싱된 계정이 없습니다. 먼저 메일을 수집해주세요.";

const MAIL_SLOTS = ["sender", "mysent", "keyword", "affinity", "sync"];
const MSG_SLOTS = ["talker", "keyword", "relationship", "monthly", "sync"];

function loadingStates(keys) {
  return Object.fromEntries(keys.map((k) => [k, LOADING_STATE]));
}

function errorStates(keys, message) {
  const state = { status: "error", error: message };
  return Object.fromEntries(keys.map((k) => [k, state]));
}

// 동기화 카드용 공통 처리 — 성공+데이터 있으면 done, 아니면 에러 메시지
function syncCardState(syncResult) {
  return syncResult.status === "fulfilled" && syncResult.value.data
    ? { status: "done", data: syncResult.value.data }
    : {
        status: "error",
        error:
          syncResult.status === "rejected"
            ? "불러오기 실패: " + syncResult.reason.message
            : "데이터가 없습니다.",
      };
}

// Promise.allSettled 결과 5개(메일)를 각 카드가 바로 쓸 수 있는 state로 변환
function buildCardStates([mailStatsResult, keywordResult, affinityResult, syncResult]) {
  const mailData = mailStatsResult.status === "fulfilled" ? mailStatsResult.value.data || {} : {};
  const sender = { status: "done", ranked: rankMailStats(mailData, "received") };
  const mysent = { status: "done", ranked: rankMailStats(mailData, "sent") };

  const keyword = {
    status: "done",
    data: keywordResult.status === "fulfilled" ? keywordResult.value.data : null,
  };
  const affinity = {
    status: "done",
    data: affinityResult.status === "fulfilled" ? affinityResult.value.data : null,
  };

  return { sender, mysent, keyword, affinity, sync: syncCardState(syncResult) };
}

// Promise.allSettled 결과 5개(메신저)를 각 카드가 바로 쓸 수 있는 state로 변환
function buildMessengerCardStates([peopleResult, keywordResult, relationshipResult, monthlyResult, syncResult]) {
  const peopleData = peopleResult.status === "fulfilled" ? peopleResult.value.data || {} : {};
  const talker = { status: "done", ranked: rankChatPeople(peopleData) };

  const keyword = {
    status: "done",
    data: keywordResult.status === "fulfilled" ? keywordResult.value.data : null,
  };
  const relationship = {
    status: "done",
    data: relationshipResult.status === "fulfilled" ? relationshipResult.value.data : null,
  };
  const monthly = {
    status: "done",
    data: monthlyResult.status === "fulfilled" ? monthlyResult.value.data : null,
  };

  return { talker, keyword, relationship, monthly, sync: syncCardState(syncResult) };
}

function resolveName() {
  const params = new URLSearchParams(window.location.search);
  const nameParam = params.get("name");
  const name = nameParam
    ? decodeURIComponent(nameParam)
    : sessionStorage.getItem("gw_user_name") || "-";
  if (nameParam) sessionStorage.setItem("gw_user_name", decodeURIComponent(nameParam));
  const gmailIdParam = params.get("gmail_id");
  if (gmailIdParam) localStorage.setItem("gw_user_id", decodeURIComponent(gmailIdParam));
  return name;
}

// 채팅방 id → 사이드바에 표시되는 채팅방 이름(store가 이미 resolve해 둔 값)
function resolveRoomLabel(roomId) {
  if (!roomId) return "";
  const { rooms = [] } = store.getCollectedLists() || {};
  const found = rooms.find((r) => r.id === roomId);
  return found ? found.label : "";
}

function RecapApp() {
  const [name] = useState(resolveName);
  const [filterState, setFilterState] = useState(null);
  const [mode, setMode] = useState("mail"); // "mail" | "messenger"
  const [cardStates, setCardStates] = useState(() => loadingStates(MAIL_SLOTS));
  const cacheRef = useRef(new Map()); // "mail:<id>" / "room:<id>" -> { timestamp, results }

  // 사이드바 + 계정 선택 상태 동기화는 공용 vanilla 모듈(filterSync.js/appSidebar.js)이 전담.
  useEffect(() => {
    initGlobalFilter((fs) => setFilterState(fs));

    initAccountPicker(document.getElementById("account-picker-mount"), (selectedMail) => {
      if (selectedMail) {
        store.setFilter("mail", selectedMail);
        refreshSidebarList();
      }
    });
  }, []);

  useEffect(() => {
    if (!filterState) return;

    // ── 메신저 채팅방 선택 ──────────────────────────────
    if (filterState.room) {
      const roomId = filterState.room;
      setMode("messenger");
      setCardStates(loadingStates(MSG_SLOTS));

      const cacheKey = "room:" + roomId;
      const cached = cacheRef.current.get(cacheKey);
      if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
        setCardStates(buildMessengerCardStates(cached.results));
        return;
      }

      let ignore = false;
      Promise.allSettled([
        postRoomStat("/chatroom-people", roomId),
        postRoomStat("/chatroom-keyword-stats", roomId),
        postRoomStat("/chatroom-relationship-stats", roomId),
        postRoomStat("/chatroom-monthly-message-stats", roomId),
        postRoomStat("/chatroom-sync-stats", roomId),
      ]).then((results) => {
        cacheRef.current.set(cacheKey, { timestamp: Date.now(), results });
        if (ignore) return;
        setCardStates(buildMessengerCardStates(results));
      });

      return () => {
        ignore = true;
      };
    }

    // ── 메일 계정 선택 ────────────────────────────────
    setMode("mail");

    const gmailId = filterState.mail;
    if (!gmailId) {
      setCardStates(errorStates(MAIL_SLOTS, NO_ACCOUNT_ERROR));
      return;
    }

    setCardStates(loadingStates(MAIL_SLOTS));

    const cacheKey = "mail:" + gmailId;
    const cached = cacheRef.current.get(cacheKey);
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      setCardStates(buildCardStates(cached.results));
      return;
    }

    let ignore = false;
    Promise.allSettled([
      postStat("/mail-stats", gmailId),
      postStat("/keyword-stats", gmailId),
      postStat("/high_affinity_person_stats", gmailId),
      postStat("/mail_sync_stats", gmailId),
      postStat("/user_rating_stats", gmailId),
    ]).then((results) => {
      // 다섯 API를 기다리는 동안 다른 선택이 됐으면(=ignore) 낡은 데이터다.
      // 캐시에는 넣어 두되 화면에는 반영하지 않는다.
      cacheRef.current.set(cacheKey, { timestamp: Date.now(), results });
      if (ignore) return;
      setCardStates(buildCardStates(results));
    });

    return () => {
      ignore = true;
    };
  }, [filterState]);

  const isMessenger = mode === "messenger" && !!filterState?.room;
  const roomName = isMessenger ? resolveRoomLabel(filterState.room) : "";

  const heroLabel = isMessenger ? "Messenger Analytics" : "Mail Analytics";
  const heroSub = isMessenger
    ? roomName
      ? `${roomName} 채팅방의 대화 통계를 보여줍니다`
      : "메신저 대화 통계 한눈에 보기"
    : name !== "-"
      ? `${name}님의 전체적인 통계를 보여줍니다`
      : "내 메일함 통계 한눈에 보기";

  return (
    <>
      <Header activePage="recap" />
      <div id="app-sidebar"></div>
      <main className="right_col" role="main" style={{ padding: 0, overflowY: "auto" }}>
        <div className="rc-hero">
          <div className="rc-hero-inner">
            <div className="rc-hero-label">{heroLabel}</div>
            <div className="rc-hero-title">📊 Recap</div>
            <div className="rc-hero-sub">{heroSub}</div>
          </div>
          <a href="graphviz.html" className="rc-hero-graph-link">
            <span>knowledge graph</span>
            <span className="rc-hero-graph-arrow">→</span>
          </a>
        </div>

        <div className="rc-content">
          {isMessenger ? (
            <>
              <MailStatsCard
                icon="💬"
                iconBg="#eef6f0"
                title="가장 많이 말한 사람"
                tag="TOP TALKER"
                unit="개 메시지"
                barUnit="개"
                secondary="bio"
                state={cardStates.talker || LOADING_STATE}
              />

              <div className="rc-grid2">
                <KeywordCloudCard
                  title="채팅방 주요 키워드"
                  iconBg="#eef6f0"
                  state={cardStates.keyword || LOADING_STATE}
                />
                <RelationshipDonutCard state={cardStates.relationship || LOADING_STATE} />
              </div>

              <MonthlyMessageCard state={cardStates.monthly || LOADING_STATE} />

              <SyncStatsCard
                title="메신저 동기화 현황"
                countField="message_count"
                countLabel="동기화된 메시지"
                countUnit="개"
                state={cardStates.sync || LOADING_STATE}
              />
            </>
          ) : (
            <>
              <div className="rc-grid2">
                <MailStatsCard
                  icon="📨"
                  iconBg="#fff9e6"
                  title="나에게 많이 보낸 사람"
                  tag="TOP RECEIVER"
                  unit="통 받음"
                  state={cardStates.sender || LOADING_STATE}
                />
                <MailStatsCard
                  icon="📤"
                  iconBg="#e8f4fd"
                  title="내가 많이 보낸 사람"
                  tag="TOP SENT"
                  unit="통 보냄"
                  state={cardStates.mysent || LOADING_STATE}
                />
              </div>

              <div className="rc-grid2">
                <KeywordCloudCard state={cardStates.keyword || LOADING_STATE} />
                <AffinityDonutCard state={cardStates.affinity || LOADING_STATE} />
              </div>

              <SyncStatsCard state={cardStates.sync || LOADING_STATE} />
            </>
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}

// #containerId 엘리먼트에 RecapApp을 React 루트로 마운트
export function mountRecapApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<RecapApp />);
}
