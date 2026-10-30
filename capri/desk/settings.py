"""Switches you flip from her menu (ears mode, talk key, mic, DJ, vibing, eyes, chatter), kept in data/settings.json
so they survive restarts. config.yaml only gives the first-run defaults."""
from __future__ import annotations

import json

from ..config import DATA


class Settings(dict):
    def __init__(self, cfg: dict):
        d = cfg["desk"]
        super().__init__(
            ears=cfg["stt"]["mode"], talk_key=cfg["stt"]["talk_key"], mic="",
            dj=d["dj"], vibe=d["vibe"], eyes=d["eyes"], chatter=d["chatter"],
            # leave me alone (no screen reading, no talking on her own), apps she never reads, reacting to videos /
            # chats / what you type, staying quiet in games, focus mode's end time, your city for the weather
            quiet=False, never_look=[], reactions=True, game_mode=True, focus_until=0.0, city="",
            brain="",  # a .gguf picked from her Brain menu ("" = config.yaml's, "none" = no AI, just her)
            my_brains=[],  # .gguf files on this PC you picked for her (shown in her Brain menu)
            size=0,  # her height in pixels, from her Size menu (0 = config.yaml's)
            voice=True,  # she talks out loud (her free Kokoro voice, once it's downloaded); off = talking blips
            whisper_model="",  # portable build: which ggml whisper model her ears use ("" = small)
        )
        self.path = DATA / "settings.json"
        try:
            self.update({k: v for k, v in json.loads(self.path.read_text(encoding="utf-8")).items() if k in self})
        except (OSError, ValueError):
            pass

    def set(self, key, value):
        self[key] = value
        try:
            DATA.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(dict(self), indent=2), encoding="utf-8")
        except OSError as e:
            print(f"[capri] couldn't save settings: {e}")
