const chatListEl = document.getElementById("chat-list");
const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("message-input");
const newChatBtn = document.getElementById("new-chat-btn");
const deleteChatBtn = document.getElementById("delete-chat-btn");
const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");
const appEl = document.querySelector(".app");
const contextMenuEl = document.getElementById("chat-context-menu");
const ctxRenameChatBtn = document.getElementById("ctx-rename-chat-btn");
const ctxDeleteChatBtn = document.getElementById("ctx-delete-chat-btn");
const composerSendBtn = formEl.querySelector("button[type='submit']");

let currentChatId = null;
let pendingQuestion = null;
let contextChatId = null;
let contextChatTitle = "";
let editingMessageIdx = null;
let editingDraft = "";

async function sendMessage(rawValue) {
  if (composerSendBtn.disabled) return;
  if (!currentChatId) {
    await createChat();
  }
  const raw = typeof rawValue === "string" ? rawValue : inputEl.value;
  const content = raw.trim();
  if (!content && !pendingQuestion) return;
  inputEl.value = "";
  setWorking(true);
  try {
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
  } catch (_) {
    alert("Network error while sending. Please retry.");
    await loadChat(currentChatId);
  } finally {
    setWorking(false);
  }
}

function renderChatList(chats) {
  chatListEl.innerHTML = "";
  for (const chat of chats) {
    const div = document.createElement("div");
    div.className = "chat-item" + (chat.id === currentChatId ? " active" : "");
    div.textContent = chat.title;
    div.dataset.chatTitle = chat.title;
    div.onclick = () => loadChat(chat.id);
    div.oncontextmenu = async (e) => {
      e.preventDefault();
      contextChatId = chat.id;
      contextChatTitle = chat.title;
      contextMenuEl.hidden = false;
      contextMenuEl.style.left = `${e.clientX}px`;
      contextMenuEl.style.top = `${e.clientY}px`;
    };
    chatListEl.appendChild(div);
  }
}

function bubble(message, idx, latestUserIdx, chat) {
  const node = document.createElement("div");
  node.className = `bubble ${message.role}`;

  if (message.role === "user" && idx === editingMessageIdx) {
    node.classList.add("editing");
    const input = document.createElement("textarea");
    input.className = "edit-input";
    input.value = editingDraft || message.content;
    input.rows = 2;
    input.oninput = () => {
      editingDraft = input.value;
    };
    input.onkeydown = async (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        await saveEdit(idx);
      }
    };
    node.appendChild(input);

    const actions = document.createElement("div");
    actions.className = "edit-actions";
    const saveBtn = document.createElement("button");
    saveBtn.className = "edit-btn";
    saveBtn.textContent = "Save";
    saveBtn.onclick = async () => saveEdit(idx);
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "edit-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.onclick = () => {
      editingMessageIdx = null;
      editingDraft = "";
      loadChat(currentChatId);
    };
    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);
    node.appendChild(actions);
  } else {
    const content = document.createElement("div");
    content.textContent = message.content;
    node.appendChild(content);
  }

  const isLastMessage = idx === chat.messages.length - 1;
  const asksFastenerChoice =
    message.role === "bot" &&
    typeof message.content === "string" &&
    /screw\s+or\s+(?:a\s+)?bolt/i.test(message.content);
  const asksDriveChoice =
    message.role === "bot" &&
    !!chat.pending_question &&
    /drive/i.test(chat.pending_question) &&
    /\b(hex|phillips|torx|no drive)\b/i.test(chat.pending_question);
  const asksYesNoChoice =
    message.role === "bot" &&
    !!chat.pending_question &&
    (
      /\[y\/N\]:?\s*$/i.test(chat.pending_question) ||
      /keep your value\?/i.test(chat.pending_question) ||
      /do you want a matching nut\?/i.test(chat.pending_question) ||
      /use max threadable length/i.test(chat.pending_question)
    );
  const asksRoundHexChoice =
    message.role === "bot" &&
    !!chat.pending_question &&
    (/style for the matching nut/i.test(chat.pending_question) || /\[hex\/square\]:?\s*$/i.test(chat.pending_question));
  if (isLastMessage && asksFastenerChoice && chat.pending_question) {
    const choices = document.createElement("div");
    choices.className = "choice-actions";
    for (const option of ["screw", "bolt"]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice-btn";
      btn.textContent = option[0].toUpperCase() + option.slice(1);
      btn.onclick = async () => {
        await sendMessage(option);
      };
      choices.appendChild(btn);
    }
    node.appendChild(choices);
  } else if (isLastMessage && asksDriveChoice && chat.pending_question) {
    const choices = document.createElement("div");
    choices.className = "choice-actions";
    const options = [
      ["hex", "Hex"],
      ["phillips", "Phillips"],
      ["torx", "Torx"],
      ["no drive", "No Drive"],
    ];
    for (const [value, label] of options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice-btn";
      btn.textContent = label;
      btn.onclick = async () => {
        await sendMessage(value);
      };
      choices.appendChild(btn);
    }
    node.appendChild(choices);
  } else if (isLastMessage && asksYesNoChoice && chat.pending_question) {
    const choices = document.createElement("div");
    choices.className = "choice-actions";
    const options = [
      ["y", "Yes"],
      ["n", "No"],
    ];
    for (const [value, label] of options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice-btn";
      btn.textContent = label;
      btn.onclick = async () => {
        await sendMessage(value);
      };
      choices.appendChild(btn);
    }
    node.appendChild(choices);
  } else if (isLastMessage && asksRoundHexChoice && chat.pending_question) {
    const choices = document.createElement("div");
    choices.className = "choice-actions";
    const options = [
      ["hex", "Hex"],
      ["square", "Square"],
    ];
    for (const [value, label] of options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice-btn";
      btn.textContent = label;
      btn.onclick = async () => {
        await sendMessage(value);
      };
      choices.appendChild(btn);
    }
    node.appendChild(choices);
  }

  if (message.kind === "result" && message.stl_url) {
    node.appendChild(resultCard(message));
  }

  if (message.role === "user" && idx === latestUserIdx) {
    const editBtn = document.createElement("button");
    editBtn.className = "edit-btn";
    editBtn.textContent = "Edit";
    editBtn.onclick = () => {
      editingMessageIdx = idx;
      editingDraft = message.content;
      loadChat(currentChatId);
    };
    node.appendChild(editBtn);
  }
  return node;
}

async function saveEdit(idx) {
  const updated = editingDraft.trim();
  if (!updated) {
    alert("Edited message cannot be empty.");
    return;
  }
  setWorking(true);
  const res = await fetch(`/api/chats/${currentChatId}/messages/${idx}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: updated }),
  });
  setWorking(false);
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: "Could not edit message." }));
    alert(errorBody.detail || "Could not edit message.");
    return;
  }
  editingMessageIdx = null;
  editingDraft = "";
  await loadChat(currentChatId);
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

  const drawingBtn = document.createElement("a");
  drawingBtn.className = "download-btn disabled";
  drawingBtn.textContent = "Download Drawing";
  drawingBtn.href = message.drawing_url || "#";
  drawingBtn.download = "";

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

  const bundleBtn = document.createElement("a");
  bundleBtn.className = "download-btn disabled";
  bundleBtn.textContent = "Download ZIP (All)";
  bundleBtn.href = message.bundle_url || "#";
  bundleBtn.download = "";

  actions.appendChild(drawingBtn);
  actions.appendChild(stepBtn);
  actions.appendChild(stlBtn);
  actions.appendChild(bundleBtn);
  card.appendChild(actions);

  if (!message.step_url || !message.stl_url) {
    drawingBtn.textContent = "No model files";
    return card;
  }
  if (message.drawing_url) {
    drawingBtn.classList.remove("disabled");
  } else {
    drawingBtn.textContent = "Drawing unavailable";
  }

  initPreviewImage(preview, message.preview_url, {
    onReady: () => {
      stepBtn.classList.remove("disabled");
      stlBtn.classList.remove("disabled");
      if (message.bundle_url) bundleBtn.classList.remove("disabled");
    },
    onError: () => {
      stepBtn.classList.remove("disabled");
      stlBtn.classList.remove("disabled");
      if (message.bundle_url) bundleBtn.classList.remove("disabled");
    },
  });

  if (!message.bundle_url) {
    bundleBtn.textContent = "ZIP unavailable";
  }

  return card;
}

function initPreviewImage(container, previewUrl, hooks) {
  if (!previewUrl) {
    hooks.onError();
    return;
  }
  const img = document.createElement("img");
  img.alt = "Fastener preview";
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
    messagesEl.appendChild(bubble(msg, idx, latestUserIdx, chat));
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setWorking(isWorking) {
  composerSendBtn.disabled = isWorking;
  composerSendBtn.textContent = isWorking ? "Working..." : "Send";
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
  await sendMessage(inputEl.value);
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage(inputEl.value);
  }
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

ctxRenameChatBtn.addEventListener("click", async () => {
  if (!contextChatId) return;
  const next = prompt("Rename chat:", contextChatTitle || "Chat");
  if (next === null) return;
  const title = next.trim();
  if (!title) {
    alert("Title cannot be empty.");
    return;
  }
  const res = await fetch(`/api/chats/${contextChatId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: "Could not rename chat." }));
    alert(errorBody.detail || "Could not rename chat.");
    return;
  }
  contextMenuEl.hidden = true;
  contextChatId = null;
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

