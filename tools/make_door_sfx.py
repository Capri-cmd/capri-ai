"""Builds the door sounds as WAVs: door_open (intro), door_idle (seamless loop) and door_close (outro). Synthesized
in code like capri/desk/sfx.py, but aimed at cinematic sci-fi rather than retro: layered noise and detuned synths,
sub-bass impacts, glitch stutters, stereo width and a long reverb tail.

Timings follow the intro frames at 12 fps: 0-0.5 s a spark becomes a line, 0.5-0.85 s it opens into a frame,
~0.85 s the door slams to full height and glitches, then settles. The close is the same story backwards, so it
glitches first and snaps shut at ~1.45 s.

    python tools/make_door_sfx.py [out_dir]     (default assets/desk/door/sfx)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
RNG = np.random.default_rng(7)  # fixed seed: same sounds every build
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "assets" / "desk" / "door" / "sfx"


def t(sec):
    return np.arange(int(SR * sec)) / SR


def at(buf, sec, x, gain=1.0):
    """Mix mono or stereo x into stereo buf starting at sec."""
    i = round(sec * SR)
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    n = min(len(x), len(buf) - i)
    buf[i:i + n] += gain * x[:n]


def bp(x, lo, hi, order=4):
    return sosfilt(butter(order, [lo, hi], "bandpass", fs=SR, output="sos"), x)


def lp(x, f, order=4):
    return sosfilt(butter(order, f, "lowpass", fs=SR, output="sos"), x)


def hp(x, f, order=4):
    return sosfilt(butter(order, f, "highpass", fs=SR, output="sos"), x)


def sweep_filter_noise(sec, f0, f1, q=0.35, steps=64):
    """Noise through a band-pass whose centre glides f0 -> f1 (exponential): the 'whoosh'."""
    n = round(sec * SR)
    noise = RNG.standard_normal(n)
    out = np.zeros(n)
    edges = np.linspace(0, n, steps + 1).astype(int)
    win = np.hanning(2 * (edges[1] - edges[0]) + 2)
    for k in range(steps):
        fc = f0 * (f1 / f0) ** (k / (steps - 1))
        a, b = max(0, edges[k] - (edges[1] - edges[0]) // 2), min(n, edges[k + 1] + (edges[1] - edges[0]) // 2)
        seg = bp(noise[a:b], fc * (1 - q), min(fc * (1 + q), SR / 2 - 100), 2)
        w = np.interp(np.linspace(0, 1, b - a), np.linspace(0, 1, len(win)), win)
        out[a:b] += seg * w
    return out / (np.abs(out).max() + 1e-9)


def osc(freq, sec, shape="sine"):
    """freq: number or per-sample array."""
    n = round(sec * SR)
    f = np.full(n, freq) if np.isscalar(freq) else freq[:n]
    ph = 2 * np.pi * np.cumsum(f) / SR
    if shape == "saw":
        return 2 * ((ph / (2 * np.pi)) % 1) - 1
    return np.sin(ph)


def glide(f0, f1, sec):
    k = t(sec) / sec
    return f0 * (f1 / f0) ** k


def env(sec, a=0.01, r=None, curve=2.0):
    n = round(sec * SR)
    e = np.ones(n)
    na = max(1, int(a * SR))
    e[:na] = np.linspace(0, 1, na)
    r = sec - a if r is None else r
    nr = min(n - na, max(1, int(r * SR)))
    e[-nr:] *= np.linspace(1, 0, nr) ** curve
    return e


def supersaw(freq, sec, voices=7, detune=0.012):
    out = np.zeros((round(sec * SR), 2))
    for v in range(voices):
        d = 1 + detune * (v - voices // 2) / (voices // 2)
        f = freq * d
        s = osc(f, sec, "saw")
        pan = (v / (voices - 1)) * 2 - 1
        out[:, 0] += s * np.sqrt((1 - pan) / 2)
        out[:, 1] += s * np.sqrt((1 + pan) / 2)
    return out / voices


def crackle(sec, density=60, bright=6000):
    """Electric crackle: sparse random clicks, high-passed, with random stereo position."""
    n = round(sec * SR)
    out = np.zeros((n, 2))
    for _ in range(int(density * sec)):
        i = RNG.integers(0, max(1, n - 400))
        L = RNG.integers(20, 300)
        click = RNG.standard_normal(L) * np.exp(-np.linspace(0, 6, L)) * RNG.uniform(0.3, 1)
        p = RNG.uniform(-1, 1)
        out[i:i + L, 0] += click * np.sqrt((1 - p) / 2)
        out[i:i + L, 1] += click * np.sqrt((1 + p) / 2)
    return np.stack([hp(out[:, 0], bright), hp(out[:, 1], bright)], 1)


def stutter(x, slices=8, slice_ms=(18, 55)):
    """Digital glitch: grab little chunks of x and repeat/skip them, with bit-crush on some."""
    out = []
    i = 0
    for _ in range(slices):
        L = int(RNG.uniform(*slice_ms) / 1000 * SR)
        chunk = x[i:i + L].copy()
        if len(chunk) < L:
            break
        if RNG.random() < 0.5:
            chunk = np.round(chunk * 6) / 6  # crush
        if RNG.random() < 0.3:
            chunk = chunk[::2].repeat(2, axis=0)[:L]  # octave-up-ish sample-and-hold
        reps = RNG.integers(1, 4)
        fade = np.ones(L)
        fade[:64] = np.linspace(0, 1, 64)
        fade[-64:] = np.linspace(1, 0, 64)
        chunk = chunk * (fade[:, None] if chunk.ndim == 2 else fade)
        out += [chunk] * reps
        i += int(L * RNG.uniform(0.5, 2.0))
    return np.concatenate(out) if out else x[:0]


def stereo(x, width=0.0):
    return np.stack([x, x], 1) if width == 0 else np.stack([x, np.roll(x, int(width * SR))], 1)


def reverb(x, sec=2.2, mix=0.28, tone=5500):
    """Stereo convolution reverb from decaying noise (decorrelated L/R)."""
    n = round(sec * SR)
    decay = np.exp(-np.linspace(0, 7, n))
    ir = [lp(RNG.standard_normal(n), tone, 2) * decay for _ in range(2)]
    ir = [h / np.sqrt((h ** 2).sum()) for h in ir]
    pad = np.vstack([x, np.zeros((n, 2))])
    wet = np.stack([fftconvolve(pad[:, c], ir[c])[:len(pad)] for c in range(2)], 1)
    dry = pad
    return dry * (1 - mix) + wet * mix * 3.0


def finish(x, peak=0.89):
    x = x - x.mean(0)
    x = np.tanh(x / (np.abs(x).max() + 1e-9) * 1.6) / np.tanh(1.6)  # soft glue
    fade = np.ones(len(x))
    fade[-int(0.08 * SR):] = np.linspace(1, 0, int(0.08 * SR))
    return (x * fade[:, None] * peak).astype(np.float32)


def sub_drop(sec=1.2, f0=95, f1=38):
    s = osc(glide(f0, f1, sec), sec) * env(sec, 0.004, sec - 0.004, 2.5)
    return s + 0.25 * np.tanh(3 * s)


def door_open():
    L = 3.6
    buf = np.zeros((int(L * SR), 2))
    # 0.00 spark: bright zap + crackle
    zap = osc(glide(5200, 900, 0.18), 0.18) * env(0.18, 0.002, 0.17, 3)
    at(buf, 0.0, stereo(zap), 0.35)
    at(buf, 0.0, crackle(0.55, 90), 0.55)
    # 0.05-0.55 the line stretches: rising airy shimmer + rising supersaw
    at(buf, 0.05, stereo(sweep_filter_noise(0.8, 700, 7000) * env(0.8, 0.35, 0.4), 0.004), 0.45)
    rise = supersaw(glide(110, 220, 0.85), 0.85) * env(0.85, 0.5, 0.3)[:, None]
    at(buf, 0.0, np.stack([lp(rise[:, c], 2500) for c in range(2)], 1), 0.5)
    # 0.5-0.85 it opens into a frame: whoosh up + tension swell
    at(buf, 0.45, stereo(sweep_filter_noise(0.45, 300, 4000) * env(0.45, 0.35, 0.1), 0.006), 0.6)
    # 0.85 slam to full height: sub drop, body hit, glitch stutter, metallic shimmer
    at(buf, 0.85, stereo(sub_drop(1.5)), 0.9)
    hit = lp(RNG.standard_normal(int(0.25 * SR)), 1800) * env(0.25, 0.001, 0.24, 4)
    at(buf, 0.85, stereo(hit, 0.002), 0.7)
    chord = sum(osc(f, 2.2) * env(2.2, 0.005, 2.1, 3) for f in (220, 329.6, 440, 659.3, 987.8)) / 5
    fm = osc(880 + 600 * osc(1318, 2.2) * env(2.2, 0.001, 0.6, 2), 2.2) * env(2.2, 0.002, 1.6, 3)
    at(buf, 0.85, stereo(chord + 0.3 * fm, 0.01), 0.45)
    pre = np.stack([bp(buf[int(0.6 * SR):int(1.0 * SR), c], 300, 9000) for c in range(2)], 1)
    at(buf, 0.9, stutter(pre, 9), 0.6)
    at(buf, 0.85, crackle(0.6, 120, 4000), 0.5)
    # 1.0+ settles: resonant hum swells in, will hand over to the idle loop
    hum_sec = 2.4
    hum = sum(a * osc(f * (1 + 0.003 * osc(0.5, hum_sec)), hum_sec) for f, a in ((55, 1), (110, 0.5), (165, 0.25), (330, 0.08)))
    at(buf, 1.0, stereo(hum * env(hum_sec, 0.3, 1.5, 1.5), 0.0), 0.35)
    return finish(reverb(buf, 2.4, 0.3))


def door_close():
    L = 3.6
    buf = np.zeros((int(L * SR), 2))
    # 0.0 glitches out: stutter of a bright buzz, crackle
    buzz = supersaw(196, 0.5) * env(0.5, 0.01, 0.2)[:, None]
    buzz = np.stack([bp(buzz[:, c], 400, 6000) for c in range(2)], 1)
    at(buf, 0.0, stutter(buzz, 10, (15, 40)), 0.6)
    at(buf, 0.0, crackle(1.0, 110, 4000), 0.5)
    # 0.3-1.4 collapses: falling supersaw + falling whoosh
    fall = supersaw(glide(260, 70, 1.1), 1.1) * env(1.1, 0.1, 0.7)[:, None]
    at(buf, 0.3, np.stack([lp(fall[:, c], 3000) for c in range(2)], 1), 0.55)
    at(buf, 0.3, stereo(sweep_filter_noise(1.1, 6000, 300) * env(1.1, 0.15, 0.8), 0.005), 0.55)
    # ~1.45 (the last frames) shrinks to a line and snaps shut: tight zap + click + small sub thump
    snap_at = 1.45
    zap = osc(glide(600, 4800, 0.09), 0.09) * env(0.09, 0.001, 0.08, 2)
    at(buf, snap_at - 0.09, stereo(zap), 0.4)
    click = hp(RNG.standard_normal(int(0.03 * SR)), 2000) * env(0.03, 0.0005, 0.029, 4)
    at(buf, snap_at, stereo(click), 0.9)
    at(buf, snap_at, stereo(sub_drop(0.6, 80, 35)), 0.7)
    # then power-down: descending sine with a last tiny crackle
    pd = osc(glide(440, 40, 1.0), 1.0) * env(1.0, 0.005, 0.99, 2)
    at(buf, snap_at, stereo(pd, 0.004), 0.25)
    at(buf, snap_at + 0.05, crackle(0.35, 30, 6000), 0.35)
    return finish(reverb(buf, 2.2, 0.3))


def door_idle(sec=6.0):
    """Seamless loop: every periodic part repeats a whole number of times in `sec`, and the reverb wraps around."""
    n = round(sec * SR)
    tt = np.arange(n) / SR
    per = lambda f: round(f * sec) / sec  # snap to a frequency that loops exactly
    hum = np.zeros(n)
    for f, a in ((55, 1.0), (110, 0.45), (165, 0.2), (220, 0.06), (330, 0.05)):
        hum += a * np.sin(2 * np.pi * per(f) * tt + RNG.uniform(0, 6.28))
    beat = 1 + 0.15 * np.sin(2 * np.pi * per(0.5) * tt)  # slow breathing
    hum *= beat
    buzz = hp(np.sign(np.sin(2 * np.pi * per(110) * tt)) * 0.02, 1800, 2)  # faint electrical buzz
    air = np.tile(RNG.standard_normal(n), 2)
    air = bp(air, 900, 5000, 2)[n:]  # filtered twice-length then take the steady second half: loops cleanly
    air *= 0.12 * (1 + 0.5 * np.sin(2 * np.pi * per(1 / 3) * tt))
    body = np.stack([hum + buzz + air, hum + buzz + np.roll(air, 211)], 1) * 0.5
    # glitch flickers, a few per loop, matching the idle frames' glitching
    for s in (0.6, 1.9, 2.4, 3.8, 5.1):
        L = int(RNG.uniform(0.04, 0.12) * SR)
        g = np.round(RNG.standard_normal(L) * 3) / 3
        g = bp(g, 1500, 9000, 2) * env(L / SR, 0.002, L / SR * 0.6, 2)
        p = RNG.uniform(-0.8, 0.8)
        i = int(s * SR)
        body[i:i + L, 0] += 0.25 * g * np.sqrt((1 - p) / 2)
        body[i:i + L, 1] += 0.25 * g * np.sqrt((1 + p) / 2)
    body += 0.3 * crackle(sec, 12, 6000)
    # circular reverb: convolve, fold the tail back onto the start
    wet = reverb(body, 1.6, 1.0)
    tail = wet[n:]
    wet = wet[:n].copy()
    wet[:len(tail)] += tail
    x = body * 0.75 + wet * 0.25
    x = x - x.mean(0)
    return (x / np.abs(x).max() * 0.6).astype(np.float32)


def menu_open():
    """The quick portal behind her right-click menu (intro at 30 fps): zap, rising swish, soft slam at ~0.35 s."""
    L = 1.6
    buf = np.zeros((round(L * SR), 2))
    zap = osc(glide(4200, 1200, 0.08), 0.08) * env(0.08, 0.001, 0.07, 3)
    at(buf, 0.0, stereo(zap), 0.25)
    at(buf, 0.0, crackle(0.3, 70), 0.4)
    at(buf, 0.02, stereo(sweep_filter_noise(0.33, 600, 6000) * env(0.33, 0.25, 0.08), 0.004), 0.5)
    rise = supersaw(glide(150, 300, 0.36), 0.36) * env(0.36, 0.25, 0.1)[:, None]
    at(buf, 0.0, np.stack([lp(rise[:, c], 2500) for c in range(2)], 1), 0.3)
    at(buf, 0.35, stereo(sub_drop(0.5, 120, 50)), 0.45)
    chord = sum(osc(f, 0.9) * env(0.9, 0.003, 0.85, 3) for f in (440, 659.3, 987.8)) / 3
    at(buf, 0.35, stereo(chord, 0.008), 0.25)
    pre = np.stack([bp(buf[round(0.2 * SR):round(0.4 * SR), c], 400, 9000) for c in range(2)], 1)
    at(buf, 0.37, stutter(pre, 5, (12, 30)), 0.35)
    return finish(reverb(buf, 1.2, 0.22), 0.7)


def menu_close():
    """Closing it again (reversed intro at 36 fps): glitch, falling swish, snap shut at ~0.58 s."""
    L = 1.4
    buf = np.zeros((round(L * SR), 2))
    buzz = supersaw(220, 0.25) * env(0.25, 0.005, 0.1)[:, None]
    buzz = np.stack([bp(buzz[:, c], 500, 6000) for c in range(2)], 1)
    at(buf, 0.0, stutter(buzz, 6, (12, 30)), 0.4)
    at(buf, 0.0, crackle(0.4, 80, 4000), 0.35)
    at(buf, 0.15, stereo(sweep_filter_noise(0.42, 5000, 400) * env(0.42, 0.05, 0.35), 0.004), 0.45)
    snap = 0.58
    click = hp(RNG.standard_normal(round(0.025 * SR)), 2000) * env(0.025, 0.0005, 0.024, 4)
    at(buf, snap, stereo(click), 0.6)
    at(buf, snap, stereo(sub_drop(0.35, 90, 40)), 0.35)
    at(buf, snap, stereo(osc(glide(400, 60, 0.4), 0.4) * env(0.4, 0.003, 0.39, 2)), 0.15)
    return finish(reverb(buf, 1.0, 0.22), 0.7)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("door_open", door_open), ("door_idle", door_idle), ("door_close", door_close),
                     ("menu_open", menu_open), ("menu_close", menu_close)):
        x = fn()
        sf.write(OUT / f"{name}.wav", x, SR, subtype="PCM_16")
        print(f"{name}.wav  {len(x) / SR:.2f}s")


if __name__ == "__main__":
    main()
