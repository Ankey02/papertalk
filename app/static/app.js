// The main page. Plain JavaScript: it loads the data from the Python API,
// draws the sidebar and the chat, and reads the streamed answer.

const $ = (id) => document.getElementById(id);
const icon = (name) => `<svg class="icon"><use href="#i-${name}"/></svg>`;

const state = {
  docs: [],
  chats: [],
  chatId: null,
  messages: [],        // {role, content, sources}
  selected: new Set(), // ids of documents to answer from
  streaming: false,
  controller: null,    // lets the Stop button cancel the request
  panelMessage: null,  // which message the sources panel is showing
};

const SUGGESTIONS = [
  "Summarize this document in 5 points",
  "What are the key terms and their definitions?",
  "Create 5 quiz questions with answers",
  "Explain the hardest topic in simple words",
];

// ------------------------------------------------------------- helpers

function esc(text) {
  return text.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (response.status === 401) {
    location.href = "/login";
    throw new Error("Please log in again.");
  }
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try { message = (await response.json()).detail || message; } catch (e) {}
    throw new Error(message);
  }
  return response;
}

let toastTimer;
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5000);
}

function saveSelection() {
  try { localStorage.setItem("selectedDocs", JSON.stringify([...state.selected])); } catch (e) {}
}

function loadSelection() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("selectedDocs")); } catch (e) {}
  const ids = state.docs.map((d) => d.id);
  const kept = Array.isArray(saved) ? saved.filter((id) => ids.includes(id)) : [];
  state.selected = new Set(kept.length ? kept : ids);
}

// --------------------------------------- tiny Markdown to HTML converter

function inline(text) {
  // Split out `code` first so nothing inside it is changed.
  return text.split(/(`[^`]+`)/).map((part) => {
    if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
      return `<code>${esc(part.slice(1, -1))}</code>`;
    }
    return esc(part)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (match, numbers) => numbers
        .split(",")
        .map((n) => `<button type="button" class="cite" data-n="${n.trim()}" aria-label="Source ${n.trim()}">${n.trim()}</button>`)
        .join(""));
  }).join("");
}

function markdown(text) {
  const lines = text.split("\n");
  let html = "";
  let list = null;
  let paragraph = [];
  const endParagraph = () => {
    if (paragraph.length) html += `<p>${paragraph.map(inline).join("<br>")}</p>`;
    paragraph = [];
  };
  const endList = () => { if (list) html += `</${list}>`; list = null; };
  const startList = (tag) => {
    endParagraph();
    if (list !== tag) { endList(); html += `<${tag}>`; list = tag; }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if (line.trim().startsWith("```")) {
      endParagraph(); endList();
      const code = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith("```"); i++) code.push(lines[i]);
      html += `<pre><code>${esc(code.join("\n"))}</code></pre>`;
    } else if ((m = line.match(/^#{1,4}\s+(.*)/))) {
      endParagraph(); endList();
      html += `<h4>${inline(m[1])}</h4>`;
    } else if ((m = line.match(/^\s*[-*•]\s+(.*)/))) {
      startList("ul"); html += `<li>${inline(m[1])}</li>`;
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) {
      startList("ol"); html += `<li>${inline(m[1])}</li>`;
    } else if (!line.trim()) {
      endParagraph(); endList();
    } else {
      endList(); paragraph.push(line);
    }
  }
  endParagraph(); endList();
  return html;
}

// ------------------------------------------------------------- sidebar

function renderDocs() {
  const list = $("docList");
  $("docNote").hidden = state.docs.length < 2;
  if (!state.docs.length) {
    list.innerHTML = `<li class="side-empty">No documents yet. Upload a PDF to begin.</li>`;
  } else {
    list.innerHTML = state.docs.map((doc) => `
      <li class="doc-item">
        <label class="doc-pick">
          <input type="checkbox" data-doc="${doc.id}" ${state.selected.has(doc.id) ? "checked" : ""}>
          <span class="doc-text">
            <span class="doc-name" title="${esc(doc.filename)}">${esc(doc.filename)}</span><br>
            <span class="doc-meta">${doc.pages} ${doc.pages === 1 ? "page" : "pages"}</span>
          </span>
        </label>
        <button class="icon-btn row-del" type="button" data-del-doc="${doc.id}" aria-label="Delete ${esc(doc.filename)}">${icon("trash")}</button>
      </li>`).join("");
  }
  renderScope();
}

function renderChats() {
  const list = $("chatList");
  if (!state.chats.length) {
    list.innerHTML = `<li class="side-empty">Your chats will appear here.</li>`;
    return;
  }
  list.innerHTML = state.chats.map((chat) => `
    <li class="chat-item ${chat.id === state.chatId ? "active" : ""}">
      <button class="chat-open" type="button" data-chat="${chat.id}" title="${esc(chat.title)}">${esc(chat.title)}</button>
      <button class="icon-btn row-del" type="button" data-del-chat="${chat.id}" aria-label="Delete chat ${esc(chat.title)}">${icon("trash")}</button>
    </li>`).join("");
}

function renderScope() {
  const chosen = state.docs.filter((d) => state.selected.has(d.id));
  let text = "Upload a PDF to start asking questions";
  if (state.docs.length) {
    if (chosen.length === 0) text = "No document selected";
    else if (chosen.length === 1) text = `Answering from ${chosen[0].filename}`;
    else if (chosen.length === state.docs.length) text = `Answering from all ${chosen.length} documents`;
    else text = `Answering from ${chosen.length} of ${state.docs.length} documents`;
  }
  $("scopeText").textContent = text;
  const ready = chosen.length > 0;
  $("summaryBtn").disabled = !ready;
  $("exportBtn").disabled = !state.messages.length;
}

// ---------------------------------------------------------------- chat

function messageHtml(message, index) {
  if (message.role === "user") {
    return `<div class="msg user"><div class="bubble">${esc(message.content)}</div></div>`;
  }
  let body;
  if (message.content) body = `<div class="content">${markdown(message.content)}</div>`;
  else if (message.status) body = `<div class="status-line">${esc(message.status)}</div>`;
  else body = `<div class="typing" aria-label="Writing the answer"><i></i><i></i><i></i></div>`;
  if (message.error) body += `<p class="msg-error">${esc(message.error)}</p>`;

  let foot = "";
  if (!message.pending && message.content) {
    const chips = (message.sources || []).map((source, n) => `
      <button class="chip" type="button" data-source="${n + 1}" data-msg="${index}">
        <b>${n + 1}</b><span>${esc(source.filename)}, p. ${source.page}</span>
      </button>`).join("");
    foot = `<div class="msg-foot">${chips}
      <button class="chip copy" type="button" data-copy="${index}">${icon("copy")}<span>Copy</span></button></div>`;
  }
  return `<div class="msg bot" data-msg="${index}">
    <div class="bot-mark" aria-hidden="true"><svg class="logo"><use href="#logo"/></svg></div>
    <div class="body">${body}${foot}</div></div>`;
}

function emptyHtml() {
  if (!state.docs.length) {
    return `<div class="empty">
      <h2>Your notes can answer back</h2>
      <p>Upload notes, a textbook or a report. Ask a question and get an answer that shows the page it came from.</p>
      <label class="dropzone" for="fileInput">
        <span class="sheet s1"></span><span class="sheet s2"></span>
        <span class="sheet top">
          <span class="drop-badge">${icon("upload")}</span>
          <strong>Drop a PDF here or click to choose</strong>
          <small>PDF files with selectable text</small>
        </span>
      </label>
      <div class="steps">
        <div class="step"><b>1</b><div><strong>Upload</strong><span>Your PDF is read and split into small passages.</span></div></div>
        <div class="step"><b>2</b><div><strong>Ask</strong><span>The passages closest to your question are found.</span></div></div>
        <div class="step"><b>3</b><div><strong>Check</strong><span>Every answer shows its sources so you can verify it.</span></div></div>
      </div>
    </div>`;
  }
  return `<div class="empty">
    <h2>What do you want to know?</h2>
    <p>Type a question below or start with one of these.</p>
    <div class="suggestions">
      ${SUGGESTIONS.map((s) => `<button class="suggestion" type="button" data-ask="${esc(s)}">${esc(s)}</button>`).join("")}
    </div>
  </div>`;
}

function renderThread(keepScroll) {
  const thread = $("thread");
  const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
  thread.innerHTML = state.messages.length
    ? `<div class="thread-inner">${state.messages.map(messageHtml).join("")}</div>`
    : emptyHtml();
  if (!keepScroll || nearBottom) thread.scrollTop = thread.scrollHeight;
  renderScope();
}

function setTitle(title) {
  $("chatTitle").textContent = title || "New chat";
  document.title = title ? `${title} · ${document.title.split(" · ").pop()}` : document.title.split(" · ").pop();
}

function setStreaming(on) {
  state.streaming = on;
  const button = $("sendBtn");
  button.classList.toggle("stop", on);
  button.innerHTML = icon(on ? "stop" : "send");
  button.setAttribute("aria-label", on ? "Stop the answer" : "Send question");
}

async function ask(question) {
  question = question.trim();
  if (!question || state.streaming) return;
  if (!state.docs.length) { toast("Upload a PDF first, then ask your question."); return; }
  if (!state.selected.size) { toast("Tick at least one document in the sidebar."); return; }

  const answer = { role: "assistant", content: "", sources: [], pending: true };
  state.messages.push({ role: "user", content: question }, answer);
  $("question").value = "";
  resizeBox();
  renderThread();
  setStreaming(true);
  state.controller = new AbortController();

  try {
    const response = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, chat_id: state.chatId, doc_ids: [...state.selected] }),
      signal: state.controller.signal,
    });
    // The server sends one JSON object per line as the answer is written.
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end;
      while ((end = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, end).trim();
        buffer = buffer.slice(end + 1);
        if (line) handleEvent(JSON.parse(line), answer);
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") answer.error = error.message;
  }

  answer.pending = false;
  if (!answer.content && !answer.error) answer.error = "The answer was stopped.";
  setStreaming(false);
  renderThread(true);
  if (answer.sources.length && !$("sourcePanel").hidden) showSources(state.messages.length - 1);
  refreshState();
}

function handleEvent(event, answer) {
  if (event.type === "chat") {
    state.chatId = event.id;
    setTitle(event.title);
  } else if (event.type === "status") {
    answer.status = event.text;
  } else if (event.type === "sources") {
    answer.sources = event.sources;
  } else if (event.type === "token") {
    answer.content += event.text;
  } else if (event.type === "error") {
    answer.error = event.message;
  }
  renderThread(true);
}

async function openChat(id) {
  if (state.streaming) return;
  try {
    const chat = await (await api(`/api/chats/${id}`)).json();
    state.chatId = chat.id;
    state.messages = chat.messages;
    setTitle(chat.title);
    renderThread();
    renderChats();
    hideSources();
    closeSidebar();
  } catch (error) { toast(error.message); }
}

function newChat() {
  if (state.streaming) return;
  state.chatId = null;
  state.messages = [];
  setTitle("");
  renderThread();
  renderChats();
  hideSources();
  closeSidebar();
  $("question").focus();
}

async function refreshState() {
  try {
    const data = await (await api("/api/state")).json();
    state.docs = data.docs;
    state.chats = data.chats;
    const ids = new Set(state.docs.map((d) => d.id));
    state.selected = new Set([...state.selected].filter((id) => ids.has(id)));
    renderDocs();
    renderChats();
  } catch (error) { toast(error.message); }
}

// ------------------------------------------------------------- uploads

async function uploadFiles(files) {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) { toast("Only PDF files can be uploaded."); return; }
  const status = $("uploadStatus");
  for (let i = 0; i < pdfs.length; i++) {
    status.hidden = false;
    status.textContent = `Reading ${pdfs[i].name} (${i + 1} of ${pdfs.length})...`;
    const form = new FormData();
    form.append("file", pdfs[i]);
    try {
      const doc = await (await api("/api/documents", { method: "POST", body: form })).json();
      state.docs.unshift(doc);
      state.selected.add(doc.id);
      saveSelection();
      renderDocs();
      if (!state.messages.length) renderThread();
    } catch (error) {
      toast(`${pdfs[i].name}: ${error.message}`);
    }
  }
  status.hidden = true;
  $("fileInput").value = "";
}

// ------------------------------------------------------- sources panel

function showSources(messageIndex, highlight) {
  const message = state.messages[messageIndex];
  if (!message) return;
  state.panelMessage = messageIndex;
  const sources = message.sources || [];
  $("sourceList").innerHTML = sources.length
    ? sources.map((source, n) => `
      <article class="source-card ${highlight === n + 1 ? "active" : ""}" id="source-${n + 1}">
        <div class="source-top"><b>${n + 1}</b><span title="${esc(source.filename)}">${esc(source.filename)}</span><em>page ${source.page}</em></div>
        <div class="source-text">${esc(source.text)}</div>
      </article>`).join("")
    : `<p class="sources-empty">This answer has no sources.</p>`;
  $("sourcePanel").hidden = false;
  $("app").classList.add("with-sources");
  $("sourcesBtn").setAttribute("aria-expanded", "true");
  const card = highlight && $(`source-${highlight}`);
  if (card) card.scrollIntoView({ block: "nearest" });
}

function hideSources() {
  $("sourcePanel").hidden = true;
  $("app").classList.remove("with-sources");
  $("sourcesBtn").setAttribute("aria-expanded", "false");
}

function lastAnswerIndex() {
  for (let i = state.messages.length - 1; i >= 0; i--) {
    if (state.messages[i].role === "assistant") return i;
  }
  return -1;
}

// ---------------------------------------------------------- small bits

function resizeBox() {
  const box = $("question");
  box.style.height = "auto";
  box.style.height = Math.min(box.scrollHeight, 180) + "px";
}

function openSidebar() { $("sidebar").classList.add("open"); $("scrim").hidden = false; }
function closeSidebar() { $("sidebar").classList.remove("open"); $("scrim").hidden = true; }

function exportChat() {
  const lines = state.messages.map((m) => {
    const who = m.role === "user" ? "You" : "Assistant";
    const sources = (m.sources || []).map((s, n) => `  [${n + 1}] ${s.filename}, page ${s.page}`).join("\n");
    return `${who}:\n${m.content}${sources ? "\n\nSources:\n" + sources : ""}`;
  });
  const blob = new Blob([lines.join("\n\n----------\n\n")], { type: "text/plain" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = ($("chatTitle").textContent || "chat").replace(/[^\w\- ]+/g, "").trim().slice(0, 50) + ".txt";
  link.click();
  URL.revokeObjectURL(link.href);
}

// -------------------------------------------------------------- events

$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.streaming) state.controller.abort();
  else ask($("question").value);
});
$("question").addEventListener("input", resizeBox);
$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (!state.streaming) ask($("question").value);
  }
});

$("newChatBtn").addEventListener("click", newChat);
$("fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));
$("summaryBtn").addEventListener("click", () => ask(SUGGESTIONS[0]));
$("exportBtn").addEventListener("click", exportChat);
$("sourcesBtn").addEventListener("click", () => {
  if (!$("sourcePanel").hidden) { hideSources(); return; }
  const index = lastAnswerIndex();
  if (index < 0) { toast("Sources appear here after you ask a question."); return; }
  showSources(index);
});
$("closeSources").addEventListener("click", hideSources);
$("openSidebar").addEventListener("click", openSidebar);
$("closeSidebar").addEventListener("click", closeSidebar);
$("scrim").addEventListener("click", closeSidebar);
$("themeBtn").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme
    ? root.dataset.theme === "dark"
    : false;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
});

$("docList").addEventListener("change", (e) => {
  const id = Number(e.target.dataset.doc);
  if (!id) return;
  if (e.target.checked) state.selected.add(id); else state.selected.delete(id);
  saveSelection();
  renderScope();
});
$("docList").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-del-doc]");
  if (!button) return;
  const doc = state.docs.find((d) => d.id === Number(button.dataset.delDoc));
  if (!doc || !confirm(`Delete "${doc.filename}"? This cannot be undone.`)) return;
  try {
    await api(`/api/documents/${doc.id}`, { method: "DELETE" });
    state.selected.delete(doc.id);
    saveSelection();
    await refreshState();
    if (!state.messages.length) renderThread();
  } catch (error) { toast(error.message); }
});

$("chatList").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del-chat]");
  const open = e.target.closest("[data-chat]");
  if (del) {
    const id = Number(del.dataset.delChat);
    if (!confirm("Delete this chat? This cannot be undone.")) return;
    try {
      await api(`/api/chats/${id}`, { method: "DELETE" });
      if (id === state.chatId) newChat();
      await refreshState();
    } catch (error) { toast(error.message); }
  } else if (open) {
    openChat(Number(open.dataset.chat));
  }
});

$("thread").addEventListener("click", async (e) => {
  const suggestion = e.target.closest("[data-ask]");
  const chip = e.target.closest("[data-source]");
  const cite = e.target.closest(".cite");
  const copy = e.target.closest("[data-copy]");
  if (suggestion) {
    ask(suggestion.dataset.ask);
  } else if (chip) {
    showSources(Number(chip.dataset.msg), Number(chip.dataset.source));
  } else if (cite) {
    const holder = cite.closest("[data-msg]");
    showSources(Number(holder.dataset.msg), Number(cite.dataset.n));
  } else if (copy) {
    const message = state.messages[Number(copy.dataset.copy)];
    try {
      await navigator.clipboard.writeText(message.content);
      copy.querySelector("span").textContent = "Copied";
      setTimeout(() => { copy.querySelector("span").textContent = "Copy"; }, 1500);
    } catch (error) { toast("Could not copy. Select the text and copy it yourself."); }
  }
});

// Drag a PDF anywhere onto the page to upload it.
let dragDepth = 0;
const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
window.addEventListener("dragenter", (e) => {
  if (!hasFiles(e)) return;
  dragDepth++;
  $("dropOverlay").hidden = false;
});
window.addEventListener("dragleave", (e) => {
  if (!hasFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("dropOverlay").hidden = true;
});
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("dropOverlay").hidden = true;
  uploadFiles(e.dataTransfer.files);
});

// --------------------------------------------------------------- start

(async function start() {
  try {
    const data = await (await api("/api/state")).json();
    state.docs = data.docs;
    state.chats = data.chats;
  } catch (error) { toast(error.message); }
  loadSelection();
  renderDocs();
  renderChats();
  renderThread();
})();
