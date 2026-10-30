"""Capri's setup in the terminal, the same on Windows and Arch: y/n questions for her brain, engine, ears, voice and
eyes (and, on Arch, the system packages), then one download with a progress bar.

    python -m capri.setup_cli            only asks when something she needs is missing (first run)
    python -m capri.setup_cli --setup    asks everything again

Exit code: 0 = start her, 2 = you chose to quit. With no terminal attached it does nothing (her menu has the downloads).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import portable
from .config import ROOT

LINUX = sys.platform.startswith("linux")
PINK, CYAN, DIM, BOLD, OFF = "\033[38;2;255;46;112m", "\033[38;2;120;250;255m", "\033[2m", "\033[1m", "\033[0m"
# Arch: what she needs from pacman, and what each extra is for
PACMAN_NEED = ["python", "portaudio", "xcb-util-cursor", "vulkan-icd-loader"]
PACMAN_EARS = ["whisper-cpp"]
PACMAN_EYES = ["tesseract", "tesseract-data-eng", "spectacle"]
PACMAN_MUSIC = ["playerctl"]
AGAIN = (("bash arch/run.sh" if shutil.which("pacman") else "bash kali/run.sh") if LINUX else r"windows\start.bat") + " --setup"


def say(text: str = "", color: str = "") -> None:
    print(f"{color}{text}{OFF}" if color else text, flush=True)


def ask(question: str, default: bool = True) -> bool:
    """y/n, Enter takes the default."""
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            a = input(f"{CYAN}?{OFF} {question} {DIM}{hint}{OFF} ").strip().lower()
        except EOFError:
            return default
        if not a:
            return default
        if a in ("y", "yes", "yeah", "ya", "yep", "ye"):
            return True
        if a in ("n", "no", "nah", "nope"):
            return False
        say("  y or n", DIM)


def pick(question: str, options: list[str], default: int = 0) -> int:
    """A numbered list; Enter takes the default. -> the index."""
    say(f"{CYAN}?{OFF} {question}")
    for i, o in enumerate(options, 1):
        say(f"  {PINK if i - 1 == default else ''}{i}){OFF} {o}")
    while True:
        try:
            a = input(f"  {DIM}number [{default + 1}]{OFF} ").strip()
        except EOFError:
            return default
        if not a:
            return default
        if a.isdigit() and 1 <= int(a) <= len(options):
            return int(a) - 1
        say(f"  1 to {len(options)}", DIM)


def text(question: str, default: str = "") -> str:
    try:
        a = input(f"{CYAN}?{OFF} {question} {DIM}[{default}]{OFF} " if default else f"{CYAN}?{OFF} {question} ").strip()
    except EOFError:
        return default
    return a or default


def _missing_pacman(pkgs: list[str]) -> list[str]:
    return [p for p in pkgs if subprocess.run(["pacman", "-Q", p], capture_output=True).returncode != 0]


def _pacman(pkgs: list[str]) -> None:
    say(f"  sudo pacman -S --needed {' '.join(pkgs)}", DIM)
    subprocess.run(["sudo", "pacman", "-S", "--needed", *pkgs])


def bar(done: int, total: int, what: str) -> None:
    w = 28
    q = done / max(1, total)
    fill = round(w * q)
    line = f"\r  {PINK}{'█' * fill}{DIM}{'░' * (w - fill)}{OFF} {q * 100:5.1f}%  {what}"
    print(line[:shutil.get_terminal_size((100, 20)).columns + 20].ljust(110), end="", flush=True)


def run(force: bool) -> int:
    if os.name == "nt":
        os.system("")  # switches on colours in the Windows console
    from .config import load
    from .desk.settings import Settings

    s = Settings(load())
    say()
    say("  CAPRI // SETUP", PINK + BOLD)
    say("  Enter takes the default. Everything downloads into this folder; nothing is installed system-wide"
        + (" (except what pacman installs, if you say yes)." if LINUX else "."), DIM)
    say()

    # -- Arch: the system packages ---------------------------------------------------------------------------
    want_pkgs: list[str] = []
    if LINUX and shutil.which("pacman"):
        need = _missing_pacman(PACMAN_NEED)
        if need:
            say(f"  She needs these system packages: {', '.join(need)}")
            want_pkgs += need

    # -- your name -------------------------------------------------------------------------------------------
    name = text("What should she call you?", portable.config_name() if portable.config_name() not in ("", "you") else "")

    # -- brain -----------------------------------------------------------------------------------------------
    items: list[portable.Item] = []
    keep: dict = {}  # saved only once you say yes at the end
    brain = s["brain"]
    have = [it for it in portable.BRAINS if it.installed()]
    if ask("Give her an AI brain (a local model on your GPU)?", True):
        mine = portable.local_models(20)
        opts = [f"{it.label}  {DIM}{portable.gb(it.size)}{' (already here)' if it.installed() else ''}{OFF}\n"
                f"     {DIM}{it.note}{OFF}" for it in portable.BRAINS]
        opts += [f"Use a model already on this PC  {DIM}({len(mine)} found){OFF}"] if mine else []
        start = portable.BRAINS.index(have[0]) if have else 0
        i = pick("Which brain?", opts, start)
        if i < len(portable.BRAINS):
            it = portable.BRAINS[i]
            if not it.installed():
                items.append(it)
            brain = str(ROOT / it.files[0][1])
        else:
            j = pick("Which model?", [f"{p.name}  {DIM}{p.parent}{OFF}" for p in mine], 0)
            brain = str(mine[j])
            keep["my_brains"] = [p for p in s["my_brains"] if p != brain] + [brain]
        # the engine that runs it
        if portable.find_exe("llama-server") is None or force:
            nvidia = portable.has_nvidia()
            eng = portable.ENGINE_GPU[1] if nvidia and ask(
                f"You have an NVIDIA card. Run her brain on CUDA (faster, {portable.gb(portable.ENGINE_GPU[1].size)})?"
                f" No = Vulkan ({portable.gb(portable.ENGINE_GPU[0].size)})", True) else portable.ENGINE_GPU[0]
            if not eng.installed():
                items.append(eng)
    else:
        brain = "none"
        say("  No AI: she still roams, peeks and plays, and answers with short lines of her own.", DIM)

    # -- ears ------------------------------------------------------------------------------------------------
    whisper = ""
    if ask("Talk to her with your mic (her ears, speech to text on your CPU)?", True):
        ears_have = {p.name for p in portable.ears_models()}
        opts = [f"{it.label}  {DIM}{portable.gb(it.size)} - {it.note}"
                f"{' (already here)' if Path(it.files[0][1]).name in ears_have else ''}{OFF}" for it in portable.EARS]
        it = portable.EARS[pick("Which ears?", opts, 2)]
        whisper = Path(it.files[0][1]).name
        if not it.installed():
            items.append(it)
        if LINUX:
            if shutil.which("pacman") and _missing_pacman(PACMAN_EARS):
                want_pkgs += PACMAN_EARS
        elif not portable.ENGINE_EARS.installed():
            items.append(portable.ENGINE_EARS)
        keep["ears"] = s["ears"] if s["ears"] != "off" else "hold"
    else:
        keep["ears"] = "off"

    # -- voice -----------------------------------------------------------------------------------------------
    voice = ask(f"Should she talk out loud (her voice, {portable.gb(portable.VOICE.size)})? No = talking blips", True)
    if voice and not portable.VOICE.installed():
        items.append(portable.VOICE)
    keep["voice"] = voice

    # -- eyes ------------------------------------------------------------------------------------------------
    eyes = ask("Let her look at your screen when you ask her to (her eyes)?", True)
    keep["eyes"] = eyes
    if LINUX and eyes and shutil.which("pacman"):
        want_pkgs += _missing_pacman(PACMAN_EYES)
    if LINUX and shutil.which("pacman") and _missing_pacman(PACMAN_MUSIC) and \
            ask("Let her see what music is playing (playerctl)?", True):
        want_pkgs += PACMAN_MUSIC

    # -- go --------------------------------------------------------------------------------------------------
    say()
    if want_pkgs:
        want_pkgs = list(dict.fromkeys(want_pkgs))
        if ask(f"Install {', '.join(want_pkgs)} with pacman now (asks for your password)?", True):
            _pacman(want_pkgs)
        else:
            say(f"  Later: sudo pacman -S --needed {' '.join(want_pkgs)}", DIM)
    need = sum(it.size for it in items)
    free = shutil.disk_usage(ROOT).free
    if items:
        say(f"  To download: {', '.join(it.label.split('  ')[0] for it in items)}")
        say(f"  {portable.gb(need)} total, {portable.gb(free)} free on this drive", DIM)
        if need >= free:
            say("  Not enough space on this drive. Free some up or move the Capri folder, then run setup again.", PINK)
            return 2
        if not ask("Download now?", True):
            say(f"  Run setup again any time:  {AGAIN}", DIM)
            return 2
        say()
        try:
            portable.download(items, bar)
        except KeyboardInterrupt:
            print()
            say("  Paused. Run it again and it carries on where it stopped.", DIM)
            return 2
        except Exception as e:
            print()
            say(f"  Download failed: {e}", PINK)
            say("  Run it again and it carries on where it stopped.", DIM)
            return 2
        print()
    if name:
        portable.set_config_name(name)
    for k, v in keep.items():
        s.set(k, v)
    s.set("brain", brain)
    if whisper:
        s.set("whisper_model", whisper)
    say()
    say("  All set. Starting Capri...", PINK + BOLD)
    say("  Click her to type, hold Ctrl+1 to talk, right-click her for everything else.", DIM)
    return 0


def main() -> int:
    force = "--setup" in sys.argv
    if not sys.stdin or not sys.stdin.isatty():
        return 0  # no terminal: her menu has the downloads
    if not force and not portable.needs_setup():
        return 0
    try:
        return run(force)
    except KeyboardInterrupt:
        print()
        return 2


if __name__ == "__main__":
    sys.exit(main())
