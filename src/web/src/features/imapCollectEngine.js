/**
"소셜 데이터 분석" 수집 페이지 엔진 — IMAP 메일 수집과 카카오톡 대화 업로드를 담당한다.
순수 함수/상태(로그·job 목록 관리, SSE 추적, 폼 검증 등)는 모듈 스코프에 두고, DOM에 직접 손을 대는 이벤트 바인딩·초기화 코드는 initImapCollectPage()로 묶어 React 마운트 후 한 번 호출한다.

Engine module for the social-data collection page — handles IMAP mail collection and KakaoTalk chat-log uploads.
Pure functions/state (log and job list management, SSE tracking, form validation, etc.) live at module scope; the DOM-touching event-binding/init code is wrapped into initImapCollectPage(), called once after the React component mounts.
 */
import { getApiBase } from "../utils/apiBase.js";

function now() {
  return new Date().toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const IMAP_JOBS_STORAGE_KEY = "gw_imap_jobs";
const IMAP_JOBS_STORAGE_MAX = 15;

function loadStoredImapJobs() {
  try {
    const raw = JSON.parse(localStorage.getItem(IMAP_JOBS_STORAGE_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function addStoredImapJob(jobId, user) {
  const jobs = loadStoredImapJobs();
  jobs.push({ jobId, user });
  localStorage.setItem(IMAP_JOBS_STORAGE_KEY, JSON.stringify(jobs.slice(-IMAP_JOBS_STORAGE_MAX)));
}

function removeStoredImapJob(jobId) {
  const jobs = loadStoredImapJobs().filter((j) => j.jobId !== jobId);
  localStorage.setItem(IMAP_JOBS_STORAGE_KEY, JSON.stringify(jobs));
}

const MESSAGE_JOBS_STORAGE_KEY = "gw_message_jobs";

function loadStoredMessageJobs() {
  try {
    const raw = JSON.parse(localStorage.getItem(MESSAGE_JOBS_STORAGE_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function addStoredMessageJob(jobId, user) {
  const jobs = loadStoredMessageJobs();
  jobs.push({ jobId, user });
  localStorage.setItem(
    MESSAGE_JOBS_STORAGE_KEY,
    JSON.stringify(jobs.slice(-IMAP_JOBS_STORAGE_MAX))
  );
}

function removeStoredMessageJob(jobId) {
  const jobs = loadStoredMessageJobs().filter((j) => j.jobId !== jobId);
  localStorage.setItem(MESSAGE_JOBS_STORAGE_KEY, JSON.stringify(jobs));
}

function dismissJobPanel(panelEl, collectJobId, kind = "mail") {
  if (kind === "message") removeStoredMessageJob(collectJobId);
  else removeStoredImapJob(collectJobId);
}

function toggleCustomLimit() {
  const select = document.getElementById("collect-limit");
  const customInput = document.getElementById("collect-limit-custom");
  customInput.style.display = select.value === "custom" ? "" : "none";
}

function applyPreset(el) {
  document.querySelectorAll(".gw-preset-chip").forEach((c) => c.classList.remove("active"));
  el.classList.add("active");

  const host = el.dataset.host;
  const port = el.dataset.port;
  const domain = el.dataset.domain || "";
  document.getElementById("imap-host").value = host;
  document.getElementById("imap-port").value = port;

  // 이메일 칸: 다른 프리셋으로 바꾸면 이전에 입력한 아이디는 지우고 "@도메인"만 새로 채움
  const userInput = document.getElementById("imap-user");
  if (domain) {
    userInput.value = "@" + domain;
    userInput.focus();
    // focus() 직후 브라우저가 자체적으로 커서를 맨 뒤로 보내는 경우가 있어서, 그 동작이 끝난 다음 틱에 커서 위치를 다시 맨 앞으로 강제 설정함
    setTimeout(() => userInput.setSelectionRange(0, 0), 0);
  } else {
    userInput.value = "";
  }

  // 다른 서비스로 바꾸면 이전 계정용 비밀번호는 의미가 없으니 같이 비움
  document.getElementById("imap-pass").value = "";
}

function resetForm() {
  const gmailChip = document.querySelector('.gw-preset-chip[data-host="imap.gmail.com"]');
  if (gmailChip) applyPreset(gmailChip);

  document.getElementById("folder-list").innerHTML =
    '<span class="gw-folder-empty">"폴더 불러오기"를 눌러 수집할 폴더를 선택하세요.</span>';
  document.getElementById("select-all-btn").style.display = "none";
  document.getElementById("folder-list-hint").textContent = "";

  document.getElementById("collect-limit").value = "0";
  toggleCustomLimit();
  document.getElementById("collect-limit-custom").value = "";
  document.getElementById("sync-mode").value = "rewrite";
}

function toggleFolder(checkbox) {
  const item = checkbox.closest(".gw-folder-item");
  if (checkbox.checked) {
    item.classList.add("checked");
  } else {
    item.classList.remove("checked");
  }
}

function getSelectedFolders() {
  return Array.from(
    document.querySelectorAll('.gw-folder-item input[type="checkbox"]:checked')
  ).map((cb) => cb.value);
}

function renderFolderList(folders) {
  const container = document.getElementById("folder-list");
  const selectAllBtn = document.getElementById("select-all-btn");
  container.innerHTML = "";

  if (!folders || folders.length === 0) {
    const empty = document.createElement("span");
    empty.className = "gw-folder-empty";
    empty.textContent = "폴더를 찾을 수 없습니다.";
    container.appendChild(empty);
    selectAllBtn.style.display = "none";
    return;
  }

  folders.forEach((folder) => {
    const isInbox = folder.toUpperCase() === "INBOX";

    const label = document.createElement("label");
    label.className = "gw-folder-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = folder;
    checkbox.checked = false;
    checkbox.addEventListener("change", () => toggleFolder(checkbox));

    const icon = document.createElement("i");
    icon.className = isInbox ? "bi bi-inbox" : "bi bi-folder";

    const span = document.createElement("span");
    span.className = "gw-folder-label";
    span.textContent = folder;

    label.appendChild(checkbox);
    label.appendChild(icon);
    label.appendChild(span);
    container.appendChild(label);
  });

  selectAllBtn.style.display = "";
  selectAllBtn.textContent = "전체 선택";
}

function toggleSelectAll() {
  const checkboxes = document.querySelectorAll('#folder-list input[type="checkbox"]');
  if (checkboxes.length === 0) return;

  const allChecked = Array.from(checkboxes).every((cb) => cb.checked);
  checkboxes.forEach((cb) => {
    cb.checked = !allChecked;
    toggleFolder(cb);
  });

  document.getElementById("select-all-btn").textContent = allChecked ? "전체 선택" : "전체 해제";
}

async function listFolders() {
  const flaskUrl = getApiBase();
  const host = document.getElementById("imap-host").value.trim();
  const port = parseInt(document.getElementById("imap-port").value) || 993;
  const ssl = document.getElementById("imap-ssl").value === "true";
  const user = document.getElementById("imap-user").value.trim();
  const pass = document.getElementById("imap-pass").value;

  const btn = document.getElementById("list-folders-btn");
  const hint = document.getElementById("folder-list-hint");

  if (!host) {
    alert("IMAP 호스트를 입력하세요.");
    return;
  }
  if (!user) {
    alert("메일 주소를 입력하세요.");
    return;
  }
  if (!pass) {
    alert("앱 비밀번호를 입력하세요.");
    return;
  }
  if (!flaskUrl) {
    alert("Flask 서버 URL이 설정되지 않았습니다.\n/init 페이지를 먼저 방문하세요.");
    return;
  }

  btn.disabled = true;
  hint.style.color = "#73879C";
  hint.textContent = "폴더 목록을 불러오는 중...";

  try {
    const res = await fetch(`${flaskUrl}/imap-list-folders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host, port, ssl, user, password: pass }),
    });

    const data = await res.json();

    if (!res.ok || !data.ok) {
      throw new Error(data.error || `서버 오류 (${res.status})`);
    }

    renderFolderList(data.folders || []);
    hint.style.color = "#1a9e6e";
    hint.textContent = `${data.folders.length}개 폴더를 찾았습니다.`;
  } catch (err) {
    hint.style.color = "#a32d2d";
    hint.textContent = `❌ ${err.message}`;
    console.error("[imap-list-folders]", err);
  } finally {
    btn.disabled = false;
  }
}

function jobAddLog(panelEl, msg, type = "") {
  const body = panelEl.querySelector(".job-log-body");
  const line = document.createElement("div");
  line.className = "gw-log-line";
  line.innerHTML = `
    <span class="gw-log-ts">${now()}</span>
    <span class="gw-log-msg ${type}">${msg}</span>
  `;
  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
}

function jobSetStatus(panelEl, status, label) {
  const badge = panelEl.querySelector(".job-status-badge");
  const dot = panelEl.querySelector(".job-status-dot");
  const text = panelEl.querySelector(".job-status-text");
  badge.className = `gw-status-badge job-status-badge ${status}`;
  dot.className = `gw-status-dot job-status-dot ${status === "running" ? "running" : ""}`;
  text.textContent = label;
}

function jobSetProgress(panelEl, pct) {
  panelEl.querySelector(".job-progress-bar").style.width = pct + "%";
}

function createJobPanel(user, kind = "mail") {
  const jobsList = document.getElementById(kind === "message" ? "message-jobs-list" : "jobs-list");
  const empty = jobsList.querySelector(".gw-log-empty");
  if (empty) empty.remove();

  const panelEl = document.createElement("div");
  panelEl.className = "gw-log-panel visible";
  panelEl.innerHTML = `
    <div class="gw-log-header">
      <div class="gw-log-header-left">
        <i class="bi bi-terminal" style="color:#26B99A;"></i>
        ${user}
      </div>
      <div class="gw-status-badge running job-status-badge">
        <span class="gw-status-dot running job-status-dot"></span>
        <span class="job-status-text">시작 중</span>
      </div>
    </div>
    <div class="gw-progress-bar-wrap">
      <div class="gw-progress-bar-fill job-progress-bar" style="width:5%;"></div>
    </div>
    <div class="gw-log-body job-log-body"></div>
  `;
  jobsList.prepend(panelEl);
  return panelEl;
}

const activeJobs = new Map(); // job_id -> { panelEl, phase: 'collect' | 'index', collectJobId, user }
let sseConn = null;

function ensureSSE(flaskUrl) {
  if (sseConn) return sseConn;
  sseConn = new EventSource(`${flaskUrl}/indexing-stream`);
  sseConn.onmessage = (e) => {
    let data;
    try {
      data = JSON.parse(e.data);
    } catch {
      return;
    }
    if (data && data.job_id) handleJobEvent(data);
  };
  sseConn.onerror = () => {
    // 브라우저가 자동으로 재연결을 시도하므로 별도 처리 없이 로그만 남김
    console.warn("[imap-collect] SSE 연결 끊김, 자동 재연결 시도 중...");
  };
  return sseConn;
}

function handleJobEvent(data) {
  const entry = activeJobs.get(data.job_id);
  if (!entry) return; // 이 페이지가 추적 중인 job이 아니면 무시 (다른 계정/다른 탭의 이벤트일 수 있음)

  const { panelEl, phase, collectJobId, user, kind = "mail" } = entry;

  if (data.type === "progress") {
    if (data.message) jobAddLog(panelEl, data.message, phase === "index" ? "info" : "");
    return;
  }

  if (data.type === "failed") {
    jobSetStatus(panelEl, "failed", phase === "index" ? "인덱싱 중단" : "실패");
    jobAddLog(panelEl, `❌ ${data.message || "오류가 발생했습니다."}`, "error");
    activeJobs.delete(data.job_id);
    dismissJobPanel(panelEl, collectJobId, kind);
    return;
  }

  if (data.type !== "done") return;

  if (phase === "index") {
    jobSetStatus(panelEl, "done", "인덱싱 완료");
    jobAddLog(panelEl, `✅ 인덱싱 완료`, "success");
    activeJobs.delete(data.job_id);
    dismissJobPanel(panelEl, collectJobId, kind);
    return;
  }

  // phase === 'collect'
  const result = data.result || {};
  activeJobs.delete(data.job_id);

  if (result.ok === false) {
    jobSetStatus(panelEl, "failed", "실패");
    jobAddLog(panelEl, `❌ ${result.error || "알 수 없는 오류"}`, "error");
    dismissJobPanel(panelEl, collectJobId, kind);
    return;
  }

  // 이후 대시보드(index.html 등)가 이 값을 user_id로 사용한다.
  // 카카오는 조회 UI 스코프 밖이라 건드리지 않음.
  if (kind === "mail") {
    localStorage.setItem("gw_user_id", user);
  }

  jobSetProgress(panelEl, 100);
  jobSetStatus(panelEl, "done", "완료");
  jobAddLog(panelEl, kind === "message" ? `✅ 업로드 완료` : `✅ 수집 완료`, "success");
  jobAddLog(
    panelEl,
    `${kind === "message" ? "저장" : "수집"}: ${result.added_count}개 / 중복 스킵: ${result.skipped_count}개`,
    "success"
  );

  if (result.job_id) {
    jobAddLog(
      panelEl,
      `인덱싱 job_id: ${result.job_id} — 인덱싱이 백그라운드에서 실행됩니다.`,
      "info"
    );
    jobSetStatus(panelEl, "running", "인덱싱 중");
    jobAddLog(panelEl, "인덱싱이 백그라운드에서 진행 중입니다...", "info");
    // 서버가 재시작되면 job 저장소가 메모리 기반이라 인덱싱 job 정보가 통째로 사라진다.
    // SSE만 기다리면 그 사실을 영영 알 수 없어서 "인덱싱 중"에 멈춰있게 되므로, 여기서도 collect phase와 동일하게 REST로 한 번 상태를 확인(catch-up)한 뒤 SSE로 이어받는다.
    trackCollectJob(getApiBase(), result.job_id, panelEl, user, kind, "index", collectJobId);
  } else {
    dismissJobPanel(panelEl, collectJobId, kind);
  }
}

function trackCollectJob(
  flaskUrl,
  jobId,
  panelEl,
  user,
  kind = "mail",
  phase = "collect",
  collectJobId = jobId
) {
  ensureSSE(flaskUrl);
  activeJobs.set(jobId, { panelEl, phase, collectJobId, user, kind });

  const statusUrl =
    kind === "message"
      ? `${flaskUrl}/message-upload-status/${jobId}`
      : `${flaskUrl}/imap-collect-status/${jobId}`;

  fetch(statusUrl)
    .then((res) => res.json())
    .then((job) => {
      if (job.status === "not_found") {
        handleJobEvent({
          type: "failed",
          job_id: jobId,
          message: "작업을 찾을 수 없습니다.",
        });
      } else if (job.status === "done") {
        handleJobEvent({ type: "done", job_id: jobId, result: job.result });
      } else if (job.status === "error" || job.status === "failed") {
        handleJobEvent({
          type: "failed",
          job_id: jobId,
          message: job.error || job.message,
        });
      }
      // 그 외(아직 진행 중)에는 아무것도 안 하고 SSE로 이어받는다 (entry는 이미 등록해둠)
    })
    .catch(() => {
      // 상태 확인 자체가 실패해도 SSE로 이어받을 수 있으니 조용히 무시
    });
}

async function startCollect() {
  const flaskUrl = getApiBase();
  const host = document.getElementById("imap-host").value.trim();
  const port = parseInt(document.getElementById("imap-port").value) || 993;
  const ssl = document.getElementById("imap-ssl").value === "true";
  const user = document.getElementById("imap-user").value.trim();
  const pass = document.getElementById("imap-pass").value;
  // "0"(전체)은 falsy라서 `|| 100`으로 처리하면 100으로 덮어써지는 버그가 있었음 → 명시적으로 분기
  const limitRaw = document.getElementById("collect-limit").value;
  const limit =
    limitRaw === "custom"
      ? parseInt(document.getElementById("collect-limit-custom").value) || 0
      : limitRaw === ""
        ? 100
        : parseInt(limitRaw);
  const syncMode = document.getElementById("sync-mode").value;
  const folders = getSelectedFolders();

  // 입력 검증
  if (!host) {
    alert("IMAP 호스트를 입력하세요.");
    return;
  }
  if (!user) {
    alert("메일 주소를 입력하세요.");
    return;
  }
  if (!pass) {
    alert("앱 비밀번호를 입력하세요.");
    return;
  }
  if (limitRaw === "custom" && limit <= 0) {
    alert("수집 개수를 입력하세요.");
    return;
  }
  if (folders.length === 0) {
    alert("수집할 폴더를 하나 이상 선택하세요.");
    return;
  }
  if (!flaskUrl) {
    alert("Flask 서버 URL이 설정되지 않았습니다.\n/init 페이지를 먼저 방문하세요.");
    return;
  }

  const btn = document.getElementById("collect-btn");
  const spinner = document.getElementById("collect-spinner");
  const icon = document.getElementById("collect-icon");
  const hint = document.getElementById("collect-hint");

  // 요청 보내는 짧은 동안만 버튼을 잠근다 (같은 계정으로 중복 클릭 방지용).
  // job이 시작되고 나면 바로 풀어줘서 다른 계정으로 이어서 수집을 시작할 수 있게 한다.
  btn.disabled = true;
  spinner.classList.add("visible");
  icon.style.display = "none";
  hint.textContent = "서버에 연결 중...";

  const panelEl = createJobPanel(user);
  jobAddLog(panelEl, `IMAP 연결 시작: ${host}:${port} (SSL: ${ssl})`);
  jobAddLog(panelEl, `계정: ${user}`);
  jobAddLog(panelEl, `폴더: ${folders.join(", ")}`);
  jobAddLog(panelEl, `수집 개수: ${limit === 0 ? "전체" : limit + "개"} / 모드: ${syncMode}`);

  let started;
  try {
    jobAddLog(panelEl, "Flask 서버에 수집 요청 전송 중...");

    const res = await fetch(`${flaskUrl}/imap-collect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host,
        port,
        ssl,
        user,
        password: pass,
        folders,
        limit,
        sync_mode: syncMode,
        user_id: user,
      }),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`서버 오류 (${res.status}): ${err.slice(0, 200)}`);
    }

    started = await res.json();
    if (!started.ok || !started.jobId) {
      throw new Error(started.error || "수집 작업을 시작하지 못했습니다.");
    }
  } catch (err) {
    jobSetStatus(panelEl, "failed", "실패");
    jobAddLog(panelEl, `❌ ${err.message}`, "error");
    hint.textContent = "수집 실패. 로그를 확인하세요.";
    console.error("[imap-collect]", err);
    btn.disabled = false;
    spinner.classList.remove("visible");
    icon.style.display = "";
    return;
  }

  btn.disabled = false;
  spinner.classList.remove("visible");
  icon.style.display = "";
  hint.textContent = "수집이 백그라운드에서 진행 중입니다. 다른 계정도 바로 시작할 수 있습니다.";

  jobSetProgress(panelEl, 20);
  jobAddLog(panelEl, "메일 수집이 백그라운드에서 시작되었습니다. 진행 상황을 확인하는 중...");

  addStoredImapJob(started.jobId, user);
  resetForm();

  trackCollectJob(flaskUrl, started.jobId, panelEl, user);
}

function switchTab(tab) {
  const isMail = tab === "mail";
  document.getElementById("tab-btn-mail").classList.toggle("active", isMail);
  document.getElementById("tab-btn-mail").setAttribute("aria-selected", String(isMail));
  document.getElementById("tab-btn-message").classList.toggle("active", !isMail);
  document.getElementById("tab-btn-message").setAttribute("aria-selected", String(!isMail));
  document.getElementById("tab-panel-mail").classList.toggle("active", isMail);
  document.getElementById("tab-panel-message").classList.toggle("active", !isMail);
}

let messageFileText = null;

function guessMessageRoomNameClient(text, fallback) {
  const lines = text.split(/\r?\n/).slice(0, 5);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/카카오톡\s*대화\s*[:：]?\s*(.+)/);
    if (m && m[1].trim()) return m[1].trim();
    break;
  }
  return fallback;
}

function decodeMessageFileBuffer(buf) {
  let utf8Text = null;
  try {
    utf8Text = new TextDecoder("utf-8", { fatal: true }).decode(buf);
  } catch (e) {
    utf8Text = null;
  }

  const looksParseable = (text) =>
    /카카오톡\s*대화|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\./.test(text);

  if (utf8Text && looksParseable(utf8Text)) return utf8Text;

  try {
    const eucKrText = new TextDecoder("euc-kr").decode(buf);
    if (looksParseable(eucKrText)) return eucKrText;
  } catch (e) {
    // euc-kr 디코딩도 실패하면 그냥 아래에서 utf8Text(또는 빈 문자열)로 폴백
  }

  return utf8Text || "";
}

function handleMessageFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    messageFileText = decodeMessageFileBuffer(reader.result);
    const nameEl = document.getElementById("message-file-name");
    nameEl.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    nameEl.style.display = "";

    const roomInput = document.getElementById("message-room-name");
    if (!roomInput.value.trim()) {
      roomInput.value = guessMessageRoomNameClient(
        messageFileText,
        file.name.replace(/\.txt$/i, "")
      );
    }
  };
  reader.readAsArrayBuffer(file);
}

async function startMessageUpload() {
  const flaskUrl = getApiBase();
  const roomName = document.getElementById("message-room-name").value.trim();
  const syncMode = document.getElementById("message-sync-mode").value;

  if (!messageFileText) {
    alert("업로드할 카카오톡 대화 .txt 파일을 선택하세요.");
    return;
  }
  if (!flaskUrl) {
    alert("Flask 서버 URL이 설정되지 않았습니다.\n/init 페이지를 먼저 방문하세요.");
    return;
  }

  const btn = document.getElementById("message-upload-btn");
  const spinner = document.getElementById("message-upload-spinner");
  const icon = document.getElementById("message-upload-icon");
  const hint = document.getElementById("message-upload-hint");

  btn.disabled = true;
  spinner.classList.add("visible");
  icon.style.display = "none";
  hint.textContent = "서버에 업로드 중...";

  const displayName = roomName || "카카오톡 대화";
  const panelEl = createJobPanel(displayName, "message");
  jobAddLog(panelEl, `대화방: ${displayName}`);
  jobAddLog(panelEl, `모드: ${syncMode}`);
  jobAddLog(panelEl, "Flask 서버에 업로드 요청 전송 중...");

  let started;
  try {
    const res = await fetch(`${flaskUrl}/message-upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: messageFileText,
        room_name: roomName,
        sync_mode: syncMode,
      }),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`서버 오류 (${res.status}): ${err.slice(0, 200)}`);
    }

    started = await res.json();
    if (!started.ok || !started.jobId) {
      throw new Error(started.error || "업로드 작업을 시작하지 못했습니다.");
    }
  } catch (err) {
    jobSetStatus(panelEl, "failed", "실패");
    jobAddLog(panelEl, `❌ ${err.message}`, "error");
    hint.textContent = "업로드 실패. 로그를 확인하세요.";
    console.error("[message-upload]", err);
    btn.disabled = false;
    spinner.classList.remove("visible");
    icon.style.display = "";
    return;
  }

  btn.disabled = false;
  spinner.classList.remove("visible");
  icon.style.display = "";
  hint.textContent =
    "업로드가 백그라운드에서 진행 중입니다. 다른 대화방도 바로 시작할 수 있습니다.";

  jobSetProgress(panelEl, 20);
  jobAddLog(panelEl, "대화 파싱/저장이 백그라운드에서 시작되었습니다. 진행 상황을 확인하는 중...");

  const finalName = started.room_name || displayName;
  addStoredMessageJob(started.jobId, finalName);

  // 다음 업로드를 바로 시작할 수 있게 폼을 초기 상태로 되돌림 (메일 탭의 resetForm()과 동일한 취지)
  messageFileText = null;
  document.getElementById("message-file-input").value = "";
  document.getElementById("message-file-name").style.display = "none";
  document.getElementById("message-room-name").value = "";

  trackCollectJob(flaskUrl, started.jobId, panelEl, finalName, "message");
}

function onCollectSuccess(newItem, type) {
  // 1. 수집 성공 시 저장소 업데이트
  if (type === "mail") {
    const mails = JSON.parse(localStorage.getItem("gw_collected_mails") || "[]");
    if (!mails.includes(newItem)) mails.push(newItem);
    localStorage.setItem("gw_collected_mails", JSON.stringify(mails));
    localStorage.setItem("gw_selected_mail", newItem); // 새 계정 자동 선택
  } else {
    const rooms = JSON.parse(localStorage.getItem("gw_collected_rooms") || "[]");
    if (!rooms.includes(newItem)) rooms.push(newItem);
    localStorage.setItem("gw_collected_rooms", JSON.stringify(rooms));
    localStorage.setItem("gw_selected_room", newItem); // 새 채팅방 자동 선택
  }

  // 2. 사이드바 실시간 갱신 이벤트 전파
  window.dispatchEvent(new CustomEvent("gwDataCollected"));
}

export function initImapCollectPage() {
  document.querySelectorAll(".gw-preset-chip[data-host]").forEach((chip) => {
    chip.addEventListener("click", () => applyPreset(chip));
  });
  document.getElementById("collect-limit").addEventListener("change", toggleCustomLimit);
  document.getElementById("list-folders-btn").addEventListener("click", listFolders);
  document.getElementById("select-all-btn").addEventListener("click", toggleSelectAll);
  document.getElementById("collect-btn").addEventListener("click", startCollect);

  // 초기화 URL 파라미터에서 user_id 저장

  const params = new URLSearchParams(location.search);
  const gid = params.get("user_id");
  if (gid) {
    localStorage.setItem("gw_user_id", gid);
    document.getElementById("imap-user").value = gid;
  }

  const flaskUrlParam = params.get("flask_url");
  if (flaskUrlParam) localStorage.setItem("gw_flask_url", decodeURIComponent(flaskUrlParam));

  // gw_user_id는 이제 "마지막으로 조회한 계정"이라는 의미로 쓰이므로(계정 선택기 도입), 새 계정을 추가하는 이 화면의 로그인 입력칸을 이 값으로 자동 채우지 않는다.
  const savedId = localStorage.getItem("gw_user_id");
  if (savedId) {
    const nameEl = document.getElementById("google-profile-name");
    if (nameEl) nameEl.textContent = savedId.split("@")[0];
  }

  // 기본 활성 프리셋(Gmail)의 "@gmail.com"도 클릭했을 때와 동일하게 커서를 맨 앞에 둠
  const userInput = document.getElementById("imap-user");
  if (userInput.value.startsWith("@")) {
    userInput.focus();
    setTimeout(() => userInput.setSelectionRange(0, 0), 0);
  }

  // 이전에 시작해둔 수집 job이 있으면 (다른 페이지 갔다 돌아온 경우 포함) 패널을 복원하고 이어서 추적
  const storedJobs = loadStoredImapJobs();
  if (storedJobs.length > 0) {
    const flaskUrl = getApiBase();
    storedJobs.forEach(({ jobId, user }) => {
      const panelEl = createJobPanel(user, "mail");
      jobAddLog(panelEl, "이전 수집 작업 상태를 이어서 확인하는 중...");
      trackCollectJob(flaskUrl, jobId, panelEl, user, "mail");
    });
  }

  // 메일 / 메시지 탭 전환

  document.getElementById("tab-btn-mail").addEventListener("click", () => switchTab("mail"));
  document.getElementById("tab-btn-message").addEventListener("click", () => switchTab("message"));

  // 메시지 탭: 카카오톡 대화 업로드

  const messageDropzone = document.getElementById("message-dropzone");
  document.getElementById("message-file-input").addEventListener("change", (e) => {
    handleMessageFile(e.target.files[0]);
  });
  messageDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    messageDropzone.classList.add("dragover");
  });
  messageDropzone.addEventListener("dragleave", () => messageDropzone.classList.remove("dragover"));
  messageDropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    messageDropzone.classList.remove("dragover");
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleMessageFile(file);
  });

  document.getElementById("message-upload-btn").addEventListener("click", startMessageUpload);

  // 이전에 시작해둔 카카오 업로드 job이 있으면 이어서 추적

  const storedMessageJobs = loadStoredMessageJobs();
  if (storedMessageJobs.length > 0) {
    const flaskUrl = getApiBase();
    storedMessageJobs.forEach(({ jobId, user }) => {
      const panelEl = createJobPanel(user, "message");
      jobAddLog(panelEl, "이전 업로드 작업 상태를 이어서 확인하는 중...");
      trackCollectJob(flaskUrl, jobId, panelEl, user, "message");
    });
  }
}
