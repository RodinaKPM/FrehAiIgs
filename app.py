# app.py
import subprocess, sys, os, json, time, re, requests
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file

app = Flask(__name__)

CHATS_DIR = Path("chats")
WORKSPACE_DIR = Path("workspace")
MODELS_DIR = Path("models")
LLAMA_DIR = Path("llama")
CHATS_DIR.mkdir(exist_ok=True)
WORKSPACE_DIR.mkdir(exist_ok=True)

LLAMA_PORT = 8080
LLAMA_BASE = f"http://127.0.0.1:{LLAMA_PORT}"
MODEL_FILE = MODELS_DIR / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
MMPROJ_FILE = MODELS_DIR / "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf"

CURRENT_CHAT_ID = None
CONVERSATION_HISTORY = []

# ---------- server management ----------

def find_llama_server():
    for p in [LLAMA_DIR / "llama-server.exe", LLAMA_DIR / "llama-server"]:
        if p.exists():
            return str(p)
    return None

def is_running():
    try:
        requests.get(f"{LLAMA_BASE}/health", timeout=2)
        return True
    except Exception:
        return False

def start_server():
    if is_running():
        print("✅ llama-server already running")
        return
    binary = find_llama_server()
    if not binary or not MODEL_FILE.exists():
        print("❌ llama-server or model missing. Run: python setup.py")
        sys.exit(1)

    print("🚀 Starting llama-server (this takes ~15s the first time)...")
    cmd = [
        binary, "-m", str(MODEL_FILE), "--mmproj", str(MMPROJ_FILE),
        "-c", "8192", "--port", str(LLAMA_PORT), "--host", "127.0.0.1",
        "-ngl", "999",  # offload all to GPU if available, ignored on CPU
    ]
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    subprocess.Popen(cmd, creationflags=flags)

    for _ in range(60):
        if is_running():
            print("✅ llama-server ready")
            return
        time.sleep(1)
    print("⚠️  llama-server did not become healthy in 60s")

# ---------- chat persistence ----------

def chat_path(cid): return CHATS_DIR / f"{cid}.json"

def save_current_chat():
    if not CONVERSATION_HISTORY or not CURRENT_CHAT_ID:
        return
    first_user = next((m for m in CONVERSATION_HISTORY if m["role"] == "user"), None)
    title = "New Chat"
    if first_user:
        c = first_user["content"]
        if isinstance(c, str):
            title = c
        else:
            title = next((p["text"] for p in c if p.get("type") == "text"), "Image chat")

    starred = False
    if chat_path(CURRENT_CHAT_ID).exists():
        try:
            starred = json.loads(chat_path(CURRENT_CHAT_ID).read_text()).get("starred", False)
        except Exception:
            pass

    data = {
        "id": CURRENT_CHAT_ID,
        "title": title[:60],
        "timestamp": datetime.now().isoformat(),
        "starred": starred,
        "messages": CONVERSATION_HISTORY,
    }
    chat_path(CURRENT_CHAT_ID).write_text(json.dumps(data, indent=2), encoding="utf-8")

# ---------- file creation ----------

CREATE_RE = re.compile(r"```create:([^\n`]+)\n([\s\S]*?)```")

def extract_and_write_files(text):
    created = []
    for m in CREATE_RE.finditer(text):
        rel = m.group(1).strip().replace("\\", "/").lstrip("/")
        if ".." in rel.split("/") or not rel:
            continue
        target = (WORKSPACE_DIR / rel).resolve()
        if not str(target).startswith(str(WORKSPACE_DIR.resolve())):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(m.group(2), encoding="utf-8")
        created.append(rel)
    return created

# ---------- system prompt ----------
def system_prompt(lang):
    base = "You are FrehAiIgs, a powerful local AI assistant. You help with coding, analysis, writing, and general tasks.\n\n"
    base += "You have two special abilities:\n\n"
    base += "1. **File creation.** To create a file, output it in this exact format (no other text inside the fence):\n\n"
    base += "```create:relative/path/to/file.ext\n<full file content>\n```\n\n"
    base += "Files are saved into the user's workspace folder and become downloadable from the chat. You can create any text file (.py, .js, .html, .css, .md, .json, etc.). Always give the file a sensible name.\n\n"
    base += "2. **Image analysis.** Users may attach images. Analyze them carefully.\n\n"
    base += "Formatting rules:\n"
    base += "- Use Markdown for all replies.\n"
    base += "- Wrap code in fenced code blocks with a language tag.\n"
    base += "- Be concise and direct. No filler like 'Certainly!' or 'Sure thing!'.\n"
    base += "- Use short paragraphs and bullet points."

    extra = {
        "cs": "\n\nOdpovídej v češtině.",
        "sk": "\n\nOdpovedaj v slovenčine.",
        "en": "\n\nRespond in English."
    }
    return base + extra.get(lang, extra["en"])