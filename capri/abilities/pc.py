"""PC controls: volume, mute, screenshots, locking, shutting down later (and cancelling it), sleep, and tidying old
files out of Downloads into the Recycle Bin. Shutdown, sleep and the Downloads clean-up only run after you say yes."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _key(vk: int, times: int = 1) -> None:
    import ctypes

    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.01)


VK_MUTE, VK_DOWN, VK_UP = 0xAD, 0xAE, 0xAF


def volume(action: str, amount: int | None = None) -> str:
    """action: up | down | set | mute | unmute. amount: percent (each volume key press is 2%)."""
    if sys.platform != "win32":
        from .. import linux

        return linux.volume(action, amount) if hasattr(linux, "volume") else "volume control isn't set up on Linux yet"
    if action == "mute" or action == "unmute":
        _key(VK_MUTE)
        return "toggled mute"
    if action == "set" and amount is not None:
        _key(VK_DOWN, 50)  # all the way down, then up to the level asked for
        _key(VK_UP, max(0, min(100, amount)) // 2)
        return f"set the volume to {max(0, min(100, amount))}%"
    step = amount if amount else 10
    _key(VK_UP if action == "up" else VK_DOWN, max(1, step // 2))
    return f"turned the volume {action} {step}%"


def screenshot() -> Path:
    """The whole screen (every monitor) to Pictures/Capri, opened so you can see it."""
    from datetime import datetime

    from PIL import ImageGrab

    folder = Path.home() / "Pictures" / "Capri"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / datetime.now().strftime("Screenshot %Y-%m-%d %H.%M.%S.png")
    if sys.platform.startswith("linux"):
        from .. import linux

        img = linux.grab_screen()
        if img is None:
            raise RuntimeError("no screenshot tool")
        img.save(path)
    else:
        ImageGrab.grab(all_screens=True).save(path)
    return path


def lock() -> str:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.LockWorkStation()
        return "locked the PC"
    subprocess.Popen(["loginctl", "lock-session"])
    return "locked the PC"


def shutdown(seconds: int) -> str:
    seconds = max(30, int(seconds))
    if sys.platform == "win32":
        subprocess.run(["shutdown", "/s", "/t", str(seconds)], creationflags=_NO_WINDOW)
    else:
        subprocess.run(["shutdown", "-h", f"+{max(1, seconds // 60)}"])
    return f"the PC shuts down in {seconds // 60} minutes"


def cancel_shutdown() -> str:
    if sys.platform == "win32":
        r = subprocess.run(["shutdown", "/a"], capture_output=True, creationflags=_NO_WINDOW)
        return "cancelled the shutdown" if r.returncode == 0 else "there was no shutdown to cancel"
    subprocess.run(["shutdown", "-c"])
    return "cancelled the shutdown"


def sleep_pc() -> str:
    if sys.platform == "win32":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=_NO_WINDOW)
    else:
        subprocess.Popen(["systemctl", "suspend"])
    return "put the PC to sleep"


def old_downloads(days: int = 30) -> list[Path]:
    """Files in Downloads you haven't touched in `days` days (folders left alone)."""
    folder = Path.home() / "Downloads"
    cutoff = time.time() - days * 86400
    try:
        return [p for p in folder.iterdir() if p.is_file() and p.stat().st_mtime < cutoff]
    except OSError:
        return []


def recycle(paths: list[Path]) -> int:
    """Into the Recycle Bin (you can still restore them from there), never deleted for good."""
    if not paths:
        return 0
    if sys.platform != "win32":
        import shutil

        trash = Path.home() / ".local/share/Trash/files"
        trash.mkdir(parents=True, exist_ok=True)
        for p in paths:
            shutil.move(str(p), trash / p.name)
        return len(paths)
    # the shell's own "delete to Recycle Bin", one call for all of them
    script = ("Add-Type -AssemblyName Microsoft.VisualBasic; $n=0; foreach ($f in $input) { try { "
              "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($f, 'OnlyErrorDialogs', 'SendToRecycleBin'); "
              "$n++ } catch {} }; $n")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], input="\n".join(str(p) for p in paths),
                       capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=300)
    try:
        return int((r.stdout or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def open_path(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            from .. import linux

            linux.open_path(str(path))
    except Exception as e:
        print(f"[capri] couldn't open {path}: {e}")
