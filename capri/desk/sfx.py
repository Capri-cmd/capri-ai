"""Cartoony sound effects, synthesized in code (no sample files): zaps, whooshes, coin-style pops, thuds, and
the little talking blips (old-school RPG text sounds) she makes instead of a voice.

One mixer stream plays everything at once. Every sound is fully described by (name, arg), so a recording can
log the events and rebuild a perfect audio track afterwards (see Recorder in video.py).
"""
from __future__ import annotations

import threading
import time
import zlib
from pathlib import Path

import numpy as np

SR = 44100
VOLUME = 0.55  # master volume


def _t(sec):
    return np.arange(int(SR * sec)) / SR


def _env(n, attack=0.005, release=0.08):
    """Linear attack, exponential-ish release."""
    e = np.ones(n, dtype=np.float32)
    a = max(1, int(SR * attack))
    e[:a] = np.linspace(0, 1, a)
    r = min(n, max(1, int(SR * release)))
    e[-r:] *= np.linspace(1, 0, r) ** 2
    return e


def _sweep(f0, f1, sec, shape="sine", curve="exp"):
    t = _t(sec)
    k = t / sec
    f = f0 * (f1 / f0) ** k if curve == "exp" else f0 + (f1 - f0) * k
    ph = 2 * np.pi * np.cumsum(f) / SR
    if shape == "square":
        return np.sign(np.sin(ph)) * 0.6
    if shape == "tri":
        return 2 / np.pi * np.arcsin(np.sin(ph))
    if shape == "saw":
        return 2 * ((ph / (2 * np.pi)) % 1) - 1
    return np.sin(ph)


def _note(f, sec, shape="square", attack=0.003, release=None):
    s = _sweep(f, f, sec, shape, "lin")
    return s * _env(len(s), attack, release if release is not None else sec * 0.7)


def _noise(sec, rng):
    return rng.uniform(-1, 1, int(SR * sec))


def _lowpass(x, a=0.15):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # one-pole; sounds are short, so this stays cheap
        acc += a * (v - acc)
        y[i] = acc
    return y


def _cat(*parts, gap=0.0):
    out = []
    for p in parts:
        out += [p, np.zeros(int(SR * gap))]
    return np.concatenate(out[:-1] if gap else out)


def _crush(x, steps=12):
    return np.round(x * steps) / steps  # 8-bit grit


def synth(name: str, arg: str = "") -> np.ndarray:
    rng = np.random.default_rng(zlib.crc32((name + arg).encode()))
    if name == "blip":  # one talking blip; arg = the letter, which picks the pitch
        ch = (arg or "a").lower()
        base = 560 if ch in "aeiou" else 660
        semis = [0, 2, 4, 5, 7, 9, 12][zlib.crc32(ch.encode()) % 7]
        f = base * 2 ** (semis / 12)
        s = _note(f, 0.055, "square", 0.002, 0.04) * 0.55 + _note(f * 2, 0.055, "tri", 0.002, 0.04) * 0.25
        return _crush(s, 10) * 0.6
    if name == "charge":  # rising whine with a wobble
        s = _sweep(220, 1400, 0.42, "saw") * 0.35 + _sweep(440, 2800, 0.42, "sine") * 0.25
        s *= 1 + 0.35 * np.sin(2 * np.pi * 18 * _t(0.42))
        return s * _env(len(s), 0.05, 0.05) * 0.5
    if name == "stream":  # breaking into pixels: shimmering swell + glittery arpeggio
        sec = 1.2
        sh = _lowpass(_noise(sec, rng), 0.25) * np.sin(np.pi * _t(sec) / sec) ** 2 * 0.5
        arp = _cat(*[_note(f, 0.07, "square", release=0.05) for f in (784, 988, 1175, 1568, 1976, 2349, 1976, 2349, 2637, 3136)])
        arp = np.pad(arp, (int(SR * 0.15), 0))[: len(sh)]
        arp = np.pad(arp, (0, len(sh) - len(arp)))
        return (sh + _crush(arp, 10) * 0.22) * 0.7
    if name == "rebuild":  # pixels clicking back into place
        return _cat(*[_note(f, 0.05, "square", release=0.04) for f in (1319, 1047, 1568, 2093)]) * 0.35
    if name == "coin":  # a new window popping in: the classic collect ding
        return _cat(_note(988, 0.07, "square", release=0.02), _note(1319, 0.42, "square", release=0.38)) * 0.4
    if name == "boom":  # the sky tearing open
        sec = 0.9
        thump = _sweep(160, 38, sec, "sine") * _env(int(SR * sec), 0.002, 0.8)
        rumble = _lowpass(_noise(sec, rng), 0.08) * _env(int(SR * sec), 0.002, 0.85) * 2.2
        crack = np.pad(_noise(0.05, rng) * 0.6, (0, int(SR * sec) - int(SR * 0.05)))
        return _crush(thump * 0.9 + rumble + crack, 16) * 0.7
    if name == "tear":  # electric fizz before the boom
        sec = 0.55
        s = _noise(sec, rng) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 37 * _t(sec)))) * 0.25
        return s * _env(len(s), 0.2, 0.05) + _sweep(300, 900, sec, "saw") * 0.12
    if name == "fall":  # cartoon falling whistle
        return _sweep(1900, 500, 0.7, "sine") * _env(int(SR * 0.7), 0.05, 0.1) * 0.25
    if name == "thud":  # landing: soft boing-thump; arg = how hard (0-1)
        k = float(arg or 0.5)
        thump = _sweep(220, 55, 0.18, "sine") * _env(int(SR * 0.18), 0.001, 0.16)
        boing = _sweep(300, 520, 0.16, "tri") * (1 + 0.5 * np.sin(2 * np.pi * 30 * _t(0.16))) * _env(int(SR * 0.16), 0.002, 0.12)
        return _cat(thump * (0.6 + 0.6 * k), boing * 0.18)
    if name == "tinkle":  # debris pixels pattering down
        return _cat(*[_note(f, 0.03, "tri", release=0.025) for f in rng.choice([2637, 3136, 3520, 4186], 5)], gap=0.03) * 0.15
    if name == "crtoff":  # old TV switching off: a falling whine, a click, a soft thump
        whine = _sweep(5200, 90, 0.32, "sine") * _env(int(SR * 0.32), 0.002, 0.2) * 0.5
        click = np.pad(_noise(0.012, rng), (0, int(SR * 0.32) - int(SR * 0.012))) * 0.8
        thump = np.pad(_sweep(120, 40, 0.15, "sine") * _env(int(SR * 0.15), 0.002, 0.12), (int(SR * 0.17), 0))[: int(SR * 0.32)]
        return whine + click + thump
    if name == "bloop":  # the last pixel dropping off
        return _cat(_sweep(1200, 260, 0.14, "sine") * _env(int(SR * 0.14), 0.002, 0.1),
                    _sweep(520, 380, 0.08, "tri") * _env(int(SR * 0.08), 0.002, 0.06) * 0.4)
    if name == "grab":
        return _sweep(400, 900, 0.09, "square") * _env(int(SR * 0.09), 0.002, 0.06) * 0.25
    if name == "throw":
        sec = 0.3
        return _lowpass(_noise(sec, rng), 0.3) * np.sin(np.pi * _t(sec) / sec) * 0.35
    if name == "key":  # a keystroke in her type box (video mode): a short soft click
        return _lowpass(_noise(0.018, rng), 0.5) * _env(int(SR * 0.018), 0.001, 0.014) * 0.5
    if name == "pop":  # bubble opening
        return _sweep(500, 1300, 0.06, "sine") * _env(int(SR * 0.06), 0.002, 0.04) * 0.3
    if name == "sleep":  # shrinking into the chip: sleepy descending trill
        return _cat(*[_note(f, 0.09, "tri", release=0.07) for f in (1047, 880, 698, 523)]) * 0.35
    if name == "wake":  # booting back up
        return _cat(*[_note(f, 0.07, "square", release=0.05) for f in (523, 659, 784, 1047)], _note(1568, 0.18, "tri")) * 0.32
    if name == "snore":  # tiny "zz" puff while she naps
        s = _sweep(300, 240, 0.35, "tri") * np.sin(np.pi * _t(0.35) / 0.35) * 0.08
        return s
    wav = WAVS / f"{name}.wav"
    if wav.exists():
        return _load_wav(wav)
    return np.zeros(1)


# designed sounds that live as files (made by tools/make_door_sfx.py): the door her menu opens in
WAVS = Path(__file__).resolve().parents[2] / "assets" / "desk" / "door" / "sfx"


def _load_wav(path: Path) -> np.ndarray:
    """Mono at SR, whatever the file's rate and channels."""
    import soundfile as sf

    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        n = round(len(x) * SR / sr)
        x = np.interp(np.arange(n) * sr / SR, np.arange(len(x)), x).astype(np.float32)
    return x


_cache: dict[tuple, np.ndarray] = {}

# peak level per sound, so a coin isn't drowned out by the boom
LEVEL = {"boom": 0.75, "thud": 0.5, "crtoff": 0.45, "bloop": 0.35, "coin": 0.38, "stream": 0.35, "charge": 0.3,
         "wake": 0.35, "sleep": 0.32, "rebuild": 0.3, "blip": 0.2, "pop": 0.22, "grab": 0.25, "throw": 0.25,
         "tinkle": 0.16, "fall": 0.22, "tear": 0.3, "snore": 0.08, "key": 0.07,
         "door_open": 0.4, "door_close": 0.36}


def sound(name: str, arg: str = "") -> np.ndarray:
    key = (name, arg)
    if key not in _cache:
        s = synth(name, arg)
        peak = float(np.abs(s).max()) or 1.0
        level = LEVEL.get(name, 0.3) * (0.5 + 0.5 * float(arg or 1) if name == "thud" else 1)
        _cache[key] = (s / peak * level * VOLUME / 0.55).astype(np.float32)
    return _cache[key]


class Mixer:
    """Plays any number of sounds at once on one output stream. Logs each one when a recording is running."""

    def __init__(self):
        self.lock = threading.Lock()
        self.voices: list[list] = []  # [samples, position]
        self.log: list[tuple[float, str, str]] | None = None
        self.quiet = lambda: False  # the app sets this: True while your music is playing (no booms over your songs)
        self.stream = None
        try:
            import sounddevice as sd

            self.stream = sd.OutputStream(samplerate=SR, channels=1, dtype="float32", blocksize=512, callback=self._fill)
            self.stream.start()
        except Exception as e:
            print(f"[sfx] no audio output: {e}")

    def _fill(self, out, frames, _time, _status):
        buf = np.zeros(frames, dtype=np.float32)
        with self.lock:
            keep = []
            for v in self.voices:
                s, pos = v
                n = min(frames, len(s) - pos)
                buf[:n] += s[pos:pos + n]
                v[1] = pos + n
                if v[1] < len(s):
                    keep.append(v)
            self.voices = keep
        out[:, 0] = np.clip(buf, -1, 1)

    def play(self, name: str, arg: str = "") -> None:
        s = sound(name, arg)
        if self.quiet():
            if name != "blip":
                return  # effects stay on screen, silent
            s = s * 0.6  # her "voice" stays, a little softer under the music
        with self.lock:
            self.voices.append([s, 0])
            if self.log is not None:
                self.log.append((time.time(), name, arg))


def add_track(key: str, samples: np.ndarray) -> None:
    """A whole song (video mode) played and logged like any other sound: play("song", key)."""
    _cache[("song", key)] = samples.astype(np.float32)


def render(events: list[tuple[float, str, str]], t0: float, seconds: float) -> np.ndarray:
    """Rebuild the exact audio of a recording from its logged events (t0 = when the video's first frame was)."""
    out = np.zeros(int(SR * seconds) + SR, dtype=np.float32)
    for t, name, arg in events:
        i = int((t - t0) * SR)
        if i < 0:
            continue
        s = sound(name, arg)
        n = min(len(s), len(out) - i)
        if n > 0:
            out[i:i + n] += s[:n]
    return np.clip(out[: int(SR * seconds)], -1, 1)
