const messagesDiv = document.getElementById('chat-messages');
const input = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const newChatBtn = document.getElementById('new-chat');
const attachFolderBtn = document.getElementById('attach-folder');
const attachBtn = document.getElementById('attach-btn');
const folderInfo = document.getElementById('folder-info');
const chatList = document.getElementById('chat-list');
const languageSelect = document.getElementById('language-select');

let currentFolder = null;
let isThinking = false;
let currentChatId = null;
let currentLanguage = localStorage.getItem('language') || 'en';

languageSelect.value = currentLanguage;
languageSelect.addEventListener('change', () => {
  currentLanguage = languageSelect.value;
  localStorage.setItem('language', currentLanguage);
});

function addMessage(text, sender) {
  const div = document.createElement('div');
  div.className = `message ${sender}`;
  div.innerHTML = text.replace(/\n/g, '<br>');
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
  return div;
}

function typeText(element, text, speed = 12) {
  element.innerHTML = '';
  let i = 0;
  const interval = setInterval(() => {
    if (i < text.length) {
      element.innerHTML += text[i] === '\n' ? '<br>' : text[i];
      i++;
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    } else {
      clearInterval(interval);
    }
  }, speed);
}

async function loadChatList() {
  const res = await fetch('/list_chats');
  const chats = await res.json();
  chatList.innerHTML = '';

  chats.forEach(chat => {
    const div = document.createElement('div');
    div.className = 'chat-item';
    const starIcon = chat.starred ? '★' : '☆';
    
    div.innerHTML = `
      <div class="chat-info">
        <div class="chat-title">${chat.title}</div>
        <div class="chat-date">${new Date(chat.timestamp).toLocaleDateString()}</div>
      </div>
      <div class="chat-actions">
        <span class="star-btn">${starIcon}</span>
        <span class="delete-btn">🗑️</span>
      </div>
    `;

    div.querySelector('.chat-info').onclick = () => loadChat(chat.id);

    div.querySelector('.star-btn').onclick = async (e) => {
      e.stopImmediatePropagation();
      await fetch(`/star_chat/${chat.id}`, { method: 'POST' });
      loadChatList();
    };

    div.querySelector('.delete-btn').onclick = async (e) => {
      e.stopImmediatePropagation();
      if (!confirm(`Delete "${chat.title}"?`)) return;
      await fetch(`/delete_chat/${chat.id}`, { method: 'POST' });
      loadChatList();
      if (currentChatId === chat.id) {
        messagesDiv.innerHTML = '';
        currentChatId = null;
        addMessage("Chat deleted.", 'assistant');
      }
    };

    chatList.appendChild(div);
  });
}

async function loadChat(chatId) {
  const res = await fetch(`/load_chat/${chatId}`);
  const data = await res.json();
  if (data.error) return alert(data.error);
  messagesDiv.innerHTML = '';
  currentChatId = chatId;
  data.messages.forEach(msg => addMessage(msg.content, msg.role));
}

newChatBtn.addEventListener('click', async () => {
  await fetch('/new_chat', { method: 'POST' });
  messagesDiv.innerHTML = '';
  currentChatId = null;
  addMessage("New chat started. How can I help you today?", 'assistant');
  loadChatList();
});

attachFolderBtn.addEventListener('click', () => {
  const inputEl = document.createElement('input');
  inputEl.type = 'file';
  inputEl.webkitdirectory = true;

  inputEl.onchange = async (e) => {
    if (!e.target.files.length) return;

    const firstFile = e.target.files[0];

    let folderName = 'selected folder';
    if (firstFile.webkitRelativePath) {
      folderName = firstFile.webkitRelativePath.split('/')[0];
    }

    let folderPath = firstFile.path 
      ? firstFile.path.replace(firstFile.name, '').slice(0, -1) 
      : null;

    if (!folderPath) {
      folderPath = prompt(
        `Folder selected: "${folderName}"\n\n` +
        `Please paste the FULL path to this folder:\n` +
        `Example: C:\\Users\\MirekPc\\Desktop\\MyProject`
      );
      if (!folderPath) return;
    }

    const res = await fetch('/set_folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: folderPath })
    });

    const data = await res.json();

    if (data.success) {
      currentFolder = folderPath;
      folderInfo.textContent = `📁 ${data.folder}`;
      addMessage(`✅ Folder attached: ${data.folder}`, 'assistant');
    } else {
      addMessage(
        `❌ Failed to attach folder.\n` +
        `Make sure the path is correct and the folder exists.\n` +
        `Error: ${data.error || 'Unknown error'}`,
        'assistant'
      );
    }
  };

  inputEl.click();
});

attachBtn.addEventListener('click', () => attachFolderBtn.click());

sendBtn.addEventListener('click', sendMessage);
input.addEventListener('keypress', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

async function sendMessage() {
  if (isThinking) return;
  const text = input.value.trim();
  if (!text) return;

  addMessage(text, 'user');
  input.value = '';

  isThinking = true;
  let seconds = 0;
  const typingMsg = addMessage(`Thinking... (${seconds}s)`, 'assistant');
  const timer = setInterval(() => { seconds++; typingMsg.innerHTML = `Thinking... (${seconds}s)`; }, 1000);

  let attachedCode = '';
  if (currentFolder) {
    const filename = prompt("Enter filename to read (optional):");
    if (filename) {
      try {
        const res = await fetch('/read_file', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({filepath: currentFolder + '\\' + filename})
        });
        const data = await res.json();
        if (data.content) attachedCode = data.content;
      } catch(e) {}
    }
  }

  const selectedLang = document.getElementById('language-select').value;

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ 
        message: text, 
        attached_code: attachedCode, 
        language: selectedLang 
      })
    });
    const data = await res.json();
    clearInterval(timer);
    typingMsg.remove();

    const aiMsg = addMessage('', 'assistant');
    typeText(aiMsg, data.reply || "Sorry, something went wrong.");
    loadChatList();
  } catch (err) {
    clearInterval(timer);
    typingMsg.remove();
    addMessage("❌ Connection error. Is Ollama running?", 'assistant');
  } finally {
    isThinking = false;
  }
}

async function init() {
  await loadChatList();
  addMessage("Hello! I'm your local FrehAiIgs.<br>Start chatting or select a language from the top right!", 'assistant');
}

init();