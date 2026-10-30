"""Her mini form (her naps, and "Go mini" from the menu): a tiny mint glitch-sprite with one curly pink strand of her hair for an
antenna, sleepy eyes, a violet misprint shadow and a little hover flame. It floats in the bottom-left corner;
drag it anywhere, click it to wake her up.
"""
from __future__ import annotations

import math
import random
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

MINT = QColor(52, 245, 160)
MINT_HI = QColor(150, 255, 205)
VIOLET = QColor(110, 50, 255)
PINK = QColor(255, 30, 110)
INK = QColor(22, 10, 40)
CYAN = QColor(120, 250, 255)
WHITE = QColor(255, 255, 255)

SIDE = 96  # logical px at her default size (240)


def _antenna(cx: float, top: float, u: float, sway: float) -> QPainterPath:
    """One curly strand: up from the head, a hook to the right, a flick at the end."""
    path = QPainterPath(QPointF(cx - 6 * u, top + 2 * u))
    path.cubicTo(QPointF(cx - 7 * u, top - 10 * u), QPointF(cx + 8 * u + sway, top - 6 * u), QPointF(cx + 6 * u + sway, top - 16 * u))
    path.cubicTo(QPointF(cx + 4 * u + sway, top - 24 * u), QPointF(cx + 12 * u + sway * 1.5, top - 27 * u), QPointF(cx + 17 * u + sway * 1.8, top - 24 * u))
    return path


ART = Path(__file__).resolve().parents[2] / "assets" / "desk" / "nap.png"  # drawn art wins over the code-drawn sprite
_art: list = []


def _art_image() -> QImage | None:
    if not _art:
        img = QImage(str(ART)) if ART.exists() else QImage()
        _art.append(None if img.isNull() else img)
    return _art[0]


def paint_chip(p: QPainter, side: float, t: float, glitch: bool = False, zs: bool = True) -> None:
    """Draws the nap sprite into a side x side box. t drives the float, the breathing and the z's."""
    art = _art_image()
    if art is not None:
        return _paint_art(p, art, side, t, glitch, zs)
    u = side / 100
    p.setRenderHint(QPainter.Antialiasing)
    bob = math.sin(t * 1.9) * 2.5 * u
    cx = 48 * u
    bw, bh = 46 * u, 32 * u
    bx, by = cx - bw / 2, 44 * u + bob

    # hover flame under it
    flick = 1 + 0.25 * math.sin(t * 23) + 0.15 * math.sin(t * 37)
    flame = QPolygonF([QPointF(cx - 5 * u, by + bh - 1 * u), QPointF(cx + 5 * u, by + bh - 1 * u), QPointF(cx, by + bh + 12 * u * flick)])
    p.setBrush(CYAN)
    p.drawPolygon(flame)
    p.setBrush(WHITE)
    p.drawPolygon(QPolygonF([QPointF(cx - 2.5 * u, by + bh), QPointF(cx + 2.5 * u, by + bh), QPointF(cx, by + bh + 7 * u * flick)]))

    sway = math.sin(t * 1.3) * 2 * u
    shift = 3.2 * u  # the misprint: a violet copy offset down-right, like a badly aligned print
    for dx, col in ((shift, VIOLET), (0.0, None)):
        ant = _antenna(cx, by, u, sway).translated(dx, dx)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col or PINK, 6 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(ant)
        body = QPainterPath()
        body.addRoundedRect(QRectF(bx + dx, by + dx, bw, bh), 8 * u, 8 * u)
        p.setPen(Qt.NoPen)
        p.setBrush(col or MINT)
        p.drawPath(body)
    # highlight along the top
    p.setBrush(MINT_HI)
    p.drawRoundedRect(QRectF(bx + 5 * u, by + 3 * u, bw - 18 * u, 3.2 * u), 1.6 * u, 1.6 * u)

    # sleepy face
    ey = by + bh * 0.5
    p.setPen(QPen(INK, 2.8 * u, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for ex in (cx - 9 * u, cx + 9 * u):
        p.drawArc(QRectF(ex - 5 * u, ey - 4.5 * u, 10 * u, 8 * u), 200 * 16, 140 * 16)
        p.drawLine(QPointF(ex - 4.6 * u, ey + 1.2 * u), QPointF(ex - 6.4 * u, ey + 2.8 * u))  # a lash
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 60, 140, 200))
    for ex in (cx - 15 * u, cx + 15 * u):
        p.drawEllipse(QPointF(ex, ey + 6 * u), 3.2 * u, 1.8 * u)

    if glitch:  # a couple of torn slices
        for _ in range(3):
            y = random.uniform(20 * u, 80 * u)
            p.fillRect(QRectF(random.uniform(0, 50) * u, y, random.uniform(20, 50) * u, random.uniform(1, 2.5) * u),
                       QColor(120, 250, 255, 160) if random.random() < 0.5 else QColor(255, 30, 110, 160))

    if zs:  # z's drifting up and fading
        f = QFont(["Consolas", "DejaVu Sans Mono", "Noto Sans Mono"])
        f.setBold(True)
        for i in range(3):
            k = ((t * 0.45) + i / 3) % 1.0
            f.setPixelSize(max(6, round((8 + 7 * k) * u)))
            p.setFont(f)
            c = QColor(CYAN)
            c.setAlphaF(math.sin(math.pi * k) * 0.9)
            p.setPen(c)
            p.drawText(QPointF(cx + (24 + 10 * k) * u + math.sin(k * 6) * 2 * u, by - (2 + 26 * k) * u), "z")


def _zs(p: QPainter, x: float, y: float, u: float, t: float) -> None:
    """z's drifting up and fading."""
    f = QFont(["Consolas", "DejaVu Sans Mono", "Noto Sans Mono"])
    f.setBold(True)
    for i in range(3):
        k = ((t * 0.45) + i / 3) % 1.0
        f.setPixelSize(max(6, round((8 + 7 * k) * u)))
        p.setFont(f)
        c = QColor(CYAN)
        c.setAlphaF(math.sin(math.pi * k) * 0.9)
        p.setPen(c)
        p.drawText(QPointF(x + 10 * k * u + math.sin(k * 6) * 2 * u, y - 26 * k * u), "z")


def _paint_art(p: QPainter, art: QImage, side: float, t: float, glitch: bool, zs: bool) -> None:
    u = side / 100
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    bob = math.sin(t * 1.9) * 2.5 * u
    breathe = math.sin(t * 1.9 + 0.6)
    cx, floor = 50 * u, 93 * u
    size = 84 * u
    aspect = art.height() / max(1, art.width())  # keep the art's own shape (the nap screen is wide)
    w, h = size * (1 - 0.025 * breathe), size * aspect * (1 + 0.03 * breathe)  # breathing squish
    rect = QRectF(cx - w / 2, floor - 3 * u - h + bob, w, h)
    if glitch:  # misprint: shifted cyan / pink copies for a frame or two
        for dx, a in ((-3 * u, 0.45), (3 * u, 0.45)):
            p.setOpacity(a)
            p.drawImage(rect.translated(dx, 0), art)
        p.setOpacity(1.0)
    p.drawImage(rect, art)
    if glitch:
        for _ in range(2):
            y = random.uniform(rect.top(), rect.bottom())
            p.fillRect(QRectF(rect.left() + random.uniform(-6, 10) * u, y, random.uniform(20, 50) * u, random.uniform(1, 2.5) * u),
                       QColor(120, 250, 255, 170) if random.random() < 0.5 else QColor(255, 30, 110, 170))
    if zs:
        _zs(p, rect.right() - 6 * u, rect.top() + 2 * u, u, t)


def chip_image(side: float, dpr: float) -> QImage:
    img = QImage(round(side * dpr), round(side * dpr), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    img.setDevicePixelRatio(dpr)
    p = QPainter(img)
    paint_chip(p, side, 0.0, zs=False)
    p.end()
    return img


def sample_chip(side: float, dpr: float, fx: float, fy: float, step: float):
    """The chip's opaque pixels on a grid, placed with its floor point (bottom middle) at (fx, fy)."""
    img = chip_image(side, dpr)
    s = max(1, round(step * dpr))
    ox, oy = fx - side * 0.5, fy - side * 0.92
    out = []
    for y in range(s // 2, img.height(), s):
        for x in range(s // 2, img.width(), s):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                out.append((ox + x / dpr, oy + y / dpr, QColor(c.red(), c.green(), c.blue())))
    return out


class Chip(QWidget):
    """The napping chip on screen. Its floor point (bottom middle) is where it sits."""

    woke = Signal()
    moved = Signal()
    menu = Signal()  # right-clicked: her menu opens in the door beside it

    def __init__(self, scale: float):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.side = SIDE * scale
        self.setFixedSize(round(self.side), round(self.side))
        self.t0 = time.monotonic()
        self.glitch_until = 0.0
        self.press = None
        self.dragged = False
        self.zs = True  # the sleepy z's (off in mini mode, where she's awake, just small)

    def floor_point(self) -> QPointF:
        return QPointF(self.x() + self.side * 0.5, self.y() + self.side * 0.92)

    def put(self, fx: float, fy: float) -> None:
        self.move(round(fx - self.side * 0.5), round(fy - self.side * 0.92))

    def tick(self):
        now = time.monotonic()
        if now > self.glitch_until + 3 and random.random() < 0.004:
            self.glitch_until = now + 0.12
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        now = time.monotonic()
        paint_chip(p, self.side, now - self.t0, glitch=now < self.glitch_until, zs=self.zs)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press = e.globalPosition() - QPointF(self.pos())
            self.dragged = False

    def mouseMoveEvent(self, e):
        if self.press is not None:
            to = e.globalPosition() - self.press
            if (to - QPointF(self.pos())).manhattanLength() > 3:
                self.dragged = True
            self.move(round(to.x()), round(to.y()))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.press is None:
            return
        self.press = None
        if self.dragged:
            self.moved.emit()
        else:
            self.woke.emit()

    def contextMenuEvent(self, e):
        self.menu.emit()
