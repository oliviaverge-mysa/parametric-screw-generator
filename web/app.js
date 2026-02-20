const chatListEl = document.getElementById("chat-list");
const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("message-input");
const newChatBtn = document.getElementById("new-chat-btn");
const deleteChatBtn = document.getElementById("delete-chat-btn");
const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");
const appEl = document.querySelector(".app");
const contextMenuEl = document.getElementById("chat-context-menu");
const ctxDeleteChatBtn = document.getElementById("ctx-delete-chat-btn");

let currentChatId = null;
let pendingQuestion = null;
let contextChatId = null;

function renderChatList(chats) {
  chatListEl.innerHTML = "";
  for (const chat of chats) {
    const div = document.createElement("div");
    div.className = "chat-item" + (chat.id === currentChatId ? " active" : "");
    div.textContent = chat.title;
    div.onclick = () => loadChat(chat.id);
    div.oncontextmenu = async (e) => {
      e.preventDefault();
      contextChatId = chat.id;
      contextMenuEl.hidden = false;
      contextMenuEl.style.left = `${e.clientX}px`;
      contextMenuEl.style.top = `${e.clientY}px`;
    };
    chatListEl.appendChild(div);
  }
}

function bubble(message, idx, latestUserIdx) {
  const node = document.createElement("div");
  node.className = `bubble ${message.role}`;

  const content = document.createElement("div");
  content.textContent = message.content;
  node.appendChild(content);

  if (message.kind === "result" && message.stl_url) {
    node.appendChild(resultCard(message));
  }

  if (message.role === "user" && idx === latestUserIdx) {
    const editBtn = document.createElement("button");
    editBtn.className = "edit-btn";
    editBtn.textContent = "Edit";
    editBtn.onclick = async () => {
      const updated = prompt("Edit message:", message.content);
      if (updated === null) return;
      await fetch(`/api/chats/${currentChatId}/messages/${idx}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: updated }),
      });
      await loadChat(currentChatId);
    };
    node.appendChild(editBtn);
  }
  return node;
}

function resultCard(message) {
  const card = document.createElement("div");
  card.className = "preview-card";

  const header = document.createElement("div");
  header.className = "preview-card-header";
  header.textContent = "Preview + Downloads";
  card.appendChild(header);

  const preview = document.createElement("div");
  preview.className = "preview-canvas";
  card.appendChild(preview);

  const actions = document.createElement("div");
  actions.className = "result-actions";

  const status = document.createElement("div");
  status.className = "preview-status";
  status.textContent = "Generating preview...";

  const stepBtn = document.createElement("a");
  stepBtn.className = "download-btn disabled";
  stepBtn.textContent = "Download STEP";
  stepBtn.href = message.step_url || "#";
  stepBtn.download = "";

  const stlBtn = document.createElement("a");
  stlBtn.className = "download-btn disabled";
  stlBtn.textContent = "Download STL";
  stlBtn.href = message.stl_url || "#";
  stlBtn.download = "";

  actions.appendChild(status);
  actions.appendChild(stepBtn);
  actions.appendChild(stlBtn);
  card.appendChild(actions);

  if (!message.step_url || !message.stl_url) {
    status.textContent = "No downloadable model in this response.";
    return card;
  }

  initPreviewImage(preview, message.preview_url, {
    onReady: () => {
      status.textContent = "Preview ready.";
      stepBtn.classList.remove("disabled");
      stlBtn.classList.remove("disabled");
    },
    onError: () => {
      status.textContent = "Preview unavailable. Downloads ready.";
      stepBtn.classList.remove("disabled");
      stlBtn.classList.remove("disabled");
    },
  });

  return card;
}

function initPreviewImage(container, previewUrl, hooks) {
  if (!previewUrl) {
    hooks.onError();
    return;
  }
  const img = document.createElement("img");
  img.alt = "Screw preview";
  img.onload = () => hooks.onReady();
  img.onerror = () => hooks.onError();
  img.src = previewUrl;
  container.innerHTML = "";
  container.appendChild(img);
}

function renderMessages(chat) {
  messagesEl.innerHTML = "";
  const latestUserIdx = [...chat.messages]
    .map((m, i) => ({ m, i }))
    .filter((x) => x.m.role === "user")
    .map((x) => x.i)
    .pop();
  chat.messages.forEach((msg, idx) => {
    messagesEl.appendChild(bubble(msg, idx, latestUserIdx));
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loadChats() {
  const res = await fetch("/api/chats");
  const chats = await res.json();
  renderChatList(chats);
  if (chats.length === 0) {
    currentChatId = null;
    messagesEl.innerHTML = "";
    return;
  }
  if (!currentChatId) {
    await loadChat(chats[chats.length - 1].id);
    return;
  }
  if (!chats.some((c) => c.id === currentChatId)) {
    currentChatId = null;
    await loadChats();
  }
}

async function createChat() {
  const res = await fetch("/api/chats", { method: "POST" });
  const chat = await res.json();
  currentChatId = chat.id;
  await loadChats();
  await loadChat(chat.id);
}

async function loadChat(chatId) {
  const res = await fetch(`/api/chats/${chatId}`);
  const chat = await res.json();
  currentChatId = chat.id;
  pendingQuestion = chat.pending_question || null;
  renderMessages(chat);
  renderChatList(await (await fetch("/api/chats")).json());
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentChatId) {
    await createChat();
  }
  const raw = inputEl.value;
  const content = raw.trim();
  if (!content && !pendingQuestion) return;
  inputEl.value = "";
  const res = await fetch(`/api/chats/${currentChatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: pendingQuestion ? raw : content }),
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: "Request failed." }));
    alert(errorBody.detail || "Could not process request.");
    await loadChat(currentChatId);
    return;
  }
  const data = await res.json();
  if (!data.chat_id) {
    alert("Request failed, please retry.");
    await loadChat(currentChatId);
    return;
  }
  await loadChat(data.chat_id);
});

toggleSidebarBtn.addEventListener("click", () => {
  appEl.classList.toggle("sidebar-collapsed");
  toggleSidebarBtn.textContent = appEl.classList.contains("sidebar-collapsed") ? "Show Chats" : "Hide Chats";
});

newChatBtn.addEventListener("click", createChat);
deleteChatBtn.addEventListener("click", async () => {
  if (!currentChatId) return;
  const ok = confirm("Delete current chat?");
  if (!ok) return;
  await fetch(`/api/chats/${currentChatId}`, { method: "DELETE" });
  currentChatId = null;
  await loadChats();
});

ctxDeleteChatBtn.addEventListener("click", async () => {
  if (!contextChatId) return;
  await fetch(`/api/chats/${contextChatId}`, { method: "DELETE" });
  if (currentChatId === contextChatId) currentChatId = null;
  contextChatId = null;
  contextMenuEl.hidden = true;
  await loadChats();
});

document.addEventListener("click", (e) => {
  if (contextMenuEl.hidden) return;
  if (!contextMenuEl.contains(e.target)) {
    contextMenuEl.hidden = true;
    contextChatId = null;
  }
});

async function boot() {
  await loadChats();
}

boot();

