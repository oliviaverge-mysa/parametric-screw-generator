const chatListEl = document.getElementById("chat-list");
const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("message-input");
const newChatBtn = document.getElementById("new-chat-btn");

let currentChatId = null;

function renderChatList(chats) {
  chatListEl.innerHTML = "";
  for (const chat of chats) {
    const div = document.createElement("div");
    div.className = "chat-item" + (chat.id === currentChatId ? " active" : "");
    div.textContent = `${chat.title} (${chat.message_count})`;
    div.onclick = () => loadChat(chat.id);
    chatListEl.appendChild(div);
  }
}

function bubble(message, idx) {
  const node = document.createElement("div");
  node.className = `bubble ${message.role}`;

  const content = document.createElement("div");
  content.textContent = message.content;
  node.appendChild(content);

  if (message.kind === "result" && message.stl_url) {
    node.appendChild(resultCard(message));
  }

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
  status.textContent = "Loading preview...";

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

  if (!message.stl_url) {
    status.textContent = "Preview unavailable.";
    return card;
  }

  initPreview(preview, message.stl_url, {
    onReady: () => {
      status.textContent = "Preview ready.";
      stepBtn.classList.remove("disabled");
      stlBtn.classList.remove("disabled");
    },
    onError: () => {
      status.textContent = "Preview failed, downloads still available.";
      stepBtn.classList.remove("disabled");
      stlBtn.classList.remove("disabled");
    },
  });

  return card;
}

function initPreview(container, stlUrl, hooks) {
  Promise.all([
    import("https://unpkg.com/three@0.160.0/build/three.module.js"),
    import("https://unpkg.com/three@0.160.0/examples/jsm/loaders/STLLoader.js"),
    import("https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js"),
  ])
    .then(([THREE, loaderMod, controlsMod]) => {
      const { STLLoader } = loaderMod;
      const { OrbitControls } = controlsMod;

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      renderer.setSize(container.clientWidth, container.clientHeight);
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xf8fbff);
      const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 2000);
      camera.position.set(40, 40, 40);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;

      const ambient = new THREE.AmbientLight(0xffffff, 0.9);
      scene.add(ambient);
      const directional = new THREE.DirectionalLight(0xffffff, 0.8);
      directional.position.set(60, 80, 20);
      scene.add(directional);

      let mesh = null;
      const loader = new STLLoader();
      loader.load(
        stlUrl,
        (geometry) => {
          geometry.computeVertexNormals();
          geometry.center();
          const material = new THREE.MeshStandardMaterial({ color: 0x9cbce6, metalness: 0.1, roughness: 0.5 });
          mesh = new THREE.Mesh(geometry, material);
          scene.add(mesh);
          hooks.onReady();
        },
        undefined,
        () => hooks.onError()
      );

      const animate = () => {
        if (!container.isConnected) return;
        requestAnimationFrame(animate);
        if (mesh) {
          mesh.rotation.y += 0.0025;
        }
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      const resize = () => {
        if (!container.isConnected) return;
        renderer.setSize(container.clientWidth, container.clientHeight);
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
      };
      window.addEventListener("resize", resize, { once: true });
    })
    .catch(() => {
      // If CDN is blocked/offline, keep chat functional and allow downloads.
      hooks.onError();
    });
}

function renderMessages(chat) {
  messagesEl.innerHTML = "";
  chat.messages.forEach((msg, idx) => {
    messagesEl.appendChild(bubble(msg, idx));
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loadChats() {
  const res = await fetch("/api/chats");
  const chats = await res.json();
  renderChatList(chats);
  if (!currentChatId && chats.length > 0) {
    await loadChat(chats[chats.length - 1].id);
  }
}

async function createChat() {
  const res = await fetch("/api/chats", { method: "POST" });
  const chat = await res.json();
  currentChatId = chat.id;
  await loadChats();
  renderMessages(chat);
}

async function loadChat(chatId) {
  const res = await fetch(`/api/chats/${chatId}`);
  const chat = await res.json();
  currentChatId = chat.id;
  renderMessages(chat);
  renderChatList(await (await fetch("/api/chats")).json());
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentChatId) {
    await createChat();
  }
  const content = inputEl.value.trim();
  if (!content) return;
  inputEl.value = "";
  const res = await fetch(`/api/chats/${currentChatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  const data = await res.json();
  await loadChat(data.chat_id);
});

newChatBtn.addEventListener("click", createChat);
createChat();

