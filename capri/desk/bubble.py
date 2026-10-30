"""Her chat box, styled like being on a call with her: a small matte panel with cut corners, her live portrait on the
left (it's her actual current frame, so it blinks and talks), her name with a signal meter and the call timer on top,
what you said as a quiet line, then her reply typing in. Small drawn icons instead of labels; no tail, no glow, one
pink accent. Doubles as the type box when you click her."""
from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLineEdit, QPushButton, QWidget


def chamfer(r: QRectF, c: float) -> QPainterPath:
    """A rectangle with its top-left and bottom-right corners cut off."""
    path = QPainterPath(QPointF(r.left() + c, r.top()))
    path.lineTo(r.right(), r.top())
    path.lineTo(r.right(), r.bottom() - c)
    path.lineTo(r.right() - c, r.bottom())
    path.lineTo(r.left(), r.bottom())
    path.lineTo(r.left(), r.top() + c)
    path.closeSubpath()
    return path


# -- icons, drawn in a size x size box at (x, y) ---------------------------------------------------------------
def icon_signal(p: QPainter, x, y, size, level: float, col: QColor):
    """Four rising bars; `level` 0..1 lights them up."""
    for i in range(4):
        h = size * (0.35 + 0.65 * i / 3)
        c = QColor(col) if level * 4 > i + 0.2 else QColor(255, 255, 255, 40)
        p.fillRect(QRectF(x + i * size * 0.27, y + size - h, size * 0.17, h), c)


def icon_user(p: QPainter, x, y, size, col: QColor):
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawEllipse(QPointF(x + size / 2, y + size * 0.3), size * 0.22, size * 0.22)
    body = QPainterPath(QPointF(x + size * 0.1, y + size))
    body.cubicTo(QPointF(x + size * 0.1, y + size * 0.55), QPointF(x + size * 0.9, y + size * 0.55),
                 QPointF(x + size * 0.9, y + size))
    body.closeSubpath()
    p.drawPath(body)


def icon_mic(p: QPainter, x, y, size, col: QColor):
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawRoundedRect(QRectF(x + size * 0.33, y, size * 0.34, size * 0.62), size * 0.17, size * 0.17)
    p.setPen(QPen(col, max(1.0, size * 0.1)))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(x + size * 0.18, y + size * 0.2, size * 0.64, size * 0.6), 180 * 16, 180 * 16)
    p.drawLine(QPointF(x + size / 2, y + size * 0.8), QPointF(x + size / 2, y + size))


def icon_moon(p: QPainter, x, y, size, col: QColor, bg: QColor):
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawEllipse(QRectF(x + size * 0.1, y + size * 0.1, size * 0.8, size * 0.8))
    p.setBrush(bg)
    p.drawEllipse(QRectF(x + size * 0.35, y, size * 0.7, size * 0.7))


def icon_send(p: QPainter, x, y, size, col: QColor):
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawPolygon([QPointF(x, y + size * 0.1), QPointF(x + size, y + size / 2), QPointF(x, y + size * 0.9),
                   QPointF(x + size * 0.22, y + size / 2)])


class IconButton(QPushButton):
    """A small square button with a drawn icon; pink on hover."""

    def __init__(self, parent, draw, tip: str):
        super().__init__(parent)
        self.draw = draw
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        bg = PINK if self.underMouse() else QColor(38, 32, 48)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawPath(chamfer(r, r.height() * 0.22))
        size = r.height() * 0.46
        self.draw(p, r.center().x() - size / 2, r.center().y() - size / 2, size,
                  QColor(255, 255, 255) if self.underMouse() else MUTED, bg)
        p.end()

FONT_FILE = Path(__file__).resolve().parents[2] / "assets" / "desk" / "fonts" / "ShareTechMono-Regular.ttf"
SANS_FILE = Path("C:/Windows/Fonts/bahnschrift.ttf")  # ships with Windows 10/11; Segoe UI if it's missing
GLYPHS = "#%&@$*+=<>/\\|01"

PANEL = QColor(17, 14, 22, 236)
PANEL_HI = QColor(28, 23, 36, 236)
EDGE = QColor(255, 255, 255, 26)
PINK = QColor(255, 46, 112)
GREEN = QColor(43, 255, 154)
CYAN = QColor(120, 250, 255)
TEXT = QColor(242, 238, 247)
MUTED = QColor(150, 140, 165)
FAINT = QColor(95, 88, 108)

_family = None
_sans = None


def mono(px: float) -> QFont:
    global _family
    if _family is None:
        fid = QFontDatabase.addApplicationFont(str(FONT_FILE))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _family = fams[0] if fams else "Consolas"
    f = QFont(_family)
    f.setPixelSize(max(8, round(px)))
    return f


def sans(px: float, weight=QFont.Normal) -> QFont:
    global _sans
    if _sans is None:
        fid = QFontDatabase.addApplicationFont(str(SANS_FILE)) if SANS_FILE.exists() else -1
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _sans = fams[0] if fams else ("Segoe UI" if sys.platform == "win32" else "Noto Sans")
    f = QFont(_sans)
    f.setPixelSize(max(8, round(px)))
    f.setWeight(weight)
    return f


class Bubble(QWidget):
    sent = Signal(str)
    typed = Signal(str)  # each newly revealed letter (the talking blips hang off this)
    nap = Signal()

    def __init__(self, scale: float):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.s = s = scale
        self.pad = 12 * s
        self.tail = 0.0  # no pointer: the portrait says who's talking
        self.cam = 62 * s  # portrait size
        self.inner_w = 262 * s  # text column
        self.font = sans(15.5 * s)
        self.small = sans(12 * s)
        self.label = mono(10.5 * s)
        self.text = ""
        self.user = ""
        self.shown_chars = 0.0
        self.cps = 38.0
        self.pauses, self.pause_until = False, 0.0
        self.opened_at = 0.0
        self.closing_at = 0.0
        self.hold_until = 0.0
        self.call_start = 0.0  # the "call" timer: keeps running while you two keep talking
        self.last_seen = -1e9
        self.tail_x = 0.5
        self.tail_up = False
        self.typing = False
        self.thinking = False
        self.hearing = False  # the talk key is held / she hears you: show "listening" with a mic meter
        self.mic_level = 0.0
        self.portrait = None  # set by Capri: () -> QPixmap of her face right now (None = keep the last one)
        self._face: QPixmap | None = None

        self.edit = QLineEdit(self)
        self.edit.setFont(sans(14 * s))
        self.edit.setPlaceholderText("message capri")
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: rgba(255,255,255,10); color: rgb(242,238,247); border: none;"
            f" border-left: {max(1, round(2 * s))}px solid rgb(255,46,112); padding: {round(5 * s)}px {round(8 * s)}px;"
            f" selection-background-color: rgb(255,46,112); }}"
            f"QLineEdit:focus {{ background: rgba(255,255,255,16); }}")
        self.edit.returnPressed.connect(self._send)
        self.edit.hide()
        self.send_btn = IconButton(self, lambda p, x, y, z, col, bg: icon_send(p, x, y, z, col), "Send")
        self.send_btn.clicked.connect(self._send)
        self.send_btn.hide()
        self.nap_btn = IconButton(self, icon_moon, "Go mini")
        self.nap_btn.clicked.connect(lambda: (self.close_bubble(), self.nap.emit()))
        self.nap_btn.hide()
        self.edit.installEventFilter(self)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # -- api ----------------------------------------------------------------
    def say(self, text: str, user: str = "", secs: float | None = None, cps: float | None = None):
        """Show a line. With `secs` (how long her voice runs) it types in step with the audio and stays up
        until release(); without, it types at reading pace and closes on its own."""
        self.text, self.user = text, user
        self.thinking = False
        self.shown_chars = 0.0
        self._opening()
        self.pauses = cps is not None  # blip voice: little beats at commas and full stops
        self.pause_until = 0.0
        if cps:
            self.cps = cps
            self.hold_until = time.monotonic() + 3600
        elif secs:
            self.cps = max(8.0, len(text) / max(0.3, secs * 0.92))
            self.hold_until = time.monotonic() + 3600
        else:
            self.cps = 38.0
            self.hold_until = time.monotonic() + len(text) / self.cps + min(9.0, 2.6 + len(text) * 0.045)
        self._layout()
        self.show()
        self.raise_()

    def append(self, text: str):
        """The next sentence of a reply that's still being written: keep typing straight on."""
        self.text = (self.text + " " + text).strip()
        self._layout()

    def typed_all(self) -> bool:
        return self.shown_chars >= len(self.text) and time.monotonic() >= self.pause_until

    def release(self, after: float):
        """Her voice finished: keep the line up a little longer, then close."""
        self.shown_chars = len(self.text)
        if not self.typing:
            self.hold_until = time.monotonic() + after

    def listen(self, on: bool):
        if on:
            self.hearing = True
            self._opening()
            self.user, self.text, self.thinking = "", "", True
            self.hold_until = time.monotonic() + 3600
            self._layout()
            self.show()
            self.raise_()
        else:
            self.hearing = False
            self.hold_until = time.monotonic() + 4  # nothing usable heard: close soon (think() extends it)

    def think(self, user: str):
        self.hearing = False
        self.user, self.text, self.thinking = user, "", True
        self.closing_at = 0.0
        self.hold_until = time.monotonic() + 30
        self._layout()
        self.show()

    def open_input(self):
        self.typing = True
        if not self.isVisible() or self.closing_at:
            self.text, self.user = "", ""
        self._opening()
        self.hold_until = time.monotonic() + 3600
        self.edit.show()
        self.send_btn.show()
        self.nap_btn.show()
        self._layout()
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def close_bubble(self):
        if self.isVisible() and not self.closing_at:
            self.closing_at = time.monotonic()
            self.typing = False
            self.edit.hide()
            self.send_btn.hide()
            self.nap_btn.hide()

    def talking(self) -> bool:
        return self.isVisible() and not self.closing_at and self.text and self.shown_chars < len(self.text)

    def place(self, head_x: float, head_y: float, screen_rect):
        """Above her head, a little to the side, always fully on screen (below her head if there's no room)."""
        w, h = self.width(), self.height()
        x = head_x - w * 0.3
        y = head_y - h - 4 * self.s
        self.tail_up = False
        if y < screen_rect.top() + 4:
            y = head_y + 30 * self.s
            self.tail_up = True
        x = max(screen_rect.left() + 6, min(x, screen_rect.right() - w - 6))
        self.move(round(x), round(y))

    # -- internals ------------------------------------------------------------
    def _opening(self):
        now = time.monotonic()
        if not self.isVisible() or self.closing_at:
            self.opened_at = now
            if now - self.last_seen > 60:  # a new "call" after a minute of silence
                self.call_start = now
        self.closing_at = 0.0

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key_Escape:
            self.close_bubble()
            return True
        return False

    def _send(self):
        line = self.edit.text().strip()
        self.edit.clear()
        if not line:
            return
        self.typing = False
        self.edit.hide()
        self.send_btn.hide()
        self.nap_btn.hide()
        self.sent.emit(line)

    def _lines(self, text, font, width):
        fm = QFontMetricsF(font)
        out, cur = [], ""
        for word in text.split():
            trial = (cur + " " + word).strip()
            if fm.horizontalAdvance(trial) <= width or not cur:
                cur = trial
            else:
                out.append(cur)
                cur = word
        if cur:
            out.append(cur)
        return out

    def _you_lines(self):
        return self._lines(self.user, self.small, self.inner_w - 40 * self.s)

    def _layout(self):
        s, pad = self.s, self.pad
        fm, sm = QFontMetricsF(self.font), QFontMetricsF(self.small)
        h = pad + 18 * s  # name + timer row
        if self.user:
            h += len(self._you_lines()) * sm.lineSpacing() + 10 * s
        body = self.text if self.text else ("..." if self.thinking else "")
        if body:
            h += len(self._lines(body, self.font, self.inner_w)) * fm.lineSpacing()
        if self.typing:
            x = pad + self.cam + 12 * s
            if not body and not self.user:  # just the message field: it sits beside her portrait
                h = pad + 26 * s
            b = 30 * s
            self.edit.setGeometry(round(x), round(h + 2 * s), round(self.inner_w - 2 * b - 8 * s), round(b))
            self.send_btn.setGeometry(round(x + self.inner_w - 2 * b - 4 * s), round(h + 2 * s), round(b), round(b))
            self.nap_btn.setGeometry(round(x + self.inner_w - b), round(h + 2 * s), round(b), round(b))
            h += 38 * s
        h = max(h, pad + self.cam + 2 * s) + pad  # never shorter than her portrait
        self.panel_h = h
        self.panel_w = pad + self.cam + 12 * s + self.inner_w + pad
        self.setFixedSize(round(self.panel_w + 2), round(h + 2))
        self.update()

    @staticmethod
    def pace(text: str, cps: float) -> float:
        """Seconds the blip voice takes to type `text` at `cps`, beats at punctuation included."""
        return len(text) / cps + 0.14 * sum(text.count(c) for c in ",;") + 0.32 * sum(text.count(c) for c in ".!?")

    def _reveal(self, now: float):
        if now < self.pause_until:
            return
        before = int(self.shown_chars)
        self.shown_chars = min(len(self.text), self.shown_chars + self.cps * 0.016)
        after = int(self.shown_chars)
        new = self.text[before:after]
        if not new:
            return
        letters = [c for c in new if c.isalnum()]
        if letters:
            self.typed.emit(letters[-1])
        if self.pauses and new[-1] in ",;.!?" and after < len(self.text):
            self.pause_until = now + (0.14 if new[-1] in ",;" else 0.32)

    def _tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        self.last_seen = now
        if self.text and self.shown_chars < len(self.text):
            self._reveal(now)
        if self.closing_at and now - self.closing_at > 0.18:
            self.closing_at = 0.0
            self.hide()
            return
        if not self.typing and not self.thinking and now > self.hold_until:
            self.close_bubble()
        self.update()

    # -- drawing ----------------------------------------------------------------
    def paintEvent(self, _):
        now = time.monotonic()
        s, pad = self.s, self.pad
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.panel_w, self.panel_h

        # open: fades in and settles up a few pixels; close: fades out. That's all.
        if self.closing_at:
            v = max(0.0, 1 - (now - self.closing_at) / 0.18)
        else:
            v = min(1.0, (now - self.opened_at) / 0.2)
        e = 1 - (1 - v) ** 3
        p.setOpacity(e)
        p.translate(1, 1 + (1 - e) * 8 * s)

        box = chamfer(QRectF(0, 0, w, h), 10 * s)
        p.setPen(Qt.NoPen)
        p.setBrush(PANEL)
        p.drawPath(box)
        p.save()
        p.setClipPath(box)
        p.fillRect(QRectF(0, 0, w, 26 * s), PANEL_HI)  # a slightly lighter strip behind the name row
        p.restore()
        p.setPen(QPen(EDGE, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(box)

        self._cam(p, QRectF(pad, pad, self.cam, self.cam), now)

        x = pad + self.cam + 12 * s
        # name row: Capri, then on the right her signal meter (live while she talks or hears you) and the call timer
        p.setFont(sans(13.5 * s, QFont.DemiBold))
        p.setPen(TEXT)
        top = pad + 12 * s
        p.drawText(QPointF(x, top), "CAPRI")
        secs = int(now - self.call_start)
        p.setFont(self.label)
        p.setPen(FAINT)
        meta = f"{secs // 60:02d}:{secs % 60:02d}"
        mw = QFontMetricsF(self.label).horizontalAdvance(meta)
        p.drawText(QPointF(x + self.inner_w - mw, top), meta)
        if self.hearing:
            level, col = min(1.0, self.mic_level * 2.2), GREEN
        elif self.talking():
            level, col = 0.5 + 0.5 * abs(math.sin(now * 7)), PINK
        else:
            level, col = 1.0, MUTED
        icon_signal(p, x + self.inner_w - mw - 18 * s, top - 9 * s, 10 * s, level, col)

        y = top + 10 * s
        sm, fm = QFontMetricsF(self.small), QFontMetricsF(self.font)
        if self.user:  # what you said: a quiet line with a "you" label
            lines = self._you_lines()
            icon_user(p, x + 2 * s, y + sm.ascent() - 10 * s, 10 * s, FAINT)
            p.setFont(self.small)
            p.setPen(MUTED)
            for line in lines:
                p.drawText(QPointF(x + 20 * s, y + sm.ascent()), line)
                y += sm.lineSpacing()
            y += 6 * s
            p.fillRect(QRectF(x, y - 2 * s, self.inner_w, 1), QColor(255, 255, 255, 18))
            y += 4 * s
        p.setFont(self.font)
        if self.thinking and self.hearing:
            icon_mic(p, x, y + fm.ascent() - 13 * s, 13 * s, GREEN)
            p.setPen(MUTED)
            p.drawText(QPointF(x + 20 * s, y + fm.ascent()), "go ahead, I'm listening")
        elif self.thinking:  # slanted segments filling in turn, like a loading strip
            p.setPen(Qt.NoPen)
            for i in range(6):
                b = max(0.0, math.sin(now * 5 - i * 0.55))
                c = QColor(PINK if b > 0.6 else MUTED)
                c.setAlphaF(0.25 + 0.75 * b)
                p.setBrush(c)
                bx, by = x + i * 10 * s, y + fm.ascent() * 0.25
                p.drawPolygon([QPointF(bx + 4 * s, by), QPointF(bx + 9 * s, by), QPointF(bx + 5 * s, by + 10 * s),
                               QPointF(bx, by + 10 * s)])
        elif self.text:
            left = int(self.shown_chars)
            for line in self._lines(self.text, self.font, self.inner_w):
                shown = line[:max(0, left)]
                rest = line[len(shown):]
                p.setPen(TEXT)
                p.drawText(QPointF(x, y + fm.ascent()), shown)
                if rest and left >= 0:  # one or two letters still decoding at the edge: her one tiny glitch
                    p.setPen(PINK)
                    p.drawText(QPointF(x + fm.horizontalAdvance(shown), y + fm.ascent()),
                               "".join(random.choice(GLYPHS) for _ in rest[:2]))
                left -= len(line) + 1
                y += fm.lineSpacing()
        p.end()

    def _cam(self, p: QPainter, r: QRectF, now: float):
        """Her portrait, like a video tile: her live frame, a voice meter along the bottom while she talks."""
        s = self.s
        face = self.portrait() if self.portrait else None
        if face is not None and not face.isNull():
            self._face = face
        clip = chamfer(r, 8 * s)
        p.save()
        p.setClipPath(clip)
        p.fillRect(r, QColor(36, 22, 44))
        p.fillRect(QRectF(r.left(), r.center().y(), r.width(), r.height() / 2), QColor(28, 18, 36))
        if self._face is not None:
            p.drawPixmap(r, self._face, QRectF(self._face.rect()))
        # voice meter: five thin bars at the bottom edge, only while she talks or hears you
        talking = self.talking()
        if talking or self.hearing:
            p.fillRect(QRectF(r.left(), r.bottom() - 11 * s, r.width(), 11 * s), QColor(0, 0, 0, 120))
            for i in range(5):
                if self.hearing:
                    lvl = min(1.0, self.mic_level * 1.8) * (0.6 + 0.4 * math.sin(now * 17 + i))
                else:
                    lvl = 0.3 + 0.7 * abs(math.sin(now * (8 + i * 1.9) + i * 1.3))
                bh = max(1.5 * s, 7 * s * lvl)
                p.fillRect(QRectF(r.center().x() - 11 * s + i * 4.6 * s, r.bottom() - 2.5 * s - bh, 2.4 * s, bh),
                           GREEN if self.hearing else PINK)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(clip)
        p.fillRect(QRectF(r.left() - 1, r.top() + 8 * s, 2 * s, r.height() - 16 * s), PINK)  # the one accent
