"""Wires Capri on the desktop to her brain (Mistral-Nemo + memory), ears (faster-whisper), eyes (window + OCR),
music (YouTube DJ + a beat ear on your speakers) and voice."""
from __future__ import annotations

import os
import random
import re
import sys
import threading
from pathlib import Path
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QApplication

from .. import config
from ..voice import tts as tts_mod
from .capri import Capri
from .settings import Settings


class Bridge(QObject):
    """Thread-safe hop from worker threads (brain, ears, voice) back onto the Qt thread."""

    replied = Signal(str, str, bool)  # her text, what the user said ("" = her own idea), go nap afterwards
    part = Signal(str, str, bool)  # one sentence of a reply still being written, what the user said, first sentence?
    part_end = Signal(bool)  # that reply is finished (go nap afterwards?)
    started = Signal(object, float)  # line token, seconds of audio
    ended = Signal(object)
    heard = Signal(str)
    hearing = Signal(bool)
    level = Signal(float)
    fetched = Signal(object)  # a download finished: run this on the Qt thread


def idle_seconds() -> float:
    """Seconds since the last keyboard / mouse input anywhere on Windows."""
    if sys.platform != "win32":
        from .. import linux

        return linux.idle_seconds() if sys.platform.startswith("linux") else 0.0
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


def _open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)
    else:
        from .. import linux

        linux.open_path(path)


def _alike(a: str, b: str) -> bool:
    """Two OCR reads of the same text (they differ by a letter here and there)."""
    import difflib

    if not a or not b:
        return False
    a, b = re.sub(r"\W+", "", a.lower()), re.sub(r"\W+", "", b.lower())
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.85


class DeskApp:
    def __init__(self, video: bool = False):
        self.cfg = config.load()
        d = self.cfg["desk"]
        self.video_mode = video
        self.s = Settings(self.cfg)
        self.bridge = Bridge()
        size = int(d["video_size"] if video else (self.s["size"] or d["size"]))  # bigger for the camera
        self.dev = self.cfg.get("edition") == "dev"  # the portable test build for other devs
        self.capri = Capri(size, tuple(d["roam_seconds"]), intro=bool(d["intro"]) and not video, start=not video)
        self.capri.voice = self.voice
        self.capri.greeting = lambda: None if self.capri.blips else tts_mod.greeting()  # her recorded hello
        self.capri.blips = True  # until her voice is picked below
        self.capri.on_user = self.on_user
        self.capri.quit_fn = self.quit
        self.on_quit: list = []
        self.lines: dict[object, tuple] = {}
        b = self.bridge
        b.replied.connect(self._replied)
        b.part.connect(self._part)
        b.part_end.connect(self._part_end)
        self.nap_after = False
        b.started.connect(lambda tok, secs: self.lines[tok][0](secs) if tok in self.lines else None)
        b.ended.connect(self._ended)
        b.heard.connect(self.capri.heard)
        b.hearing.connect(self._hearing)
        b.fetched.connect(lambda then: then())
        self.dl = None  # what's downloading right now, shown at the top of her Brain menu ("Getting X: 40%")
        self.dl_action = None
        b.level.connect(lambda v: setattr(self.capri.bubble, "mic_level", v))
        self.agent = None
        self.busy = threading.Lock()
        self.tts = tts_mod.NoTTS()
        self._set_voice(self.s["voice"], quiet=True)
        self.ears = None
        self.beat = None
        if video:  # the video is scripted: no brain, ears or eyes needed
            return
        threading.Thread(target=self._boot, daemon=True).start()
        self._start_ears()
        QTimer.singleShot(5000, self._start_beat)  # after boot: starting it mid-startup raced numpy imports and crashed
        self._build_menu()
        # what she keeps an eye on
        self.title = ""
        self.last_own = time.monotonic()  # last time she said something unprompted
        self.last_talk = time.monotonic()  # last time you two talked
        self.idle_pinged = False
        self.song = ""  # YouTube song in the browser
        self.song_since = 0.0
        self.song_judged = ""
        self.her_pick = ""  # what she put on (DJ mode), so she doesn't judge her own pick
        self.last_glance = 0.0
        from ..abilities.music import Playlist

        self.playlist = Playlist()
        # game mode, focus nagging, and reacting to videos / chats / what you type
        self.game = None  # (game, since) while you're in one
        self.react_video, self.video_since, self.video_done = "", 0.0, True
        self.last_react = 0.0  # her last reaction to a video / chat (they have their own pace)
        self.last_nag, self.nag_due = 0.0, False
        self.last_read, self.reading = 0.0, False
        self.chat_last, self.draft_prev, self.draft_said = "", "", ""
        self.react_next = None  # (draft, make line): what the chat reader wants her to say next
        self.hello_due, self.video_roll = False, False
        self.watch = QTimer()
        self.watch.timeout.connect(self._watch)
        self.watch.start(3000)

    # -- boot ---------------------------------------------------------------------
    def _boot(self):
        from ..brain.agent import Agent

        t = time.monotonic()
        brain = self.s["brain"]  # picked from her Brain menu
        if brain:
            self.cfg["llm"]["model_path"] = brain
        self.agent = Agent(self.cfg)
        self.agent.on_played = self._played
        self.agent.settings = self.s  # "leave me alone", never-look apps, focus mode, city... change them by voice
        from ..abilities import screen

        screen.never_look = list(self.s["never_look"])
        from ..abilities.reminders import describe

        # a timer / alarm / reminder going off: she wakes up and says it (the alarm sound is already ringing)
        self.agent.on_reminder = lambda item: self.bridge.replied.emit(describe(item), "", False)
        self.agent.reminders.start()
        from ..abilities.launcher import warm_youtube

        threading.Thread(target=warm_youtube, daemon=True).start()
        try:
            self.agent.warm_up()
        except Exception as e:
            print(f"[capri] warm-up failed: {e}")
        print(f"[capri] brain online in {time.monotonic() - t:.1f}s")
        if (self.cfg["llm"].get("model_path") or "").lower() == "none" and not self.s["my_brains"]:
            from .. import portable

            if not portable.brains():  # first run: point at where her brain comes from
                self.bridge.replied.emit("No brain chip in me yet. Right-click me, Brain, and pick one to download.",
                                         "", False)
        sight_dir = None if self.dev else self.cfg.get("sight", {}).get("model_dir")
        if getattr(self.agent.llm, "vision", False):  # her brain came with eyes (an mmproj): no second model needed
            from ..abilities.sight import BrainEyes

            self.agent.eyes = BrainEyes(self.agent.llm)
            sight_dir = None
        if sight_dir:  # her real eyes load after the brain, so they only take what VRAM is left
            from ..abilities.sight import Eyes
            from ..brain.llm import GPU_LOCK

            for _ in range(120):  # the ears import the same libraries: loading both at once broke transformers' imports
                if self.ears is None or self.ears.stt is not None or not self.ears.is_alive():
                    break
                time.sleep(0.5)
            eyes = Eyes(sight_dir, GPU_LOCK)
            eyes.load()
            if not eyes.ok and "ImportError" in (eyes.error or ""):
                time.sleep(3)
                eyes = Eyes(sight_dir, GPU_LOCK)
                eyes.load()
            self.agent.eyes = eyes

    def _played(self, result: str):
        if result.startswith("playing"):
            self.her_pick = result[len("playing "):].rsplit(" on YouTube", 1)[0]

    def _start_ears(self):
        try:
            from ..voice.stt import Listener

            if self.s["whisper_model"]:
                self.cfg["stt"]["whisper_model"] = self.s["whisper_model"]
            self.ears = Listener(self.cfg, self.s, self.bridge.heard.emit, self.bridge.hearing.emit, self.bridge.level.emit)
            self.ears.start()
        except Exception as e:
            print(f"[capri] ears unavailable: {e}")

    def _start_beat(self):
        try:
            from ..abilities.music import BeatEar

            self.beat = BeatEar()
            self.beat.start()
            # music = a YouTube song in the browser, or a steady beat (not game explosions)
            music = lambda: self.beat.playing and (bool(getattr(self, "song", "")) or self.beat.rhythmic)  # noqa: E731
            self.capri.beat = lambda: (self.beat.pulse, music()) if self.s["vibe"] else (0.0, False)
            self.capri.sfx.quiet = music  # no booms or zaps over your songs
        except Exception as e:
            print(f"[capri] beat ear unavailable: {e}")

    def _set_voice(self, on: bool, quiet: bool = False):
        """Her voice on (her clone, else Kokoro, offline) or off (soft talking blips). Saved; from her next line."""
        self.s.set("voice", bool(on))
        backend = self.cfg["tts"]["backend"]
        if on and backend in ("blips", "none", "kokoro", "clone"):
            backend = "clone" if tts_mod.CloneTTS.installed() else "kokoro"
        elif not on:
            backend = "blips"
        if backend == "kokoro" and not tts_mod.KokoroTTS.installed(tts_mod.kokoro_dir(self.cfg)):
            if not quiet:
                self._get_voice()
            backend = "blips"
        cfg = dict(self.cfg, tts=dict(self.cfg["tts"], backend=backend))
        self.tts = tts_mod.create(cfg) if backend != "blips" else tts_mod.NoTTS()
        self.capri.blips = backend == "blips"
        print(f"[capri] voice: {backend}")

    def _hearing(self, on: bool):
        self.capri.listening(on)
        if on:
            self.last_talk = time.monotonic()

    # -- voice --------------------------------------------------------------------
    def voice(self, text, on_start, on_end):
        tok = object()
        self.lines[tok] = (on_start, on_end)
        start, end = lambda secs: self.bridge.started.emit(tok, secs), lambda: self.bridge.ended.emit(tok)
        if not self.capri.blips and tts_mod.play_recorded(text, start, end):  # her own recorded hello
            return
        tts_mod.speak_async(self.tts, text, start, end)

    def _ended(self, tok):
        cbs = self.lines.pop(tok, None)
        if cbs:
            cbs[1]()

    # -- brain --------------------------------------------------------------------
    def on_user(self, line: str):
        self.last_talk = time.monotonic()
        if self.agent is None:
            self.capri.say("Hold up, choom, my brain's still booting. Gimme a sec.", user=line)
            return
        if not self.busy.acquire(blocking=False):
            return
        print(f"[capri] you: {line}")

        def work():
            t = time.monotonic()
            try:
                first = [True]

                def sentence(s):
                    if first[0]:
                        print(f"[capri] first words after {time.monotonic() - t:.2f}s")
                    self.bridge.part.emit(s, line, first[0])
                    first[0] = False

                streaming = self.capri.blips  # a real voice needs the whole line before it can speak
                reply = self.agent.respond(line, on_sentence=sentence if streaming else None)
                for a in reply.actions:
                    print(f"[capri] {a}")
                print(f"[capri] capri ({time.monotonic() - t:.1f}s): {reply.text}")
                if streaming and not first[0]:
                    self.bridge.part_end.emit(reply.go_idle)
                else:
                    self.bridge.replied.emit(reply.text, line, reply.go_idle)
                threading.Thread(target=self.agent.learn, args=(line,), daemon=True).start()
            except Exception as e:
                import traceback

                traceback.print_exc()
                self.bridge.replied.emit(f"Something flatlined in my code: {e}", line, False)
            finally:
                self.busy.release()

        threading.Thread(target=work, daemon=True).start()

    def _replied(self, text: str, line: str, nap: bool):
        if self.ears:
            self.ears.muted = True  # auto mode: don't transcribe her own blips

        def done():
            if self.ears:
                self.ears.muted = False
            if nap:
                self.capri.nap()

        self.capri.say(text, user=line, done=done)

    def _part(self, text: str, line: str, first: bool):
        if not first:
            self.capri.say_more(text)
            return
        if self.ears:
            self.ears.muted = True
        self.nap_after = False

        def done():
            if self.ears:
                self.ears.muted = False
            if self.nap_after:
                self.capri.nap()

        self.capri.say(text, user=line, done=done, more=True)

    def _part_end(self, nap: bool):
        self.nap_after = nap
        self.capri.say_end()

    def _own(self, make, then=None) -> bool:
        """Something she brings up herself: think in the background, say it if it's still a good moment.
        -> False when it isn't one (she's busy, napping, mid-teleport), so the caller can try again later."""
        if self.agent is None or self.capri.mode not in ("stand", "perch") or self.capri.speaking or self.capri.bubble.isVisible():
            return False
        if not self.busy.acquire(blocking=False):
            return False
        self.last_own = time.monotonic()

        def work():
            try:
                text = make()
                if text:
                    print(f"[capri] capri (own): {text}")
                    self.bridge.replied.emit(text, "", False)
                if then:
                    then()
            except Exception as e:
                print(f"[capri] own line failed: {e}")
            finally:
                self.busy.release()

        threading.Thread(target=work, daemon=True).start()
        return True

    # -- eyes, chatter and the DJ (every 3 s) --------------------------------------------------
    def _watch(self):
        from ..abilities import vision
        from ..abilities.music import CYBER

        if self.agent is None:
            return
        d = self.cfg["desk"]
        now = time.monotonic()
        cooldown = d["react_cooldown_minutes"] * 60
        idle = idle_seconds()

        # what's playing on YouTube (any window, even behind others)
        song = vision.youtube_song(vision.window_titles())
        self.agent.now_playing = song
        if song != self.song:
            self.song, self.song_since = song, now
        playing = song and (self.beat is None or self.beat.playing)

        # her eyes: a fresh glance when you switch windows (and every 30 s anyway)
        from ..abilities import screen

        title = vision.active_window_title().strip()
        own_window = not title or title in ("Capri", "Capri CMD") or "Program Manager" in title
        switched = title != self.title and not own_window
        if switched:
            self.title = title
        exe = screen.foreground_exe() if not own_window else ""
        kind, name = screen.kind(title, exe) if not own_window else ("other", "")
        quiet = self.s["quiet"]  # "leave me alone": no reading your screen, no talking on her own
        hidden = quiet or screen.private(title, exe) or (kind == "game" and self.s["game_mode"])
        if self.s["eyes"] and not own_window and not hidden and (switched or now - self.last_glance > 30):
            self.last_glance = now

            def look():
                t, text = vision.glance()
                self.agent.glance = {"t": time.time(), "title": t, "text": text}

            threading.Thread(target=look, daemon=True).start()

        if quiet or getattr(self, "video", None) is not None:  # a scripted video records: it does the talking
            return
        # focus mode: quiet, except to send you back to work when you wander off
        focus_left = self.s["focus_until"] - time.time()
        if focus_left > 0:
            # the moment you open one, then every 3 minutes you stay on it
            if kind in ("youtube", "distracting", "game", "chat"):
                if switched:
                    self.nag_due = True
                if self.nag_due or now - self.last_nag > 180:
                    if self.capri.mode == "chip":
                        self.capri.wake_chip()  # she wakes up to catch you
                        return
                    where, left = name or title, int(focus_left // 60) + 1
                    if self._own(lambda: self.agent.focus_nag(where, left)):
                        self.last_nag, self.nag_due = now, False
            else:
                self.nag_due = False
            return
        # game mode: not a word while you play; when you stop, she asks how it went
        if kind == "game" and self.s["game_mode"]:
            if self.game is None or self.game[0] != name:
                self.game = (name, now)
            return
        if self.game and not own_window:
            game, since = self.game
            self.game = None
            mins = int((now - since) // 60)
            if mins >= 3 and self.s["chatter"]:
                QTimer.singleShot(4000, lambda: self._own(lambda: self.agent.game_over(game, mins)))
                return
        if self.s["chatter"] and self.s["reactions"] and not screen.private(title, exe):
            if self._react(kind, name, title, exe, switched, now):
                return

        # DJ: judge a new song once it's been on a bit
        if playing and song != self.song_judged and now - self.song_since > 12:
            self.song_judged = song
            mine = self.her_pick and _same_song(self.her_pick, song)
            if mine:
                if random.random() < 0.6:
                    self._own(lambda: self.agent.hype_line(song))
                return
            if self.s["dj"] and not self.dev and not CYBER.search(song):
                pick = self.playlist.next()

                def swap():
                    from ..abilities import launcher
                    from ..abilities.spotify import _media_key

                    _media_key("pause")
                    time.sleep(0.4)
                    result = launcher.youtube_play(pick)
                    print(f"[capri] DJ: {result}")
                    if result.startswith("playing"):
                        self.her_pick = result[len("playing "):].rsplit(" on YouTube", 1)[0]

                self._own(lambda: self.agent.music_take(song, switching_to=pick.split(" (")[0]), then=swap)
                return
            if now - self.last_own > cooldown and random.random() < 0.5:
                self._own(lambda: self.agent.music_take(song))
                return

        if not self.s["chatter"]:
            return
        # you've been gone a while
        if idle > d["chatter_idle_minutes"] * 60:
            if not self.idle_pinged and now - self.last_own > cooldown:
                self.idle_pinged = True
                self._own(lambda: self.agent.idle_line(int(idle // 60)))
            return
        self.idle_pinged = False
        # you just opened something new (videos and chats have their own reactions)
        if switched and kind not in ("youtube", "chat", "game") and now - self.last_own > cooldown \
                and now - self.last_talk > 60 and random.random() < 0.5:
            QTimer.singleShot(2500, lambda: self._own(lambda: self.agent.react_line(title)))  # after the glance lands

    def _react(self, kind: str, name: str, title: str, exe: str, switched: bool, now: float) -> bool:
        """Reacting like a friend next to you: the YouTube video you're watching (and its comments once you scroll
        to them), the chat you're in, and what you're typing in it. -> True when she's busy with one.
        A reaction only counts (cooldown, "already said") once she actually says it."""
        from ..abilities import screen

        if self.capri.mode == "chip" and (self.react_next is not None or self.hello_due or kind == "youtube"
                                          and not self.video_done and now - self.video_since > 20):
            self.capri.wake_chip()  # something juicy on screen: she wakes up for it (says it next tick)
            return True
        if self.react_next is not None:  # the chat reader (a thread) found something: say it from here
            make, self.react_next = self.react_next, None
            if self._own(make[1]):
                self.last_react = now
                if make[0]:
                    self.draft_said = make[0]
                return True
        if kind != "chat":
            self.chat_last = self.draft_prev = ""
        if now - self.last_talk < 30:  # you're talking to her: not the moment
            return False
        if kind == "youtube":
            if name != self.react_video:
                self.react_video, self.video_since, self.video_done = name, now, False
                self.video_roll = random.random() < 0.7  # not every video
            elif not self.video_done and self.video_roll and now - self.video_since > 25 and now - self.last_react > 120:
                if self._own(lambda: self.agent.youtube_take(name, screen.read_comments(title))):
                    self.video_done, self.last_react = True, now
                    return True
            return False
        if kind != "chat":
            return False
        if switched:
            self.hello_due = now - self.last_react > 180 and random.random() < 0.5
        if self.hello_due and now - self.last_react > 180:
            if self._own(lambda: self.agent.chat_hello(name)):
                self.hello_due, self.last_react = False, now
                return True
        if self.reading or now - self.last_read < 5:
            return False
        self.last_read, self.reading = now, True

        def read():
            try:
                msgs, draft = screen.read_chat(name, title, exe)
                newest = msgs[-1] if msgs else ""
                fresh = bool(newest) and bool(self.chat_last) and not _alike(newest, self.chat_last)
                t = time.monotonic()
                if draft and _alike(draft, self.draft_prev) and not _alike(draft, self.draft_said) and len(draft) > 6 \
                        and t - self.last_react > 75:
                    # the same draft for 5+ s: you've stopped to think, she has a look
                    if random.random() < 0.6:
                        self.react_next = (draft, lambda: self.agent.typing_take(name, draft, msgs))
                    else:
                        self.draft_said = draft
                elif fresh and not draft and t - self.last_react > 150 and random.random() < 0.5:
                    self.react_next = ("", lambda: self.agent.chat_take(name, msgs))
                self.draft_prev, self.chat_last = draft, newest or self.chat_last
            finally:
                self.reading = False

        threading.Thread(target=read, daemon=True).start()
        return False

    # -- menu ---------------------------------------------------------------------
    def _build_menu(self):
        from ..voice import hotkey

        self._hotkey = hotkey
        m = self.capri.menu
        before = m.actions()[-1]  # keep "Delta (quit)" last
        ears = m.addMenu("Ears")
        m.insertMenu(before, ears)
        group = QActionGroup(ears)
        self.ear_actions = {}
        for mode, label in (("hold", "Hold to talk"), ("auto", "Auto (always listening)"), ("off", "Off")):
            a = QAction(label, ears, checkable=True, checked=self.s["ears"] == mode)
            a.triggered.connect(lambda _=False, md=mode: self.s.set("ears", md))
            group.addAction(a)
            ears.addAction(a)
            self.ear_actions[mode] = a
        ears.addSeparator()
        self.key_action = ears.addAction("Change talk key", self._rebind)
        mics = ears.addMenu("Mic")
        ears.aboutToShow.connect(lambda: self._fill_ears(mics))
        if self.dev:  # her whisper model, picked in setup; switching restarts her ears
            self._ear_models = ears.addMenu("Model")
            ears.aboutToShow.connect(self._fill_ear_models)
        voice = QAction("Her voice  (talks out loud)", m, checkable=True, checked=bool(self.s["voice"]))
        voice.toggled.connect(lambda on: self._set_voice(on))
        m.insertAction(before, voice)
        toggles = (("vibe", "Vibe to the music"),
                   ("eyes", "Watch my screen"), ("chatter", "Chatter / react  (she talks on her own)"),
                   ("reactions", "React to videos, chats && what I type"), ("game_mode", "Game mode  (quiet while I play)"),
                   ("quiet", "Leave me alone  (no watching, no chatter)"))
        self.toggle_actions = {}
        for key, label in toggles:
            a = QAction(label, m, checkable=True, checked=bool(self.s[key]))
            a.toggled.connect(lambda on, k=key: self.s.set(k, on))
            m.insertAction(before, a)
            self.toggle_actions[key] = a

        def sync():  # some of these change by voice ("leave me alone"): the ticks follow
            for k, act in self.toggle_actions.items():
                if act.isChecked() != bool(self.s[k]):
                    act.blockSignals(True)
                    act.setChecked(bool(self.s[k]))
                    act.blockSignals(False)

        m.aboutToShow.connect(sync)
        m.insertSeparator(before)
        sizes = m.addMenu("Size")
        m.insertMenu(before, sizes)
        for label, px in (("Tiny", 150), ("Small", 190), ("Medium", 240), ("Large", 320), ("Huge", 420)):
            a = sizes.addAction(label)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, v=px: (self.s.set("size", v), self.capri.set_size(v)))
            sizes.aboutToShow.connect(lambda a=a, v=px: a.setChecked(self.capri.S == v))
        brains = m.addMenu("Brain")
        m.insertMenu(before, brains)
        brains.aboutToShow.connect(lambda: self._fill_brains(brains))
        m.insertSeparator(before)

    def _fill_brains(self, menu):
        """Every .gguf in ERU AI's models/llm folder; picking one swaps her brain live (a few seconds). Brains she
        doesn't have yet are right there too: picking one downloads it (and her brain engine if it's missing)."""
        import glob

        from .. import portable

        menu.clear()
        self.dl_action = None
        if self.dl:
            self.dl_action = menu.addAction(self.dl)
            self.dl_action.setEnabled(False)
            menu.addSeparator()
        mp = self.cfg["llm"].get("model_path") or ""
        cur = os.path.normcase(os.path.abspath(mp)) if mp != "none" else "none"
        off = menu.addAction("No AI  (just her: apps, timers, music... no chatting)")
        off.setCheckable(True)
        off.setChecked(cur == "none")
        off.triggered.connect(lambda _=False: self._swap_brain("none"))
        menu.addSeparator()
        if self.dev:
            paths = [str(p) for p in portable.brains()]
        else:
            root = os.path.join(self.cfg["eru_ai_root"], "models", "llm")
            paths = sorted(glob.glob(os.path.join(root, "**", "*.gguf"), recursive=True))
        # the brain in use and any you picked from your PC show up too, wherever they live
        for extra in [mp] + list(self.s["my_brains"]):
            if extra and extra != "none" and os.path.exists(extra) and \
                    os.path.normcase(os.path.abspath(extra)) not in {os.path.normcase(os.path.abspath(p)) for p in paths}:
                paths.append(extra)
        for path in paths:
            if "mmproj" in os.path.basename(path).lower():  # a vision add-on file, not a brain
                continue
            name = os.path.basename(path).rsplit(".", 1)[0]
            label = re.sub(r"[-_.](?:Q\d\w*|IQ\d\w*|q\d\w*)$", "", name)
            a = menu.addAction(f"{label}  ({os.path.getsize(path) / 2 ** 30:.1f} GB)")
            a.setCheckable(True)
            a.setChecked(os.path.normcase(os.path.abspath(path)) == cur)
            a.triggered.connect(lambda _=False, p=path: self._swap_brain(p))
        have = {os.path.basename(p).lower() for p in paths}  # already on this PC somewhere else: no "Get" for it
        missing = [it for it in portable.BRAINS if not it.installed() and Path(it.files[0][1]).name.lower() not in have]
        if missing:
            menu.addSeparator()
            for it in missing:
                a = menu.addAction(f"Get {it.label.split('  (')[0]}, {portable.gb(it.size)}")
                a.setToolTip(it.note)
                a.setEnabled(self.dl is None)
                a.triggered.connect(lambda _=False, i=it: self._get_brain(i))
        menu.addSeparator()
        menu.addAction("Use a model from my PC...  (.gguf)", self._pick_brain)
        menu.addAction("Open my models folder",
                       lambda: (portable.LLM_DIR.mkdir(parents=True, exist_ok=True), _open_folder(portable.LLM_DIR)))

    def _fill_ear_models(self):
        from .. import portable

        menu = self._ear_models
        menu.clear()
        cur = self.s["whisper_model"] or ""
        for path in portable.ears_models():
            a = menu.addAction(path.name.replace("ggml-", "").replace(".bin", ""))
            a.setCheckable(True)
            a.setChecked(path.name == cur or (not cur and "small" in path.name))
            a.triggered.connect(lambda _=False, n=path.name: self._swap_ears(n))
        missing = [it for it in portable.EARS if not it.installed()]
        if missing:
            menu.addSeparator()
            for it in missing:
                a = menu.addAction(f"Get {it.label} ears, {portable.gb(it.size)}")
                a.setToolTip(it.note)
                a.setEnabled(self.dl is None)
                a.triggered.connect(lambda _=False, i=it: self._get_ears(i))

    def _swap_ears(self, name: str):
        """A different whisper model: saved, and her ears restart with it."""
        self.s.set("whisper_model", name)
        self.cfg["stt"]["whisper_model"] = name
        if self.ears:
            self.ears.stopped = True
            stt = getattr(self.ears, "stt", None)
            if stt is not None and hasattr(stt, "close"):
                stt.close()
        QTimer.singleShot(1500, self._start_ears)

    # -- downloads, straight from her menu (no setup window) ---------------------------------------
    def _fetch(self, items, what: str, then=None):
        """Download in the background. The progress shows at the top of her Brain menu; she says when it's done,
        then `then()` runs (on the Qt thread)."""
        from .. import portable

        if self.dl:
            self.capri.say("One download at a time, choom. I'm still pulling the last one.")
            return
        items = [it for it in items if not it.installed()]
        if not items:
            if then:
                then()
            return
        self.dl = f"Getting {what}..."
        self.capri.say(f"Pulling {what} now ({portable.gb(sum(it.size for it in items))}). "
                       "Right-click me, Brain, to see how far along it is.")
        self._dl_timer = timer = QTimer()
        timer.timeout.connect(lambda: self.dl_action is not None and self.dl and self.dl_action.setText(self.dl))
        timer.start(500)

        def progress(done, total, _what):
            self.dl = f"Getting {what}: {100 * done // max(1, total)}%"

        def work():
            try:
                portable.download(items, progress)
                line, ok = f"Got {what}. Hooking it up now.", True
            except Exception as e:
                print(f"[capri] download failed: {e}")
                line, ok = f"Couldn't get {what}: {e}. Try again from my Brain menu.", False
            self.dl = None

            def done():
                timer.stop()
                self.capri.say(line)
                if ok and then:
                    then()
            self.bridge.fetched.emit(done)

        threading.Thread(target=work, daemon=True).start()

    def _engine(self):
        """Her brain engine (llama.cpp) if it isn't there yet: CUDA on NVIDIA, Vulkan on anything else."""
        from .. import portable

        if portable.find_exe("llama-server") is not None:
            return []
        want = "cuda" if portable.has_nvidia() else "vulkan"
        return [next(it for it in portable.ENGINE_GPU if it.key == want)]

    def _get_brain(self, item):
        from ..config import ROOT

        path = str(ROOT / item.files[0][1])
        self._fetch(self._engine() + [item], item.label.split("  (")[0], then=lambda: self._swap_brain(path))

    def _get_ears(self, item):
        from .. import portable

        extra = []
        if not portable.ENGINE_EARS.installed():
            if portable.ENGINE_EARS.system:  # Linux: the package manager has it
                self.capri.say("My ears need whisper.cpp first: sudo pacman -S whisper-cpp on Arch. "
                               "On Kali, kali/run.sh already gave me faster-whisper.")
                return
            extra = [portable.ENGINE_EARS]
        name = Path(item.files[0][1]).name

        def ready():
            if self.s["ears"] == "off":
                self.s.set("ears", "hold")
            self._swap_ears(name)
        self._fetch(extra + [item], f"the {item.label} ears", then=ready)

    def _get_voice(self):
        """Her voice files: the clone's helper data if her clone ships here, else the free Kokoro pack."""
        from .. import portable

        item = portable.VOICE if tts_mod.CloneTTS.folder().exists() else portable.KOKORO
        self._fetch([item], "my voice", then=lambda: self._set_voice(True))

    def _pick_brain(self):
        """Any .gguf already on this PC (LM Studio's, one you downloaded...): no copy, she just loads it from there."""
        from PySide6.QtWidgets import QFileDialog

        from .. import portable

        start = next((str(d) for d in portable.model_dirs()), os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(None, "Pick a model for Capri", start, "GGUF models (*.gguf)")
        if not path or "mmproj" in os.path.basename(path).lower():
            return
        self.s.set("my_brains", [p for p in self.s["my_brains"] if p != path] + [path])
        self._swap_brain(path)

    def _swap_brain(self, path: str):
        if self.agent is None or os.path.normcase(path) == os.path.normcase(self.cfg["llm"].get("model_path") or ""):
            return
        self.s.set("brain", path)
        self.capri.say("Hold up, swapping out my brain chip. Don't look.")

        def work():
            import gc

            from ..brain import llm as llm_mod

            with self.busy:  # nothing else thinks while the brain is out
                t = time.monotonic()
                with llm_mod.GPU_LOCK:
                    old = self.agent.llm
                    self.agent.llm = None
                    try:
                        old.model.close()
                    except Exception:
                        pass
                    del old
                    gc.collect()
                self.cfg["llm"]["model_path"] = path
                try:
                    self.agent.llm = llm_mod.create(self.cfg)
                    self.agent.warm_up()
                    print(f"[capri] brain swapped to {os.path.basename(path)} in {time.monotonic() - t:.1f}s")
                    self.bridge.replied.emit("Brain's out. I'll still open stuff, set timers and play music for u, "
                                             "I just won't chat much." if path == "none" else
                                             "New brain chip, who dis? ...Okay, I'm back.", "", False)
                except Exception as e:
                    print(f"[capri] brain swap failed: {e}")
                    self.bridge.replied.emit(f"That brain chip flatlined: {e}", "", False)

        threading.Thread(target=work, daemon=True).start()

    def _fill_ears(self, mics):
        self.key_action.setText(f"Change talk key  (now {self._hotkey.pretty(self.s['talk_key'])})")
        mics.clear()
        from ..voice.stt import list_inputs

        cur = self.s["mic"] or self.cfg["stt"].get("input_device") or ""
        for name in ["Windows default"] + list_inputs():
            a = mics.addAction(name)
            a.setCheckable(True)
            a.setChecked((name == "Windows default" and not cur) or (bool(cur) and cur.lower() in name.lower()))
            a.triggered.connect(lambda _=False, n=name: self._pick_mic("" if n == "Windows default" else n))

    def _pick_mic(self, name: str):
        self.s.set("mic", name)
        if self.ears:
            self.ears.reopen = True

    def _rebind(self):
        """Ask for the new combo, then catch it as soon as every key is let go."""
        self.capri.say("Hit your new talk key combo, choom. I'm watching.")
        cap = self._hotkey.Capture()
        timer = QTimer()
        started = time.monotonic()

        def poll():
            if time.monotonic() - started < 0.6:  # let go of the menu click first
                return
            combo = cap.poll()
            if combo:
                timer.stop()
                self.s.set("talk_key", combo)
                self.s.set("ears", "hold")
                self.ear_actions["hold"].setChecked(True)
                self.capri.say(f"Locked in. Hold {self._hotkey.pretty(combo)} and talk to me.")
            elif time.monotonic() - started > 12:
                timer.stop()
                self.capri.say("Too slow, choom. Keeping the old key.")

        timer.timeout.connect(poll)
        timer.start(20)
        self._rebind_timer = timer

    def quit(self):
        """Stop the voice server, then leave without the interpreter's teardown (CUDA + PortAudio threads
        being torn down at exit crash on Windows)."""
        for hook in self.on_quit:
            try:
                hook()
            except Exception as e:
                print(f"[capri] quit hook failed: {e}")
        if self.ears:
            self.ears.stopped = True
        try:
            self.agent.mcp.close()
        except Exception:
            pass
        # the portable build's helper servers (llama-server, whisper-server) go with her
        for helper in (getattr(self.agent, "llm", None), getattr(self.ears, "stt", None)):
            if helper is not None and hasattr(helper, "close"):
                try:
                    helper.close()
                except Exception:
                    pass
        proc = getattr(self.tts, "proc", None)
        if proc:
            proc.terminate()
        sys.stdout.flush()
        os._exit(0)


def _same_song(a: str, b: str) -> bool:
    words = lambda s: set(re.findall(r"[a-z0-9']{3,}", s.lower()))  # noqa: E731
    wa, wb = words(a), words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) > 0.6


def main():
    import argparse

    ap = argparse.ArgumentParser(prog="capri")
    ap.parse_args()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.desk = DeskApp()  # kept alive with the app
    sys.exit(app.exec())
