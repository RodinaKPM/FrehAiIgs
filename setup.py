# setup.py
import os, sys, zipfile, platform, subprocess
from pathlib import Path
import requests

BASE = Path(__file__).parent
LLAMA_DIR = BASE / "llama"
MODELS_DIR = BASE / "models"
LLAMA_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

REPO = "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"
FILES = ["Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf", "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf"]

def download_llama_server():
    print("Fetching latest llama.cpp release...")
    r = requests.get("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest", timeout=30)
    r.raise_for_status()
    assets = r.json()["assets"]

    system = platform.system().lower()
    if system == "windows":
        patterns = ["bin-win-cpu-x64.zip", "bin-win-avx2-x64.zip"]
    elif system == "linux":
        patterns = ["bin-ubuntu-x64.zip", "bin-linux-x64.zip"]
    elif system == "darwin":
        patterns = ["bin-macos-arm64.zip"]
    else:
        sys.exit(f"Unsupported OS: {system}")

    asset = next((a for p in patterns for a in assets if p in a["name"]), None)
    if not asset:
        sys.exit("Could not find suitable llama.cpp release asset. Download manually from https://github.com/ggml-org/llama.cpp/releases")

    print(f"Downloading {asset['name']}...")
    zpath = LLAMA_DIR / "llama.zip"
    with requests.get(asset["browser_download_url"], stream=True) as r:
        r.raise_for_status()
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

    with zipfile.ZipFile(zpath) as z:
        z.extractall(LLAMA_DIR)
    zpath.unlink()

    # The zip sometimes nests binaries one level deep - flatten if needed
    for f in LLAMA_DIR.rglob("llama-server*"):
        if f.parent != LLAMA_DIR and f.is_file():
            f.rename(LLAMA_DIR / f.name)
    print("✅ llama-server installed in ./llama/")

def download_model():
    from huggingface_hub import hf_hub_download
    for fn in FILES:
        dest = MODELS_DIR / fn
        if dest.exists():
            print(f"✅ Already have {fn}")
            continue
        print(f"Downloading {fn} (~1.5GB)...")
        hf_hub_download(repo_id=REPO, filename=fn, local_dir=str(MODELS_DIR))
    print("✅ Model ready")

if __name__ == "__main__":
    try:
        import requests, huggingface_hub  # noqa
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "huggingface_hub"])

    has_bin = any(LLAMA_DIR.glob("llama-server*"))
    if not has_bin:
        download_llama_server()
    else:
        print("✅ llama-server already present")

    download_model()
    print("\n🎉 Setup complete. Run: python app.py")