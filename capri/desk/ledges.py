"""Places she can stand or sit: the top edges of open windows, desktop icons, and the taskbar line.

Everything comes back in Qt's logical pixels. Win32 hands out physical pixels (Qt makes the process
per-monitor DPI aware), so each rect is mapped through the monitor it sits on.
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

WIN = sys.platform == "win32"


@dataclass
class Ledge:
    kind: str  # "window" | "icon" | "floor" | "peek" (a screen edge she leans out of)
    left: float
    right: float
    y: float
    hwnd: int = 0
    rect: QRect = field(default_factory=QRect)  # window / icon rect (logical)

    @property
    def key(self):
        return (self.kind, self.hwnd) if self.kind == "window" else (self.kind, self.rect.x(), self.rect.y())

    def holds(self, x: float) -> bool:
        return self.left <= x <= self.right


ZOOMED = 0  # how many maximized app windows the last find() saw (no top edge to sit on: they fill the screen)
FULL = False  # video mode: the taskbar is hidden, so the floor is the very bottom of the screen


def work_area(scr) -> QRect:
    return scr.geometry() if FULL else scr.availableGeometry()


def floors() -> list[Ledge]:
    out = []
    for scr in QGuiApplication.screens():
        g = work_area(scr)
        out.append(Ledge("floor", g.left(), g.right(), g.bottom() + 1, rect=g))
    return out


def _open(left, right, y, above):
    """The parts of [left, right] at height y that no window above is covering."""
    spans = [(left, right)]
    for c in above:
        if not (c.top() <= y <= c.bottom()):
            continue
        nxt = []
        for a, b in spans:
            if c.right() < a or c.left() > b:
                nxt.append((a, b))
                continue
            if c.left() > a:
                nxt.append((a, c.left() - 1))
            if c.right() < b:
                nxt.append((c.right() + 1, b))
        spans = nxt
    return spans


def _native_to_logical(l, t, r, b) -> QRect:
    """Qt keeps each screen's top-left in device pixels and scales the size, so map through the screen it's on."""
    cx, cy = (l + r) / 2, (t + b) / 2
    for scr in QGuiApplication.screens():
        g, dpr = scr.geometry(), scr.devicePixelRatio()
        if g.x() <= cx < g.x() + g.width() * dpr and g.y() <= cy < g.y() + g.height() * dpr:
            return QRect(g.x() + round((l - g.x()) / dpr), g.y() + round((t - g.y()) / dpr),
                         round((r - l) / dpr), round((b - t) / dpr))
    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
    return QRect(round(l / dpr), round(t / dpr), round((r - l) / dpr), round((b - t) / dpr))


if sys.platform.startswith("linux"):  # X11 windows (on Wayland: the X11 / XWayland ones)
    from .. import linux as _lx

    _NOSEAT = {"_NET_WM_STATE_FULLSCREEN", "_NET_WM_STATE_SHADED"}

    def _seat_ok(rect: QRect, states) -> bool:
        if states & _NOSEAT or {"_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"} <= states:
            return False
        if rect.width() < 120 or rect.height() < 60:
            return False
        scr = QGuiApplication.screenAt(rect.center())
        return not (scr and rect.contains(scr.geometry()))

    def window_rect(hwnd) -> QRect | None:
        hit = _lx.window_box(hwnd)
        return _native_to_logical(*hit[0]) if hit else None

    def find(skip=(), with_icons=True, now=0.0) -> list[Ledge]:
        out: list[Ledge] = []
        above: list[QRect] = []
        skip = set(skip)
        for wid, box, _, states in _lx.windows():  # top of the stack first
            if wid in skip:
                continue
            rect = _native_to_logical(*box)
            if _seat_ok(rect, states):
                for a, b in _open(rect.left(), rect.right(), rect.top(), above):
                    if b - a >= 40:
                        out.append(Ledge("window", a, b, rect.top(), wid, rect))
            above.append(rect)
        return out + floors()
elif not WIN:  # keeps her usable (floor only) anywhere else
    def find(skip=(), with_icons=True, now=0.0) -> list[Ledge]:
        return floors()

    def window_rect(hwnd):
        return None
else:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    dwmapi = ctypes.windll.dwmapi
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    kernel32.VirtualAllocEx.restype = ctypes.c_void_p
    kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    SHELL = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "#32768", "tooltips_class32",
             "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland"}
    _ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _class(hwnd) -> str:
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, buf, 128)
        return buf.value

    def _phys_rect(hwnd):
        r = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:  # extended frame bounds
            if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
                return None
        return r.left, r.top, r.right, r.bottom

    def _monitors():
        """(device name, physical rect) per monitor, to line Win32 up with QScreen."""
        out = []
        import win32api  # pywin32 ships with the runtime

        for hmon, _, _ in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(hmon)
            out.append((info["Device"], info["Monitor"]))
        return out

    _MONS = None

    def to_logical(l, t, r, b) -> QRect:
        global _MONS
        if _MONS is None:
            try:
                _MONS = _monitors()
            except Exception:
                _MONS = []
        cx, cy = (l + r) // 2, (t + b) // 2
        screens = {s.name(): s for s in QGuiApplication.screens()}
        best = None
        for name, (ml, mt, mr, mb) in _MONS:
            if ml <= cx < mr and mt <= cy < mb and name in screens:
                best = (screens[name], ml, mt)
                break
        if best is None:  # off every monitor: use the primary's mapping
            scr = QGuiApplication.primaryScreen()
            dpr = scr.devicePixelRatio()
            return QRect(round(l / dpr), round(t / dpr), round((r - l) / dpr), round((b - t) / dpr))
        scr, ml, mt = best
        dpr = scr.devicePixelRatio()
        g = scr.geometry()
        return QRect(g.x() + round((l - ml) / dpr), g.y() + round((t - mt) / dpr),
                     round((r - l) / dpr), round((b - t) / dpr))

    def _showing(hwnd):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None
        cloaked = ctypes.c_int(0)
        if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
            return None
        ex = user32.GetWindowLongW(hwnd, -20)
        if ex & 0x20 or (ex & 0x08080000) == 0x08080000:  # click-through overlays, no-activate layered junk
            return None
        if _class(hwnd) in SHELL:
            return None
        r = _phys_rect(hwnd)
        if not r or r[2] - r[0] <= 0 or r[3] - r[1] <= 0:
            return None
        return r

    def _seatable(hwnd, rect: QRect) -> bool:
        ex = user32.GetWindowLongW(hwnd, -20)
        if ex & 0x80 and not ex & 0x40000:  # tool windows that aren't app windows (menus, popups)
            return False
        if user32.IsZoomed(hwnd) or rect.width() < 120 or rect.height() < 60:
            return False
        scr = QGuiApplication.screenAt(rect.center())
        return not (scr and rect.contains(scr.geometry()))  # fullscreen apps have no top edge to sit on

    def window_rect(hwnd) -> QRect | None:
        """Live logical rect of a window she's sitting on, or None once it's gone / hidden."""
        if not user32.IsWindow(hwnd):
            return None
        r = _showing(hwnd)
        return to_logical(*r) if r else None

    _ME = kernel32.GetCurrentProcessId()

    def _mine(hwnd) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == _ME

    def _windows(skip):
        found = []

        def visit(hwnd, _):
            # never her own windows (her menu's door, the chat box, effects...): sitting on them, or having one
            # cover her seat, dropped her off whatever she was on
            if hwnd not in skip and not _mine(hwnd):
                r = _showing(hwnd)
                if r:
                    rect = to_logical(*r)
                    found.append((hwnd, rect, _seatable(hwnd, rect)))
            return True

        user32.EnumWindows(_ENUM(visit), 0)
        return found

    def _desktop_list():
        view = user32.FindWindowExW(user32.FindWindowW("Progman", None), None, "SHELLDLL_DefView", None)
        if not view:
            hit = []

            def visit(hwnd, _):
                if _class(hwnd) == "WorkerW":
                    v = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
                    if v:
                        hit.append(v)
                        return False
                return True

            user32.EnumWindows(_ENUM(visit), 0)
            view = hit[0] if hit else None
        return user32.FindWindowExW(view, None, "SysListView32", None) if view else None

    def icons() -> list[QRect]:
        """Desktop icon rects: asks Explorer's list view, through a 16-byte buffer in its process."""
        lv = _desktop_list()
        if not lv or not user32.IsWindowVisible(lv):
            return []
        count = user32.SendMessageW(lv, 0x1004, 0, 0)  # LVM_GETITEMCOUNT
        if count <= 0:
            return []
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(lv, ctypes.byref(pid))
        proc = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020 | 0x0400, False, pid.value)
        if not proc:
            return []
        out = []
        buf = kernel32.VirtualAllocEx(proc, None, 16, 0x1000 | 0x2000, 0x04)
        try:
            if not buf:
                return []
            for i in range(min(count, 400)):
                rc = wintypes.RECT(1, 0, 0, 0)  # left = LVIR_ICON
                kernel32.WriteProcessMemory(proc, buf, ctypes.byref(rc), 16, None)
                if not user32.SendMessageW(lv, 0x100E, i, buf):  # LVM_GETITEMRECT
                    continue
                kernel32.ReadProcessMemory(proc, buf, ctypes.byref(rc), 16, None)
                pts = (wintypes.POINT * 2)((rc.left, rc.top), (rc.right, rc.bottom))
                user32.MapWindowPoints(lv, None, pts, 2)
                r = to_logical(pts[0].x, pts[0].y, pts[1].x, pts[1].y)
                if r.width() >= 16 and r.height() >= 16:
                    out.append(r)
        finally:
            if buf:
                kernel32.VirtualFreeEx(proc, buf, 0, 0x8000)
            kernel32.CloseHandle(proc)
        return out

    _icon_cache: tuple[float, list] = (-1e9, [])

    def find(skip=(), with_icons=True, now=0.0) -> list[Ledge]:
        global _icon_cache, ZOOMED
        out: list[Ledge] = []
        above: list[QRect] = []
        ZOOMED = 0
        for hwnd, rect, seat in _windows(set(skip)):  # EnumWindows walks top of the z-order down
            ZOOMED += bool(user32.IsZoomed(hwnd))
            if seat:
                for a, b in _open(rect.left(), rect.right(), rect.top(), above):
                    if b - a >= 40:
                        out.append(Ledge("window", a, b, rect.top(), hwnd, rect))
            above.append(rect)
        if with_icons:
            if now - _icon_cache[0] > 2.0:
                try:
                    _icon_cache = (now, icons())
                except Exception:
                    _icon_cache = (now, [])
            for r in _icon_cache[1]:
                for a, b in _open(r.left(), r.right(), r.top() + 2, above):
                    if b - a >= 24:
                        out.append(Ledge("icon", a, b, r.top() + 2, rect=r))
        return out + floors()
