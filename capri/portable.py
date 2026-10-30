"""The portable dev build: what it can download, where things go, and finding them again.

Folder layout next to Capri.exe:
    models\\llm\\      brains (.gguf). Drop your own GGUF in here and it shows up in her Brain menu.
    models\\whisper\\  ears (whisper.cpp ggml-*.bin)
    engines\\llama\\   llama.cpp's llama-server (runs any GGUF, new architectures included)
    engines\\whisper\\ whisper.cpp's whisper-server (on the CPU, so the GPU stays free for her brain)
                    (Linux: from the package manager instead, `sudo pacman -S whisper-cpp`)
    data\\            her settings and memory (starts empty)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT

MODELS = ROOT / "models"
LLM_DIR = MODELS / "llm"
WHISPER_DIR = MODELS / "whisper"
ENGINES = ROOT / "engines"

LLAMA_TAG = "b11932"  # pinned so every dev runs the same engine
_LLAMA = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/"
_WHISPER = "https://github.com/ggml-org/whisper.cpp/releases/download/b5454/"
_HF = "https://huggingface.co/"
LINUX = sys.platform.startswith("linux")


@dataclass
class Item:
    key: str
    label: str
    note: str
    files: list[tuple[str, str, int]]  # (url, path under ROOT, bytes)
    unzip: bool = False
    system: str = ""  # Linux: a program the package manager installs (nothing to download)

    @property
    def size(self) -> int:
        return sum(f[2] for f in self.files)

    def installed(self) -> bool:
        if self.system:
            return shutil.which(self.system) is not None
        if self.key == "kokoro":  # unpacked by hand counts too
            return (MODELS / "voice" / "capri-voice-1" / "voices.bin").exists()
        if self.key == "genie":  # downloaded by setup or by hand, same files
            return all((ROOT / p).exists() for _, p, _ in self.files)
        if self.unzip:
            return (ROOT / self.files[0][1]).parent.joinpath(".done-" + self.key).exists()
        return all((ROOT / p).exists() and (ROOT / p).stat().st_size == n for _, p, n in self.files)


BRAINS = [
    Item("nemotron", "Nemotron Heretic E4B  (recommended)",
         "the best one: smart, real answers, and it can see your screen (eyes included) (~6 GB VRAM)",
         [(_HF + "Ghasty3/CapriAI2/resolve/main/nemotron-3.5-bolt-e4b-heretic/Nemotron-3.5-Bolt-E4B-Heretic.Q4_K_M.gguf",
           "models/llm/Nemotron-Heretic/Nemotron-3.5-Bolt-E4B-Heretic.Q4_K_M.gguf", 5335293696),
          (_HF + "Ghasty3/CapriAI2/resolve/main/nemotron-3.5-bolt-e4b-heretic/Nemotron-3.5-Bolt-E4B-Heretic.BF16-mmproj.gguf",
           "models/llm/Nemotron-Heretic/Nemotron-3.5-Bolt-E4B-Heretic.BF16-mmproj.gguf", 991552032)]),
    Item("nemo", "Mistral-Nemo 12B", "the smartest one; best for talking one-on-one (needs ~8 GB VRAM)",
         [(_HF + "bartowski/Mistral-Nemo-Instruct-2407-GGUF/resolve/main/Mistral-Nemo-Instruct-2407-IQ4_XS.gguf",
           "models/llm/Mistral-Nemo-Instruct-2407-IQ4_XS.gguf", 6742713472)]),
    Item("conv7b", "Conversational 7B", "fast and chatty, but gets facts wrong sometimes (~5 GB VRAM)",
         [(_HF + "xiaoheiqaq/conversational-7b-v0.4-Q4_K_M-GGUF/resolve/main/conversational-7b-v0.4-q4_k_m.gguf",
           "models/llm/conversational-7b-v0.4-q4_k_m.gguf", 4372815648)]),
    Item("capriai2", "CapriAI2 (Qwen3.5 4B)", "trained to be Capri; small and new (~4 GB VRAM)",
         [(_HF + "Ghasty3/CapriAI2/resolve/main/qwen3.5-4b/Qwen3.5-4B.Q6_K.gguf",
           "models/llm/CapriAI2-Qwen3.5-4B.Q6_K.gguf",
           3563028064)]),
]
EARS = [
    Item("tiny", "Tiny", "fastest, makes the most mistakes",
         [(_HF + "ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin", "models/whisper/ggml-tiny.en.bin", 77704715)]),
    Item("base", "Base", "fast, decent",
         [(_HF + "ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin", "models/whisper/ggml-base.en.bin", 147964211)]),
    Item("small", "Small", "the sweet spot (what Capri uses)",
         [(_HF + "ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin", "models/whisper/ggml-small.en.bin", 487614201)]),
    Item("medium", "Medium", "most accurate, slower on the CPU",
         [(_HF + "ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin", "models/whisper/ggml-medium.en.bin",
           1533774781)]),
]
ENGINE_GPU = [
    Item("vulkan", "Vulkan", "any GPU (NVIDIA, AMD, Intel); small download",
         [(_LLAMA + f"llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip", "engines/llama/llama-vulkan.zip", 37180481)], True),
    Item("cuda", "CUDA", "NVIDIA only; a bit faster, big download",
         [(_LLAMA + f"llama-{LLAMA_TAG}-bin-win-cuda-12.4-x64.zip", "engines/llama/llama-cuda.zip", 279443090),
          (_LLAMA + "cudart-llama-bin-win-cuda-12.4-x64.zip", "engines/llama/cudart.zip", 391443627)], True),
]
ENGINE_EARS = Item("whisper", "whisper.cpp", "her ears, on the CPU",
                   [(_WHISPER + "whisper-blas-bin-x64.zip", "engines/whisper/whisper.zip", 21715607)], True)
# her voice: her cloned voice model ships with her (models/voice/capri-clone); Genie, which runs it on the CPU, needs
# these files (English reading, voice features), pinned to one revision of High-Logic/Genie (MIT)
_GENIE = "https://huggingface.co/High-Logic/Genie/resolve/52b17272e0b7032415e85ad37b551db2386b1810/"
_GENIE_FILES = [
    ("GenieData/G2P/EnglishG2P/checkpoint20.npz", 3342298),
    ("GenieData/G2P/EnglishG2P/cmudict-fast.rep", 3613898),
    ("GenieData/G2P/EnglishG2P/cmudict.rep", 3731285),
    ("GenieData/G2P/EnglishG2P/engdict-hot.rep", 75),
    ("GenieData/G2P/EnglishG2P/engdict_cache.pickle", 5965909),
    ("GenieData/G2P/EnglishG2P/namedict_cache.pickle", 760663),
    ("GenieData/G2P/EnglishG2P/taggers/averaged_perceptron_tagger_eng/averaged_perceptron_tagger_eng.classes.json", 285),
    ("GenieData/G2P/EnglishG2P/taggers/averaged_perceptron_tagger_eng/averaged_perceptron_tagger_eng.tagdict.json", 25788),
    ("GenieData/G2P/EnglishG2P/taggers/averaged_perceptron_tagger_eng/averaged_perceptron_tagger_eng.weights.json", 5677744),
    ("GenieData/G2P/EnglishG2P/wordsegment/bigrams.txt", 5566017),
    ("GenieData/G2P/EnglishG2P/wordsegment/unigrams.txt", 4952042),
    ("GenieData/G2P/EnglishG2P/wordsegment/words.txt", 1763461),
    ("GenieData/chinese-hubert-base/chinese-hubert-base.onnx", 237741),
    ("GenieData/chinese-hubert-base/chinese-hubert-base_weights_fp16.bin", 188741632),
    ("GenieData/speaker_encoder.onnx", 184812166),
]
VOICE = Item("genie", "Her voice", "she talks out loud in her own voice, offline, on the CPU",
             [(_GENIE + rel, "models/voice/" + rel, size) for rel, size in _GENIE_FILES])
# the older free voice (Lachy's Kokoro pack): used when her clone can't run
KOKORO = Item("kokoro", "Her voice", "she talks out loud in her own voice (Lachy's Kokoro pack), offline, on the CPU",
             [("https://github.com/lachydotmcg/capri-desktop/releases/download/voice-pack-1/capri-voice-1.zip",
               "models/voice/capri-voice-1.zip", 316041808)], True)
if LINUX:  # llama.cpp's Ubuntu builds run on Arch too; whisper.cpp ships no Linux build, Arch packages it
    ENGINE_GPU = [
        Item("vulkan", "Vulkan", "any GPU (NVIDIA, AMD, Intel); small download",
             [(_LLAMA + f"llama-{LLAMA_TAG}-bin-ubuntu-vulkan-x64.tar.gz", "engines/llama/llama-vulkan.tar.gz",
               35281110)], True),
        Item("cuda", "CUDA", "NVIDIA only; a bit faster, big download",
             [(_LLAMA + f"llama-{LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz", "engines/llama/llama-cuda.tar.gz",
               182241275),
              (_LLAMA + f"cudart-llama-{LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz", "engines/llama/cudart.tar.gz",
               594371573)], True),
    ]
    ENGINE_EARS = Item("whisper", "whisper.cpp", "her ears: sudo pacman -S whisper-cpp", [], system="whisper-server")


def has_nvidia() -> bool:
    return (shutil.which("nvidia-smi") is not None or Path(r"C:\Windows\System32\nvidia-smi.exe").exists()
            or Path("/proc/driver/nvidia").exists())


def finish(item: Item) -> None:
    """After an engine's zips / tarballs are downloaded: unpack them flat into the engine folder, drop the archives."""
    if not item.unzip:
        return
    folder = (ROOT / item.files[0][1]).parent
    for _, p, _ in item.files:
        z = ROOT / p
        if item.key == "kokoro":  # her voice pack keeps its folders (espeak data): into models/voice/capri-voice-1
            with zipfile.ZipFile(z) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                top = z.stem + "/"
                zf.extractall(folder if all(n.startswith(top) for n in names) else folder / z.stem)
        elif z.name.endswith(".tar.gz"):
            _untar(z, folder)
        else:
            with zipfile.ZipFile(z) as zf:
                for m in zf.infolist():
                    if m.is_dir():
                        continue
                    target = folder / Path(m.filename).name  # flat: the exes and their DLLs side by side
                    with zf.open(m) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        z.unlink()
    for other in ENGINE_GPU:  # one llama engine at a time
        if other is not item:
            folder.joinpath(".done-" + other.key).unlink(missing_ok=True)
    folder.joinpath(".done-" + item.key).write_text("ok")


def download(items: list[Item], progress=lambda done, total, what: None, cancelled=lambda: False) -> bool:
    """Fetch the items' files into the folder (resuming .part files, retrying a dropped connection), then unpack the
    engines. progress(bytes done, bytes total, what) as it goes. -> False if cancelled() stopped it (it carries on
    where it stopped next time); raises when a download can't be finished."""
    import time

    import requests

    total = sum(it.size for it in items)
    done = 0
    t0, last = time.monotonic(), 0.0
    for it in items:
        for url, rel, size in it.files:
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.stat().st_size == size:
                done += size
                continue
            part = dest.with_name(dest.name + ".part")
            for attempt in range(30):  # flaky connections: keep resuming
                have = part.stat().st_size if part.exists() else 0
                if have >= size:
                    break
                try:
                    with requests.get(url, stream=True, timeout=30, allow_redirects=True,
                                      headers={"Range": f"bytes={have}-"} if have else {}) as r:
                        if r.status_code in (401, 403, 404, 410):  # moved or gone: retrying won't help
                            raise RuntimeError(f"{it.label}: dead download link ({r.status_code}) {url}")
                        r.raise_for_status()
                        if have and r.status_code != 206:  # server ignored the range: start over
                            have = 0
                        with open(part, "ab" if have else "wb") as f:
                            for chunk in r.iter_content(1 << 20):
                                if cancelled():
                                    return False
                                f.write(chunk)
                                have += len(chunk)
                                now = time.monotonic()
                                if now - last > 0.25:
                                    last = now
                                    speed = (done + have) / max(1.0, now - t0)
                                    progress(done + have, total, f"{it.label}: {gb(have)} of {gb(size)}   "
                                                                 f"({speed / 2 ** 20:.1f} MB/s)")
                except requests.RequestException as e:
                    progress(done + have, total, f"connection dropped ({type(e).__name__}), resuming... "
                                                 f"(try {attempt + 2})")
                    time.sleep(min(30, 2 + attempt * 2))
            if not part.exists() or part.stat().st_size != size:
                raise RuntimeError(f"{it.label} didn't download completely")
            part.replace(dest)
            done += size
        finish(it)
    return True


def gb(n: int) -> str:
    return f"{n / 2 ** 30:.1f} GB" if n >= 2 ** 30 * 0.95 else f"{n / 2 ** 20:.0f} MB"


def config_name() -> str:
    """Your name from config.yaml ("" when it isn't set)."""
    import re

    try:
        m = re.search(r"^user_name:\s*['\"]?([^'\"#\n]*?)['\"]?\s*(?:#.*)?$",
                      (ROOT / "config.yaml").read_text(encoding="utf-8"), re.M)
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def set_config_name(name: str) -> None:
    """Your name into config.yaml (the rest of the file, comments and all, stays as it is)."""
    import json
    import re

    p = ROOT / "config.yaml"
    try:
        s = p.read_text(encoding="utf-8")
    except OSError:
        s = ""
    line = "user_name: " + json.dumps(name)  # quoted: any name is valid YAML
    s = re.sub(r"^user_name:.*$", line, s, flags=re.M) if re.search(r"^user_name:", s, re.M) else s + "\n" + line + "\n"
    p.write_text(s, encoding="utf-8")


def _untar(z: Path, folder: Path) -> None:
    """Linux engines: flat like the zips, keeping the .so symlinks and the executable bits."""
    with tarfile.open(z) as tf:
        for m in tf.getmembers():
            target = folder / Path(m.name).name
            if m.issym() or m.islnk():
                target.unlink(missing_ok=True)
                os.symlink(Path(m.linkname).name, target)
            elif m.isfile():
                with tf.extractfile(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.chmod(target, 0o755 if m.mode & 0o111 else 0o644)


def find_exe(name: str) -> Path | None:
    """An engine program: the one setup downloaded, else one on PATH (Linux packages: whisper-cpp, llama.cpp)."""
    name = name.removesuffix(".exe") + (".exe" if os.name == "nt" else "")
    for p in ENGINES.rglob(name):
        return p
    found = shutil.which(name)
    return Path(found) if found else None


def model_dirs() -> list[Path]:
    """Folders where people usually keep .gguf models (LM Studio, GPT4All, Jan, text-generation-webui, ERU AI,
    Downloads...), the ones that exist."""
    import os

    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    cands = [home / ".lmstudio" / "models", home / ".cache" / "lm-studio" / "models", local / "nomic.ai" / "GPT4All",
             home / "jan" / "models", home / "AppData" / "Roaming" / "Jan" / "data" / "models",
             home / "text-generation-webui" / "models", Path(r"D:\ERU AI\models\llm"), home / "CapriModels",
             home / "Downloads", LLM_DIR]
    return [d for d in cands if d.is_dir()]


def local_models(limit: int = 60) -> list[Path]:
    """.gguf brains already on this PC (vision add-ons and tiny files left out), biggest folders first."""
    found, seen = [], set()
    for d in model_dirs():
        try:
            for p in d.rglob("*.gguf"):
                low = p.name.lower()
                if "mmproj" in low or p.stat().st_size < 300 * 2 ** 20:
                    continue
                key = (p.name, p.stat().st_size)
                if key not in seen:
                    seen.add(key)
                    found.append(p)
                if len(found) >= limit:
                    return found
        except OSError:
            continue
    return found


def brains() -> list[Path]:
    """Every .gguf in models\\llm (the catalog's and any a dev dropped in), minus vision add-on files."""
    if not LLM_DIR.exists():
        return []
    return sorted(p for p in LLM_DIR.rglob("*.gguf") if "mmproj" not in p.name.lower())


def ears_models() -> list[Path]:
    return sorted(WHISPER_DIR.glob("ggml-*.bin")) if WHISPER_DIR.exists() else []


def needs_setup() -> bool:
    """Nothing to think with yet? Not when a brain was picked (downloaded, your own .gguf anywhere, or "none")."""
    import json

    from .config import DATA

    try:
        picked = json.loads((DATA / "settings.json").read_text(encoding="utf-8")).get("brain", "")
    except (OSError, ValueError):
        picked = ""
    if picked == "none":
        return False  # no AI: nothing to run
    if picked and Path(picked).exists():
        return find_exe("llama-server") is None
    return not brains() or find_exe("llama-server") is None


def no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


_job = None


def tie_to_me(proc) -> None:
    """Put a helper process (llama-server, whisper-server) in a Windows job that dies with Capri, so a crash or a
    killed Capri never leaves them running in the background."""
    global _job
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    if _job is None:
        class Limits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Limits), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        _job = job
    k32.AssignProcessToJobObject(wintypes.HANDLE(_job), wintypes.HANDLE(int(proc._handle)))


def spawn(cmd: list[str], **kw) -> subprocess.Popen:
    """Start a helper (llama-server, whisper-server) that can't outlive Capri, with no console window."""
    if os.name == "nt":
        proc = subprocess.Popen(cmd, creationflags=no_window(), **kw)
        tie_to_me(proc)
        return proc
    env = dict(os.environ)  # the downloaded engines keep their .so files next to the program
    env["LD_LIBRARY_PATH"] = str(Path(cmd[0]).parent) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    import ctypes
    import signal

    prctl = ctypes.CDLL(None).prctl  # looked up here: the child, between fork and exec, should only make the call

    def die_with_capri():  # SIGTERM once the thread that started it is gone (see _on_spawner)
        prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG

    return _on_spawner(lambda: subprocess.Popen(cmd, env=env, preexec_fn=die_with_capri, **kw))


_jobs = None


def _on_spawner(start):
    """Linux ties a child's death signal to the *thread* that forked it, so every helper is forked from one thread
    that lives exactly as long as Capri does: when she dies, for any reason, they get SIGTERM."""
    global _jobs
    import queue

    if _jobs is None:
        _jobs = queue.Queue()

        def run():
            while True:
                fn, box, done = _jobs.get()
                try:
                    box.append(fn())
                except BaseException as e:
                    box.append(e)
                done.set()

        threading.Thread(target=run, daemon=True, name="capri-spawner").start()
    box, done = [], threading.Event()
    _jobs.put((start, box, done))
    done.wait()
    if isinstance(box[0], BaseException):
        raise box[0]
    return box[0]
