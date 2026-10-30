"""Capri as a desktop creature: she drops in from the top of the screen, stands on the taskbar, sits on
windows and icons, gets picked up and thrown, and every so often turns into a bolt of light and zaps
somewhere new.

Positions are her *anchor* in global logical pixels: the point between her feet when she stands, her
hip when she sits. Her window is placed so that point lands on a fixed spot of its canvas.
"""
from __future__ import annotations

import math
import random
import sys
import time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from . import ledges
from .bubble import Bubble
from . import sfx as sfx_mod
from .fx import CYAN, PINK, WHITE, Fx, FxLayer
from .doormenu import INSIDE, DoorMenu
from .mini import Chip, sample_chip
from .portal import BOOT as SCREEN_BOOT, FACE as SCREEN_FACE, OUT as SCREEN_OFF, STAMP as SCREEN_STAMP, Portal
from .sprites import Sprites

# chat box portrait: crop size, then where her face sits relative to head() standing / sitting (units of her size)
FACE = (0.34, (0.03, 0.32), (0.08, 0.35))
STREAM_STEP = 6.5  # px between her pixels when she streams (bigger = fewer pixels = smoother)
BYES = ["Delta-ing out. Don't flatline without me, choom.", "Jacking out. Keep the rig warm for me.",
        "Logging off. Try not to be a gonk while I'm gone.", "Powering down. Miss me a normal amount."]
GREETING = "Ow. Okay. Whose desktop is this? ...Nice. I'm staying."
GREETINGS = ["Hi there! ...Ooh, nice desktop. I'm staying.", "Breach complete. Hiii! I live here now.",
             "Hey hey! Whose desktop is this? ...Mine now.", "Ta-da! Missed me? Don't answer that.",
             "Hi there. Just call me Capri!"]
PEEKS = ["I see u.", "Whatcha doing?", "Don't mind me.", "Peekaboo.", "...", "Hi.", "Just checking on u.", None, None]
POP_OUTS = ["Boo!", "Ha. Got u.", "Okay okay, I'm out.", "Caught me."]
ARRIVALS = ["Comfy.", "This window's mine now.", "Don't mind me, choom.", "Better view from up here.",
            "Zap. Miss me?", "What're we working on?", None, None, None]
DEMO_REPLIES = ["Heard you loud and clear, choom.", "Ha. Say that again, I dare you.",
                "Hold on, I'm still settling into your desktop.", "Mm-hm. Noted. Filed under 'later'.",
                "You're lucky I like you."]


def _dot(x, y, floor, k):
    from .fx import P

    return P(x, y, 0.0, 0.0, 1.0, max(3, round(6 * k)), WHITE, "pixel", floor, 2200 * k, 0.6)


def ease_in_out(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


class Body(QWidget):
    """Her sprite window. Fully transparent pixels don't take clicks, so only she is grabbable."""

    def __init__(self, ctl: "Capri", side: int):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(side, side)
        self.setMouseTracking(False)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        self.ctl.draw(p)
        p.end()

    def mousePressEvent(self, e):
        self.ctl.press(e)

    def mouseMoveEvent(self, e):
        self.ctl.drag_move(e)

    def mouseReleaseEvent(self, e):
        self.ctl.release(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.ctl.teleport()

    def contextMenuEvent(self, e):
        self.ctl.open_menu()


class Capri:
    def __init__(self, size: int = 240, roam: tuple[float, float] = (18, 40), intro: bool = True, start: bool = True):
        self.app = QApplication.instance()
        scr = QGuiApplication.primaryScreen()
        self.S = size
        self.k = size / 240  # effect scale
        self.dpr = scr.devicePixelRatio()
        self.sp = Sprites(size, self.dpr)
        self.sfx = sfx_mod.Mixer()
        self.fx = Fx(self.k)
        self.layers = [FxLayer(self.fx, s) for s in QGuiApplication.screens()]
        side = round(1.5 * size)
        self.A = QPointF(0.75 * size, 1.22 * size)  # canvas spot that sits on her anchor
        self.body = Body(self, side)
        self.bubble = Bubble(self.k)
        self.bubble.sent.connect(self.heard)
        self.bubble.typed.connect(self._typed)
        self.bubble.nap.connect(self.toggle_mini)
        self.bubble.portrait = self._portrait  # the chat box shows her live face, like a video call
        self._faces: dict = {}
        self.chip = Chip(self.k)
        self.chip.woke.connect(lambda: self.wake_chip())
        self.chip.moved.connect(self._chip_moved)
        self.chip.menu.connect(self.open_menu)
        self.mini = False  # True = she went mini on purpose (stays small, no snoring, no waking up by herself)
        self.chip_home = None  # where the chip was before her menu pulled it beside the door
        self.door = DoorMenu(self.k, self.sfx)
        self.chip_pos = None  # where the chip naps; None = bottom-left corner
        self.blips = False  # the app turns this on when she "talks" in blips instead of a voice
        self.blip_n = 0
        self.on_user = None  # set by the app: what happens with a line typed to her (the brain)
        self.voice = None  # set by the app: voice(text, on_start(seconds), on_end) speaks a line out loud
        self.speaking = False
        self.on_settled = None  # called once the next time she comes to rest (the video script waits on it)
        self.quit_fn = self.app.quit  # the app swaps in one that also stops the voice server
        self.talk_open = False  # a streamed reply is still coming in
        self.talk_timer = None
        self.beat = None  # set by the app: () -> (pulse 0..1, music playing) from the ear on your speakers
        self.vibe = 0.0

        self.mode = "hidden"  # intro | stand | perch | held | fall | charge | travel | appear | sleep
        self.x, self.y = 0.0, 0.0
        self.vx = self.vy = 0.0
        self.seat: ledges.Ledge | None = None
        self.clip, self.clip_t = "idle", 0.0
        self.cycle = -1
        self.blink = None
        self.mouth = -1
        self.frame, self.shown = 0, "idle"
        self.sx = self.sy = 1.0
        self.angle = 0.0
        self.white = 0.0
        self.squash_t = -1.0
        self.t0 = time.monotonic()
        self.now = 0.0
        self.st = 0.0  # time the current mode started
        self.ledge_list: list[ledges.Ledge] = []
        self.ledges_at = -9.0
        self.lost_since = -1.0
        self.roam = roam
        self.roaming = True
        self.next_roam = 0.0
        self.last_touch = 0.0
        self.press_at = None
        self.grab = QPointF()
        self.hist: list[tuple[float, float, float]] = []
        self.intro_only_floor = False
        self.portal = None  # the transmission card she arrives through (made on her first entrance)
        self.told_zoomed = False
        self.greeting = None  # set by the app: () -> her hello line (a recorded one when her voice is on)
        self._screen_faces: dict = {}
        self.target = None
        self.say_after = None

        self._build_menu()
        self._build_tray()
        self.timer = QTimer()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(15)
        self.last = time.monotonic()
        if sys.platform == "win32":
            self.top_timer = QTimer()
            self.top_timer.timeout.connect(self._topmost)
            self.top_timer.start(1500)
        if intro:
            QTimer.singleShot(400, self.drop_in)
        elif start:
            g = ledges.work_area(scr)
            self._land_floor(g.right() - 0.3 * g.width(), g.bottom() + 1, quiet=True)

    def set_size(self, size: int):
        """A new height for her, live: sprites rebuilt at that size, her window resized, then she drops onto
        whatever is under her."""
        if size == self.S or self.mode in ("hidden", "intro", "stream", "to_chip", "chip", "bye"):
            return
        if self._peeking():
            self.pop_out()
        self.S = size
        self.k = size / 240
        self.sp = Sprites(size, self.dpr)
        self.A = QPointF(0.75 * size, 1.22 * size)
        side = round(1.5 * size)
        self.body.setFixedSize(side, side)
        self.fx.s = self.k  # her effects scale with her
        self._faces = {}
        self.seat = None
        self.ledges_at = -9
        self.fall_from_here(0, -120 * self.k)

    # -- small helpers ------------------------------------------------------------
    def skip(self):
        return {int(w.winId()) for w in [self.body, self.bubble, self.chip] + self.layers}

    def refresh_ledges(self, force=False):
        if force or self.now - self.ledges_at > 0.3:
            self.ledges_at = self.now
            try:
                self.ledge_list = ledges.find(self.skip(), True, self.now)
            except Exception as e:  # never let a weird window kill her
                print("ledges:", e)
                self.ledge_list = ledges.floors()

    def screen_rect(self, x, y) -> QRect:
        scr = QGuiApplication.screenAt(QPointF(x, y).toPoint()) or QGuiApplication.primaryScreen()
        return ledges.work_area(scr)

    def cur(self):
        return self.sp[self.clip]

    def play(self, name):
        if name != self.clip:
            self.clip, self.clip_t = name, self.now
            self.cycle = -1

    def set_mode(self, m):
        self.mode, self.st = m, self.now

    def _peeking(self) -> bool:
        return self.seat is not None and self.seat.kind == "peek"

    def center(self):
        """Middle of her body, global coords (for effects)."""
        if self._peeking():
            return self.pc
        up = 0.38 if self.mode == "perch" else 0.5
        return self.x + (0.1 if self.mode == "perch" else -0.05) * self.S, self.y - up * self.S

    def head(self):
        if self._peeking():  # her head is the part sticking out of the edge
            cx, cy = self.pc
            d = 0.36 * self.S
            return {"left": (cx + d, cy), "right": (cx - d, cy), "top": (cx, cy + d)}[self.peek_edge]
        if self.mode == "perch" or self.clip.startswith("perch"):
            return self.x + 0.14 * self.S, self.y - 0.64 * self.S
        return self.x - 0.07 * self.S, self.y - 1.03 * self.S

    def standing_clip(self):
        if self.mode == "perch":  # also sitting on the stream stage's CMD, where her desktop seat is still the floor
            return "perch"
        return "perch" if self.seat is not None and self.seat.kind != "floor" else "idle"

    def _portrait(self):
        """Her face right now for the call-style chat box: the current frame (blinks, talking mouth) cropped around
        her head. None while she's not on screen (the box keeps the last face)."""
        if self.mode in ("hidden", "chip", "to_chip", "stream", "intro"):
            return None
        key = (self.shown, self.frame, self.mouth)
        if key in self._faces:
            return self._faces[key]
        c = self.sp[self.shown]
        ax, ay = c.anchor
        hx, hy = self.head()
        cx, cy = hx - (self.x - ax * c.w), hy - (self.y - ay * c.h)  # her head in the frame's own pixels
        side = FACE[0] * self.S
        fx, fy = FACE[2] if self.shown.startswith("perch") else FACE[1]
        src = QRectF(cx + fx * self.S - side / 2, cy + fy * self.S - side / 2, side, side)
        out = QPixmap(round(side * self.dpr), round(side * self.dpr))
        out.setDevicePixelRatio(self.dpr)
        out.fill(Qt.transparent)
        q = QPainter(out)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        q.translate(-src.topLeft())
        q.drawPixmap(0, 0, c.frames[self.frame])
        if self.mouth >= 0:
            q.drawPixmap(0, 0, self.sp["mouth"].frames[self.mouth])
        q.end()
        if len(self._faces) > 200:
            self._faces.clear()
        self._faces[key] = out
        return out

    # -- per-frame ----------------------------------------------------------------
    def tick(self):
        t = time.monotonic()
        dt = min(0.05, t - self.last)
        self.last = t
        self.now = t - self.t0
        m = self.mode
        if m == "intro":
            self._intro_step()
        elif m == "fall":
            self._fall_step(dt)
        elif m == "held":
            self._held_step()
        elif m == "charge":
            self._charge_step()
        elif m == "stream":
            if self.now - self.st >= self.stream_T - 0.05:
                self.arrive()
        elif m == "to_chip":
            if self.now - self.st >= self.stream_T - 0.05:
                self._chip_arrive()
        elif m == "chip":
            self._chip_step()
        elif m == "appear":
            self._appear_step()
        elif m == "bye":
            self._bye_step()
        elif m in ("stand", "perch", "sleep"):
            self._rest_step()
        elif m == "peek":
            self._peek_step()
        pulse, playing = self.beat() if self.beat else (0.0, False)
        target = pulse if playing else 0.0
        self.vibe = max(target, self.vibe * 0.88)
        self.fx.step(dt)
        if self.portal is not None and self.portal.isVisible():
            self.portal.step()
            if self.portal.done:
                self.portal.hide()
        for layer in self.layers:
            layer.refresh()
        self._animate()
        if self.mode != "hidden" and self.body.isVisible():
            self._place()
            self.body.update()
        if self.bubble.isVisible():
            hx, hy = self.head()
            self.bubble.place(hx, hy, self.screen_rect(hx, self.y - 10))

    def _place(self):
        self.body.move(round(self.x - self.A.x()), round(self.y - self.A.y()))

    def _animate(self):
        """Pick the frame for this tick: clip timing, blinks during idle loops, mouth flaps while talking."""
        c = self.cur()
        i = int((self.now - self.clip_t) * c.fps)
        if self.clip in ("glitch", "perch_glitch", "wake") and i >= c.count:
            self.play(self.standing_clip() if self.mode != "sleep" else "idle")
            c, i = self.cur(), 0
        if self.clip == "grin" and i >= c.count * 2:
            self.play("idle")
            c, i = self.cur(), 0
        if self.clip in ("idle", "perch"):
            cyc = i // c.count
            if cyc != self.cycle:
                self.cycle = cyc
                r = random.random()
                pre = "perch_" if self.clip == "perch" else ""
                self.blink = (pre + ("blink_glitch" if r < 0.08 else "blink")) if r < 0.45 else None
                if self.clip == "idle" and r > 0.95 and self.mode == "stand" and not self.bubble.isVisible():
                    self.play("grin")
                    return self._animate()
        self.frame = i % c.count
        self.shown = self.clip
        if self.blink and self.clip in ("idle", "perch") and 6 <= self.frame < 10:
            self.shown, self.frame = self.blink, self.frame - 6
        self.mouth = -1
        if self.speaking and self.shown == "idle":
            self.mouth = int(self.now * 12 + 0.5) % 5 if int(self.now * 12) % 4 else 0

    def draw(self, p: QPainter):
        if self.mode in ("hidden", "chip", "to_chip"):
            return
        c = self.sp[self.shown]
        pm = c.frames[self.frame]
        if self._peeking():
            return self._draw_peek(p, c, pm)
        ax, ay = c.anchor
        breathe = tilt = 0.0
        if self.mode in ("stand", "perch"):
            breathe = math.sin(self.now * 1.75) * 2.0 * self.k
            tilt = math.sin(self.now * 0.95) * 0.6
        sx, sy = self.sx, self.sy
        if self.squash_t >= 0:  # landing squash: flatten, overshoot, settle
            q = (self.now - self.squash_t) / 0.42
            if q >= 1:
                self.squash_t = -1
            else:
                amt = self.squash_amt * math.exp(-5 * q) * math.cos(q * 9)
                sy *= 1 - amt
                sx *= 1 + amt * 0.7
        p.translate(self.A)
        p.translate(0, (breathe if self.mode == "stand" else 0) - self.vibe * 3 * self.k)
        p.rotate(self.angle + tilt)
        mid = 0.5 * self.S if self.mode == "bye" else 0.0
        p.translate(0, -mid)
        p.scale(sx, sy)
        p.translate(0, mid)
        if self.mode == "perch":
            p.translate(0, breathe * 0.5)
        tl = QPointF(-ax * c.w, -ay * c.h)
        if self.white > 0.02:  # electric aura behind her while charging / materialising
            p.save()
            p.setOpacity(min(1.0, self.white) * 0.55)
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                p.drawPixmap(tl + QPointF(dx * self.k, dy * self.k), c.white(self.frame))
            p.restore()
        if self.vibe > 0.35 and self.mode in ("stand", "perch") and self.white < 0.05:
            pm = self._vibed(c, pm)  # on the beat: bands of her hair jump sideways
        p.drawPixmap(tl, pm)
        if self.mouth >= 0:
            p.drawPixmap(tl, self.sp["mouth"].frames[self.mouth])
        if self.white > 0.02:
            p.setOpacity(min(1.0, self.white))
            p.drawPixmap(tl, c.white(self.frame))
            p.setOpacity(1.0)

    def _draw_peek(self, p: QPainter, c, pm):
        """Leaning in from a screen edge: drawn around the middle of her canvas, turned toward the screen, bobbing
        in and out a little like she's sneaking a look."""
        bob = (math.sin(self.now * 1.6) * 0.5 + 0.5) * 0.06 * self.S
        dx, dy = {"left": (bob, 0), "right": (-bob, 0), "top": (0, bob)}[self.peek_edge]
        p.translate(0.75 * self.S + dx, 0.75 * self.S + dy)
        p.rotate(self.peek_angle)
        tl = QPointF(-0.5 * c.w, -0.5 * c.h)
        if self.white > 0.02:
            p.save()
            p.setOpacity(min(1.0, self.white) * 0.55)
            for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                p.drawPixmap(tl + QPointF(ox * self.k, oy * self.k), c.white(self.frame))
            p.restore()
        p.drawPixmap(tl, pm)
        if self.mouth >= 0:
            p.drawPixmap(tl, self.sp["mouth"].frames[self.mouth])
        if self.white > 0.02:
            p.setOpacity(min(1.0, self.white))
            p.drawPixmap(tl, c.white(self.frame))
            p.setOpacity(1.0)

    # -- peeking: she leans in from the side of the screen, or hangs upside down from the top -----------------
    def _peek_spot(self):
        """A screen edge with nothing beyond it (not the side that leads to another monitor): left, right or top,
        somewhere along it. -> a Ledge("peek") with .edge set, or None."""
        screens = QGuiApplication.screens()
        scr = QGuiApplication.screenAt(QPointF(self.x, self.y - 10).toPoint()) or QGuiApplication.primaryScreen()
        g, w = scr.geometry(), ledges.work_area(scr)

        def outside(px, py):
            return not any(s.geometry().contains(round(px), round(py)) for s in screens)

        S = self.S
        edges = []
        if outside(g.left() - 4, g.center().y()):
            edges.append("left")
        if outside(g.right() + 4, g.center().y()):
            edges.append("right")
        if outside(g.center().x(), g.top() - 4):
            edges += ["top", "top"]  # hanging from the top is the cutest: twice the odds
        if not edges:
            return None
        edge = random.choice(edges)
        L = ledges.Ledge("peek", 0, 0, 0)
        L.edge = edge
        L.t = (random.uniform(w.top() + 0.45 * S, w.bottom() - 0.45 * S) if edge != "top"
               else random.uniform(w.left() + 0.4 * S, w.right() - 0.4 * S))
        L.g = g
        return L

    def _edge_peek(self, gx, gy):
        """Dropped close to the left, right or top of the screen (an edge with no monitor beyond it)?
        -> a Ledge("peek") on that edge where she was let go, or None."""
        scr = QGuiApplication.screenAt(QPointF(gx, gy).toPoint()) or QGuiApplication.primaryScreen()
        g, w = scr.geometry(), ledges.work_area(scr)
        S, near = self.S, 0.28 * self.S

        def outside(px, py):
            return not any(s.geometry().contains(round(px), round(py)) for s in QGuiApplication.screens())

        edge = None
        if gx - g.left() < near and outside(g.left() - 4, gy):
            edge = "left"
        elif g.right() - gx < near and outside(g.right() + 4, gy):
            edge = "right"
        elif gy - g.top() < near and outside(gx, g.top() - 4):
            edge = "top"
        if edge is None:
            return None
        L = ledges.Ledge("peek", 0, 0, 0)
        L.edge, L.g = edge, g
        L.t = (min(w.bottom() - 0.45 * S, max(w.top() + 0.45 * S, gy)) if edge != "top"
               else min(w.right() - 0.4 * S, max(w.left() + 0.4 * S, gx)))
        return L

    def _peek_center(self, L):
        out = -0.1 * self.sp["idle"].h  # her middle sits just inside the edge: head, face and shoulders show
        g = L.g
        if L.edge == "left":
            return g.left() - out, L.t
        if L.edge == "right":
            return g.right() + out, L.t
        return L.t, g.top() - out

    def _peek_pixels(self, L, step):
        """Her idle frame turned for that edge, sampled for the pixel stream (so the flight lands in the pose)."""
        c = self.sp["idle"]
        cx, cy = self._peek_center(L)
        ang = math.radians({"left": 90, "right": -90, "top": 180}[L.edge])
        ax, ay = c.anchor
        pts = c.sample(0, cx + (ax - 0.5) * c.w, cy + (ay - 0.5) * c.h, step)
        ca, sa = math.cos(ang), math.sin(ang)
        return [(cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca, col) for x, y, col in pts]

    def _peek_step(self):
        if self.now - self.st > self.peek_len and not self.bubble.isVisible() and not self.speaking:
            self.pop_out()

    def pop_out(self, line=None):
        """Out of the edge and back onto the desktop: she drops in toward the middle of the screen."""
        if not self._peeking():
            return
        edge, (cx, cy) = self.peek_edge, self.pc
        h = self.sp["idle"].h
        self.seat = None
        self.angle = 0.0
        self.x = {"left": cx + 0.5 * h, "right": cx - 0.5 * h, "top": cx}[edge]
        self.y = {"left": cy + 0.5 * h, "right": cy + 0.5 * h, "top": cy + h}[edge]
        vx = {"left": 520, "right": -520, "top": random.uniform(-150, 150)}[edge] * self.k
        vy = {"left": -380, "right": -380, "top": 60}[edge] * self.k
        self.fx.flash(cx, cy, 90, life=0.2, color=PINK)
        self.fx.sparks(cx, cy, 14, speed=(100, 380), life=(0.12, 0.3))
        self.sfx.play("throw")
        self.fall_from_here(vx, vy)
        if line:
            QTimer.singleShot(250, lambda: self.say(line))

    def _vibed(self, c, pm):
        """A copy of the frame with two or three bands of her hair moved sideways (moved, not copied on top, so
        she never looks doubled). Same tear for a few frames so it reads as a glitch, not noise."""
        out = QPixmap(pm.size())
        out.setDevicePixelRatio(pm.devicePixelRatio())
        out.fill(Qt.transparent)
        q = QPainter(out)
        q.drawPixmap(0, 0, pm)
        d, k, v = c.dpr, self.k, self.vibe
        top, bottom = c.h * (0.03 if self.mode == "stand" else 0.16), c.h * (0.42 if self.mode == "stand" else 0.45)
        rnd = random.Random(int(self.now * 12))
        for _ in range(2 + (v > 0.7)):
            hh = rnd.uniform(5, 14) * k
            y0 = rnd.uniform(top, bottom - hh)
            dx = rnd.choice((-1, 1)) * rnd.uniform(3, 9) * k * v
            band = QRectF(0, y0, c.w, hh)
            q.setCompositionMode(QPainter.CompositionMode_Clear)
            q.fillRect(band, Qt.transparent)
            q.setCompositionMode(QPainter.CompositionMode_SourceOver)
            q.drawPixmap(band.translated(dx, 0), pm, QRectF(0, y0 * d, pm.width(), hh * d))
        q.end()
        return out

    def listening(self, on: bool):
        """Talk key held (or she caught your voice): the bubble shows a REC dot and your mic level."""
        if on:
            self.sfx.play("pop")
            self.next_roam = max(self.next_roam, self.now + 30)
            hx, hy = self.head()
            self.bubble.listen(True)
            self.bubble.place(hx, hy, self.screen_rect(hx, self.y - 10))
        else:
            self.bubble.listen(False)

    # -- intro: the sky tears open and she drops out ------------------------------
    def drop_in(self, greet=True, x_frac=None):
        """Her entrance: an "incoming transmission" card glides in at the top right and decrypts her signal, then
        she pours out of it as a stream of pixels, rebuilds on your desktop and says hi."""
        self.bubble.close_bubble()
        scr = QGuiApplication.primaryScreen()
        work = ledges.work_area(scr)
        self.ix = work.left() + work.width() * (x_frac if x_frac is not None else random.uniform(0.55, 0.8))
        if self.portal is None:
            self.portal = Portal(self.k, self._screen_face)
        self.portal.start(work)  # the transmission card glides in at the top-right corner
        self.iy = work.bottom() + 1
        self.body.hide()
        self.seat = None
        self.say_after = ((self.greeting() if self.greeting else None) or random.choice(GREETINGS)) if greet else None
        self.set_mode("intro")
        self.stage = 0
        self.sfx.play("tear")

    def _screen_face(self, t: float):
        """Her face for the card's avatar: the standing frames cropped round her head, blinking now and then."""
        blink = (t % 2.6) > 2.35
        name = "blink" if blink else "idle"
        c = self.sp[name]
        frame = min(c.count - 1, int((t % 2.6 - 2.35) * c.fps)) if blink else int(t * c.fps) % c.count
        key = (name, frame, self.S)
        if key in self._screen_faces:
            return self._screen_faces[key]
        ax, ay = c.anchor
        cx, cy = ax * c.w - 0.07 * self.S, ay * c.h - 1.03 * self.S  # her head in the frame's own pixels
        side = FACE[0] * self.S
        fx, fy = FACE[1]
        src = QRectF(cx + fx * self.S - side / 2, cy + fy * self.S - side / 2, side, side)
        out = QPixmap(round(side * self.dpr), round(side * self.dpr))
        out.setDevicePixelRatio(self.dpr)
        out.fill(Qt.transparent)
        q = QPainter(out)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        q.translate(-src.topLeft())
        q.drawPixmap(0, 0, c.frames[frame])
        q.end()
        self._screen_faces[key] = out
        return out

    def _intro_step(self):
        P = self.portal
        t = P.t
        P.step()
        g = P.screen_rect()
        c = g.center()
        if self.stage == 0 and t > SCREEN_BOOT:  # brackets locked on: a quick ring of speed lines, the screen hums on
            self.stage = 1
            self.sfx.play("charge")
            self.fx.burst(c.x(), c.y(), 8, r0=0.62 * g.height() / self.k, r1=110, life=0.3, width=(2, 6),
                          colors=(WHITE, PINK))
        elif self.stage == 1 and t > SCREEN_STAMP:  # the sticker slaps on: lines shoot out behind it
            self.stage = 2
            self.fx.burst(g.left() - 50 * self.k, c.y() + 0.18 * g.height(), 7, r0=30, r1=360, life=0.4,
                          aim=160, spread=70, width=(4, 13))
        elif self.stage == 2 and t > SCREEN_FACE:  # the screen is down to a dot: she pours out of it
            self.stage = 3
            self.fx.burst(c.x(), c.y(), 11, r0=12, r1=560, life=0.45, aim=125, spread=150, width=(5, 18))
            self._break_out(g)

    def _break_out(self, glass: QRectF):
        """Out of the dot the screen shut down to: her pixels pour out of it and fly down to the desktop."""
        work = ledges.work_area(QGuiApplication.primaryScreen())
        x = work.left() + work.width() * random.uniform(0.35, 0.85)  # a long arc down onto the taskbar
        x = max(work.left() + 0.5 * self.S, min(work.right() - 0.6 * self.S, x))
        L = next((f for f in ledges.floors() if f.holds(x)), ledges.floors()[0])
        self.target = (L, x)
        step = STREAM_STEP * self.k
        cx, cy = glass.center().x(), glass.center().y()
        c = self.sp["idle"]
        ax, ay = c.anchor
        src = [(cx + (px - cx) * 0.1, cy + (py - cy) * 0.1, col)  # her, squeezed into the dot
               for px, py, col in c.sample(0, cx + (ax - 0.5) * c.w, cy + (ay - 0.5) * c.h, step)]
        pair = self._pair(src, self._target_pixels(L, x, step), step)
        self.sfx.play("stream")
        self.fx.flash(cx, cy, 110, life=0.3, color=PINK)
        self.fx.ring(cx, cy, 120, life=0.4, color=CYAN, width=2)
        QTimer.singleShot(int((SCREEN_OFF - SCREEN_FACE) * 1000), lambda: self.sfx.play("throw"))
        if pair:
            self.stream_T = self.fx.start_stream(*pair, travel=1.0, spread=0.35)
        else:
            self.stream_T = 0.2
        self.set_mode("stream")

    # -- falling (thrown, dropped, or knocked off a window) -------------------------
    def _fall_step(self, dt):
        g = 2600 * self.k
        self.vy = min(self.vy + g * dt, 4200 * self.k)
        self.vx *= 1 - 0.4 * dt
        nx, ny = self.x + self.vx * dt, self.y + self.vy * dt
        self.white = max(0.0, self.white - dt * 2.5)
        self.angle += (max(-25, min(25, self.vx * 0.02)) - self.angle) * min(1, dt * 6)
        area = self.screen_rect(nx, min(ny, self.y) - 40)
        margin = 0.3 * self.S
        if nx < area.left() + margin:
            nx, self.vx = area.left() + margin, abs(self.vx) * 0.5
        if nx > area.right() - margin:
            nx, self.vx = area.right() - margin, -abs(self.vx) * 0.5
        if ny < area.top() + 1.1 * self.S and self.vy < 0:
            self.vy = max(self.vy, 0) * 0.3
        if self.vy > 0:
            self.refresh_ledges()
            best = None
            for L in self.ledge_list:
                if self.intro_only_floor and L.kind != "floor":
                    continue
                if self.y - 2 <= L.y <= ny + 1 and L.holds(nx) and (best is None or L.y < best.y):
                    best = L
            floor = self._floor_under(nx, self.y)
            if best is None and ny >= floor.y:  # already under every ledge (dragged below the taskbar...): the floor
                best = floor
            if best is not None:
                self.x, self.y = (nx if best.holds(nx) else max(best.left + 8, min(best.right - 8, nx))), best.y
                self.land(best, self.vy)
                return
        self.x, self.y = nx, ny
        if self.vy > 0 and random.random() < 0.25:
            cx, cy = self.center()
            self.fx.embers(cx, cy, 1, radius=40)

    def _floor_under(self, x, y) -> ledges.Ledge:
        """The floor (bottom of a screen's work area) she'd hit falling from (x, y): the nearest one below her on a
        screen under x, else the lowest one there, else the closest screen's (she's off to the side of them all)."""
        fl = ledges.floors()
        under = [f for f in fl if f.holds(x)]
        if not under:
            return min(fl, key=lambda f: min(abs(x - f.left), abs(x - f.right)))
        below = [f for f in under if f.y >= y - 2]
        return min(below, key=lambda f: f.y) if below else max(under, key=lambda f: f.y)

    def land(self, L: ledges.Ledge, speed: float):
        self.intro_only_floor = False
        self.seat = L
        self.angle = 0
        self.vx = self.vy = 0
        x = max(L.left + 8, min(L.right - 8, self.x))
        self.x = x
        self.seat_off = (x - L.rect.left(), L.rect.top()) if L.kind == "window" else None
        perch = L.kind != "floor"
        self.set_mode("perch" if perch else "stand")
        self.play("perch_glitch" if perch else "glitch")
        self.impact(speed)
        self.last_touch = self.now
        self.next_roam = self.now + random.uniform(*self.roam)
        if self.say_after:
            line, self.say_after = self.say_after, None
            QTimer.singleShot(650, lambda: self.say(line))
        QTimer.singleShot(700, self._settled)

    def _settled(self):
        cb, self.on_settled = self.on_settled, None
        if cb:
            cb()

    def _land_floor(self, x, y, quiet=False):
        L = next((f for f in ledges.floors() if f.holds(x)), ledges.floors()[0])
        self.x, self.y = x, L.y
        self.body.show()
        if quiet:
            self.seat = L
            self.set_mode("stand")
            self.play("idle")
            self.next_roam = self.now + random.uniform(*self.roam)
        else:
            self.land(L, 0)

    def impact(self, speed):
        """Hit the ground: a squash, soft dust rolling out both ways, a few of her pixels hopping off, a faint ripple."""
        k = self.k
        s = max(0.25, min(1.5, speed / (1900 * k)))
        self.squash_t, self.squash_amt = self.now, 0.12 + 0.16 * min(1, s)
        x, y = self.x + (0.12 * self.S if self.mode == "perch" else 0), self.y
        self.fx.puffs(x, y, int(4 + 6 * s), spread=0.6 + 0.6 * s)
        self.fx.pixels(x, y - 2, int(6 + 12 * s), self.sp.color, speed=(90 * s + 80, 260 * s + 120),
                       up=(215, 325), ground=y, life=(0.7, 1.2), size=(3, 5))
        self.fx.ring(x, y, 60 + 90 * s, life=0.45, color=QColor(235, 228, 240), width=1.6, flat=0.18)
        self.sfx.play("thud", f"{min(1.0, s):.1f}")
        if s > 0.5:
            QTimer.singleShot(180, lambda: self.sfx.play("tinkle"))

    # -- resting: idle on the floor, or sitting on a window / icon ----------------------
    def _rest_step(self):
        if self.mode == "sleep":
            if self.now - self.st > 40:
                self.wake()
            elif random.random() < 0.012:
                hx, hy = self.head()
                self.fx.embers(hx + 0.1 * self.S, hy + 0.1 * self.S, 1, radius=4, colors=(CYAN,))
            return
        if self.seat and self.seat.kind != "floor":
            self._follow_seat()
            if self.mode != "perch":
                return
        if self.roaming and self.now > self.next_roam and not self.bubble.isVisible() and not self.speaking:
            if random.random() < 0.12:
                self.go_chip()
            else:
                self.teleport()

    def _follow_seat(self):
        """Ride along when her window moves; fall when it closes, minimises or something covers her."""
        L = self.seat
        if L.kind == "window":
            r = ledges.window_rect(L.hwnd)
            if r is not None:
                dx = r.left() - L.rect.left()
                dy = r.top() - L.rect.top()
                if dx or dy:
                    self.x += dx
                    self.y = r.top()
                    L.left += dx
                    L.right += dx
                    L.y = r.top()
                    L.rect = r
        else:
            r = L.rect
        self.refresh_ledges()
        ok = r is not None and any(o.key == L.key and o.holds(self.x) for o in self.ledge_list)
        if ok:
            self.lost_since = -1
            return
        if self.lost_since < 0:
            self.lost_since = self.now
        if self.now - self.lost_since > 0.45:
            self.lost_since = -1
            self.fall_from_here()

    def fall_from_here(self, vx=0.0, vy=0.0):
        self.seat = None
        self.vx, self.vy = vx, vy
        self.play("dangle")
        self.set_mode("fall")

    def wake(self):
        self.play("wake")
        self.set_mode("stand")
        self.next_roam = self.now + random.uniform(*self.roam)

    # -- teleport: charge up, become a bolt of light, strike down somewhere else ---------
    def pick_spot(self):
        self.refresh_ledges(force=True)
        cur = self.seat.key if self.seat else None
        S = self.S
        pools = {"window": [], "icon": [], "floor": []}
        for L in self.ledge_list:
            if L.key == cur and L.kind != "floor":
                continue
            area = self.screen_rect((L.left + L.right) / 2, L.y - 5)
            if L.y - (0.85 if L.kind == "floor" else 0.64) * S < area.top():  # no headroom (seated she's ~0.62 S tall)
                continue
            lo, hi = max(L.left, area.left()) + 0.3 * S, min(L.right, area.right()) - 0.45 * S
            if L.kind == "icon":
                lo, hi = L.left + 4, max(L.left + 4, L.right - 4)
            if hi <= lo:
                continue
            pools[L.kind].append((L, lo, hi))
        if random.random() < 0.18 and self.mode != "peek":  # every so often: peek in from an edge instead
            L = self._peek_spot()
            if L is not None:
                return L, 0.0
        weights = {"window": 0.6, "icon": 0.2, "floor": 0.2}
        kinds = [k for k in pools if pools[k]]
        if not pools["window"] and ledges.ZOOMED and not self.told_zoomed and random.random() < 0.3:
            self.told_zoomed = True  # once: tell them why she isn't on their apps
            QTimer.singleShot(900, lambda: self.say("Your apps are all full screen, nowhere to sit. Shrink one and I'll hop on it."))
        if not kinds:
            return None
        kind = random.choices(kinds, [weights[k] for k in kinds])[0]
        L, lo, hi = random.choice(pools[kind])
        for _ in range(6):  # floor: don't land right where she already is
            x = random.uniform(lo, hi)
            if kind != "floor" or abs(x - self.x) > 1.2 * S:
                break
        return L, x

    def teleport(self, spot=None):
        """Defrag: she breaks into her own pixels, they fly over and rebuild her somewhere else."""
        if self.mode == "peek":
            return self.pop_out()
        if self.mode not in ("stand", "perch", "sleep"):
            return
        spot = spot or self.pick_spot()
        if not spot:
            self.next_roam = self.now + 5
            return
        self.bubble.close_bubble()
        self.target = spot
        self.play("perch_glitch" if self.mode == "perch" else "glitch")
        self.sfx.play("charge")
        self.set_mode("charge")
        self.last_touch = self.now

    def _charge_step(self):
        t = (self.now - self.st) / 0.42
        e = t * t
        cx, cy = self.center()
        if random.random() < 0.08:
            self.fx.arc_around(cx, cy, 0.42 * self.S, 1, random.choice((CYAN, PINK)))
        self.white = min(0.45, e * 0.5)
        if t >= 1:
            self.white = 0.0
            self.start_stream()

    @staticmethod
    def _pair(src, dst, step):
        """Match pixels top to bottom (her hair flies to where her hair will be), thinned to the same count."""
        n = min(len(src), len(dst))
        if n < 10:
            return None
        src.sort(key=lambda q: (round(q[1] / step), q[0]))
        dst.sort(key=lambda q: (round(q[1] / step), q[0]))

        def even(lst):
            return [lst[round(i * (len(lst) - 1) / max(1, n - 1))] for i in range(n)]

        return even(src), even(dst)

    def _target_pixels(self, L, x, step):
        if L.kind == "peek":
            return self._peek_pixels(L, step)
        return self.sp["perch" if L.kind != "floor" else "idle"].sample(0, x, L.y, step)

    def start_stream(self):
        L, x = self.target
        step = STREAM_STEP * self.k
        pair = self._pair(self.sp[self.shown].sample(self.frame, self.x, self.y, step), self._target_pixels(L, x, step), step)
        cx, cy = self.center()
        if not pair:  # nothing to sample (shouldn't happen): just blink over
            self.body.hide()
            self.stream_T = 0.2
            self.seat = None
            return self.set_mode("stream")
        self.body.hide()
        self.sfx.play("stream")
        self.fx.flash(cx, cy, 100, life=0.25, color=PINK)
        self.stream_T = self.fx.start_stream(*pair, travel=0.9, spread=0.4)
        self.seat = None
        self.set_mode("stream")

    # -- naps: she streams into her biochip in the corner -----------------------------
    def focus(self):
        """Where a camera should look right now: her, her pixels mid-flight, or her napping sprite."""
        st = self.fx.stream
        if self.mode in ("stream", "to_chip") and st and st["pos"]:
            pos = st["pos"]
            return sum(q[0] for q in pos) / len(pos), sum(q[1] for q in pos) / len(pos)
        if self.mode == "chip":
            fp = self.chip.floor_point()
            return fp.x(), fp.y() - self.chip.side * 0.5
        if self.mode in ("hidden", "intro"):  # not placed yet: watch where she'll come from
            g = ledges.work_area(QGuiApplication.primaryScreen())
            return getattr(self, "ix", g.left() + g.width() * 0.72), g.center().y()
        cx, cy = self.center()
        if self.bubble.isVisible():  # frame her line too: the bubble is wider than she is
            return self.bubble.geometry().center().x(), cy - 0.25 * self.S
        return cx, cy

    def chip_spot(self):
        if self.chip_pos:
            return self.chip_pos
        g = ledges.work_area(QGuiApplication.primaryScreen())
        return g.left() + self.chip.side * 0.62, g.bottom() + 1

    def _chip_moved(self):
        p = self.chip.floor_point()
        self.chip_pos = (p.x(), p.y())

    def go_chip(self, instant=False):
        if self.mode not in ("stand", "perch", "hidden"):
            return
        self.bubble.close_bubble()
        self.seat = None
        cx, cy = self.chip_spot()
        if instant or self.mode == "hidden":
            self.body.hide()
            return self._chip_arrive(quiet=True)
        step = 0.8 * STREAM_STEP * self.k
        pair = self._pair(self.sp[self.shown].sample(self.frame, self.x, self.y, step),
                          sample_chip(self.chip.side, self.dpr, cx, cy, step), step)
        self.body.hide()
        self.sfx.play("stream")
        if pair:
            self.stream_T = self.fx.start_stream(*pair, travel=0.8, spread=0.45)
        else:
            self.stream_T = 0.1
        self.set_mode("to_chip")

    def _chip_arrive(self, quiet=False):
        self.fx.end_stream()
        cx, cy = self.chip_spot()
        self.chip.put(cx, cy)
        self.chip.show()
        self.chip.raise_()
        self.set_mode("chip")
        self.nap_len = random.uniform(50, 110)
        self.snore_at = self.now + 2.5
        if not quiet:
            self.sfx.play("sleep")
            self.fx.flash(cx, cy - self.chip.side * 0.4, 70, life=0.25, color=PINK)
            self.fx.sparks(cx, cy - self.chip.side * 0.4, 12, speed=(100, 300), life=(0.15, 0.35))

    def _chip_step(self):
        self.chip.tick()
        if self.mini or self.door.active:
            return
        if self.now > self.snore_at:
            self.sfx.play("snore")
            self.snore_at = self.now + 4.5
        if self.roaming and self.now - self.st > self.nap_len:
            self.wake_chip()

    def wake_chip(self, spot=None):
        """Out of the chip: her pixels stream out and rebuild her (next to the chip unless told where)."""
        if self.mode != "chip":
            return
        self.mini = False
        fp = self.chip.floor_point()
        if spot is None:
            g = ledges.work_area(QGuiApplication.screenAt(fp.toPoint()) or QGuiApplication.primaryScreen())
            x = min(g.right() - 0.5 * self.S, max(g.left() + 0.4 * self.S, fp.x() + 1.3 * self.S))
            L = next((f for f in ledges.floors() if f.holds(x)), ledges.floors()[0])
            spot = (L, x)
        L, x = spot
        step = 0.8 * STREAM_STEP * self.k
        pair = self._pair(sample_chip(self.chip.side, self.dpr, fp.x(), fp.y(), step), self._target_pixels(L, x, step), step)
        self.chip.hide()
        self.sfx.play("wake")
        self.sfx.play("stream")
        self.target = spot
        self.stream_T = self.fx.start_stream(*pair, travel=0.85, spread=0.4) if pair else 0.1
        self.last_touch = self.now
        self.set_mode("stream")

    def arrive(self):
        L, x = self.target
        if L.kind == "peek":
            return self._arrive_peek(L)
        self.target = None
        k, S = self.k, self.S
        self.x, self.y = x, L.y
        self.seat = L
        self.seat_off = None
        perch = L.kind != "floor"
        self.set_mode("appear")
        self.play("perch_glitch" if perch else "glitch")
        cx, cy = self.center()
        gx = x + (0.12 * S if perch else 0)
        self.sfx.play("rebuild")
        self.fx.end_stream()
        self.fx.flash(cx, cy, 110, life=0.3, color=PINK)
        self.white, self.sx, self.sy = 0.8, 1.0, 1.0
        self.fx.ring(gx, L.y, 150, life=0.45, color=CYAN, width=2.4, flat=0.2)
        self.fx.pixels(gx, L.y - 2, 10, self.sp.color, speed=(120, 320), up=(210, 330), ground=L.y, life=(0.8, 1.4), size=(3, 6))
        self._place()
        self.body.show()

    def _arrive_peek(self, L):
        self.target = None
        self.seat = L
        self.peek_edge = L.edge
        self.peek_angle = {"left": 90, "right": -90, "top": 180}[L.edge]
        self.pc = self._peek_center(L)
        self.peek_len = random.uniform(15, 35)
        cx, cy = self.pc
        # her canvas middle on that point (the body window is placed from x / y and the anchor)
        self.x = cx - 0.75 * self.S + self.A.x()
        self.y = cy - 0.75 * self.S + self.A.y()
        self.angle = 0.0
        self.set_mode("appear")
        self.play("idle")
        self.sfx.play("rebuild")
        self.fx.end_stream()
        hx, hy = self.head()
        self.fx.flash(hx, hy, 100, life=0.3, color=PINK)
        self.white, self.sx, self.sy = 0.8, 1.0, 1.0
        self._place()
        self.body.show()

    def _appear_step(self):
        t = min(1.0, (self.now - self.st) / 0.38)
        self.white = max(0.0, 0.8 - t * 1.3)
        if t >= 1 and self._peeking():
            self.white = 0
            self.set_mode("peek")
            if random.random() < 0.35:
                line = random.choice(PEEKS)
                if line:
                    QTimer.singleShot(700, lambda: self.say(line))
            self._settled()
            return
        if t >= 1:
            self.sx = self.sy = 1.0
            self.white = 0
            self.set_mode("perch" if self.seat.kind != "floor" else "stand")
            self.next_roam = self.now + random.uniform(*self.roam)
            if self.say_after:  # just arrived on your desktop: hi!
                line, self.say_after = self.say_after, None
                self.play("grin")
                QTimer.singleShot(350, lambda: self.say(line))
            elif self.roaming and random.random() < 0.2:
                line = random.choice(ARRIVALS)
                if line:
                    QTimer.singleShot(500, lambda: self.say(line))
            self._settled()

    # -- mouse: click to chat, drag to carry, let go to throw ---------------------------
    def press(self, e):
        if e.button() != Qt.LeftButton or self.mode not in ("stand", "perch", "sleep", "fall", "peek"):
            return
        self.press_at = e.globalPosition()
        self.grab = e.position()
        self.hist = [(self.now, self.press_at.x(), self.press_at.y())]
        if self.mode == "fall":  # snatch her out of the air
            self._grab()

    def _grab(self):
        if self._peeking():  # pulled out of the edge: upright, under the cursor
            cx, cy = self.pc
            self.seat = None
            self.angle = 0.0
            self.x, self.y = cx, cy + 0.5 * self.sp["idle"].h
            g = QCursor.pos()
            self.grab = QPointF(g.x() - self.x + self.A.x(), g.y() - self.y + self.A.y())
        self.set_mode("held")
        self.seat = None
        self.play("dangle")
        self.bubble.close_bubble()
        self.white = 0
        self.sx = self.sy = 1.0
        self.sfx.play("grab")

    def drag_move(self, e):
        if self.press_at is None:
            return
        g = e.globalPosition()
        if self.mode != "held":
            if (g - self.press_at).manhattanLength() < 6:
                return
            self._grab()
        self.hist.append((self.now, g.x(), g.y()))
        self.hist = self.hist[-8:]

    def _held_step(self):
        g = QCursor.pos()
        nx = g.x() - self.grab.x() + self.A.x()
        ny = g.y() - self.grab.y() + self.A.y()
        vx = (nx - self.x) * 60
        self.x, self.y = nx, ny
        self.angle += (max(-30, min(30, -vx * 0.012)) - self.angle) * 0.18  # swings behind the motion

    def release(self, e):
        if e.button() != Qt.LeftButton:
            return
        was = self.press_at
        self.press_at = None
        if self.mode != "held":
            if was is not None:
                self.click()
            return
        recent = [h for h in self.hist if self.now - h[0] < 0.09] or self.hist[-2:]
        vx = vy = 0.0
        if len(recent) >= 2 and recent[-1][0] > recent[0][0]:
            span = recent[-1][0] - recent[0][0]
            vx = (recent[-1][1] - recent[0][1]) / span
            vy = (recent[-1][2] - recent[0][2]) / span
        cap = 3200 * self.k
        vx, vy = max(-cap, min(cap, vx)), max(-cap, min(cap, vy))
        self.ledges_at = -9
        if math.hypot(vx, vy) < 900 * self.k:  # set down against a screen edge: she tucks in and peeks from it
            g = QCursor.pos()
            L = self._edge_peek(g.x(), g.y())
            if L is not None:
                self.target = (L, 0.0)
                self._arrive_peek(L)
                self.last_touch = self.now
                return
        if math.hypot(vx, vy) > 900 * self.k:
            self.sfx.play("throw")
        self.fall_from_here(vx, vy)
        self.last_touch = self.now

    def click(self):
        self.last_touch = self.now
        if self.mode == "peek":  # caught peeking
            return self.pop_out(random.choice(POP_OUTS))
        self.sfx.play("pop")
        if self.mode == "sleep":
            self.wake()
            return
        if self.bubble.typing:
            self.bubble.close_bubble()
        else:
            hx, hy = self.head()
            self.bubble.open_input()
            self.bubble.place(hx, hy, self.screen_rect(hx, self.y - 10))
        self.next_roam = max(self.next_roam, self.now + 20)

    # -- talking ----------------------------------------------------------------
    def say(self, text, user="", done=None, more=False):
        """Speak a line: the bubble types it in step with her voice, her mouth moves while the audio plays.
        more=True: the reply is still being written; say_more() adds sentences, say_end() closes it (blips only)."""
        if self.mode == "sleep":
            self.wake()
        self.next_roam = max(self.next_roam, self.now + 30)

        def started(secs, cps=None):
            if not self.bubble.isVisible():
                self.sfx.play("pop")
            self.speaking = True
            self.blip_n = 0
            self.bubble.say(text, user=user, secs=secs, cps=cps)

        def ended():
            self.speaking = False
            self.bubble.release(2.4)
            self.next_roam = max(self.next_roam, self.now + 8)
            if done:
                done()

        if self.blips:  # no voice: old-school RPG text blips, paced by the bubble; done once it's all typed
            started(None, 24.0)
            self.talk_open = more
            if self.talk_timer is not None:
                self.talk_timer.stop()
            timer = QTimer()

            def check():
                if not self.talk_open and self.bubble.typed_all():
                    timer.stop()
                    QTimer.singleShot(200, ended)

            timer.timeout.connect(check)
            timer.start(50)
            self.talk_timer = timer
        elif self.voice:
            self.voice(text, started, ended)
        else:
            secs = min(9.0, 0.6 + len(text) * 0.05)
            started(secs)
            QTimer.singleShot(int(secs * 1000), ended)

    def _typed(self, ch: str):
        if self.blips and self.speaking:
            self.blip_n += 1
            if self.blip_n % 2:  # every other letter, like the old handhelds
                self.sfx.play("blip", ch.lower())

    def say_more(self, text: str):
        if self.speaking:
            self.bubble.append(text)
        else:  # the first line already finished: start a fresh one
            self.say(text, more=True)

    def say_end(self):
        self.talk_open = False

    def nap(self):
        """A nap she takes herself (the brain decides): snores, and wakes up again after a while."""
        self.mini = False
        self.chip.zs = True
        self.go_chip()

    def toggle_mini(self):
        if self.mode == "chip":
            self.wake_chip()
        elif self.mode in ("stand", "perch", "hidden"):
            self.mini = True
            self.chip.zs = False
            self.go_chip()

    # -- her menu, drawn inside a glitchy door that opens beside her (beside the chip in mini mode) -------
    def open_menu(self):
        D = self.door
        if D.active or self.mode not in ("stand", "perch", "sleep", "chip", "appear"):
            return
        w, h = D.size_for(self.menu)
        self.next_roam = max(self.next_roam, self.now + 30)
        self.press_at = None  # a left press the menu swallowed must not turn into a drag once it closes
        if self.mode == "chip":
            fp = self.chip.floor_point()
            side = self.chip.side
            g = ledges.work_area(QGuiApplication.screenAt(fp.toPoint()) or QGuiApplication.primaryScreen())
            gap = 0.15 * side
            pad = side + gap  # the chip's spot, left of the door
            cx = 0.5 * side  # chip centre, in the door window
            x = min(max(fp.x() - cx, g.left()), g.right() - (pad + w))
            y = min(max(fp.y() - 0.42 * side - h / 2, g.top()), g.bottom() - h)
            self.chip_home = (fp.x(), fp.y())
            self.chip.put(x + cx, y + h / 2 + 0.42 * side)  # halfway up the door's left side
            self.chip.glitch_until = time.monotonic() + 0.2
            D.open(x, y, pad, link=(cx + 0.3 * side, pad + INSIDE.left() * D.sx + 4, h / 2), on_closed=self._menu_closed)
            self.chip.raise_()
        else:
            cx, cy = self.center()
            g = ledges.work_area(QGuiApplication.screenAt(QPointF(cx, cy).toPoint()) or QGuiApplication.primaryScreen())
            reach = 0.3 * self.S
            x = cx + reach
            if x + w > g.right():  # no room on her right: open on her left
                x = cx - reach - w
            x = min(max(x, g.left()), g.right() - w)
            y = min(max(cy - h / 2, g.top()), g.bottom() - h)
            D.open(x, y, on_closed=self._menu_closed)

    def _menu_closed(self):
        self.next_roam = max(self.next_roam, self.now + 8)
        if self.chip_home and self.mode == "chip":  # back where it was
            self.chip.glitch_until = time.monotonic() + 0.2
            self.chip.put(*self.chip_home)
        self.chip_home = None

    # -- quitting: a goodbye line, then she switches off like an old CRT --------------------
    def bye(self, then):
        if self.mode == "bye":
            return
        self.roaming = False
        if self.mode == "chip":  # the nap sprite just blinks out
            fp = self.chip.floor_point()
            self.chip.hide()
            self._crt_dot(fp.x(), fp.y() - self.chip.side * 0.45, fp.y())
            QTimer.singleShot(1500, then)
            return
        if self.mode in ("stand", "perch"):
            self.say(random.choice(BYES), done=lambda: self._crt_off(then))
        else:
            self._crt_off(then)

    def _crt_off(self, then):
        self.bubble.close_bubble()
        if not self.body.isVisible():
            QTimer.singleShot(300, then)
            return
        self.play("perch_glitch" if self.mode == "perch" else "glitch")
        self.bye_then = then
        self.bye_stage = 0
        if self.portal is None:
            self.portal = Portal(self.k, self._screen_face)
        self.portal.start(ledges.work_area(QGuiApplication.primaryScreen()), leaving=True)
        self.sfx.play("charge")
        self.set_mode("bye")

    def _bye_step(self):
        """The entrance backwards: the brackets lock on at the top right, she streams up into them, the little screen
        flicks on with her face and a "cya" sticker, then shuts down to a dot and the brackets fly apart."""
        t = self.now - self.st
        P = self.portal
        if self.bye_stage == 0:
            self.white = min(0.5, t / 0.35 * 0.5)  # glowing up before she goes
            if t < 0.35:
                return
            g = P.screen_rect()
            cx, cy = g.center().x(), g.center().y()
            step = STREAM_STEP * self.k
            c = self.sp["idle"]
            ax, ay = c.anchor
            dot = [(cx + (px - cx) * 0.1, cy + (py - cy) * 0.1, col)
                   for px, py, col in c.sample(0, cx + (ax - 0.5) * c.w, cy + (ay - 0.5) * c.h, step)]
            pair = self._pair(self.sp[self.shown].sample(self.frame, self.x, self.y, step), dot, step)
            self.body.hide()
            self.white = 0.0
            self.sfx.play("stream")
            self.bye_T = self.now + (self.fx.start_stream(*pair, travel=0.85, spread=0.35) if pair else 0.1)
            self.bye_stage = 1
        elif self.bye_stage == 1 and self.now > self.bye_T:  # all of her is in: the screen comes on
            self.fx.end_stream()
            c = P.screen_rect().center()
            self.fx.flash(c.x(), c.y(), 90, life=0.3, color=PINK)
            self.bye_stage = 2
        elif self.bye_stage == 2 and P.t > SCREEN_FACE:
            c = P.screen_rect().center()
            self.fx.burst(c.x(), c.y(), 12, r0=10, r1=420, life=0.45, width=(4, 14))
            self.sfx.play("crtoff")
            self.bye_stage = 3
        elif self.bye_stage == 3 and P.done:
            P.hide()
            self.sx = self.sy = 1.0
            self.set_mode("hidden")
            QTimer.singleShot(250, self.bye_then)

    def _crt_dot(self, x, y, floor):
        """The last glowing pixel hangs for a beat, then drops and bounces on the floor. Bloop."""
        self.fx.flash(x, y, 60, life=0.5)
        self.fx.embers(x, y, 3, radius=3, colors=(WHITE,))
        QTimer.singleShot(450, lambda: (self.fx.parts.append(_dot(x, y, floor, self.k)), self.sfx.play("bloop")))

    def heard(self, line: str):
        self.bubble.think(line)
        self.next_roam = max(self.next_roam, self.now + 40)
        if self.on_user:
            self.on_user(line)
        else:
            QTimer.singleShot(900, lambda: self.say(random.choice(DEMO_REPLIES), user=line))

    # -- menu / tray -------------------------------------------------------------
    def _build_menu(self):
        m = self.menu = QMenu()
        m.setStyleSheet(
            "QMenu { background: rgb(14,6,22); color: rgb(246,240,250); border: 1px solid rgb(255,20,96); padding: 4px; }"
            "QMenu::item { padding: 5px 18px; } QMenu::item:selected { background: rgb(255,20,96); color: black; }"
            "QMenu::separator { height: 1px; background: rgb(60,30,70); margin: 4px 8px; }")
        m.addAction("Talk to her", self.click)
        self.nap_action = m.addAction("Go mini", self.toggle_mini)
        m.addSeparator()
        roam = QAction("Roam the grid", m, checkable=True, checked=True)
        roam.toggled.connect(lambda on: setattr(self, "roaming", on))
        m.addAction(roam)
        self.roam_action = roam
        m.addSeparator()
        m.addAction("Quit", lambda: self.bye(self.quit_fn))
        m.aboutToShow.connect(lambda: self.nap_action.setText("Back to full size" if self.mode == "chip" else "Go mini"))

    def _build_tray(self):
        from ..config import ASSETS

        icon = QIcon(str(ASSETS / "icons" / "tray.png"))
        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip("Capri  //  click: go mini / back to full size")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(lambda r: self.toggle_mini() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _topmost(self):
        import ctypes

        for w in (self.body, self.bubble):
            if w.isVisible():
                ctypes.windll.user32.SetWindowPos(int(w.winId()), -1, 0, 0, 0, 0, 0x2 | 0x1 | 0x10)
