const chatListEl = document.getElementById("chat-list");
const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("message-input");
const imageUploadBtn = document.getElementById("image-upload-btn");
const imageInputEl = document.getElementById("image-input");
const newChatBtn = document.getElementById("new-chat-btn");
const deleteChatBtn = document.getElementById("delete-chat-btn");
const globalMenuBtn = document.getElementById("global-menu-btn");
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const appEl = document.querySelector(".app");
const contextMenuEl = document.getElementById("chat-context-menu");
const ctxRenameChatBtn = document.getElementById("ctx-rename-chat-btn");
const ctxDeleteChatBtn = document.getElementById("ctx-delete-chat-btn");
const libraryContextMenuEl = document.getElementById("library-context-menu");
const ctxRenameLibraryBtn = document.getElementById("ctx-rename-library-btn");
const chatPanelEl = document.getElementById("chat-panel");
const libraryViewEl = document.getElementById("library-view");
const libraryGridEl = document.getElementById("library-grid");
const sidebarRecentGridEl = document.getElementById("sidebar-recent-grid");
const composerSendBtn = formEl.querySelector("button[type='submit']");
const landingEl = document.getElementById("landing");
const landingFormEl = document.getElementById("landing-form");
const landingInputEl = document.getElementById("landing-input");
const landingSendBtn = document.getElementById("landing-send-btn");
const landingImageBtn = document.getElementById("landing-image-btn");
const landingImageInputEl = document.getElementById("landing-image-input");

let currentChatId = null;
let pendingQuestion = null;
let contextChatId = null;
let contextChatTitle = "";
let contextLibraryItemKey = null;
let renamingChatId = null;
let renamingChatDraft = "";
let renamingLibraryKey = null;
let renamingLibraryDraft = "";
let activeView = "chat";
let libraryItems = [];
let libraryRefreshTimer = null;
const LIBRARY_CACHE_KEY = "fastener-library-cache-v1";
const THEME_KEY = "fastener-ui-theme-v1";
let libraryCache = (() => {
  try {
    const raw = localStorage.getItem(LIBRARY_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_) {
    return {};
  }
})();

function detectInitialTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch (_) {
    // ignore
  }
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  document.body.dataset.theme = theme === "dark" ? "dark" : "light";
  if (themeToggleBtn) {
    const isDark = theme === "dark";
    themeToggleBtn.setAttribute("aria-pressed", isDark ? "true" : "false");
    themeToggleBtn.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  }
}

function toggleTheme() {
  const next = document.body.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch (_) {
    // ignore storage issues
  }
}

function capitalize(s) {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function appendOptimisticUserBubble(text) {
  const node = document.createElement("div");
  node.className = "bubble user";
  const content = document.createElement("div");
  content.textContent = capitalize(text);
  node.appendChild(content);
  messagesEl.appendChild(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setLandingMode(enabled) {
  if (!landingEl) return;
  if (enabled && contextMenuEl) {
    contextMenuEl.hidden = true;
    contextChatId = null;
    if (libraryContextMenuEl) {
      libraryContextMenuEl.hidden = true;
      contextLibraryItemKey = null;
    }
  }
  document.body.classList.toggle("landing-active", enabled);
  landingEl.hidden = !enabled;
  appEl.classList.toggle("hidden", enabled);
  if (enabled) {
    landingInputEl?.focus();
  } else {
    inputEl?.focus();
  }
}

function persistLibraryNames() {
  try {
    localStorage.setItem(LIBRARY_CACHE_KEY, JSON.stringify(libraryCache));
  } catch (_) {
    // Non-fatal: storage can fail in strict/private modes.
  }
}

function queueLibraryRefresh(delayMs = 120) {
  if (libraryRefreshTimer) {
    clearTimeout(libraryRefreshTimer);
  }
  libraryRefreshTimer = setTimeout(() => {
    libraryRefreshTimer = null;
    refreshLibraryData().catch(() => {
      // Background refresh failure should never block chat UX.
    });
  }, delayMs);
}

function setActiveView(nextView) {
  activeView = nextView === "library" ? "library" : "chat";
  if (chatPanelEl) chatPanelEl.hidden = activeView !== "chat";
  if (libraryViewEl) libraryViewEl.hidden = activeView !== "library";
  if (activeView !== "chat" && contextMenuEl) {
    contextMenuEl.hidden = true;
    contextChatId = null;
  }
  if (libraryContextMenuEl) {
    libraryContextMenuEl.hidden = true;
    contextLibraryItemKey = null;
  }
}

function getContextChatMeta() {
  const idFromData = contextMenuEl?.dataset?.chatId;
  const parsed = Number(idFromData || contextChatId || 0);
  const chatId = Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  const chatTitle = (contextMenuEl?.dataset?.chatTitle || contextChatTitle || "Chat").trim();
  return { chatId, chatTitle };
}

function hideChatContextMenu() {
  if (!contextMenuEl) return;
  contextMenuEl.hidden = true;
  contextMenuEl.dataset.chatId = "";
  contextMenuEl.dataset.chatTitle = "";
  contextChatId = null;
  contextChatTitle = "";
}

async function saveInlineChatRename(chatId) {
  const title = (renamingChatDraft || "").trim();
  if (!title) {
    alert("Title cannot be empty.");
    return;
  }
  const res = await fetch(`/api/chats/${chatId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: "Could not rename chat." }));
    alert(errorBody.detail || "Could not rename chat.");
    return;
  }
  renamingChatId = null;
  renamingChatDraft = "";
  await loadChats();
}

async function startInlineChatRename(chatId, title) {
  renamingChatId = chatId;
  renamingChatDraft = (title || "").trim();
  hideChatContextMenu();
  await loadChats();
  setTimeout(() => {
    const input = document.querySelector(`.chat-item[data-chat-id="${chatId}"] .chat-rename-input`);
    if (input) {
      input.focus();
      input.select();
    }
  }, 0);
}

function itemKey(item) {
  return item.step_url || item.stl_url || item.preview_url || `${item.chat_id}:${item.message_idx}`;
}

function cleanGeneratedName(raw) {
  return (raw || "")
    .replace(/\.\s*use the buttons.*$/i, "")
    .replace(/\s*generated\.?\s*$/i, "")
    .replace(/^done:\s*/i, "")
    .trim();
}

function itemName(item) {
  const cleaned = cleanGeneratedName(item.name);
  return cleaned || "Generated Fastener";
}

function recentItemName(item) {
  return itemName(item);
}

function deriveItemName(chat, message) {
  if (chat.title && chat.title !== "New Fastener") {
    return chat.title;
  }
  if (typeof message.content === "string") {
    const first = message.content.split("\n")[0].trim();
    const cleaned = cleanGeneratedName(first);
    if (cleaned) return cleaned;
  }
  return chat.title || "Generated Fastener";
}

function cacheUpsert(item) {
  const key = itemKey(item);
  const existing = libraryCache[key] || {};
  const userRenamed = Boolean(existing.user_renamed);
  libraryCache[key] = {
    ...existing,
    ...item,
    name: userRenamed ? existing.name : (item.name || existing.name || "Generated Fastener").trim(),
    user_renamed: userRenamed,
    deleted: Boolean(existing.deleted),
    saved_at: Date.now(),
  };
  return libraryCache[key];
}

function renameLibraryItem(item) {
  const key = itemKey(item);
  const existing = libraryCache[key] || item;
  renamingLibraryKey = key;
  renamingLibraryDraft = itemName(existing);
  renderLibraryGrid();
  setTimeout(() => {
    const input = document.querySelector(".library-rename-input");
    if (input) { input.focus(); input.select(); }
  }, 0);
}

function saveLibraryRename() {
  const trimmed = (renamingLibraryDraft || "").trim();
  if (!trimmed) return;
  const key = renamingLibraryKey;
  if (!key) return;
  const existing = libraryCache[key] || {};
  libraryCache[key] = {
    ...existing,
    name: trimmed,
    user_renamed: true,
    deleted: false,
    saved_at: Date.now(),
  };
  renamingLibraryKey = null;
  renamingLibraryDraft = "";
  persistLibraryNames();
  queueLibraryRefresh(0);
}

function cancelLibraryRename() {
  renamingLibraryKey = null;
  renamingLibraryDraft = "";
  renderLibraryGrid();
}

function showLibraryContextMenu(e, item) {
  if (!libraryContextMenuEl) return;
  e.preventDefault();
  const cached = cacheUpsert(item);
  persistLibraryNames();
  contextLibraryItemKey = itemKey(cached);
  libraryContextMenuEl.hidden = false;
  libraryContextMenuEl.style.left = `${e.clientX}px`;
  libraryContextMenuEl.style.top = `${e.clientY}px`;
}

function deleteLibraryItem(item) {
  const key = itemKey(item);
  const existing = libraryCache[key] || item;
  libraryCache[key] = {
    ...existing,
    ...item,
    deleted: true,
    saved_at: Date.now(),
  };
  persistLibraryNames();
  queueLibraryRefresh(0);
}

async function openLibraryItemChat(item) {
  if (!item.chat_id) {
    alert("Original chat is unavailable for this library item.");
    return;
  }
  const res = await fetch(`/api/chats/${item.chat_id}`);
  if (!res.ok) {
    alert("Original chat was deleted. Item remains in library.");
    return;
  }
  setActiveView("chat");
  await loadChat(item.chat_id);
}

function renderSidebarRecent() {
  if (!sidebarRecentGridEl) return;
  sidebarRecentGridEl.innerHTML = "";
  const hasOverflow = libraryItems.length > 2;
  const recent = hasOverflow ? libraryItems.slice(0, 1) : libraryItems.slice(0, 2);
  for (const item of recent) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-tile";
    button.title = recentItemName(item);
    button.onclick = async () => openLibraryItemChat(item);
    button.oncontextmenu = (e) => showLibraryContextMenu(e, item);

    const preview = document.createElement("div");
    preview.className = "recent-thumb";
    if (item.preview_url) {
      initPreviewImage(preview, item.preview_url, {
        onReady: () => {},
        onError: () => {
          preview.textContent = "Preview unavailable";
        },
      });
    } else {
      preview.textContent = "No preview";
    }

    const label = document.createElement("div");
    label.className = "recent-label";
    label.textContent = recentItemName(item);
    button.appendChild(preview);
    button.appendChild(label);
    sidebarRecentGridEl.appendChild(button);
  }

  if (hasOverflow) {
    const viewAllBtn = document.createElement("button");
    viewAllBtn.type = "button";
    viewAllBtn.className = "recent-tile recent-tile-full";
    viewAllBtn.title = "View full library";
    const icon = document.createElement("span");
    icon.className = "recent-tile-full-icon";
    icon.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4H20v14H6.5A2.5 2.5 0 0 0 4 20.5V6.5Zm2.5-.9A.9.9 0 0 0 5.6 6.5v10.98A4 4 0 0 1 6.5 17.4H18.4V5.6H6.5Zm-.9 14.9c0 .5.4.9.9.9h13.9v-2.4H6.5a.9.9 0 0 0-.9.9Z" fill="currentColor"/>
      </svg>
    `;
    const label = document.createElement("span");
    label.className = "recent-tile-full-label";
    label.textContent = "View Full Library";
    viewAllBtn.appendChild(icon);
    viewAllBtn.appendChild(label);
    viewAllBtn.onclick = () => setActiveView("library");
    sidebarRecentGridEl.appendChild(viewAllBtn);
  }
}

function renderLibraryGrid() {
  if (!libraryGridEl) return;
  libraryGridEl.innerHTML = "";
  if (libraryItems.length === 0) {
    const empty = document.createElement("div");
    empty.className = "library-empty";
    empty.textContent = "No generated fasteners yet. Generate one from chat to populate the library.";
    libraryGridEl.appendChild(empty);
    return;
  }

  for (const item of libraryItems) {
    const card = document.createElement("article");
    card.className = "library-card";
    card.oncontextmenu = (e) => showLibraryContextMenu(e, item);

    const media = document.createElement("div");
    media.className = "library-media";
    if (item.preview_url) {
      initPreviewImage(media, item.preview_url, {
        onReady: () => {},
        onError: () => {
          media.textContent = "Preview unavailable";
        },
      });
    } else {
      media.textContent = "Preview unavailable";
    }

    const key = itemKey(item);
    const isRenaming = renamingLibraryKey === key;

    let title;
    if (isRenaming) {
      title = document.createElement("div");
      title.className = "library-item-title library-renaming";
      const input = document.createElement("input");
      input.type = "text";
      input.className = "library-rename-input";
      input.value = renamingLibraryDraft;
      input.oninput = () => { renamingLibraryDraft = input.value; };
      input.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); saveLibraryRename(); }
        else if (e.key === "Escape") { e.preventDefault(); cancelLibraryRename(); }
      };
      input.onblur = () => { saveLibraryRename(); };
      title.appendChild(input);
    } else {
      title = document.createElement("div");
      title.className = "library-item-title";
      title.textContent = itemName(item);
      title.title = "Click Rename or right-click to rename";
      title.oncontextmenu = (e) => showLibraryContextMenu(e, item);
    }

    const actions = document.createElement("div");
    actions.className = "library-actions";

    const openBtn = document.createElement("button");
    const chatUnavailable = !item.chat_id || Boolean(item.chat_missing);
    openBtn.type = "button";
    openBtn.className = "toolbar-btn" + (chatUnavailable ? " disabled" : "");
    openBtn.textContent = "Open Chat";
    openBtn.disabled = chatUnavailable;
    openBtn.title = chatUnavailable ? "Original chat was deleted" : "Open source chat";
    if (!chatUnavailable) {
      openBtn.onclick = async () => openLibraryItemChat(item);
    }
    actions.appendChild(openBtn);

    const zipBtn = document.createElement("a");
    zipBtn.className = "download-btn" + (item.bundle_url ? "" : " disabled");
    zipBtn.textContent = "Download ZIP";
    zipBtn.href = item.bundle_url || "#";
    zipBtn.download = "";
    actions.appendChild(zipBtn);

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "toolbar-btn";
    renameBtn.textContent = "Rename";
    renameBtn.onclick = () => renameLibraryItem(item);
    actions.appendChild(renameBtn);

    const deleteIconBtn = document.createElement("button");
    deleteIconBtn.type = "button";
    deleteIconBtn.className = "library-delete-icon";
    deleteIconBtn.title = "Delete from library";
    deleteIconBtn.setAttribute("aria-label", "Delete from library");
    deleteIconBtn.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M8.5 5h7l.75 1H20v2H4V6h3.75L8.5 5ZM6 9h12l-1 10H7L6 9Zm3 2v6h2v-6H9Zm4 0v6h2v-6h-2Z" fill="currentColor"/>
      </svg>
    `;
    deleteIconBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      deleteLibraryItem(item);
    };
    actions.appendChild(deleteIconBtn);

    card.appendChild(title);
    card.appendChild(media);
    card.appendChild(actions);
    libraryGridEl.appendChild(card);
  }
}

async function refreshLibraryData() {
  const res = await fetch("/api/chats");
  if (!res.ok) return;
  const chats = await res.json();
  const detailedChats = await Promise.all(
    chats.map(async (chat) => {
      const detailRes = await fetch(`/api/chats/${chat.id}`);
      if (!detailRes.ok) return null;
      return detailRes.json();
    }),
  );
  const items = [];
  const seenKeys = new Set();
  for (const chat of detailedChats) {
    if (!chat || !Array.isArray(chat.messages)) continue;
    chat.messages.forEach((msg, idx) => {
      if (msg.kind !== "result") return;
      if (!msg.step_url && !msg.stl_url && !msg.preview_url) return;
      const generated = {
        chat_id: chat.id,
        chat_title: chat.title || "Chat",
        message_idx: idx,
        chat_missing: false,
        name: deriveItemName(chat, msg),
        step_url: msg.step_url || "",
        stl_url: msg.stl_url || "",
        preview_url: msg.preview_url || "",
        drawing_url: msg.drawing_url || "",
        bundle_url: msg.bundle_url || "",
      };
      const cached = cacheUpsert(generated);
      const key = itemKey(cached);
      seenKeys.add(key);
      if (!cached.deleted) items.push(cached);
    });
  }
  for (const [key, cached] of Object.entries(libraryCache)) {
    if (!cached || cached.deleted || seenKeys.has(key)) continue;
    items.push({
      ...cached,
      chat_missing: true,
    });
  }
  persistLibraryNames();
  libraryItems = items.sort((a, b) => {
    const aTs = Number(a.saved_at || 0);
    const bTs = Number(b.saved_at || 0);
    if (aTs !== bTs) return bTs - aTs;
    const aChat = Number(a.chat_id || 0);
    const bChat = Number(b.chat_id || 0);
    if (aChat !== bChat) return bChat - aChat;
    return Number(b.message_idx || 0) - Number(a.message_idx || 0);
  });
  renderSidebarRecent();
  renderLibraryGrid();
}

async function startFromLanding(rawValue) {
  const content = (rawValue || "").trim();
  if (!content) return;
  setLandingMode(false);
  setActiveView("chat");
  // Recover from any stale disabled state so landing submit can proceed.
  if (composerSendBtn.disabled) setWorking(false);
  // Landing always starts a fresh chat, never reuses the currently open one.
  await createChat();
  inputEl.value = content;
  await sendMessage(content);
}

async function sendMessage(rawValue) {
  if (composerSendBtn.disabled) return;
  if (!currentChatId) {
    await createChat();
  }
  const raw = typeof rawValue === "string" ? rawValue : inputEl.value;
  const content = raw.trim();
  if (!content && !pendingQuestion) return;
  const outbound = pendingQuestion ? raw : content;
  inputEl.value = "";
  appendOptimisticUserBubble(outbound);
  setWorking(true);
  try {
    const res = await fetch(`/api/chats/${currentChatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: outbound }),
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

async function sendImageMessage(file) {
  if (!file) return;
  if (composerSendBtn.disabled) return;
  if (!currentChatId) {
    await createChat();
  }
  setWorking(true);
  try {
    const body = new FormData();
    body.append("file", file);
    body.append("content", file.name || "Uploaded reference image");
    const res = await fetch(`/api/chats/${currentChatId}/image`, {
      method: "POST",
      body,
    });
    if (!res.ok) {
      const errorBody = await res.json().catch(() => ({ detail: "Image upload failed." }));
      alert(errorBody.detail || "Could not process image.");
      await loadChat(currentChatId);
      return;
    }
    const data = await res.json();
    if (!data.chat_id) {
      alert("Image request failed, please retry.");
      await loadChat(currentChatId);
      return;
    }
    await loadChat(data.chat_id);
  } catch (_) {
    alert("Network error while uploading image. Please retry.");
    await loadChat(currentChatId);
  } finally {
    if (imageInputEl) imageInputEl.value = "";
    setWorking(false);
  }
}

function renderChatList(chats) {
  chatListEl.innerHTML = "";
  for (const chat of chats) {
    const div = document.createElement("div");
    div.className = "chat-item" + (chat.id === currentChatId ? " active" : "");
    div.dataset.chatId = String(chat.id);
    div.dataset.chatTitle = chat.title;
    if (chat.id === renamingChatId) {
      div.classList.add("editing");
      const input = document.createElement("input");
      input.type = "text";
      input.className = "chat-rename-input";
      input.value = renamingChatDraft || chat.title;
      input.oninput = () => {
        renamingChatDraft = input.value;
      };
      input.onkeydown = async (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          await saveInlineChatRename(chat.id);
        } else if (e.key === "Escape") {
          e.preventDefault();
          renamingChatId = null;
          renamingChatDraft = "";
          await loadChats();
        }
      };
      const actions = document.createElement("div");
      actions.className = "chat-rename-actions";
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "edit-btn";
      saveBtn.textContent = "Save";
      saveBtn.onclick = async (e) => {
        e.stopPropagation();
        await saveInlineChatRename(chat.id);
      };
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "edit-btn";
      cancelBtn.textContent = "Cancel";
      cancelBtn.onclick = async (e) => {
        e.stopPropagation();
        renamingChatId = null;
        renamingChatDraft = "";
        await loadChats();
      };
      actions.appendChild(saveBtn);
      actions.appendChild(cancelBtn);
      div.appendChild(input);
      div.appendChild(actions);
      div.onclick = (e) => e.stopPropagation();
    } else {
      div.textContent = chat.title;
      div.onclick = async () => {
        setActiveView("chat");
        await loadChat(chat.id);
      };
    }
    div.oncontextmenu = async (e) => {
      e.preventDefault();
      contextChatId = chat.id;
      contextChatTitle = chat.title;
      if (!contextMenuEl) return;
      contextMenuEl.dataset.chatId = String(chat.id);
      contextMenuEl.dataset.chatTitle = chat.title || "Chat";
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

  if (message.kind === "image" && message.image_url) {
    const imageWrap = document.createElement("div");
    imageWrap.className = "chat-upload-wrap";
    const img = document.createElement("img");
    img.className = "chat-upload-image";
    img.src = message.image_url;
    img.alt = message.content || "Uploaded image";
    imageWrap.appendChild(img);
    node.appendChild(imageWrap);
  } else if (message.kind === "result" && message.stl_url) {
    // Result text is already shown in the preview card header.
  } else {
    const content = document.createElement("div");
    content.textContent = message.role === "user" ? capitalize(message.content) : message.content;
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
    (
      /what kind of drive is it\??/i.test(chat.pending_question) ||
      (/drive/i.test(chat.pending_question) && /\b(hex|phillips|torx|no drive)\b/i.test(chat.pending_question))
    );
  const asksYesNoChoice =
    message.role === "bot" &&
    !!chat.pending_question &&
    (
      /\[y\/N\]:?\s*$/i.test(chat.pending_question) ||
      /keep your value\?/i.test(chat.pending_question) ||
      /do you want a matching nut\?/i.test(chat.pending_question) ||
      /use max threadable length/i.test(chat.pending_question) ||
      /does this look right/i.test(chat.pending_question)
    );
  const asksRoundHexChoice =
    message.role === "bot" &&
    !!chat.pending_question &&
    (
      /what style for the matching nut\??/i.test(chat.pending_question) ||
      /style for the matching nut/i.test(chat.pending_question) ||
      /what shape for the nut\??/i.test(chat.pending_question) ||
      /nut shape/i.test(chat.pending_question) ||
      /\[hex\/square\]:?\s*$/i.test(chat.pending_question)
    );
  const asksHeadChoice =
    message.role === "bot" &&
    !!chat.pending_question &&
    (
      /missing head type/i.test(chat.pending_question) ||
      /what (kind of|type of) head/i.test(chat.pending_question) ||
      /\(flat\/pan\/button\/hex\)/i.test(chat.pending_question)
    );
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
      ["square", "Square"],
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
  } else if (isLastMessage && asksHeadChoice && chat.pending_question) {
    const choices = document.createElement("div");
    choices.className = "choice-actions";
    const options = [
      ["flat", "Flat"],
      ["pan", "Pan"],
      ["button", "Button"],
      ["hex", "Hex"],
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
    node.appendChild(resultCard(message, idx));
  }
  return node;
}

function resultCard(message, messageIdx = -1) {
  const card = document.createElement("div");
  card.className = "preview-card";
  const resultItem = {
    chat_id: currentChatId,
    chat_title: "Current Chat",
    message_idx: messageIdx,
    name: deriveItemName({ title: "Fastener" }, message),
    step_url: message.step_url || "",
    stl_url: message.stl_url || "",
    preview_url: message.preview_url || "",
    drawing_url: message.drawing_url || "",
    bundle_url: message.bundle_url || "",
  };
  const isNutPreview =
    typeof message.content === "string" &&
    /\b(hex|square)\s+nut\s+generated\b/i.test(message.content);

  const header = document.createElement("div");
  header.className = "preview-card-header";
  const key = itemKey(resultItem);
  const existing = libraryCache[key];
  if (existing) resultItem.name = existing.name || resultItem.name;
  header.textContent = itemName(resultItem);
  header.title = "Right-click to rename";
  header.oncontextmenu = (e) => showLibraryContextMenu(e, resultItem);
  card.appendChild(header);

  const preview = document.createElement("div");
  preview.className = "preview-canvas";
  if (isNutPreview) preview.classList.add("nut-preview");
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
  let retried = false;
  img.onload = () => hooks.onReady();
  img.onerror = () => {
    if (!retried) {
      retried = true;
      const glue = previewUrl.includes("?") ? "&" : "?";
      img.src = `${previewUrl}${glue}v=${Date.now()}`;
      return;
    }
    hooks.onError();
  };
  img.src = previewUrl;
  img.className = "preview-img-colorized";
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
  if (imageUploadBtn) imageUploadBtn.disabled = isWorking;
  composerSendBtn.textContent = isWorking ? "Working..." : "Send";
}

function toggleSidebar() {
  appEl.classList.toggle("sidebar-collapsed");
}

async function loadChats() {
  const res = await fetch("/api/chats");
  const chats = await res.json();
  renderChatList(chats);
  if (chats.length === 0) {
    currentChatId = null;
    messagesEl.innerHTML = "";
    queueLibraryRefresh(0);
    return;
  }
  if (!currentChatId) {
    await loadChat(chats[chats.length - 1].id);
    queueLibraryRefresh();
    return;
  }
  if (!chats.some((c) => c.id === currentChatId)) {
    currentChatId = null;
    await loadChats();
    return;
  }
  queueLibraryRefresh();
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
  queueLibraryRefresh();
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  await sendMessage(inputEl.value);
});

if (imageUploadBtn && imageInputEl) {
  imageUploadBtn.addEventListener("click", () => {
    if (composerSendBtn.disabled) return;
    imageInputEl.click();
  });
  imageInputEl.addEventListener("change", async () => {
    const file = imageInputEl.files && imageInputEl.files[0];
    if (!file) return;
    await sendImageMessage(file);
  });
}

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage(inputEl.value);
  }
});

if (globalMenuBtn) {
  globalMenuBtn.addEventListener("click", toggleSidebar);
}

if (newChatBtn) {
  newChatBtn.addEventListener("click", createChat);
}
if (deleteChatBtn) deleteChatBtn.addEventListener("click", async () => {
  if (!currentChatId) return;
  const ok = confirm("Delete current chat?");
  if (!ok) return;
  await fetch(`/api/chats/${currentChatId}`, { method: "DELETE" });
  currentChatId = null;
  await loadChats();
});
if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", toggleTheme);
}

async function handleContextDelete() {
  const { chatId } = getContextChatMeta();
  if (!chatId) return;
  const ok = confirm("Delete this chat?");
  if (!ok) return;
  const res = await fetch(`/api/chats/${chatId}`, { method: "DELETE" });
  if (!res.ok) {
    alert("Could not delete chat.");
    return;
  }
  if (currentChatId === chatId) currentChatId = null;
  hideChatContextMenu();
  await loadChats();
}

async function handleContextRename() {
  const { chatId, chatTitle } = getContextChatMeta();
  if (!chatId) return;
  await startInlineChatRename(chatId, chatTitle || "Chat");
}

if (contextMenuEl) {
  contextMenuEl.addEventListener("click", async (e) => {
    e.stopPropagation();
    const target = e.target instanceof Element ? e.target.closest("button") : null;
    if (!target) return;
    if (target.id === "ctx-delete-chat-btn") {
      e.preventDefault();
      await handleContextDelete();
      return;
    }
    if (target.id === "ctx-rename-chat-btn") {
      e.preventDefault();
      await handleContextRename();
    }
  });
}

if (ctxRenameLibraryBtn) {
  ctxRenameLibraryBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!contextLibraryItemKey) return;
    const item = libraryCache[contextLibraryItemKey];
    if (libraryContextMenuEl) libraryContextMenuEl.hidden = true;
    if (item) renameLibraryItem(item);
    contextLibraryItemKey = null;
  });
}

if (libraryContextMenuEl) {
  libraryContextMenuEl.addEventListener("click", (e) => e.stopPropagation());
}

document.addEventListener("click", (e) => {
  if (!contextMenuEl) return;
  if (contextMenuEl.hidden) return;
  if (!contextMenuEl.contains(e.target)) {
    hideChatContextMenu();
  }
});

document.addEventListener("click", (e) => {
  if (!libraryContextMenuEl || libraryContextMenuEl.hidden) return;
  if (!libraryContextMenuEl.contains(e.target)) {
    libraryContextMenuEl.hidden = true;
    contextLibraryItemKey = null;
  }
});

async function boot() {
  applyTheme(detectInitialTheme());
  setWorking(false);
  if (landingSendBtn) landingSendBtn.disabled = false;
  setActiveView("chat");
  setLandingMode(true);
  await loadChats();
}

boot();

if (landingFormEl) {
  landingFormEl.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (landingSendBtn.disabled) return;
    const text = landingInputEl.value;
    landingInputEl.value = "";
    landingSendBtn.disabled = true;
    const previousLabel = landingSendBtn.textContent;
    landingSendBtn.textContent = "Generating...";
    try {
      await startFromLanding(text);
    } catch (_) {
      alert("Could not start generation. Please try again.");
    } finally {
      landingSendBtn.disabled = false;
      landingSendBtn.textContent = previousLabel;
    }
  });
}

if (landingImageBtn && landingImageInputEl) {
  landingImageBtn.addEventListener("click", () => {
    landingImageInputEl.click();
  });
  landingImageInputEl.addEventListener("change", async () => {
    const file = landingImageInputEl.files && landingImageInputEl.files[0];
    if (!file) return;
    setLandingMode(false);
    setActiveView("chat");
    await createChat();
    await sendImageMessage(file);
    landingImageInputEl.value = "";
  });
}

