/**
메일/메신저 계정을 선택하는 드롭다운 위젯.
GET /accounts로 인덱싱된 계정 목록을 받아 <select>를 그려주고, 선택된 user_id(또는 chatroom_id)를 localStorage에 저장 후 반환한다.

Account/chatroom picker dropdown — fetches indexed accounts via GET /accounts, renders a <select>, and persists the chosen user_id/chatroom_id to localStorage.
 */

/**
계정 선택 드롭다운 — GET /accounts로 인덱싱된 계정(또는 카카오 대화방) 목록을 가져와 container 안에 <select>를 렌더링하고, 확정된 user_id를 반환한다.
(해당 페이지에서만 명시적으로 호출 — bootstrapApp()에는 연결하지 않음)
 */

/** 화면에 보여줄 계정 라벨을 반환 — 항상 실제 계정 id 그대로. */
export function displayAccountLabel(userId) {
  return userId;
}

export async function initAccountPicker(container, onChange, options = {}) {
  const { domain = "mail", storageKey = "gw_user_id" } = options;
  injectStyle();

  const current = localStorage.getItem(storageKey) || "";
  let effective = current;

  let select = null;
  if (container) {
    container.innerHTML = "";
    select = document.createElement("select");
    select.id = "account-picker";
    select.className = "gw-account-picker";
    const loadingOpt = document.createElement("option");
    loadingOpt.textContent = "계정 불러오는 중...";
    select.appendChild(loadingOpt);
    container.appendChild(select);
  }

  try {
    const res = await fetch("/accounts?domain=" + encodeURIComponent(domain));
    const data = await res.json();
    const accounts = data.accounts || [];

    // 메신저(카카오 등)는 user_id가 40자리 chatroom_id 해시라 그대로 보여주면 어느 방인지 알 수 없음 — POST /chatroom-name으로 방마다 실제 이름을 받아와 드롭다운 라벨에만 쓴다(값/저장은 여전히 chatroom_id 기준, 이름은 표시용).
    // 이름 조회가 실패(400/404)한 방은 그냥 원래 id를 그대로 보여준다.
    let nameById = {};
    if (domain === "messenger" && accounts.length > 0) {
      const names = await Promise.all(accounts.map((acc) => fetchChatroomName(acc.user_id)));
      accounts.forEach((acc, i) => {
        if (names[i]) nameById[acc.user_id] = names[i];
      });
    }

    if (select) {
      select.innerHTML = "";
      if (accounts.length === 0) {
        const opt = document.createElement("option");
        opt.textContent = domain === "mail" ? "인덱싱된 계정 없음" : "인덱싱된 대화방 없음";
        select.appendChild(opt);
      } else {
        const hasCurrent = accounts.some((acc) => acc.user_id === current);
        effective = hasCurrent ? current : accounts[0].user_id;
        accounts.forEach((acc) => {
          const opt = document.createElement("option");
          opt.value = acc.user_id;
          const label = nameById[acc.user_id] || displayAccountLabel(acc.user_id);
          opt.textContent = label + (acc.indexed ? "" : " (인덱싱 중)");
          if (acc.user_id === effective) opt.selected = true;
          select.appendChild(opt);
        });
        select.onchange = () => {
          localStorage.setItem(storageKey, select.value);
          if (onChange) {
            onChange(select.value);
          } else {
            location.reload();
          }
        };
      }
    } else if (accounts.length > 0) {
      const hasCurrent = accounts.some((acc) => acc.user_id === current);
      effective = hasCurrent ? current : accounts[0].user_id;
    }
  } catch (err) {
    console.error("[accounts] 로드 실패:", err);
  }

  localStorage.setItem(storageKey, effective);
  return effective;
}

/**
POST /chatroom-name — chatroom_id로 실제 채팅방 이름을 조회.
400/404 등 실패 시 null을 반환해서 호출부가 원래 id로 폴백할 수 있게 한다.
 */
async function fetchChatroomName(chatroomId) {
  try {
    const res = await fetch("/chatroom-name", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chatroom_id: chatroomId }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data?.data?.chatroom_name || null;
  } catch (err) {
    return null;
  }
}

// 계정 선택 드롭다운 전용 스타일을 한 번만 <head>에 주입
function injectStyle() {
  if (document.getElementById("gw-account-picker-style")) return;
  const style = document.createElement("style");
  style.id = "gw-account-picker-style";
  style.textContent = `
    .gw-account-picker { padding:7px 12px; border-radius:8px; border:1px solid #dde3ea; font-size:0.85rem; background:#fff; color:#2A3F54; cursor:pointer; }
    .gw-account-picker:focus { outline:none; border-color:#8a8a8a; box-shadow:0 0 0 3px rgba(138, 138, 138,0.12); }
  `;
  document.head.appendChild(style);
}
