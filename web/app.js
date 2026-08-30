"use strict";

/* 금융 통합 비서 — 채팅 화면 로직.
   빌드 스텝 없이 브라우저가 그대로 읽는 파일이다. 외부 라이브러리를 쓰지 않는다. */

const REQUEST_TIMEOUT_MS = 60000;

/* 답변 끝에 붙는 유의문구는 본문에서 떼어 캡션으로 보여준다.
   아래 두 문장은 app/agents/prompts.py 의 DEPOSIT_AGENT_SYSTEM · LOAN_AGENT_SYSTEM 이
   지시하는 문구와 글자 그대로 같아야 한다. 어느 한쪽을 고치면 반드시 같이 고칠 것.
   정규식으로 짐작하지 않고 정확히 일치할 때만 떼어내며, 어긋나면 본문에 그대로 남긴다
   — 잘못 잘라내 답을 훼손하는 쪽이 캡션을 못 만드는 것보다 나쁘다. */
const DISCLAIMERS = [
  "공시된 금리는 변동될 수 있으니 실제 가입 조건은 해당 금융회사에서 확인하세요.",
  "실제 금리와 한도는 심사 결과에 따라 달라지니 자세한 조건은 해당 금융회사에서 확인하세요.",
];

/* 응답이 늦어질 때 무엇을 하고 있는지 알려주는 단계 문구 (경과 ms → 문구) */
const STAGES = [
  [5000, "금융감독원 공시와 정책금융 데이터를 조회하고 있어요…"],
  [15000, "상품이 많아 시간이 걸리고 있어요. 조금만 기다려주세요…"],
];

const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("chat-input");
const sendBtn = document.getElementById("send");
const newChatBtn = document.getElementById("new-chat");
const scrollBtn = document.getElementById("scroll-bottom");
const welcomeTpl = document.getElementById("welcome-tpl");

// session_id는 페이지 수명 동안만 유지한다. sessionStorage에 넣으면
// 탭 복제 시 그대로 복사되어 두 탭이 한 대화 스레드를 공유하게 된다.
let sessionId = null;
// 요청이 오가는 동안 다음 전송을 막는다 — 연타하면 같은 스레드에 요청이 겹친다.
let pending = false;
// 실패한 요청을 다시 보내기 위해 원문을 들고 있는다 (재타이핑을 시키지 않는다).
let lastRequestText = null;
// "새 대화"를 누르면 올라간다. 그 전에 보낸 요청의 응답이 늦게 도착해도
// 새 대화에 끼어들지 못하게 하는 표식이다 — 특히 옛 session_id를 되살리면 안 된다.
let conversationEpoch = 0;
// 진행 중인 요청. 새 대화를 시작할 때 끊는다.
let activeController = null;

/* ---------------- 마크다운 렌더링 ----------------
   LLM 답변은 신뢰할 수 없는 문자열로 다룬다. innerHTML을 쓰지 않고
   createElement · createTextNode 로만 조립해 태그 주입 자체를 불가능하게 만든다.
   지원 범위: 제목 · 굵게 · 인라인 코드 · 순서/비순서 목록 · GFM 표 · 문단. */

const RE_HEADING = /^(#{1,6})\s+(.*)$/;
const RE_UL = /^\s*[-*+]\s+(.*)$/;
const RE_OL = /^\s*\d+[.)]\s+(.*)$/;
const RE_TABLE_ROW = /^\s*\|.*\|?\s*$/;
const RE_TABLE_SEP = /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$/;
const RE_INLINE = /`([^`\n]+)`|\*\*([^*\n]+)\*\*/g;

function isBlockStart(line) {
  return RE_HEADING.test(line) || RE_UL.test(line) || RE_OL.test(line) || RE_TABLE_ROW.test(line);
}

function renderInline(text, parent) {
  RE_INLINE.lastIndex = 0;
  let last = 0;
  let m;
  while ((m = RE_INLINE.exec(text)) !== null) {
    if (m.index > last) {
      parent.appendChild(document.createTextNode(text.slice(last, m.index)));
    }
    const el = document.createElement(m[1] !== undefined ? "code" : "strong");
    el.textContent = m[1] !== undefined ? m[1] : m[2];
    parent.appendChild(el);
    last = RE_INLINE.lastIndex;
  }
  if (last < text.length) {
    parent.appendChild(document.createTextNode(text.slice(last)));
  }
}

function splitTableRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderTable(lines, start, root) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const cell of splitTableRow(lines[start])) {
    const th = document.createElement("th");
    renderInline(cell, th);
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  let i = start + 2; // 헤더 행 + 구분 행을 건너뛴다
  while (i < lines.length && RE_TABLE_ROW.test(lines[i]) && lines[i].includes("|")) {
    const tr = document.createElement("tr");
    for (const cell of splitTableRow(lines[i])) {
      const td = document.createElement("td");
      renderInline(cell, td);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
    i++;
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  root.appendChild(wrap);
  return i;
}

function indentOf(line) {
  return /^[ \t]*/.exec(line)[0].replace(/\t/g, "    ").length;
}

function renderList(lines, start, root) {
  const baseIndent = indentOf(lines[start]);
  const ordered = RE_OL.test(lines[start]);
  const list = document.createElement(ordered ? "ol" : "ul");
  if (ordered) {
    const first = parseInt(/^\s*(\d+)/.exec(lines[start])[1], 10);
    if (first > 1) list.start = first;
  }

  const sameKind = (line) => (ordered ? RE_OL : RE_UL).test(line);
  const anyItem = (line) => RE_OL.test(line) || RE_UL.test(line);

  let i = start;
  let item = null;
  while (i < lines.length) {
    const line = lines[i];
    const indent = indentOf(line);

    // 같은 깊이의 같은 종류 항목
    if (sameKind(line) && indent <= baseIndent) {
      item = document.createElement("li");
      renderInline((ordered ? RE_OL : RE_UL).exec(line)[1], item);
      list.appendChild(item);
      i++;
      continue;
    }
    // 더 깊이 들여쓴 목록은 직전 항목 안에 중첩한다. 이걸 빼면 항목마다
    // 목록이 끊겨 "1개짜리 목록"이 줄줄이 생긴다 (정책대출 답변이 이 형태다).
    if (item && anyItem(line) && indent > baseIndent) {
      i = renderList(lines, i, item);
      continue;
    }
    // 항목 사이를 빈 줄로 띄운 목록(loose list)도 하나의 목록으로 잇는다
    if (!line.trim()) {
      let next = i;
      while (next < lines.length && !lines[next].trim()) next++;
      const continues =
        next < lines.length &&
        ((sameKind(lines[next]) && indentOf(lines[next]) <= baseIndent) ||
          (item && anyItem(lines[next]) && indentOf(lines[next]) > baseIndent));
      if (continues) {
        i = next;
        continue;
      }
      break;
    }
    // 항목 아래 들여쓴 설명 줄은 직전 항목에 이어 붙인다
    if (item && indent > baseIndent && !isBlockStart(line)) {
      item.appendChild(document.createElement("br"));
      renderInline(line.trim(), item);
      i++;
      continue;
    }
    break;
  }
  root.appendChild(list);
  return i;
}

function renderMarkdown(text, root) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    // 표는 헤더 행 바로 아래 구분 행이 있을 때만 표로 본다 (오탐 방지)
    if (RE_TABLE_ROW.test(line) && line.includes("|") && i + 1 < lines.length && RE_TABLE_SEP.test(lines[i + 1])) {
      i = renderTable(lines, i, root);
      continue;
    }
    const heading = RE_HEADING.exec(line);
    if (heading) {
      const h = document.createElement("h3");
      renderInline(heading[2], h);
      root.appendChild(h);
      i++;
      continue;
    }
    if (RE_UL.test(line) || RE_OL.test(line)) {
      i = renderList(lines, i, root);
      continue;
    }
    const para = document.createElement("p");
    let firstLine = true;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      if (!firstLine) para.appendChild(document.createElement("br"));
      renderInline(lines[i].trim(), para);
      firstLine = false;
      i++;
    }
    root.appendChild(para);
  }
}

/* ---------------- 유의문구 분리 ---------------- */

function splitDisclaimer(reply) {
  const trimmed = reply.trimEnd();
  for (const note of DISCLAIMERS) {
    // 문장이 답변 끝에 그대로 붙어 있을 때만 떼어낸다
    if (trimmed.endsWith(note)) {
      return { body: trimmed.slice(0, trimmed.length - note.length).trimEnd(), note };
    }
  }
  return { body: reply, note: null };
}

/* ---------------- 스크롤 ---------------- */

function isAtBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
  scrollBtn.hidden = true;
}

/* 읽는 중에 화면이 끌려가지 않게, 이미 맨 아래를 보고 있을 때만 따라 내린다. */
function appendTurn(turn, { follow = true } = {}) {
  const wasAtBottom = isAtBottom();
  messagesEl.appendChild(turn);
  if (follow && wasAtBottom) {
    scrollToBottom();
  } else if (follow) {
    scrollBtn.hidden = false;
  }
  return turn;
}

messagesEl.addEventListener("scroll", () => {
  if (isAtBottom()) scrollBtn.hidden = true;
});
scrollBtn.addEventListener("click", scrollToBottom);

/* ---------------- 말풍선 ---------------- */

function makeTurn(role) {
  const turn = document.createElement("div");
  turn.className = `turn ${role}`;
  const msg = document.createElement("div");
  msg.className = "msg";
  turn.appendChild(msg);
  return { turn, msg };
}

function addUserTurn(text) {
  const { turn, msg } = makeTurn("user");
  msg.textContent = text;
  appendTurn(turn);
}

function addTypingTurn() {
  const { turn, msg } = makeTurn("assistant");
  msg.classList.add("typing");

  const dots = document.createElement("span");
  dots.className = "dots";
  dots.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 3; i++) dots.appendChild(document.createElement("i"));
  msg.appendChild(dots);

  const stage = document.createElement("span");
  stage.className = "stage";
  // 단계 문구가 바뀔 때마다 스크린리더가 다시 읽지 않도록 숨긴다
  stage.setAttribute("aria-hidden", "true");
  msg.appendChild(stage);

  const status = document.createElement("span");
  status.className = "sr-only";
  status.textContent = "답변을 생성하고 있어요";
  msg.appendChild(status);

  appendTurn(turn);
  const timers = STAGES.map(([delay, text]) => setTimeout(() => (stage.textContent = text), delay));
  return { turn, timers };
}

/* 답변에 번호 목록이 있으면 후속 질문 칩을 붙인다.
   "N번 자세히"는 상품 목록이든 설명 단계든 자연스럽게 이어지는 표현이라
   목록의 내용을 넘겨짚지 않는다. 칩은 가장 최근 답변에만 남긴다. */
function addFollowupChips(turn, msg) {
  for (const stale of messagesEl.querySelectorAll(".followup")) stale.remove();

  const list = msg.querySelector("ol");
  if (!list) return;
  // 상위 5~6건을 추리는 답변이 흔하므로 6까지 받는다. 그보다 길면 칩이 화면을 덮는다.
  const count = list.children.length;
  if (count < 2 || count > 6) return;

  const chips = document.createElement("div");
  chips.className = "chips followup";
  for (let n = 1; n <= count; n++) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = `${n}번 자세히 알려줘`;
    chips.appendChild(chip);
  }
  turn.appendChild(chips);
}

function fillAssistantTurn(turn, reply) {
  const msg = turn.querySelector(".msg");
  msg.classList.remove("typing");
  msg.replaceChildren();

  const { body, note } = splitDisclaimer(reply);
  renderMarkdown(body, msg);
  if (note) {
    const caption = document.createElement("p");
    caption.className = "note";
    caption.textContent = note;
    turn.appendChild(caption);
  }
  addFollowupChips(turn, msg);
}

function fillErrorTurn(turn, message) {
  turn.className = "turn assistant error";
  const msg = turn.querySelector(".msg");
  msg.classList.remove("typing");
  msg.replaceChildren();

  const p = document.createElement("p");
  p.textContent = message;
  msg.appendChild(p);

  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "retry";
  retry.textContent = "다시 시도";
  retry.addEventListener("click", () => {
    if (pending || !lastRequestText) return;
    turn.remove();
    send(lastRequestText, { echo: false });
  });
  msg.appendChild(retry);
}

/* ---------------- 웰컴 ---------------- */

/* 웰컴은 라이브 리전 안에 들어가므로, 삽입하는 동안에는 낭독을 끈다.
   화면 전체가 바뀌는 것이지 새 답변이 도착한 것이 아니다. */
function renderWelcome() {
  messagesEl.setAttribute("aria-live", "off");
  messagesEl.appendChild(welcomeTpl.content.cloneNode(true));
  // requestAnimationFrame은 배경 탭에서 멈추므로 쓰지 않는다 — 그러면 낭독이 꺼진 채 남는다
  setTimeout(() => messagesEl.setAttribute("aria-live", "polite"), 50);
}

function clearWelcome() {
  const welcome = messagesEl.querySelector(".welcome");
  if (welcome) welcome.remove();
}

/* ---------------- 전송 ---------------- */

async function postChat(text, signal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: text, session_id: sessionId }),
    signal,
  });
  if (!res.ok) {
    // 백엔드가 한국어 안내문(detail)을 주면 그대로 보여주는 편이 낫다
    let detail = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = null;
    }
    const err = new Error(typeof detail === "string" && detail ? detail : `HTTP ${res.status}`);
    err.status = res.status;
    err.hasDetail = typeof detail === "string" && Boolean(detail);
    throw err;
  }
  return res.json();
}

function describeFailure(err, timedOut) {
  if (timedOut) return "응답이 60초를 넘겨 중단했어요. 잠시 후 다시 시도해주세요.";
  if (err.hasDetail) return err.message;
  if (err.status >= 500) return "서버가 답변을 만들지 못했어요. 잠시 후 다시 시도해주세요.";
  if (err.status) return `요청을 처리하지 못했어요 (HTTP ${err.status}).`;
  return "서버에 연결하지 못했어요. 네트워크 상태를 확인한 뒤 다시 시도해주세요.";
}

async function send(text, { echo = true } = {}) {
  if (pending) return;
  pending = true;
  sendBtn.disabled = true;
  lastRequestText = text;
  const epoch = conversationEpoch;

  clearWelcome();
  if (echo) addUserTurn(text);
  scrollToBottom(); // 사용자가 방금 보낸 것이므로 항상 따라 내린다

  const { turn, timers } = addTypingTurn();

  const controller = new AbortController();
  activeController = controller;
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    const data = await postChat(text, controller.signal);
    // 새 대화가 시작됐다면 이 응답은 버린 대화의 것이다. 화면에도 세션에도 반영하지 않는다.
    if (epoch !== conversationEpoch) return;
    sessionId = data.session_id;
    fillAssistantTurn(turn, data.reply);
  } catch (err) {
    if (epoch !== conversationEpoch) return;
    fillErrorTurn(turn, describeFailure(err, timedOut));
  } finally {
    clearTimeout(timeout);
    for (const t of timers) clearTimeout(t);
    if (activeController === controller) activeController = null;
    // 새 대화가 이미 상태를 초기화했고 그 뒤 다른 요청이 시작됐을 수 있다.
    // 그 요청의 pending을 여기서 풀어버리면 전송이 겹친다.
    if (epoch === conversationEpoch) {
      pending = false;
      sendBtn.disabled = false;
      // 기다리는 동안 위로 올라가 읽고 있었다면 화면을 끌어내리지 않고 버튼만 띄운다
      if (isAtBottom()) scrollToBottom();
      else scrollBtn.hidden = false;
      inputEl.focus();
    }
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text || pending) return;
  inputEl.value = "";
  send(text);
});

// 웰컴 예시 칩과 후속 질문 칩은 누르는 즉시 그 문장을 보낸다
messagesEl.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip || pending) return;
  send(chip.textContent);
});

newChatBtn.addEventListener("click", () => {
  // 진행 중인 요청을 끊고 잠금을 푼다. 이걸 빼면 pending이 true로 남아
  // 다음 전송이 통째로 막히고, 늦게 온 응답이 옛 session_id를 되살린다.
  conversationEpoch++;
  if (activeController) {
    activeController.abort();
    activeController = null;
  }
  pending = false;
  sendBtn.disabled = false;

  sessionId = null;
  lastRequestText = null;
  messagesEl.replaceChildren();
  scrollBtn.hidden = true;
  renderWelcome();
  inputEl.focus();
});

renderWelcome();
inputEl.focus();
