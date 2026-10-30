"""Config loading. Defaults live here; config.yaml in the repo root overrides them."""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # yaml is optional, defaults still work
    yaml = None

FROZEN = getattr(sys, "frozen", False)  # the portable dev build (Capri.exe)
# ROOT: where config.yaml, data\ and (portable) models\ + engines\ live. Frozen, that's the folder Capri.exe is in,
# while the assets ship inside the bundle.
_SRC = Path(__file__).resolve().parent.parent
ROOT = Path(sys.executable).resolve().parent if FROZEN else _SRC
if os.environ.get("CAPRI_HOME"):  # run from source against another folder (testing the portable layout)
    ROOT = Path(os.environ["CAPRI_HOME"]).resolve()
ASSETS = (Path(getattr(sys, "_MEIPASS", _SRC)) if FROZEN else _SRC) / "assets"
DATA = ROOT / "data"

DEFAULTS: dict = {
    # "full": everything (DJ, ERU AI). "dev": the portable test build for other devs: no DJ,
    # models + engines in its own folder (portable.py)
    "edition": "full",
    "eru_ai_root": r"D:\ERU AI",
    # ERU AI's Qdrant vector memory (in Capri's own store under data\); falls back to JSON facts if it can't load
    "eru": {"memory": True},
    # how she lives on the desktop
    "desk": {
        "size": 240,  # her height in pixels
        "video_size": 360,  # her height in video mode (big enough for a 9:16 phone crop)
        "roam_seconds": [18, 40],  # she zaps somewhere new every this-many seconds
        "intro": True,  # the drop-in from the top of the screen on launch
        # these four are first-run defaults; after that her right-click menu remembers your choice
        "dj": False,  # let her swap your YouTube music for Cyberpunk OSTs when she thinks it's not nova
        "vibe": True,  # her hair glitches to the beat of whatever's playing
        "eyes": True,  # she glances at the window you're in (title + Windows OCR, nothing saved)
        "chatter": True,  # she pipes up when you've been quiet a while, and reacts to what you open
        "chatter_idle_minutes": 6,  # no keyboard / mouse this long: she says something
        "react_cooldown_minutes": 4,  # at most one unprompted remark per this many minutes
    },
    "stt": {
        "mode": "hold",  # hold = hold the talk key while you speak; auto = she listens all the time; off
        "talk_key": "ctrl+1",
        "input_device": "",  # part of the mic's name ("FDUCE"); "" = Windows default (also pickable in her menu)
        "model": "small.en",  # only if ERU's whisper model isn't found
        "hotwords": "Capri, Campy, Capricorn, choom, chooms, preem, nova",
        "silence_seconds": 0.7,  # auto mode: this much quiet ends a sentence
        "energy_threshold": 0.015,
    },
    "llm": {
        # llama_cpp: load a GGUF directly; openai: any OpenAI-compatible server (LM Studio, Ollama, llama-server, ...)
        "backend": "llama_cpp",
        "model_path": r"D:\ERU AI\models\llm\Mistral-Nemo-Instruct-2407\Mistral-Nemo-Instruct-2407-IQ4_XS.gguf",
        "n_ctx": 5120,  # her prompt is ~2.4k tokens plus ~1.4k of chat history and the reply; 8-bit cache keeps it small
        "n_gpu_layers": -1,
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key": "not-needed",
        "model": "local-model",
        "temperature": 0.7,
        "max_tokens": 90,  # she talks in one or two short sentences; a cap keeps a rambling reply from costing seconds
    },
    "tts": {
        # blips: no voice, old-school RPG talking blips while the bubble types (the default for now)
        # gpt_sovits: Capri's cloned voice through ERU's GPT-SoVITS (voice_server/sovits_server.py, started for you)
        # none: silent text
        "backend": "blips",
        "gpt_sovits": {
            "url": "http://127.0.0.1:9880/tts",
            "autostart": True,
            "version": "v2",
            "ref_audio_path": "",  # empty = voices/capri/ref.wav
            "prompt_text": "",  # empty = voices/capri/ref.txt
            "prompt_lang": "en",
            "text_lang": "en",
            "speed_factor": 1.0,
        },
    },
    "spotify": {
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "http://127.0.0.1:8888/callback",
    },
    "memory": {"file": "data/memory.json", "history_turns": 12},
    # web search: a Brave Search API key (free tier: https://brave.com/search/api/) or a SearXNG instance's URL;
    # with neither she still looks things up on Wikipedia + DuckDuckGo instant answers
    "search": {"brave_api_key": "", "searxng_url": ""},
    "tools": {"files_dir": ""},  # where the text files she writes go ("" = Documents/Capri)
    # MCP servers she can use as tools (capri/abilities/mcp.py has an example)
    "mcp": {"servers": {}},
    # her real eyes (looking at pictures for "rate this"): InternVL3.5-1B, ~2.5 GB of VRAM. "" = off
    "sight": {"model_dir": "D:/ERU AI/models/vision/InternVL3_5-1B-HF"},
    "user_name": "you",
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    cfg = DEFAULTS
    path = Path(os.environ.get("CAPRI_CONFIG", ROOT / "config.yaml"))
    if path.exists() and yaml is not None:
        with open(path, encoding="utf-8") as f:
            cfg = _merge(DEFAULTS, yaml.safe_load(f) or {})
    DATA.mkdir(exist_ok=True)
    return cfg
