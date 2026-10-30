"""Her right-click menu, drawn into the artist's glitchy neon door (assets/desk/door): the door opens beside her
(the intro frames, with its sound), the menu is written on its dark inside, submenus open in the same door (with a
back row), and the door closes again (the intro backwards, with its sound) when you pick something or click away. In mini mode the chip sits at the door's left, halfway up, tied to it
by a strip of torn scanlines.

The items come from her normal QMenu, read fresh every time (so whatever the app adds to it shows up here too);
the QMenu itself is still what the tray icon shows.
"""
from __future__ import annotations

import random
import re
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .bubble import sans

DOOR = Path(__file__).resolve().parents[2] / "assets" / "desk" / "door"
CROP = QRectF(90, 0, 476, 640)  # everything drawn in the 640 x 640 frames
INSIDE = QRectF(117, 61, 240, 536)  # the door's dark inside, within CROP
FPS = {"in": 19, "open": 10, "out": 22}  # intro / idle loop / outro (the intro backwards)
MENU_AT = 11  # intro frame where the door reaches full height: the menu's text comes in from here
TEAR = 0.18  # seconds of glitch when a submenu page swaps in
MAX_WIDE = 1.5  # the door may get this much wider than its drawn shape

PINK = QColor(255, 30, 110)
CYAN = QColor(120, 250, 255)
MINT = QColor(52, 245, 160)
WHITE = QColor(246, 240, 250)
DIM = QColor(150, 130, 170)
SHREDS = (PINK, CYAN, MINT, QColor(255, 255, 255))


def _frames(name: str) -> list[QImage]:
    files = sorted((f for f in (DOOR / name).glob("*.png") if re.fullmatch(r"\d+", f.stem)), key=lambda f: int(f.stem))
    return [QImage(str(f)).copy(CROP.toRect()).convertToFormat(QImage.Format_ARGB32_Premultiplied) for f in files]


# shorter names where the menu's own text is too long for the door
SHORT = {"React to videos, chats & what I type": "React to things", "Chatter / react": "Chatter",
         "Vibe to the music": "Vibe to music", "Auto (always listening)": "Always listening",
         "Roam the grid": "Wander around"}


def _label(a) -> str:
    """Menu text without its "  (explanation)" tail, && as &, shortened if it has a short name."""
    t = a.text().split("  (")[0].replace("&&", "&") if a else ""
    return SHORT.get(t, t)


class DoorMenu(QWidget):
    def __init__(self, k: float = 1.0, sfx=None):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.k = max(0.8, min(k, 1.4))
        self.font_ = sans(14 * self.k, QFont.Medium)
        self.fm = QFontMetricsF(self.font_)
        self.row = round(22 * self.k)
        self.sep = round(9 * self.k)
        self.sfx = sfx
        self.raw: dict | None = None
        self.pms: dict[str, list[QPixmap]] = {}
        self.fitted = None
        self.sx = self.sy = 1.0
        self.pad = 0.0  # room on the left for the chip (mini mode)
        self.link = None  # (from x, to x, y) of the glitch strip, window coords
        self.menu = None
        self.stack: list = []  # submenus we've walked into
        self.rows: list[tuple] = []  # (kind, action, rect)
        self.hover = -1
        self.phase = "off"  # in (door opening) | open | out (closing) | off
        self.i = 0  # frame of the current phase
        self.tear_t = -9.0  # when a page swap glitched it
        self.on_closed = None
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self.phase != "off"

    # -- what's on the current page ---------------------------------------------------
    def _page(self):
        return self.stack[-1] if self.stack else self.menu

    def _items(self, menu):
        out = [("back", None)] if self.stack else []
        for a in menu.actions():
            if not a.isVisible():
                continue
            if a.isSeparator():
                if out and out[-1][0] != "sep":
                    out.append(("sep", a))
            else:
                out.append(("sub" if a.menu() else "item", a))
        while out and out[-1][0] == "sep":
            out.pop()
        return out

    def _measure(self, items):
        w = max([self.fm.horizontalAdvance(_label(a) if a else "Back") for _, a in items] + [70 * self.k])
        h = sum(self.sep if kind == "sep" else self.row for kind, _ in items)
        return min(w, 190 * self.k) + 40 * self.k, h  # tick on the left, arrow on the right  # tick box on the left, arrow on the right

    # -- sizing -----------------------------------------------------------------------
    def _fit(self, items):
        if self.raw is None:
            self.raw = {"in": _frames("intro"), "open": _frames("idle")}
        cw, ch = self._measure(items)
        m = 10 * self.k  # breathing room inside the door
        sx, sy = (cw + 2 * m) / INSIDE.width(), (ch + 2 * m) / INSIDE.height()
        sy = max(sy, sx / MAX_WIDE, 0.25)  # too wide for its height: grow taller instead of stretching more
        sx = max(sx, 0.8 * sy)  # and never thinner than a bit under its drawn shape
        if self.fitted is None or abs(self.fitted[0] - sx) > 0.01 or abs(self.fitted[1] - sy) > 0.01:
            dpr = QGuiApplication.primaryScreen().devicePixelRatio()
            w, h = round(CROP.width() * sx * dpr), round(CROP.height() * sy * dpr)
            for name, imgs in self.raw.items():
                self.pms[name] = []
                for img in imgs:
                    pm = QPixmap.fromImage(img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                    pm.setDevicePixelRatio(dpr)
                    self.pms[name].append(pm)
            self.pms["out"] = self.pms["in"][::-1]
            self.fitted = (sx, sy)
        self.sx, self.sy = self.fitted

    def size_for(self, menu) -> tuple[float, float]:
        """The door's size (without pad) for this menu's first page."""
        self.menu, self.stack = menu, []
        menu.aboutToShow.emit()  # let the app tick its toggles and relabel things first
        self._fit(self._items(menu))
        return CROP.width() * self.sx, CROP.height() * self.sy

    def inside(self) -> QRectF:
        return QRectF(self.pad + INSIDE.x() * self.sx, INSIDE.y() * self.sy, INSIDE.width() * self.sx, INSIDE.height() * self.sy)

    def door(self) -> QRectF:
        return QRectF(self.pad, 0, CROP.width() * self.sx, CROP.height() * self.sy)

    def _layout(self):
        items = self._items(self._page())
        r = self.inside()
        h = sum(self.sep if kind == "sep" else self.row for kind, _ in items)
        y = r.top() + max(10 * self.k, (r.height() - h) / 2)
        m = 10 * self.k
        self.rows = []
        for kind, a in items:
            rh = self.sep if kind == "sep" else self.row
            self.rows.append((kind, a, QRectF(r.left() + m, y, r.width() - 2 * m, rh)))
            y += rh
        self.hover = -1

    # -- opening / closing --------------------------------------------------------------
    def open(self, x: float, y: float, pad: float = 0.0, link=None, on_closed=None):
        """Call size_for() first. (x, y) is the window's top-left (pad included)."""
        self.pad, self.link, self.on_closed = pad, link, on_closed
        self.setFixedSize(round(pad + CROP.width() * self.sx), round(CROP.height() * self.sy))
        self.move(round(x), round(y))
        self._layout()
        self._phase("in")
        self.show()
        self.activateWindow()
        if self.sfx:
            self.sfx.play("door_open")

    def close_door(self):
        if self.phase in ("out", "off"):
            return
        at = self.i if self.phase == "in" else len(self.pms["in"]) - 1
        self._phase("out")
        self.i = len(self.pms["out"]) - 1 - at  # from wherever the opening had got to
        for m in [self.menu] + self.stack:
            m.aboutToHide.emit()
        if self.sfx:
            self.sfx.play("door_close")

    def _phase(self, ph):
        self.phase, self.i = ph, 0
        self.timer.start(round(1000 / FPS[ph]))
        self.update()

    def _tick(self):
        clip = self.pms[self.phase]
        if self.i + 1 < len(clip):
            self.i += 1
        elif self.phase == "in":
            return self._phase("open")
        elif self.phase == "open":
            self.i = 0
        else:
            return self._finish()
        self.update()

    def _finish(self):
        self.timer.stop()
        self.phase = "off"
        self.hide()
        if self.on_closed:
            cb, self.on_closed = self.on_closed, None
            cb()

    def hideEvent(self, e):
        """Hidden some other way (focus lost to another window, Windows closing popups...): reset, so the next
        right-click opens it again instead of thinking it's still up."""
        super().hideEvent(e)
        if self.phase != "off":
            self._finish()

    def _go(self, menu):
        """Into a submenu (or back out of one) without closing the door: a quick glitch while the page changes."""
        if menu is None:
            self.stack.pop()
        else:
            menu.aboutToShow.emit()
            self.stack.append(menu)
        old = (self.sx, self.sy, self.pad)
        self._fit(self._items(self._page()))
        if (self.sx, self.sy) != old[:2]:  # this page needs a different door: keep its middle where it was
            mid = self.y() + self.height() / 2
            self.setFixedSize(round(self.pad + CROP.width() * self.sx), round(CROP.height() * self.sy))
            self.move(self.x(), round(mid - self.height() / 2))
            if self.link:
                x0, _, _ = self.link
                self.link = (x0, self.pad + INSIDE.left() * self.sx + 6, self.height() / 2)
        self._layout()
        self.tear_t = time.monotonic()
        self.update()

    # -- input --------------------------------------------------------------------------
    def _row_at(self, pos) -> int:
        for n, (kind, _, r) in enumerate(self.rows):
            if kind != "sep" and r.adjusted(-4, 0, 4, 0).contains(pos):
                return n
        return -1

    def mouseMoveEvent(self, e):
        n = self._row_at(e.position())
        if n != self.hover:
            self.hover = n
            self.update()

    def mousePressEvent(self, e):
        if self.phase in ("out", "off"):
            return
        if not self.door().contains(e.position()) or not self.rect().contains(e.position().toPoint()):
            return self.close_door()  # a click anywhere else closes it (it's a popup: we see those clicks too)
        n = self._row_at(e.position())
        if n >= 0 and e.button() == Qt.LeftButton:
            self._pick(n)

    def _pick(self, n):
        kind, a, _ = self.rows[n]
        if kind == "back":
            return self._go(None)
        if not a.isEnabled():
            return
        if kind == "sub":
            return self._go(a.menu())
        if a.isCheckable():  # toggles stay open so you can flip a few
            a.trigger()
            self.update()
            return
        self.close_door()
        QTimer.singleShot(0, a.trigger)

    def keyPressEvent(self, e):
        k = e.key()
        live = [n for n, (kind, a, _) in enumerate(self.rows) if kind != "sep"]
        if k == Qt.Key_Escape:
            return self._go(None) if self.stack else self.close_door()
        if k in (Qt.Key_Left, Qt.Key_Backspace) and self.stack:
            return self._go(None)
        if k in (Qt.Key_Down, Qt.Key_Up) and live:
            at = live.index(self.hover) if self.hover in live else (-1 if k == Qt.Key_Down else 0)
            self.hover = live[(at + (1 if k == Qt.Key_Down else -1)) % len(live)]
            self.update()
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right, Qt.Key_Space) and self.hover >= 0:
            self._pick(self.hover)

    # -- drawing ------------------------------------------------------------------------
    def _text_glitch(self) -> float | None:
        """How torn the menu text is right now (0 clean .. 1), or None when it isn't shown at all."""
        n = len(self.pms["in"])
        if self.phase == "in":
            if self.i < MENU_AT:
                return None
            return 1 - (self.i - MENU_AT) / max(1, n - 1 - MENU_AT)
        if self.phase == "out":
            return None if self.i > 2 else (self.i + 1) / 3  # gone as soon as the door starts closing
        return 0.0

    def paintEvent(self, _):
        if self.phase == "off" or not self.pms:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.TextAntialiasing)
        clip = self.pms[self.phase]
        tear = max(0.0, 1 - (time.monotonic() - self.tear_t) / TEAR)
        self._paint_door(p, clip[min(self.i, len(clip) - 1)], tear)
        g = self._text_glitch()
        if g is not None:
            g = max(g, tear)
            p.setOpacity(1 - 0.7 * g)
            self._paint_rows(p, g)
            p.setOpacity(1.0)
            if self.link:
                self._paint_link(p)
        if tear > 0:
            QTimer.singleShot(16, self.update)
        p.end()

    def _paint_door(self, p, pm, g):
        d = self.door()
        if g <= 0:
            p.drawPixmap(d.topLeft(), pm)
            return
        # torn: horizontal slices shoved sideways, with pink / cyan ghosts, fading in (or out)
        dpr = pm.devicePixelRatio()
        n = 12
        hh = d.height() / n
        for s in range(n):
            if random.random() < g * 0.35:
                continue  # dropped slice
            dx = random.gauss(0, 28 * g * self.k)
            src = QRectF(0, s * hh * dpr, pm.width(), hh * dpr)
            dst = QRectF(d.left() + dx, d.top() + s * hh, d.width(), hh)
            if random.random() < g:
                p.setOpacity(0.5 * g)
                ghost = random.choice((-1, 1)) * 6 * self.k * g
                p.drawPixmap(dst.translated(ghost, 0), pm, src)
            p.setOpacity(1 - 0.6 * g)
            p.drawPixmap(dst, pm, src)
        p.setOpacity(1.0)
        for _ in range(int(10 * g)):
            c = QColor(random.choice(SHREDS))
            c.setAlpha(200)
            p.fillRect(QRectF(d.left() + random.uniform(0, d.width()), d.top() + random.uniform(0, d.height()),
                              random.uniform(20, 90) * self.k, random.uniform(1, 3) * self.k), c)

    def _paint_rows(self, p, g):
        p.setFont(self.font_)
        k = self.k
        for n, (kind, a, r) in enumerate(self.rows):
            if g > 0:
                r = r.translated(random.gauss(0, 6 * g * k), 0)
            if kind == "sep":
                c = QColor(PINK)
                c.setAlpha(110)
                p.fillRect(QRectF(r.left() + 4 * k, r.center().y(), r.width() - 8 * k, max(1.0, k)), c)
                continue
            hot = n == self.hover
            enabled = kind == "back" or a.isEnabled()
            if hot and enabled:
                if random.random() < 0.06:  # the odd misprint on the highlighted row
                    p.fillRect(r.translated(random.choice((-3, 3)) * k, 0), QColor(120, 250, 255, 120))
                p.fillRect(r, PINK)
            fg = QColor(10, 4, 18) if hot and enabled else (WHITE if enabled else DIM)
            tx = r.left() + 20 * k
            if kind == "back":
                p.setPen(fg if hot else CYAN)
                p.drawText(QRectF(tx, r.top(), r.width(), r.height()), Qt.AlignVCenter, "‹  Back")
                continue
            if a.isCheckable():
                box = QRectF(r.left() + 5 * k, r.center().y() - 4.5 * k, 9 * k, 9 * k)
                p.setRenderHint(QPainter.Antialiasing)
                if a.isChecked():
                    p.setPen(Qt.NoPen)
                    p.setBrush(fg if hot else MINT)
                else:
                    p.setPen(fg if hot else DIM)
                    p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(box, 2.5 * k, 2.5 * k)
                p.setBrush(Qt.NoBrush)
            p.setPen(fg)
            room = r.right() - tx - (14 * k if kind == "sub" else 2 * k)
            text = self.fm.elidedText(_label(a), Qt.ElideRight, room)
            p.drawText(QRectF(tx, r.top(), room, r.height()), Qt.AlignVCenter, text)
            if kind == "sub":
                p.setPen(fg if hot else CYAN)
                p.drawText(QRectF(r.right() - 12 * k, r.top(), 12 * k, r.height()), Qt.AlignVCenter, "›")

    def _paint_link(self, p):
        """Torn scanlines between the chip and the door, new every frame."""
        x0, x1, y = self.link
        u = self.k
        for _ in range(random.randint(6, 11)):
            a = random.uniform(x0, x1 - 10)
            c = QColor(random.choice(SHREDS))
            c.setAlpha(random.randint(140, 235))
            p.fillRect(QRectF(a, y + random.gauss(0, 7 * u), random.uniform(0.25, 1.0) * (x1 - a), random.uniform(1.5, 4) * u), c)
        for _ in range(random.randint(4, 9)):
            c = QColor(random.choice(SHREDS))
            s = random.uniform(2, 4) * u
            p.fillRect(QRectF(random.uniform(x0, x1), y + random.gauss(0, 11 * u), s, s), c)
