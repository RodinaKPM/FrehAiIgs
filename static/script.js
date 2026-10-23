const messagesDiv = document.getElementById('chat-messages');
const input = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const stopBtn = document.getElementById('stop-btn');
const newChatBtn = document.getElementById('new-chat');
const attachBtn = document.getElementById('attach-btn');
const fileInput = document.getElementById('file-input');
const imagePreviews = document.getElementById('image-previews');
const chatList = document.getElementById('chat-list');
const languageSelect = document.getElementById('language-select');
const toastContainer = document.getElementById('toast-container');

const openSettings = document.getElementById('open-settings');

let isThinking = false;
let currentChatId = null;
let pendingImages = [];
let abortController = null;

const translations = {
  en: { newChat: "+ New Chat", recent: "Recent Chats", settings: "⚙️ Settings", badge: "Under Construction", placeholder: "Message FrehAiIgs..." },
  cs: { newChat: "+ Nový chat", recent: "Nedávné chaty", settings: "⚙️ Nastavení", badge: "Ve výstavbě", placeholder: "Napište FrehAiIgs..." },
  sk: { newChat: "+ Nový chat", recent: "Nedávne chaty", settings: "⚙️ Nastavenia", badge: "Vo výstavbe", placeholder: "Napíšte FrehAiIgs..." }
};

function updateUIText(lang) {
  document.getElementById('new-chat').textContent = translations[lang].newChat;
  document.querySelector('.history-title').textContent = translations[lang].recent;
  
  const settingsText = document.getElementById('settings-text');
  if (settingsText) settingsText.textContent = translations[lang].settings;
  
  const badgeText = document.getElementById('construction-badge');
  if (badgeText) badgeText.textContent = translations[lang].badge;

  document.getElementById('user-input').placeholder = translations[lang].placeholder;
}

let currentLanguage = localStorage.getItem('language') || 'en';
languageSelect.value = currentLanguage;
updateUIText(currentLanguage);

languageSelect.addEventListener('change', () => {
  currentLanguage = languageSelect.value;
  localStorage.setItem('language', currentLanguage);
  updateUIText(currentLanguage);
});

// Stacking Toast Notifications
function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  toastContainer.appendChild(toast);
  
  setTimeout(() => toast.classList.add('show'), 10);
  
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// SETTINGS UNDER CONSTRUCTION
if (openSettings) {
  openSettings.onclick = () => {
    showToast("⚙️ Settings are currently under construction!");
  };
}

marked.setOptions({ breaks: true, gfm: true });
const renderer = new marked.Renderer();
renderer.code = (code, lang) => {
  let highlighted = code;
  try {
    highlighted = lang && hljs.getLanguage(lang) ? hljs.highlight(code, { language: lang }).value : hljs.highlightAuto(code).value;
  } catch (_) {}
  return `<pre><code class="language-${lang}">${highlighted}</code></pre>`;
};

const CREATE_RE = /```create:([^\n`]+)\n([\s\S]*?)```/g;

function renderMarkdown(text) {
  const cards = [];
  const replaced = text.replace(CREATE_RE, (_, path, content) => {
    const i = cards.length;
    cards.push({ path });
    return `\n\n__FILECARD_${i}__\n\n`;
  });

  let html = marked.parse(replaced, { renderer });
  html = DOMPurify.sanitize(html);

  cards.forEach((c, i) => {
    const cardHtml = `<div class="file-card"><span>📄</span><span>${c.path}</span><a class="file-download" href="/download/${encodeURIComponent(c.path)}" download>Download</a></div>`;
    html = html.replace(new RegExp(`<p>\\s*__FILECARD_${i}__\\s*</p>`, 'g'), cardHtml).replace(new RegExp(`__FILECARD_${i}__`, 'g'), cardHtml);
  });
  return html;
}

function enhanceCodeBlocks(container) {
  container.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.copy-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = 'Copy';
    btn.onclick = () => {
      navigator.clipboard.writeText(pre.querySelector('code').textContent);
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = 'Copy', 1500);
    };
    pre.appendChild(btn);
  });
}

function addMessage(text, sender) {
  const div = document.createElement('div');
  div.className = `message ${sender}`;
  if (sender === 'user') div.textContent = text;
  else { div.innerHTML = renderMarkdown(text); enhanceCodeBlocks(div); }
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
  return div;
}

// Close dropdowns when clicking anywhere else
document.addEventListener('click', (e) => {
  if (!e.target.closest('.chat-menu-btn') && !e.target.closest('.dropdown-menu')) {
    document.querySelectorAll('.dropdown-menu').forEach(m => m.classList.remove('active'));
  }
});

async function loadChatList() {
  const res = await fetch('/list_chats');
  const chats = await res.json();
  chatList.innerHTML = '';
  
  chats.forEach(chat => {
    const div = document.createElement('div');
    div.className = 'chat-item';
    
    const pinIndicator = chat.pinned ? '<span class="pin-icon">📌</span>' : '';
    
    div.innerHTML = `
      <div class="chat-title">${pinIndicator}<span style="overflow:hidden; text-overflow:ellipsis;">${chat.title}</span></div>
      <div class="chat-actions">
        <div class="chat-menu-btn">⋮</div>
      </div>
      <div class="dropdown-menu">
        <div class="dropdown-item pin-btn">📌 ${chat.pinned ? 'Unpin' : 'Pin'}</div>
        <div class="dropdown-item rename-btn">✏️ Rename</div>
        <div class="dropdown-item export-btn">📥 Export</div>
        <div class="dropdown-item delete-btn">🗑️ Delete</div>
      </div>
    `;

    div.querySelector('.chat-title').onclick = () => {
      loadChat(chat.id);
    };

    const menuBtn = div.querySelector('.chat-menu-btn');
    const dropdown = div.querySelector('.dropdown-menu');
    menuBtn.onclick = (e) => {
      e.stopPropagation();
      document.querySelectorAll('.dropdown-menu').forEach(m => {
        if (m !== dropdown) m.classList.remove('active');
      });
      dropdown.classList.toggle('active');
    };

    div.querySelector('.pin-btn').onclick = async (e) => {
      e.stopPropagation();
      await fetch(`/toggle_pin_chat/${chat.id}`, { method: 'POST' });
      dropdown.classList.remove('active');
      loadChatList();
    };

    div.querySelector('.rename-btn').onclick = async (e) => {
      e.stopPropagation();
      dropdown.classList.remove('active');
      const newTitle = prompt("Rename chat:", chat.title);
      if (newTitle && newTitle.trim() !== "") {
        await fetch(`/rename_chat/${chat.id}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ title: newTitle.trim() })
        });
        loadChatList();
      }
    };

    // Individual Export from 3-Dots Menu
    div.querySelector('.export-btn').onclick = async (e) => {
      e.stopPropagation();
      dropdown.classList.remove('active');
      try {
        const res = await fetch(`/load_chat/${chat.id}`);
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat_${chat.id}.json`;
        a.click();
        URL.revokeObjectURL(url);
        showToast("✅ Chat exported!");
      } catch (err) {
        showToast("❌ Failed to export chat.");
      }
    };

    div.querySelector('.delete-btn').onclick = async (e) => {
      e.stopPropagation();
      dropdown.classList.remove('active');
      if (confirm(`Delete "${chat.title}"?`)) {
        await fetch(`/delete_chat/${chat.id}`, { method: 'POST' });
        if (currentChatId === chat.id) { 
            messagesDiv.innerHTML = ''; 
            currentChatId = null; 
            addMessage("Hello! I'm your local FrehAiIgs.", 'assistant');
        }
        loadChatList();
      }
    };

    chatList.appendChild(div);
  });
}

async function loadChat(id) {
  const res = await fetch(`/load_chat/${id}`);
  const d = await res.json();
  if (d.error) return;
  messagesDiv.innerHTML = '';
  currentChatId = id;
  d.messages.forEach(m => {
    if (m.role === 'user') addMessage(typeof m.content === 'string' ? m.content : (m.content.find(p => p.type === 'text')?.text || ''), 'user');
    else if (m.role === 'assistant') addMessage(m.content, 'assistant');
  });
}

newChatBtn.onclick = async () => {
  await fetch('/new_chat', { method: 'POST' });
  messagesDiv.innerHTML = '';
  currentChatId = null;
  pendingImages = [];
  updateImagePreviews();
  addMessage("Hello! I'm your local FrehAiIgs.<br>I am smart enough to search the web if you ask me to.", 'assistant');
  loadChatList();
};

attachBtn.onclick = () => fileInput.click();
fileInput.onchange = async e => {
  for (const f of e.target.files) {
    if (!f.type.startsWith('image/')) continue;
    pendingImages.push(await new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); }));
  }
  updateImagePreviews();
  fileInput.value = '';
};

function updateImagePreviews() {
  imagePreviews.innerHTML = '';
  pendingImages.forEach((src, i) => {
    const w = document.createElement('div');
    w.className = 'preview-thumb';
    w.innerHTML = `<img src="${src}"><button>×</button>`;
    w.querySelector('button').onclick = () => { pendingImages.splice(i, 1); updateImagePreviews(); };
    imagePreviews.appendChild(w);
  });
}

sendBtn.onclick = sendMessage;
input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } };

async function sendMessage() {
  if (isThinking) return;
  const text = input.value.trim();
  if (!text && pendingImages.length === 0) return;

  const images = [...pendingImages];
  addMessage(text || '[image]', 'user');
  input.value = ''; pendingImages = []; updateImagePreviews();

  isThinking = true;
  sendBtn.style.display = 'none';
  stopBtn.style.display = 'flex';
  abortController = new AbortController();

  const aiDiv = document.createElement('div');
  aiDiv.className = 'message assistant';
  aiDiv.innerHTML = '<span style="color:var(--dim);font-style:italic;">Thinking...</span>';
  messagesDiv.appendChild(aiDiv);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;

  let full = '';
  let first = true;

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: abortController.signal,
      body: JSON.stringify({ message: text, images }),
    });

    if (!res.ok) throw new Error("Server error");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const d = JSON.parse(line.slice(6));
        
        if (d.status) {
            aiDiv.innerHTML = `<span style="color:var(--dim);font-style:italic;">🌐 ${d.status}</span>`;
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        if (d.delta) {
          if (first) { aiDiv.innerHTML = ''; first = false; }
          full += d.delta;
          aiDiv.innerHTML = renderMarkdown(full);
          enhanceCodeBlocks(aiDiv);
          messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
        if (d.error) {
          aiDiv.innerHTML = `<span style="color:#ef4444">Error: ${d.error}</span>`;
        }
        if (d.done) {
          loadChatList();
        }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') {
        aiDiv.innerHTML = full ? renderMarkdown(full) + '<br><span style="color:var(--dim)">[Stopped]</span>' : '[Stopped]';
    } else {
        aiDiv.innerHTML = `<span style="color:#ef4444">Connection error: ${err.message}</span>`;
    }
  } finally {
    isThinking = false;
    sendBtn.style.display = 'flex';
    stopBtn.style.display = 'none';
    if (first && !full && aiDiv.innerHTML.includes('Thinking')) {
        aiDiv.innerHTML = '❌ No response received.';
    }
  }
}

stopBtn.onclick = () => { if (abortController) abortController.abort(); };

async function init() {
  await loadChatList();
  if (messagesDiv.innerHTML === '') {
    addMessage("Hello! I'm your local FrehAiIgs.<br>I am smart enough to search the web if you ask me to.", 'assistant');
  }
}

init();