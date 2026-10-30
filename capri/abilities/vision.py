"""Her eyes: which window you're in, and a quick read of what's in it (Windows' built-in OCR, on the CPU;
on Linux, tesseract).
Nothing is saved. Logins, banking, password managers and private windows are never read."""
from __future__ import annotations

import re
import sys

PRIVATE = re.compile(r"password|passwort|1password|bitwarden|keepass|lastpass|bank|paypal|sign[ -]?in|log[ -]?in|"
                     r"incognito|inprivate|private (?:browsing|window)|authenticator|wallet", re.I)
BROWSER = re.compile(r"\s-\s(?:Brave|Google Chrome|Microsoft​? Edge|Mozilla Firefox|Opera|Vivaldi)$", re.I)
YOUTUBE = re.compile(r"^(?:\(\d+\)\s*)?(?P<song>.+?)\s-\sYouTube(?:\s-\s.*)?$", re.I)


def active_window_title() -> str:
    if sys.platform != "win32":
        from .. import linux

        return linux.active_title() if sys.platform.startswith("linux") else ""
    import ctypes

    u = ctypes.windll.user32
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(u.GetForegroundWindow(), buf, 512)
    return buf.value


def window_titles() -> list[str]:
    """Titles of every visible top-level window (to spot a YouTube tab playing behind something else)."""
    if sys.platform != "win32":
        from .. import linux

        return linux.titles() if sys.platform.startswith("linux") else []
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(h, _):
        if u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(512)
            if u.GetWindowTextW(h, buf, 512):
                out.append(buf.value)
        return True

    u.EnumWindows(visit, 0)
    return out


def youtube_song(titles: list[str]) -> str:
    """'(3) Kavinsky - Nightcall - YouTube - Brave' -> 'Kavinsky - Nightcall' (first YouTube window found)."""
    for t in titles:
        m = YOUTUBE.match(BROWSER.sub("", t.strip()))
        if m and m.group("song").strip().lower() != "youtube":
            return re.sub(r"\s*[(\[](?:official|lyrics?|audio|video|hd|4k|mv|music video)[^)\]]*[)\]]", "", m.group("song"), flags=re.I).strip()
    return ""


def foreground_rect() -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        if sys.platform.startswith("linux"):
            from .. import linux

            return linux.active_box()
        return None
    import ctypes
    import ctypes.wintypes as wt

    r = wt.RECT()
    if not ctypes.windll.user32.GetWindowRect(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def glance(max_chars: int = 700) -> tuple[str, str]:
    """(window title, text read off it). Empty text for private windows or when OCR isn't available."""
    title = active_window_title().strip()
    if sys.platform.startswith("linux"):  # on Wayland the title can be blank (a native window): still a glance
        if PRIVATE.search(title):
            return title, ""
        try:
            from .. import linux

            img = linux.grab_active()
            if img is None or img.width < 80 or img.height < 60:
                return title, ""
            img = img.crop((0, min(110 if BROWSER.search(title) else 0, img.height // 3), img.width, img.height))
            lines = [ln for ln in linux.ocr(img) if len(ln) > 2 and re.search(r"[A-Za-z]{3}", ln)]
            return title, " | ".join(lines)[:max_chars]
        except Exception as e:
            print(f"[capri] eyes: {e}")
            return title, ""
    if not title or PRIVATE.search(title):
        return title, ""
    try:
        import winocr
        from PIL import ImageGrab

        r = foreground_rect()
        if not r or r[2] - r[0] < 80 or r[3] - r[1] < 60:
            return title, ""
        top = r[1] + (110 if BROWSER.search(title) else 30)  # skip tabs / address bar / title bar
        img = ImageGrab.grab(bbox=(r[0], top, r[2], r[3]), all_screens=True)
        if img.width > 1600:
            img = img.resize((1600, round(img.height * 1600 / img.width)))
        res = winocr.recognize_pil_sync(img, "en")
        lines = [ln["text"].strip() for ln in res.get("lines", []) if len(ln["text"].strip()) > 2]
        lines = [ln for ln in lines if re.search(r"[A-Za-z]{3}", ln)]  # drop timestamps, counters, glyph junk
        return title, " | ".join(lines)[:max_chars]
    except Exception as e:
        print(f"[capri] eyes: {e}")
        return title, ""
