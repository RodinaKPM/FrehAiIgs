import subprocess, sys, os, json, time, re, requests, logging
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file

def check_dependencies():
    packages = ["flask", "requests", "huggingface_hub", "ddgs", "beautifulsoup4"]
    for pkg in packages:
        import_name = pkg.replace("-", "_")
        try:
            __import__(import_name)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

check_dependencies()

from ddgs import DDGS
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent

try:
    CHATS_DIR = BASE_DIR / "chats"
    WORKSPACE_DIR = BASE_DIR / "workspace"
    MODELS_DIR = BASE_DIR / "models"
    LLAMA_DIR = BASE_DIR / "llama"
    
    CHATS_DIR.mkdir(exist_ok=True)
    WORKSPACE_DIR.mkdir(exist_ok=True)
    MODELS_DIR.mkdir(exist_ok=True)
    LLAMA_DIR.mkdir(exist_ok=True)
except PermissionError:
    print("ERROR: Windows denied permission to create folders.")
    input("Press Enter to exit...")
    sys.exit(1)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

LLAMA_PORT = 8080
LLAMA_BASE = f"http://127.0.0.1:{LLAMA_PORT}"
MODEL_FILE = MODELS_DIR / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
MMPROJ_FILE = MODELS_DIR / "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf"

CURRENT_CHAT_ID = None
CONVERSATION_HISTORY = []

def download_models_if_needed():
    if MODEL_FILE.exists() and MMPROJ_FILE.exists():
        return

    from huggingface_hub import hf_hub_download
    repo = "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"
    files = [
        "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf"
    ]
    
    for fn in files:
        if not (MODELS_DIR / fn).exists():
            hf_hub_download(repo_id=repo, filename=fn, local_dir=str(MODELS_DIR))

def is_running():
    try:
        requests.get(f"{LLAMA_BASE}/health", timeout=2)
        return True
    except Exception:
        return False

def start_server():
    if is_running():
        return
    
    binary = str(LLAMA_DIR / "llama-server.exe")
    if not os.path.exists(binary):
        print("FATAL: Could not find llama-server.exe in the 'llama' folder.")
        input("Press Enter to exit...")
        sys.exit(1)

    threads = max(1, os.cpu_count() - 1)
    cmd = [
        binary, "-m", str(MODEL_FILE), "--mmproj", str(MMPROJ_FILE),
        "-c", "4096", "--port", str(LLAMA_PORT), "--host", "127.0.0.1",
        "-t", str(threads)
    ]
    
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)

    for i in range(30):
        if is_running():
            return
        time.sleep(1)
        
    print("Server did not start in 30s.")
    input("Press Enter to exit...")
    sys.exit(1)

def chat_path(cid): return CHATS_DIR / f"{cid}.json"

def save_current_chat():
    if not CONVERSATION_HISTORY or not CURRENT_CHAT_ID:
        return
    first_user = next((m for m in CONVERSATION_HISTORY if m["role"] == "user"), None)
    title = "New Chat"
    if first_user:
        c = first_user["content"]
        title = c if isinstance(c, str) else next((p["text"] for p in c if p.get("type") == "text"), "Image chat")

    existing_pinned = False
    existing_title = title[:60]
    path = chat_path(CURRENT_CHAT_ID)
    if path.exists():
        try:
            old_data = json.loads(path.read_text(encoding="utf-8"))
            existing_pinned = old_data.get("pinned", False)
            if old_data.get("title") and old_data.get("title") != "New Chat":
                existing_title = old_data["title"]
        except Exception:
            pass

    data = {
        "id": CURRENT_CHAT_ID,
        "title": existing_title,
        "timestamp": datetime.now().isoformat(),
        "pinned": existing_pinned,
        "messages": CONVERSATION_HISTORY,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

CREATE_RE = re.compile(r"```create:([^\n`]+)\n([\s\S]*?)```")

def extract_and_write_files(text):
    created = []
    for m in CREATE_RE.finditer(text):
        rel = m.group(1).strip().replace("\\", "/").lstrip("/")
        if ".." in rel.split("/") or not rel: continue
        target = (WORKSPACE_DIR / rel).resolve()
        if not str(target).startswith(str(WORKSPACE_DIR.resolve())): continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(m.group(2), encoding="utf-8")
        created.append(rel)
    return created

def system_prompt():
    base = "You are FrehAiIgs, a powerful local AI assistant.\n\n"
    base += "1. **File creation.** To create a file, output it in this exact format:\n"
    base += "```create:relative/path/to/file.ext\n<full file content>\n```\n"
    base += "2. **Image analysis.** Analyze attached images.\n"
    base += "3. **Correction:** If the user corrects you, APOLOGIZE and accept their correction immediately. Do not argue.\n"
    base += "4. **Web Search:** If web search results are provided, use them to answer the question. If the search results are empty or unhelpful, use your own internal knowledge to answer normally. Do NOT say 'I could not find the answer' unless you genuinely have no idea.\n"
    base += "5. ALWAYS reply in the exact language the user is speaking. Be concise."
    return base

@app.route("/")
def home(): return render_template("index.html")

@app.route("/list_chats")
def list_chats():
    out = []
    for f in CHATS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "id": f.stem, 
                "title": d.get("title", "Untitled"), 
                "timestamp": d.get("timestamp", ""),
                "pinned": d.get("pinned", False)
            })
        except Exception: continue
    
    out.sort(key=lambda x: (x["pinned"], x["timestamp"]), reverse=True)
    return jsonify(out)

@app.route("/load_chat/<chat_id>")
def load_chat(chat_id):
    global CURRENT_CHAT_ID, CONVERSATION_HISTORY
    p = chat_path(chat_id)
    if not p.exists(): return jsonify({"error": "Not found"}), 404
    d = json.loads(p.read_text(encoding="utf-8"))
    CURRENT_CHAT_ID = chat_id
    CONVERSATION_HISTORY = d.get("messages", [])
    return jsonify(d)

@app.route("/new_chat", methods=["POST"])
def new_chat():
    global CURRENT_CHAT_ID, CONVERSATION_HISTORY
    save_current_chat()
    CONVERSATION_HISTORY = []
    CURRENT_CHAT_ID = str(int(time.time() * 1000))
    return jsonify({"id": CURRENT_CHAT_ID})

@app.route("/delete_chat/<chat_id>", methods=["POST"])
def delete_chat(chat_id):
    global CURRENT_CHAT_ID, CONVERSATION_HISTORY
    p = chat_path(chat_id)
    if p.exists(): p.unlink()
    
    if CURRENT_CHAT_ID == chat_id:
        CURRENT_CHAT_ID = None
        CONVERSATION_HISTORY = []
        
    return jsonify({"success": True})

@app.route("/rename_chat/<chat_id>", methods=["POST"])
def rename_chat(chat_id):
    data = request.json or {}
    new_title = data.get("title", "").strip()
    p = chat_path(chat_id)
    if p.exists() and new_title:
        d = json.loads(p.read_text(encoding="utf-8"))
        d["title"] = new_title
        p.write_text(json.dumps(d, indent=2), encoding="utf-8")
        return jsonify({"success": True})
    return jsonify({"error": "Failed"}), 400

@app.route("/toggle_pin_chat/<chat_id>", methods=["POST"])
def toggle_pin_chat(chat_id):
    p = chat_path(chat_id)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        d["pinned"] = not d.get("pinned", False)
        p.write_text(json.dumps(d, indent=2), encoding="utf-8")
        return jsonify({"success": True, "pinned": d["pinned"]})
    return jsonify({"error": "Failed"}), 404

@app.route("/chat", methods=["POST"])
def chat():
    global CURRENT_CHAT_ID
    data = request.json or {}
    text = (data.get("message") or "").strip()
    images = data.get("images") or []
    temp = 0.7

    if not CURRENT_CHAT_ID: CURRENT_CHAT_ID = str(int(time.time() * 1000))

    if images:
        content = [{"type": "text", "text": text or "Describe this image."}]
        for img in images: content.append({"type": "image_url", "image_url": {"url": img}})
    else:
        content = text

    CONVERSATION_HISTORY.append({"role": "user", "content": content})

    def generate():
        full = ""
        try:
            needs_search = False
            search_query = text
            lower_text = text.lower()

            if "github.com/" in lower_text:
                needs_search = True
                url_match = re.search(r'https?://github\.com/[^\s]+', text)
                if url_match:
                    url = url_match.group(0)
                    parts = url.strip("/").split("/")
                    if len(parts) >= 5:
                        owner, repo = parts[3], parts[4]
                        yield f"data: {json.dumps({'status': f'Checking GitHub API for {owner}/{repo}...'})}\n\n"
                        try:
                            api_res = requests.get(f"https://api.github.com/repos/{owner}/{repo}", timeout=10)
                            if api_res.status_code == 200:
                                repo_data = api_res.json()
                                search_query = f"The creator/owner of this GitHub repository is {repo_data.get('owner', {}).get('login')}."
                            else:
                                search_query = "GitHub API returned 404 Not Found."
                        except Exception:
                            pass

            if not needs_search:
                if lower_text.startswith("/web "):
                    needs_search = True
                    search_query = text[5:].strip()
                elif any(phrase in lower_text for phrase in ["search for", "look up", "news about", "latest news", "current weather", "google "]):
                    needs_search = True
                elif len(text.split()) < 8 and any(lower_text.startswith(q) for q in ["who", "what", "where", "when"]) and "how" not in lower_text:
                    needs_search = True

            messages_to_send = [{"role": "system", "content": system_prompt()}] + CONVERSATION_HISTORY[-12:-1]

            if needs_search and not images:
                if not search_query.startswith("The creator"):
                    yield f"data: {json.dumps({'status': f'Searching web for: {search_query}...'})}\n\n"
                
                try:
                    context = ""
                    if search_query.startswith("http"):
                        res = requests.get(search_query, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                        soup = BeautifulSoup(res.text, 'html.parser')
                        for script in soup(["script", "style"]):
                            script.decompose()
                        context = soup.get_text(separator=' ', strip=True)[:6000]
                        web_info = f"CONTENT FROM {search_query}:\n{context}\n\n"
                    elif search_query.startswith("The creator"):
                        web_info = search_query
                    else:
                        results = list(DDGS().text(search_query, max_results=3))
                        if results:
                            web_info = "LIVE WEB SEARCH RESULTS:\n\n"
                            for res in results:
                                web_info += f"Title: {res.get('title')}\nURL: {res.get('href')}\nSnippet: {res.get('body')}\n\n"
                        else:
                            web_info = "NO RESULTS FOUND."

                    modified_text = (
                        f"Web Search Results:\n{web_info}\n\n"
                        f"User Question: {text}\n\n"
                        f"Use the search results above to answer. If the results are irrelevant, use your own knowledge to answer."
                    )
                    messages_to_send.append({"role": "user", "content": modified_text})
                except Exception as e:
                    print(f"Search error: {e}")
                    messages_to_send.append({"role": "user", "content": content})
            else:
                messages_to_send.append({"role": "user", "content": content})

            payload = {
                "messages": messages_to_send,
                "stream": True,
                "max_tokens": 4096,
                "temperature": float(temp),
            }

            with requests.post(f"{LLAMA_BASE}/v1/chat/completions", json=payload, stream=True, timeout=600) as r:
                r.raise_for_status()
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw: continue
                    line = raw[6:] if raw.startswith("data: ") else raw
                    if line.strip() == "[DONE]": break
                    try: chunk = json.loads(line)
                    except json.JSONDecodeError: continue
                    choices = chunk.get("choices") or []
                    if not choices: continue
                    delta = choices[0].get("delta", {}).get("content", "")
                    if delta:
                        full += delta
                        yield f"data: {json.dumps({'delta': delta})}\n\n"
                        
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        CONVERSATION_HISTORY.append({"role": "assistant", "content": full})
        created = extract_and_write_files(full)
        save_current_chat()
        yield f"data: {json.dumps({'done': True, 'created': created})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/download/<path:filename>")
def download(filename):
    safe = (WORKSPACE_DIR / filename).resolve()
    if not str(safe).startswith(str(WORKSPACE_DIR.resolve())) or not safe.exists():
        return "Not found", 404
    return send_file(safe, as_attachment=True)

if __name__ == "__main__":
    download_models_if_needed()
    start_server()
    print("--- Ready: http://localhost:5000 ---")
    app.run(debug=False, port=5000, threaded=True)