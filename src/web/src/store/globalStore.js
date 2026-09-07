// src/store/globalStore.js

/**
선택된 메일/채팅방 필터와 수집된 계정·채팅방 목록을 관리하는 전역 스토어(싱글턴). 백엔드 /accounts, /messenger-chatrooms를 호출해 목록을 갱신하고, 선택 상태가 실제로 바뀔 때만 gwStoreStateChanged 이벤트를 쏴서 사이드바/각 페이지를 동기화한다.

Singleton global store for the selected mail/room filter and the fetched account/chatroom lists.
Refreshes lists via the backend's /accounts and /messenger-chatrooms, and fires a gwStoreStateChanged event only when the selection actually changes.
 */

const STORAGE_KEYS = {
  MAIL: "gw_selected_mail",
  ROOM: "gw_selected_room",
  MAILS_LIST: "gw_collected_mails",
  ROOMS_LIST: "gw_collected_rooms",
};

/* My People / My Time / Recap 페이지에서 화면에 그려지지 않고 헤드리스로 호출되는 계정 선택기(features/accountPicker.js)가 실제로 읽고 쓰는 키(화면에 계정 선택기가 보이는 페이지는 GraphViz 하나뿐이다). 사이드바 전용 키(gw_selected_mail/gw_selected_room)와 이 값이 서로 다르면 URL로 넘어온 계정과 사이드바가 고른 계정이 어긋나 보이므로,setFilter에서 항상 같이 갱신해 두 값이 하나를 공유하게 한다.*/
const LEGACY_KEYS = {
  MAIL: "gw_user_id",
  ROOM: "gw_chatroom_id",
};

class GlobalStore {
  constructor() {
    this.state = {
      selectedMail:
        localStorage.getItem(STORAGE_KEYS.MAIL) || localStorage.getItem(LEGACY_KEYS.MAIL) || "",
      selectedRoom:
        localStorage.getItem(STORAGE_KEYS.ROOM) || localStorage.getItem(LEGACY_KEYS.ROOM) || "",
      collectedMails: JSON.parse(localStorage.getItem(STORAGE_KEYS.MAILS_LIST) || "[]"),
      collectedRooms: JSON.parse(localStorage.getItem(STORAGE_KEYS.ROOMS_LIST) || "[]"),
    };

    this.debounceTimer = null;
  }

  // [백엔드 DB 실제 연동] 80번 포트 Flask API 동시 호출 계정 토글(accountPicker.js)이 쓰는 것과 완전히 같은 엔드포인트/파싱을 그대로 가져와서 쓴다
  async fetchCollectedLists() {
    try {
      // 1. 메일 계정 — 계정 토글과 동일하게 GET /accounts?domain=mail
      const mailPromise = fetch("/accounts?domain=mail")
        .then((res) => (res.ok ? res.json() : { accounts: [] }))
        .catch(() => ({ accounts: [] }));

      // 2. 메신저 채팅방 — /messenger-chatrooms는 방마다 chatroom_name을 이미 서버(list_indexed_chatrooms)에서 resolve해서 내려주므로, 계정 토글처럼 방 하나하나 /chatroom-name을 또 부를 필요 없이 그 이름을 그대로 쓴다.
      const roomPromise = fetch("/messenger-chatrooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
        .then((res) => (res.ok ? res.json() : { data: { chatrooms: [] } }))
        .catch(() => ({ data: { chatrooms: [] } }));

      const [mailsData, roomsData] = await Promise.all([mailPromise, roomPromise]);

      // {id, label, indexed} 형태로 통일 — id: data-value/필터에 쓰는 실제 값,
      // label: 화면에 보여줄 이름.
      const mails = (mailsData.accounts || []).map((acc) => ({
        id: acc.user_id,
        label: acc.user_id,
        indexed: !!acc.indexed,
      }));

      const chatrooms = (roomsData.data && roomsData.data.chatrooms) || [];
      const rooms = chatrooms.map((r) => ({
        id: r.chatroom_id,
        label: r.chatroom_name || r.chatroom_id,
        indexed: r.indexed !== false,
      }));

      // DB 데이터로 스토어 상태 갱신
      this.setCollectedLists(mails, rooms);
    } catch (err) {
      console.error("DB 수집 목록 조회 중 오류 발생:", err);
    }
  }

  setCollectedLists(mails = [], rooms = []) {
    // 인덱싱 상태를 주기적으로 다시 불러올 때(filterSync.js의 폴링) 목록 내용이 실제로는 그대로인데도 매번 gwStoreStateChanged를 쏘면, 이 이벤트를 듣는 페이지들이 "사용자가 계정을 바꿨다"고 착각하고 데이터를 계속 처음부터 다시 불러온다. 실제로 목록 내용이 달라졌을 때만 이벤트를 쏘도록 비교한다.
    const nextMailsJson = JSON.stringify(mails);
    const nextRoomsJson = JSON.stringify(rooms);
    const changed =
      nextMailsJson !== JSON.stringify(this.state.collectedMails) ||
      nextRoomsJson !== JSON.stringify(this.state.collectedRooms);

    this.state.collectedMails = mails;
    this.state.collectedRooms = rooms;

    localStorage.setItem(STORAGE_KEYS.MAILS_LIST, nextMailsJson);
    localStorage.setItem(STORAGE_KEYS.ROOMS_LIST, nextRoomsJson);

    if (!changed) return;

    window.dispatchEvent(
      new CustomEvent("gwStoreStateChanged", {
        detail: this.getFilterState(),
      })
    );
  }

  getFilterState() {
    return {
      mail: this.state.selectedMail,
      room: this.state.selectedRoom,
    };
  }

  // 메일/메신저 선택을 하나의 트랜잭션으로 원자적으로 갱신한다.

  // mail/room 값을 한 번에 같이 넘겨서 중간 상태 자체가 생기지 않게
  // 하고, 실제로 값이 바뀌었을 때만(변화 없으면 재호출돼도 무시) 이벤트를
  // 딱 한 번만 쏘도록 한다.
  applySelection(mail, room) {
    const nextMail = mail || null;
    const nextRoom = room || null;
    const changed =
      nextMail !== (this.state.selectedMail || null) ||
      nextRoom !== (this.state.selectedRoom || null);

    this.state.selectedMail = nextMail;
    this.state.selectedRoom = nextRoom;

    if (nextMail) {
      localStorage.setItem(STORAGE_KEYS.MAIL, nextMail);
      localStorage.setItem(LEGACY_KEYS.MAIL, nextMail); // 페이지 상단 계정 토글과 동기화
      localStorage.removeItem(STORAGE_KEYS.ROOM);
    } else if (nextRoom) {
      localStorage.setItem(STORAGE_KEYS.ROOM, nextRoom);
      localStorage.setItem(LEGACY_KEYS.ROOM, nextRoom); // 페이지 상단 채팅방 토글과 동기화
      localStorage.removeItem(STORAGE_KEYS.MAIL);
    } else {
      localStorage.removeItem(STORAGE_KEYS.MAIL);
      localStorage.removeItem(STORAGE_KEYS.ROOM);
    }

    // 값이 실제로 안 바뀌었으면(같은 항목을 다시 클릭했거나, 위에서 설명한 재진입 상황) 굳이 이벤트를 또 쏘지 않는다 — 이게 재귀적 중복 호출을 막는 마지막 안전장치.
    if (!changed) return;

    //페이지가 데이터를 누르고 나서 잠깐 멈칫하는 느낌이 있었다 — 디바운스 없이 즉시 이벤트를 쏘도록 바꿈.
    if (this.debounceTimer) clearTimeout(this.debounceTimer);

    window.dispatchEvent(
      new CustomEvent("gwStoreStateChanged", {
        detail: this.getFilterState(),
      })
    );
  }

  // 기존 호출부(appSidebar.js 등)와의 호환을 위해 남겨둔 래퍼 — 내부적으로는 applySelection()으로 위임해서 항상 원자적으로 처리된다.
  setFilter(type, value) {
    if (type === "mail") {
      this.applySelection(value, null);
    } else if (type === "room") {
      this.applySelection(null, value);
    }
  }

  getCollectedLists() {
    return {
      mails: this.state.collectedMails,
      rooms: this.state.collectedRooms,
    };
  }
}

export const store = new GlobalStore();
