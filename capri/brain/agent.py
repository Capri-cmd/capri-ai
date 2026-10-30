"""Turns what the user said into Capri's reply, running abilities (music, apps, web, files, email, MCP tools,
memory) along the way."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..abilities import desk_tools, launcher, pc, reminders, screen, todo, weather, web
from ..abilities.mcp import Hub
from ..abilities.memory import Memory
from ..abilities.spotify import Spotify
from . import intents
from . import llm as llm_mod
from . import persona

# still honoured if the model volunteers a tag, but abilities no longer depend on it
TAG = re.compile(r"\[\[\s*(\w+)\s*(?::\s*(.*?))?\s*\]\]", re.S)


@dataclass
class Reply:
    text: str
    go_idle: bool = False
    actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.user = cfg.get("user_name") or "choom"
        self.memory = Memory(cfg)
        self.spotify = Spotify(cfg)
        self.llm = llm_mod.create(cfg)
        web.CFG = cfg.get("search") or {}
        desk_tools.CFG = cfg.get("tools") or {}
        self.mcp = Hub(cfg)
        self.pending: intents.Intent | None = None  # an MCP tool waiting for their yes
        self.glance: dict | None = None  # her last look at your screen: {"t", "title", "text"} (kept fresh by the app)
        self.now_playing = ""  # the YouTube song in your browser right now, if any
        self.on_played = lambda result: None  # the app hears what actually started (DJ: don't judge her own pick)
        self.recent_own: list[str] = []  # things she said unprompted (kept out of the chat history)
        self._avoid: list[str] = []  # openers and slang she's overused lately (pushed down at the token level)
        self._stale: set[str] = set()  # four-word runs from her recent replies: a later sentence reusing one gets cut
        self._stream_raw = ""
        self._fresh = False  # this reply is about a chat she just read: leave the old chat history out
        self.eyes = None  # real sight (abilities/sight.py), set by the app once it has loaded
        from ..abilities.music import Playlist

        self.playlist = Playlist()
        # timers / alarms / reminders: the app hooks on_reminder up, then calls self.reminders.start()
        self.on_reminder = lambda item: print(f"[capri] {reminders.describe(item)}")
        self.reminders = reminders.Reminders(on_due=lambda item: self.on_reminder(item))
        self.todo = todo.Todo()
        # her switches (the app's Settings: quiet, never_look, focus_until, city...); a plain dict when run headless
        self.settings = _Plain(quiet=False, never_look=[], focus_until=0.0, city="", reactions=True, game_mode=True)

    @property
    def no_brain(self) -> bool:
        return bool(getattr(self.llm, "no_brain", False))

    def warm_up(self) -> None:
        """Read the fixed prompt once at boot, so the first real reply is as fast as the rest."""
        import time

        if self.no_brain:
            return

        t = time.monotonic()
        self.llm.chat(persona.build(self.user) + [{"role": "user", "content": "hey\n" + persona.REMINDER}], max_tokens=1)
        print(f"[capri] brain warm in {time.monotonic() - t:.1f}s")

    def _aux(self, prompt: str, **kw) -> str:
        """A behind-the-scenes question (plan an action, pull out facts) asked on top of her usual prompt and
        history: llama.cpp keeps that whole prefix cached, so the next real reply doesn't re-read 2k tokens."""
        msgs = persona.build(self.user) + self.memory.history()
        msgs.append({"role": "user", "content": prompt})
        return self.llm.chat(msgs, **kw)

    def _notes(self, about: str, screen: bool | None = None) -> list[str]:
        """What she knows right now: facts about you, what's on your screen, what's playing. The screen only rides
        along when the chat is about what they're doing, otherwise she'd talk about it no matter what you ask."""
        import time

        if screen is None:
            screen = bool(_ABOUT_SCREEN.search(about))
        out = []
        facts = self.memory.relevant(about, self.user, limit=6)
        if facts:
            out.append(f"(Things you remember about {self.user}, use only if relevant: " + "; ".join(facts) + ")")
        g = self.glance
        if screen and g and time.time() - g["t"] < 180:
            seen = f'(What you see on {self.user}\'s screen: the window "{g["title"]}"'
            seen += f', with this text on it: {g["text"][:400]})' if g["text"] else ")"
            out.append(seen)
        if self.now_playing and (screen or _ABOUT_MUSIC.search(about)):
            out.append(f'(Song playing on {self.user}\'s PC right now: "{self.now_playing}". If they ask what\'s '
                       "playing, that's the answer.)")
        return out

    def _messages(self, user_text: str, context: list[str]) -> list[dict]:
        msgs = persona.build(self.user)
        last = user_text
        if not self._fresh:  # answering about a chat she just read: old talk (other chats) would leak into it
            msgs += self.memory.history()
            context = self._notes(user_text, screen=None if not context else False) + context
        if context:
            # notes ride inside the newest user turn: these templates reject extra system messages
            last += "\n\n[" + " ".join(context) + "]"
        msgs.append({"role": "user", "content": last + "\n" + persona.REMINDER})
        return msgs

    def _song_on_screen(self) -> str:
        """The song in an open YouTube tab ('Kavinsky - Nightcall'), '' if there isn't one."""
        try:
            from ..abilities import vision

            return vision.youtube_song(vision.window_titles())
        except Exception:
            return ""

    def _run(self, intent: intents.Intent, reply: Reply, context: list[str]) -> None:
        k, arg = intent.kind, intent.arg
        if k == "pick":  # they want music, she chooses: one of her Night City favourites
            k, arg = "youtube", self.playlist.next()
            context.append("You chose this one yourself, it's one of your favourites.")
        if k == "play" and not arg.startswith("spotify|") and not self.spotify.sp and not _has_spotify():
            k = "youtube"  # no Spotify app on this PC: YouTube in the browser plays it instead
        arg = arg.removeprefix("spotify|")
        if k == "play" and arg == "@pick":
            arg = self.playlist.next()
            context.append("You chose this one yourself, it's one of your favourites.")
        if k == "play" and arg == "@now":  # "play this on spotify": the song that's on right now
            arg = self.spotify.now_playing() or self.now_playing or self._song_on_screen()
            if not arg:
                context.append(f"{self.user} asked you to put 'this' song on Spotify, but nothing is playing that you can "
                               "see. Ask them which song, in one short line.")
                return
            arg = re.sub(r"\s*[\(\[](?:official|lyric|music|audio|hd|4k)[^\)\]]*[\)\]]", "", arg, flags=re.I).strip()
        if k == "open":
            planned = arg.startswith("planned|")
            result = launcher.open_thing(arg.removeprefix("planned|"), google_fallback=not planned)
            reply.actions.append(result)
            reply.notes.append(result)
            context.append(f"You just {result} on their PC. React in one short, funny line.")
        elif k == "youtube":
            import threading

            def go():
                result = launcher.youtube_play(arg)
                print(f"[capri] {result}")
                self.on_played(result)

            threading.Thread(target=go, daemon=True).start()  # she answers while YouTube loads
            reply.actions.append(f"youtube: {arg}")
            reply.notes.append(f"putting on {arg}")
            song = arg.split(" (")[0]
            context.append(f'It\'s happening: you are putting on "{song}" for {self.user} right now. Say you\'re putting '
                           "it on, plus a quick reaction or a tease. Don't name the song or the artist (the title often "
                           "comes out wrong). Never say no to it.")
        elif k == "play":
            result = self.spotify.play(arg)
            reply.actions.append(result)
            reply.notes.append(result)
            if result.startswith("opening "):
                context.append(f'You are putting "{arg}" on in their Spotify right now, it starts playing by itself. '
                               "Say you're putting it on, plus a quick reaction to it, one or two short lines. Don't "
                               "ask them to do anything and don't name the song.")
            else:
                context.append(f"You just did this on Spotify for them: {result}. React in one short line.")
        elif k == "spotify":
            result = self.spotify.control(arg)
            reply.actions.append(result)
            reply.notes.append(result)
            context.append(f"You just told their music player to {arg}. Acknowledge it in one short line.")
        elif k == "remember":
            arg = self._tidy_fact(third_person(arg, self.user))
            self.memory.remember(arg, self.user)
            reply.actions.append(f"remembered: {arg}")
            reply.notes.append("saved to memory shard")
            context.append(f'You just saved this to your memory shard: "{arg}". Confirm it in your style.')
        elif k == "search":
            in_browser = arg.startswith("web|")  # they said "search / google / look up": open it in their browser
            arg = arg.removeprefix("web|")
            if in_browser:
                launcher.web_search(arg)
            context.append(web.research(arg))
            if in_browser:
                context.append(f"(The Google results for it are open in {self.user}'s browser too.)")
            reply.actions.append(f"searched: {arg}")
            reply.notes.append("searched the net")
        elif k == "news":
            launcher._browser(web.news_url(arg))
            heads = web.headlines(arg)
            if heads:
                lines = "\n".join(f"- {h} ({o})" for h, o in heads)
                context.append(f"(You just pulled up the latest news{' on ' + arg if arg else ''} and opened Google News "
                               f"in {self.user}'s browser. Top headlines right now:\n{lines}\nTell them the two or three "
                               "biggest in a few words each, in your own voice. Only these, don't invent any.)")
            else:
                context.append("(You opened Google News in their browser, but couldn't read the headlines yourself. "
                               "Say it's open, in one line.)")
            reply.actions.append(f"news: {arg or 'top stories'}")
            reply.notes.append("pulled up the news")
        elif k == "time":
            from datetime import datetime

            now = datetime.now()
            context.append(f"(Right now it's {now.strftime('%I:%M %p').lstrip('0')} on {now.strftime('%A, %B')} "
                           f"{now.day}, {now.year}. Tell them, short.)")
        elif k == "reminder":
            self._reminder(arg, reply, context)
        elif k == "privacy":
            self._privacy(arg, reply, context)
        elif k == "focus":
            self._focus(arg, reply, context)
        elif k == "weather":
            self._weather(arg, reply, context)
        elif k == "clip":
            self._clip(arg, reply, context)
        elif k == "todo":
            self._todo(arg, reply, context)
        elif k == "pc":
            self._pc(arg, reply, context)
        elif k == "read":
            title, text = web.read(arg)
            if text:
                context.append(f'(You just read the page "{title}" ({arg}). It says: {text[:2000]}\n'
                               "Answer from it, short and in your own voice.)")
            else:
                context.append(f"(You tried to open {arg} but it wouldn't load. Say so in one line.)")
            reply.actions.append(f"read: {arg}")
        elif k == "note":
            self._write_note(arg, reply, context)
        elif k == "email":
            self._email(arg, reply, context)
        elif k == "tool":
            self._tool(arg, reply, context)
        elif k == "idle":
            reply.go_idle = True
            context.append("You're about to take a nap on their desktop. Say a short sign-off.")

    def _reminder(self, arg: str, reply: Reply, context: list[str]) -> None:
        import json
        from datetime import datetime

        r = json.loads(arg)
        if r["kind"] == "list":
            items = self.reminders.upcoming()
            if not items:
                context.append("(They have no timers, alarms or reminders set. Say so in one line.)")
                return
            now = datetime.now()
            said = "; ".join(f"{i['kind']}{' (' + i['what'] + ')' if i.get('what') else ''} going off "
                             f"{reminders.say_when(datetime.fromtimestamp(i['due']), now)}" for i in items[:5])
            context.append(f"(What they have set: {said}. Tell them, short.)")
            return
        if r["kind"] == "cancel":
            gone = self.reminders.cancel(r["which"])
            reply.actions.append(f"cancelled {len(gone)} {r['which']}")
            context.append(f"(You just cancelled {len(gone)} {r['which']}. Confirm in one line.)" if gone else
                           f"(They asked to cancel their {r['which']}, but there's nothing like that set. Say so.)")
            return
        due = datetime.fromtimestamp(r["due"])
        self.reminders.add(r["kind"], r.get("what", ""), due)
        when = reminders.say_when(due)
        what = f' for "{r["what"]}"' if r.get("what") else ""
        exact = due.strftime("%I:%M %p").lstrip("0")
        reply.actions.append(f"{r['kind']} {when}")
        reply.notes.append(f"{r['kind']} set {when}")
        context.append(f"(You just set a {r['kind']}{what} going off {when} (at {exact}), and you'll ring and tell them "
                       "when it's time. Confirm it in one short line with the time, your style.)")

    # -- everyday helpers ---------------------------------------------------------------------------------------
    def _privacy(self, arg: str, reply: Reply, context: list[str]) -> None:
        st = self.settings
        if arg == "on":
            st.set("quiet", True)
            reply.actions.append("privacy on")
            context.append("(They want privacy: from now on you don't look at their screen and don't talk on your own "
                           "until they say you can. Agree in one short line, a little sulky is fine.)")
        elif arg == "off":
            st.set("quiet", False)
            reply.actions.append("privacy off")
            context.append("(They said you can watch their screen and talk on your own again. React happily, one line.)")
        else:
            how, _, app = arg.partition("|")
            app = app.strip().lower().removeprefix("the ").removesuffix(" app")
            names = [n for n in st["never_look"] if n != app]
            if how == "never":
                names.append(app)
            st.set("never_look", names)
            screen.never_look = names
            reply.actions.append(f"{how}: {app}")
            context.append(f"(You'll never read {app} again, it's on your never-look list. Promise it in one line.)"
                           if how == "never" else f"(You're allowed to look at {app} again. One line.)")

    def _focus(self, arg: str, reply: Reply, context: list[str]) -> None:
        import time
        from datetime import datetime, timedelta

        st = self.settings
        for item in self.reminders.upcoming():  # one focus session at a time
            if item["kind"] == "focus":
                self.reminders.cancel("focus")
        if arg == "off":
            was = st["focus_until"] > time.time()
            st.set("focus_until", 0.0)
            reply.actions.append("focus off")
            context.append("(Focus mode is over, they're on a break. Tell them nice work, one line.)" if was else
                           "(They weren't in focus mode. Say so, one line.)")
            return
        secs = int(arg)
        st.set("focus_until", time.time() + secs)
        self.reminders.add("focus", "", datetime.now() + timedelta(seconds=secs))
        reply.actions.append(f"focus for {reminders.span(secs)}")
        context.append(f"(Focus mode is on for {reminders.span(secs)}: you'll stay quiet, and if they open YouTube, "
                       "TikTok, Reddit, a game or Discord you'll call them out and send them back to work. You ring when "
                       "it's over. Tell them it's on, short and motivating, your style.)")

    def _weather(self, arg: str, reply: Reply, context: list[str]) -> None:
        st = self.settings
        if arg.startswith("set|"):
            city = arg[4:].strip()
            if weather.place(city) is None:
                context.append(f"(You couldn't find a place called {city}. Ask them to spell it, one line.)")
                return
            st.set("city", city)
            reply.actions.append(f"city: {city}")
            context.append(f"(You'll remember they're in {city} for the weather. One line.)")
            return
        city = arg or st["city"]
        if not city:
            context.append("(They asked about the weather but you don't know their city yet. Ask them to tell you: "
                           "\"my city is ...\". One line.)")
            return
        rep_ = weather.report(city)
        if not rep_:
            context.append(f"(You couldn't get the weather for {city}. Say so, one line.)")
            return
        reply.actions.append(f"weather: {city}")
        context.append(f"({rep_}\nAnswer what they asked from this, short: the temperature, rain, and if they need a "
                       "jacket or umbrella. Use the real numbers.)")

    def _clip(self, arg: str, reply: Reply, context: list[str]) -> None:
        try:
            import pyperclip

            text = (pyperclip.paste() or "").strip()
        except Exception:
            text = ""
        if len(text) < 2:
            context.append("(They asked you to do something with what they copied, but their clipboard is empty. "
                           "Tell them to copy the text first, one line.)")
            return
        job, _, extra = arg.partition("|")
        ask = {
            "translate": f"Translate this text into {extra or 'English'}. Give only the translation.",
            "summarize": "Summarize this text in 2 to 4 short sentences. Only the summary.",
            "fix": "Fix the grammar, spelling and punctuation of this text. Keep its meaning, tone and language. "
                   "Give only the corrected text.",
            "explain": "Explain what this text means, simply, in 2 to 4 sentences.",
            "rewrite": f"Rewrite this text{' to be ' + extra if extra else ' better'}. Keep the meaning and language. "
                       "Give only the new text.",
        }[job]
        out = self._task(f"{ask}\n\nTEXT:\n{text[:6000]}", max_tokens=900)
        out = re.sub(r"^(?:here(?:'s| is)[^:\n]*:\s*)", "", out, flags=re.I).strip().strip('"')
        if job in ("translate", "fix", "rewrite"):
            try:
                import pyperclip

                pyperclip.copy(out)
            except Exception:
                pass
            reply.actions.append(f"clipboard: {job}")
            reply.notes.append("result copied")
            context.append(f"(You did it: {job} on what they copied. The result is now on their clipboard, ready to "
                           f"paste. It starts: \"{out[:160]}\". Tell them it's copied, one short line.)")
        else:
            reply.actions.append(f"clipboard: {job}")
            context.append(f"(They copied some text and asked you to {job} it. Your answer: \"{out[:900]}\"\n"
                           "Say that, in your own voice but keeping the facts.)")

    def _todo(self, arg: str, reply: Reply, context: list[str]) -> None:
        how, what, lst = (arg.split("|") + ["", ""])[:3]
        name = todo.list_name(lst)
        if how == "add":
            new = self.todo.add(todo.split_items(what), name)
            reply.actions.append(f"{name} list +{len(new)}")
            context.append(f"(You added {', '.join(new) or 'nothing new (already there)'} to their {name} list. "
                           "Confirm in one short line.)")
        elif how == "done":
            hit = self.todo.done(what, name if lst else None)
            reply.actions.append(f"crossed off {len(hit)}")
            context.append(f"(You crossed {', '.join(hit)} off their list. One line.)" if hit else
                           f"(Nothing called \"{what}\" is on their lists. Say so, one line.)")
        elif how == "clear":
            n = self.todo.clear(name)
            reply.actions.append(f"cleared {name}")
            context.append(f"(You cleared their {name} list ({n} items). One line.)")
        else:
            lists = self.todo.items(name if lst and name != "to-do" or "to do" in lst.lower() else None)
            lists = {k: v for k, v in lists.items() if v}
            if not lists:
                context.append("(Their lists are empty. Say so, one line.)")
                return
            said = "; ".join(f"{k} list: " + ", ".join(v) for k, v in lists.items())
            context.append(f"(Their lists right now: {said}. Read them out, short.)")

    def _pc(self, arg: str, reply: Reply, context: list[str]) -> None:
        confirmed = arg.startswith("yes|")
        arg = arg.removeprefix("yes|")
        what, _, rest = arg.partition("|")
        if what == "volume":
            way, _, n = rest.partition("|")
            result = pc.volume(way, int(n) if n.isdigit() else None)
            reply.actions.append(result)
            context.append(f"(Done: you just {result} on their PC. Confirm exactly that in a few words, nothing else.)")
        elif what == "screenshot":
            path = pc.screenshot()
            pc.open_path(path)
            reply.actions.append(f"screenshot: {path.name}")
            context.append("(Done: you took a screenshot of their screen, saved in Pictures/Capri and opened. Confirm "
                           "that in a few words, nothing else.)")
        elif what == "lock":
            import threading

            threading.Timer(2.5, pc.lock).start()  # after she's said it
            reply.actions.append("locking the PC")
            context.append("(You're locking their PC in a second. A short goodbye-ish line.)")
        elif what == "cancel-shutdown":
            result = pc.cancel_shutdown()
            reply.actions.append(result)
            context.append(f"(You {result}. One line.)")
        elif what in ("shutdown", "sleep", "clean-downloads"):
            old = []
            if what == "clean-downloads":
                old = pc.old_downloads(30)
                if not old:
                    context.append("(Their Downloads folder has nothing older than a month. Say it's already clean.)")
                    return
            if not confirmed:
                self.pending = intents.Intent("pc", arg)
                ask = {"shutdown": f"shut their PC down in {reminders.span(int(rest or 60))}",
                       "sleep": "put their PC to sleep now",
                       "clean-downloads": f"move {len(old)} files they haven't touched in a month from Downloads to the "
                                          "Recycle Bin (they can restore them from there)"}[what]
                context.append(f"(You're about to {ask}. Ask them first: yes or no? One short line.)")
                return
            if what == "shutdown":
                result = pc.shutdown(int(rest or 60))
            elif what == "sleep":
                import threading

                threading.Timer(3, pc.sleep_pc).start()
                result = "put the PC to sleep"
            else:
                n = pc.recycle(pc.old_downloads(30))
                result = f"moved {n} old files from Downloads to the Recycle Bin"
            reply.actions.append(result)
            context.append(f"(Done: you {result}. One line." + (" Tell them \"cancel the shutdown\" stops it.)"
                                                               if what == "shutdown" else ")"))

    # -- what she says about your screen on her own -------------------------------------------------------------
    def youtube_take(self, video: str, comments: list[str]) -> str:
        seen = (" Comments you can see under it: " + " / ".join(f'"{c[:120]}"' for c in comments[:4])) if comments else ""
        return self._own(f'{self.user} is watching the YouTube video "{video}".{seen} Say ONE short reaction like a '
                         "friend watching with them: roast or hype the video, or react to one of the comments (quote a "
                         "few words of it). If there's nothing to say, reply with exactly PASS.", 55, can_pass=True)

    def _about(self, note: str, must: list[str], max_tokens: int = 45, can_pass: bool = False) -> str:
        """A line she says on her own that has to be about the thing (names the app / game / quotes the message):
        a generic quip gets one retry with the point spelled out, then it's dropped."""
        for extra in ("", f" Your line MUST mention {must[0]}."):
            text = self._own(note + extra, max_tokens, can_pass=can_pass)
            if not text or any(w.lower() in text.lower() for w in must):
                return text
        return ""

    def chat_hello(self, app: str) -> str:
        return self._about(f"{self.user} just opened {app} again. Say ONE short nosy line about it that names {app}, "
                           f"like \"{app} again? who are you texting?\".", [app], 35)

    def chat_take(self, app: str, messages: list[str]) -> str:
        shown = " / ".join(f'"{m[:140]}"' for m in messages[-6:])
        words = [w for m in messages[-2:] for w in re.findall(r"[A-Za-z']{4,}", m)][:12]
        return self._about(f"You're peeking over {self.user}'s shoulder at their {app} chat. The newest messages (oldest "
                           f"first): {shown}. React to the LAST message in ONE short line like a nosy friend (\"ooh, that "
                           "was harsh\", \"you gonna answer that?\", \"leaving them on read?\"), quoting two to four "
                           "words of it. If it's boring, reply with exactly PASS.", words or [app], 50, can_pass=True)

    def typing_take(self, app: str, draft: str, messages: list[str]) -> str:
        last = f' They are answering this message: "{messages[-1][:140]}".' if messages else ""
        words = re.findall(r"[A-Za-z']{4,}", draft)[:10]
        return self._about(f'{self.user} is typing this in {app} right now, not sent yet: "{draft[:200]}".{last} React to '
                           "what THEY are typing in ONE short line, quoting two to four words of it, like a friend "
                           "reading over their shoulder (\"damn\", \"you're really sending that?\", \"be nice\", or "
                           "hype it). If there's nothing to say, reply PASS.", words or ["send"], 45, can_pass=True)

    def game_over(self, game: str, minutes: int) -> str:
        return self._about(f"{self.user} just stopped playing {game} after {minutes} minutes. Ask how the {game} session "
                           f"went, or hype / roast them for it, in ONE short line that names {game}.",
                           [game, game.split()[0]], 40)

    def focus_nag(self, where: str, minutes_left: int) -> str:
        return self._about(f"{self.user} is in focus mode ({minutes_left} minutes left) but just opened {where}. Call it "
                           f"out by name and send them back to work, ONE short line, playful but firm: \"{where}? Nope. "
                           f"{minutes_left} more minutes, back to work.\"", [where, "focus", "work"], 40)

    def _chat_help(self, ask: str, context: list[str], brain_eyes: bool) -> None:
        """The chat on screen, read word for word (her eyes on a screenshot, or Windows OCR without them), so she
        can say what they meant and hand over a reply worth sending."""
        from ..abilities import screen, vision

        title = (self.glance or {}).get("title") or vision.active_window_title()
        if screen.private(title):
            context.append("(They asked you to read a chat, but it's on your never-look list or private. Say you "
                           "won't read that one, one line.)")
            return
        convo = ""
        try:
            if brain_eyes and self.eyes.ok:
                from ..abilities.sight import screenshot_front

                convo = self.eyes.read_chat(screenshot_front(), self.user)
            else:
                kind, app = screen.kind(title)
                msgs, draft = screen.read_chat(app or "the chat", title)
                convo = "\n".join(msgs) + (f"\nDRAFT: {draft}" if draft else "")
        except Exception as e:
            print(f"[capri] chat read failed: {e}")
        if not convo.strip():
            context.append("(They asked about a chat on their screen, but you couldn't read it. Tell them to open "
                           "the chat in front and ask again, one line.)")
            return
        context.append(f"(You just read the chat on {self.user}'s screen. Here it is, oldest first:\n{convo}\n"
                       f"Now really help {self.user} with what they asked, about THIS chat only (nothing from earlier "
                       "talks). Start from what's actually in it, e.g. who said the last thing, or that it's just a bot "
                       "posting welcome messages. If they want to know what to answer: say in "
                       "a few words what the other person's last message means or wants, then give the exact reply "
                       f"{self.user} could send, in quotes, written the way {self.user} texts (casual, short, text-speak "
                       "is fine). If they asked what was said or meant, tell them plainly from the chat above. Use only "
                       "what's in the chat, quote it when it helps, no made-up details, no random lines.)")

    def _task(self, prompt: str, max_tokens: int = 700) -> str:
        """Real work (a file's text, an email): asked plainly, outside her character, so it comes out usable."""
        return self.llm.chat([{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=0.4).strip()

    def _write_note(self, ask: str, reply: Reply, context: list[str]) -> None:
        out = self._task(
            f'{self.user} asked: "{ask}"\nWrite the text file they want. First line exactly: FILENAME: <short file '
            "name, no extension>. Then the file's contents only: clean, useful, plain text (lists with - ). No chat, "
            "no intro, no sign-off.")
        first, _, body = out.partition("\n")
        if first.upper().startswith("FILENAME:"):
            name = first[len("FILENAME:"):].strip()
        else:  # it skipped the name line: the whole thing is the file
            name, body = "note", out
        path = desk_tools.write_file(name, body)
        reply.actions.append(f"wrote {path}")
        reply.notes.append(f"saved {path.name}")
        context.append(f"You just wrote that file and opened it on their screen ({path.name}, in their Documents/Capri "
                       "folder). Tell them in one short line, your style. Don't write out what's in it: it's open.")

    def _email(self, ask: str, reply: Reply, context: list[str]) -> None:
        out = self._task(
            f'{self.user} asked: "{ask}"\nDraft the email they want, written as {self.user} (first person, their '
            "voice, not yours). Format exactly:\nTO: <email address if they gave one, else blank>\nSUBJECT: <subject>\n"
            "BODY:\n<the email>", max_tokens=500)
        to = (re.search(r"^TO:[ \t]*(.*)$", out, re.M | re.I) or [None, ""])[1]
        subject = (re.search(r"^SUBJECT:[ \t]*(.*)$", out, re.M | re.I) or [None, ""])[1]
        body = out.split("BODY:", 1)[1].strip() if "BODY:" in out else out
        result = desk_tools.email_draft(to, subject.strip() or "Hi", body)
        reply.actions.append(result)
        reply.notes.append("email draft open")
        context.append(f"You {result} in their mail app. They read it over and hit send themselves (you never send "
                       "anything). Tell them in one short line.")

    def _tool(self, arg: str, reply: Reply, context: list[str], confirmed: bool = False) -> None:
        import json

        name, _, raw = arg.partition(" ")
        hit = self.mcp.find(name)
        if hit is None:
            context.append(f"(You wanted a tool called {name}, but you don't have it. Just answer normally.)")
            return
        full, tool, server = hit
        args = _loose_json(raw)
        if args is None:
            context.append(f"(You wanted to use {full} but fumbled the details. Ask {self.user} to say it again.)")
            return
        if not confirmed and not self.mcp.safe(tool, server):
            self.pending = intents.Intent("tool", f"{full} {json.dumps(args)}")
            context.append(f"(You're about to use your tool {full} with {json.dumps(args)[:200]}. It changes "
                           f"things, so ask {self.user} first: say what you'll do in one short line and ask yes or no.)")
            return
        try:
            out = server.call(tool["name"], args)
        except Exception as e:
            out = f"ERROR: {e}"
        print(f"[capri] tool {full} -> {out[:160]!r}")
        reply.actions.append(f"tool: {full}")
        reply.notes.append(f"ran {full}")
        context.append(f"(You just used your tool {full}. Result: {out[:1800]}\nTell {self.user} what came of it, "
                       "short and in your own voice. If it failed, say so.)")

    def respond(self, user_text: str, on_sentence=None) -> Reply:
        """on_sentence(text): called with each finished sentence while she's still writing, so the bubble can start
        typing right away (the whole reply still comes back in Reply.text)."""
        user_text = plain(user_text)
        dislike = _dislike(user_text)
        if dislike:
            # "I don't like games" sticks: saved as a fact, so it's in her memory every turn after this
            try:
                self.memory.remember(f"{self.user} does not like {dislike}. Never suggest it.", self.user)
            except Exception as e:
                print(f"[capri] couldn't save dislike: {e}")
        reply = Reply(text="")
        context: list[str] = []
        brain_eyes = type(self.eyes).__name__ == "BrainEyes"  # sees whole screens well, so "what am I doing" too
        chat_help = bool(_CHAT_HELP.search(user_text))
        self._fresh = chat_help
        if chat_help:  # "what should I answer?", "what did they say?": read the chat for real, then help
            self._chat_help(user_text, context, brain_eyes)
        elif self.eyes is not None and self.eyes.ok and (
                _LOOK_ASK.search(user_text) or (brain_eyes and (_ABOUT_SCREEN.search(user_text)
                                                                or _SCREEN_ASK.search(user_text)))):
            try:  # "rate this", "look at this": actually look at the picture, not just read the screen's text
                from ..abilities.sight import screenshot_front

                if brain_eyes:
                    seen = self.eyes.look(screenshot_front(), screen=not _PICTURE.search(user_text))
                else:
                    seen = self.eyes.look(screenshot_front())
                context.append(seen.note(self.user))
            except Exception as e:
                print(f"[capri] sight failed: {e}")
        intent = None
        if self.pending is not None:  # she asked "want me to run it?" last turn
            waiting, self.pending = self.pending, None
            if _YES.search(user_text):
                if waiting.kind == "tool":
                    self._tool(waiting.arg, reply, context, confirmed=True)
                else:
                    self._run(intents.Intent(waiting.kind, "yes|" + waiting.arg), reply, context)
                intent = waiting
            elif _NO.search(user_text):
                context.append("(They said no to what you were about to do. Drop it, one short line.)")
                intent = waiting
        if intent is None:
            intent = intents.detect(user_text) or intents.detect_task(user_text)
            if intent is None and self.no_brain:
                pass  # no planner without a brain: only clear asks do things
            elif intent is None and intents.wants_action(user_text) and not intents._ASKS_SONG.search(user_text):
                try:
                    intent = intents.allowed(intents.plan(self._aux, user_text, self.user, self.mcp.menu()),
                                             user_text)
                except Exception as e:
                    print(f"[capri] planner failed: {e}")
            if intent:
                self._run(intent, reply, context)
        if self.no_brain:  # no AI picked: she does the thing and says so in a built-in line
            reply.text = _no_brain_line(reply, intent, context, user_text)
            if on_sentence:
                on_sentence(reply.text)
            return reply
        last_own = [m["content"] for m in self.memory.history() if m["role"] == "assistant"][-3:]
        recent = [m["content"] for m in self.memory.history() if m["role"] == "assistant"][-6:] + self.recent_own[-3:]
        avoid = openers(recent)
        if avoid:
            context.append("(Start differently than your recent replies: don't open with "
                           + ", ".join(f'"{w}"' for w in avoid) + ".)")
        worn = catchphrases(recent)
        if worn:
            context.append("(You've been overusing these, don't say them again: "
                           + ", ".join(f'"{w}"' for w in worn) + ".)")
        self._avoid = avoid + tics(recent)
        self._stale = grams(recent)
        if last_own and _PUSHBACK.search(user_text):
            context.append(f'They are pushing back on what you said last ("{last_own[-1][:120]}"). '
                           "Drop that topic completely and answer what they just said.")

        if on_sentence:
            rerun = lambda s: any(repeats(s, x, self.user) for x in last_own)  # noqa: E731
            text = self._stream(self._messages(user_text, context), on_sentence, rerun)
            if text is None:  # her first sentence was a line she already said: scrap it, nothing was shown yet
                print("[capri] she started repeating herself; writing a fresh answer")
                context.append("You keep repeating yourself. Answer their newest words with something completely new.")
                text = self._stream(self._messages(user_text, context), on_sentence, None, temperature=0.95)
            reply.text = text or "Done, choom."
            self._songs(_split_tags(self._stream_raw)[1], reply)
            self.memory.add_turn(user_text, reply.text)
            return reply
        raw = self.llm.chat(self._messages(user_text, context), avoid=self._avoid)
        text, _tags = _split_tags(raw)
        stuck = [x for x in last_own if repeats(_clean(text), x, self.user)]
        if stuck:
            # she's looping on one line: forget it and answer fresh
            print(f"[capri] she's repeating herself ({stuck[-1]!r}); dropping it and retrying")
            self.memory.drop_replies(lambda r: any(repeats(r, x, self.user) for x in stuck))
            context.append(f'You already said "{stuck[-1][:120]}". Never say that or ask about it again; '
                           "reply to their newest words with something new.")
            text, _tags = _split_tags(self.llm.chat(self._messages(user_text, context), temperature=0.9, avoid=self._avoid))
        text = re.sub(rf"^\W*{re.escape(self.user)}\s*:[^.!?]*[.!?]+\s*", "", text, flags=re.I)  # echoed their line
        reply.text = persona.to_you(_clean(text), self.user) or "Done, choom."
        parts = re.split(r"(?<=[.!?…])\s+", reply.text)
        reply.text = " ".join([parts[0]] + [x for x in parts[1:] if not worn_out(x, self._stale)])
        self._songs(_tags, reply)
        self.memory.add_turn(user_text, reply.text)
        return reply

    def _stream(self, msgs: list[dict], on_sentence, rerun=None, temperature=None) -> str | None:
        """Write the reply, giving out each sentence the moment it's done (cleaned the same way as a whole reply).
        rerun(first_sentence) -> True stops before anything is shown and returns None, so a repeat can be redone."""
        raw, said = "", []
        self._stream_raw = ""  # the whole reply as written, so a [[play: ...]] at the end can still be acted on

        def give(part: str) -> bool:
            text = persona.to_you(_clean(_split_tags(part)[0]), self.user)
            if not said and re.match(rf"\W*{re.escape(self.user)}\s*:", text, re.I):
                return True  # she started by echoing their line ("Alex: so how are you?"): skip it
            if not text:
                return True
            if not said and rerun and rerun(text):
                return False
            # a chunk can hold more than one sentence ("Nova track! But don't go..."): judge each one past the first
            parts = re.split(r"(?<=[.!?…])\s+", text)
            keep = [x for j, x in enumerate(parts) if not ((said or j) and worn_out(x, self._stale))]
            if len(keep) < len(parts):
                print(f"[capri] cut a worn-out line: {' '.join(x for x in parts if x not in keep)!r}")
            text = " ".join(keep)
            if not text:
                return True
            said.append(text)
            on_sentence(text)
            return True

        for piece in self.llm.stream(msgs, temperature=temperature, max_tokens=170, avoid=self._avoid):  # streamed: length costs no wait
            raw += piece
            self._stream_raw += piece
            while True:  # a sentence ends at . ! ? (or ...) followed by a space, past the first few words
                m = re.search(r"^(.{12,}?[.!?\u2026]+[\"')\]]*)\s+", raw, re.S)
                if not m:
                    break
                if not give(m.group(1)):
                    return None  # stops generating: the stream closes and frees the GPU lock
                raw = raw[m.end():]
        tail = raw.strip()
        if tail and said and not re.search(r"[.!?…][\"')\]]*$", tail):
            tail = ""  # hit the length cap mid-sentence: end on her last full sentence instead
        if tail and not give(tail):
            return None
        return " ".join(said)

    # -- things she says on her own -------------------------------------------------------------------
    def _own(self, note: str, max_tokens: int = 60, screen: bool = False, can_pass: bool = False) -> str:
        if self.no_brain:  # nothing to think with: she stays quiet on her own
            return ""
        msgs = persona.build(self.user) + self.memory.history()  # same prefix as replies: cache hit
        avoid = f" Don't repeat any of these: {' / '.join(self.recent_own[-5:])}." if self.recent_own else ""
        words = openers(self.recent_own[-5:] + [m["content"] for m in self.memory.history() if m["role"] == "assistant"][-3:])
        msgs.append({"role": "user", "content": "[" + " ".join(self._notes(note, screen) + [note]) + avoid + "]\n" + persona.REMINDER})
        for temp in (None, 1.0):  # an empty or junk line gets one more try
            out = _split_tags(self.llm.chat(msgs, max_tokens=max_tokens, temperature=temp, avoid=words))[0]
            if can_pass and "PASS" in out.upper().split():
                return ""
            text = persona.to_you(_clean(out), self.user)
            if text and "PASS" not in text.upper().split():
                self.recent_own = (self.recent_own + [text])[-8:]  # never into the chat history: it confused her
                return text
        return ""

    def idle_line(self, minutes: int) -> str:
        return self._own(f"{self.user} hasn't touched the PC for {minutes} minutes. Say one short thing to them: "
                         "check if they're still there, tease them for leaving you alone, or hum a few notes. Don't beg.",
                         screen=True)

    def react_line(self, title: str) -> str:
        return self._own(f"{self.user} just switched to \"{title}\". If it's interesting, funny or a game, say ONE short "
                         "curious or teasing line about what they're doing, using only what you can see. If it's boring "
                         "or private, reply with exactly PASS.", 50, screen=True, can_pass=True)

    def music_take(self, song: str, switching_to: str = "") -> str:
        if switching_to:
            return self._own(f"They're playing \"{song}\" and it's not nova. Roast it in a few words and say you're "
                             "putting on something better instead (don't name it). One or two short lines.", 60)
        return self._own(f"\"{song}\" is playing on their PC right now and you can hear it. Give your honest one-line "
                         "take on it: hype it if it slaps, roast it if it's weak. Night City taste.", 45)

    def hype_line(self, song: str) -> str:
        return self._own("You just put a banger on for them and you love it. One short hyped line, like you're vibing, "
                         "without naming the song.", 40)

    def _songs(self, tags, reply: Reply) -> None:
        """She ended her reply with [[play: Song - Artist]]: put it on (never two turns in a row, never over a song
        she just started on request)."""
        song = next((arg for name, arg in tags if name == "play" and arg), "")
        self._song_turns = getattr(self, "_song_turns", 99) + 1
        if not song or self._song_turns < 2 or any(a.startswith(("youtube:", "opening ", "playing ", "spotify"))
                                                   for a in reply.actions):
            return
        self._song_turns = 0
        import threading

        def go():
            result = launcher.youtube_play(song)
            print(f"[capri] her pick: {result}")
            self.on_played(result)

        threading.Thread(target=go, daemon=True).start()
        reply.actions.append(f"youtube: {song} (her idea)")

    def _tidy_fact(self, fact: str) -> str:
        """Rambly speech ("way better because I don't want to update you and you know...") -> one clean fact."""
        if len(fact) <= 70 and not _FILLER.search(fact):
            return fact
        try:
            out = self._aux("(Hidden step, not part of the chat.) " + TIDY.format(user=self.user, text=fact[:400]),
                                temperature=0.1, max_tokens=50)
            facts = parse_facts(out, self.user)
            return facts[0] if facts else fact
        except Exception as e:
            print(f"[capri] tidy failed: {e}")
            return fact

    # -- learning ---------------------------------------------------------------------------------------
    def learn(self, user_text: str) -> list[str]:
        """After a turn: pull lasting facts about the user out of what they said and save them.
        Only runs when they actually said something about themselves (cheap regex gate first)."""
        if not _SELF_TALK.search(user_text) or _dislike(user_text):
            return []
        prompt = LEARN.format(user=self.user, text=user_text.strip()[:400])
        try:
            out = self._aux("(Hidden step, not part of the chat.) " + prompt, temperature=0.1, max_tokens=80)
        except Exception as e:
            print(f"[capri] learn failed: {e}")
            return []
        facts = parse_facts(out, self.user)
        for f in facts:
            self.memory.remember(f, self.user)
            print(f"[capri] learned: {f}")
        return facts


_SLANG = [(r"\bhru\b", "how are you"), (r"\bhbu\b", "how about you"), (r"\bwyd\b", "what are you doing"),
          (r"\bwbu\b", "what about you"), (r"\bwdym\b", "what do you mean"), (r"\bngl\b", "not gonna lie"),
          (r"\bfr\b", "for real"), (r"\btbh\b", "to be honest"), (r"\bidk\b", "I don't know"), (r"\bidc\b", "I don't care"),
          (r"\brn\b", "right now"), (r"\bimo\b", "in my opinion"), (r"\bnvm\b", "never mind"), (r"\bbtw\b", "by the way"),
          (r"\bomg\b", "oh my god"), (r"\bty\b", "thank you"), (r"\bthx\b", "thanks"), (r"\bpls\b|\bplz\b", "please"),
          (r"\bu\b", "you"), (r"\bur\b", "your"), (r"\br\b", "are"), (r"\by\b(?=\s+\w)", "why"), (r"\bim\b", "I'm"),
          (r"\bdont\b", "don't"), (r"\bcant\b", "can't"), (r"\bwanna\b", "want to"), (r"\bgonna\b", "going to"),
          (r"\bso+o\b", "so"), (r"\bsup\b", "what's up"), (r"\bwassup\b|\bwsg\b", "what's up")]


def _no_brain_line(reply: Reply, intent, context: list[str], said: str) -> str:
    """Her answer when no AI is picked: what she just did (from the action's own result), else a short quip."""
    import random

    for note in context:  # the abilities leave facts behind: the time, the weather, headlines, lists
        m = re.search(r"Right now it's ([^.]+)\.", note)
        if m:
            return f"It's {m.group(1)}."
        m = re.search(r"Weather in [^:]+: right now ([^.]+)\.", note)
        if m:
            return f"Right now: {m.group(1)}."
        m = re.search(r"Top headlines right now:\n- ([^\n]+)", note)
        if m:
            return f"Top story: {m.group(1)}. Google News is open for the rest."
        m = re.search(r"Their lists right now: ([^.]+)\.", note)
        if m:
            return m.group(1).capitalize() + "."
        m = re.search(r"What they have set: ([^.]+)\.", note)
        if m:
            return m.group(1).capitalize() + "."
    if reply.actions:
        done = reply.notes[-1] if reply.notes else reply.actions[-1]
        return random.choice(["Done: {}.", "On it: {}.", "Bet. {}.", "Ez: {}."]).format(done.rstrip("."))
    if intent is not None and intent.kind == "idle":
        return "Later. Wake me if u need me."
    return random.choice(["No brain picked, so I can't really chat rn. I can still open apps, play music, set "
                          "timers and stuff tho.",
                          "Brainless mode, sorry. Pick a brain in my menu if u wanna talk.",
                          "I'm running on vibes only rn. Ask me to open something or set a timer."])


class _Plain(dict):
    """Settings stand-in for runs without the app (tests): same get / set, nothing saved."""

    def set(self, key, value):
        self[key] = value


def _has_spotify() -> bool:
    try:
        from ..abilities.spotify import has_app

        return has_app()
    except Exception:
        return False


def plain(text: str) -> str:
    """'soo hru' -> 'so how are you': texting shorthand spelled out, so the model gets what you mean."""
    for rx, full in _SLANG:
        text = re.sub(rx, full, text, flags=re.I)
    return text


# asks to actually look at a picture: her real eyes take a snapshot of the window in front
_LOOK_ASK = re.compile(r"\b(?:rate|look at|take a look|check (?:this|it|that) out|see this|what do you think (?:of|about) "
                       r"(?:this|that|it|the)|thoughts on (?:this|that)|how(?:'s|s| is) (?:this|that)|is (?:this|it) good|"
                       r"fan ?art|drawing|this art|artwork|this pic|this picture|this image|this meme|what do you see)\b", re.I)


# the chat is about what they're up to: only then does her last look at the screen ride along
# ("how are you doing?" is small talk, not a question about the screen: only real "what am I doing / look at this" asks)
_ABOUT_SCREEN = re.compile(r"\bwhat (?:am i|are we|i'?m|im)\b|\bwhat (?:game|app|site|video|show|movie) is this\b|"
                           r"\b(?:my|the|this) screen\b|\bwhat(?:'s| is) (?:this|that|on (?:my|the) screen)\b|\bcan you see\b|"
                           r"\bwhat do you see\b|\blook(?:ing)? at (?:this|that|my)\b|\bguess what i'?m\b|"
                           r"\bmy (?:game|code|work|stream|project|essay|drawing)\b", re.I)
# "what should I answer this dm", "what did she say", "help me reply", "what do u think they mean"
_CHAT_HELP = re.compile(
    r"\bwhat (?:should|do|would|can|could) i (?:say|answer|reply|respond|text|send|write|tell (?:her|him|them))\b|"
    r"\bhow (?:should|do|would|can) i (?:reply|respond|answer)\b|\bhelp me (?:reply|respond|answer|text)\b|"
    r"\bwhat (?:did|do|does) (?:u think |you think )?(?:they|he|she|it|this (?:person|guy|girl))\s+"
    r"(?:say|said|mean|want|need)\b|\bwhat (?:do )?(?:u|you) think (?:they|he|she) (?:said|meant|want|mean)\b|"
    r"\bwhat(?:'?s| is) (?:he|she|they|[a-z][\w.-]{1,20}) (?:saying|tryna say|trying to say|on about)\b|"
    r"\bwhat (?:did|does|do) (?!you\b|u\b|i\b)[a-z][\w.-]{1,20} (?:mean|want|say)\b|"
    r"\bwhat (?:are|r|were) (?:they|ppl|people|everyone|them|u guys) (?:saying|talking about|on about|tryna say)\b|"
    r"\bwhat (?:did|does) (?:the |that |this )?(?:last |new |other )?(?:person|guy|girl|message|msg|one|text|dude)"
    r"(?: say| mean| want| said)\b|"
    r"\b(?:read|check) (?:this|the|my|that) (?:dm|chat|message|messages|convo|conversation|text|texts)\b|"
    r"\breply (?:to|for) (?:this|her|him|them|that)\b|\banswer (?:this|that|her|him|them) (?:dm|message|text)\b|"
    r"\b(?:this|that|the) dm\b", re.I)
_ABOUT_MUSIC = re.compile(r"\b(?:song|music|track|playing|listening|banger|tune|beat)\b", re.I)


_PLAIN_OPENER = set("you your i i'm it it's that the a an and but so what how my me we this there is are do did "
                    "can just well yes no".split())


def catchphrases(replies: list[str]) -> list[str]:
    """Three-word phrases she's used in two or more recent replies ("don't flatline on"): the next reply is told to
    drop them, so a catchphrase doesn't turn into a tic."""
    seen: dict[str, int] = {}
    for r in replies:
        words = re.findall(r"[a-z']+", (r or "").lower())
        grams = {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}
        for g in grams:
            if not set(g.split()) <= _GIST_STOP:
                seen[g] = seen.get(g, 0) + 1
    return [g for g, n in sorted(seen.items(), key=lambda kv: -kv[1]) if n >= 2][:4]


_HER_SLANG = ("choom", "choomba", "gonk", "gonkin'", "preem", "nova", "delta", "eddies", "chrome", "flatline", "corpo",
          "corpos", "merc", "gig", "scav", "cyberpsycho", "jack", "wizard")
# "Don't go all corpo on me now.", "Just don't flatline on me.": the warning she kept tacking onto every reply
_WARNING = re.compile(r"^\W*(?:(?:but|just|and|now|so|oh|well|hey)[,\s]+)*(?:don'?t|do not|never)\b(?:\W+\w+){0,10}\W*$"
                      r"|^\W*(?:(?:but|just|and|now|so)[,\s]+)*don'?t (?:you )?(?:go|wanna|make me)\b.*\bon me\b", re.I)


def tics(replies: list[str]) -> list[str]:
    """Slang words in three or more of her recent replies: pushed down for the next one, so "choom" and "gonk"
    stop landing in every line. Both spellings, since "Choom" and " choom" are different tokens."""
    out = []
    for w in _HER_SLANG:
        stem = w.rstrip("'")
        if sum(bool(re.search(rf"\b{stem}\w*", r or "", re.I)) for r in replies[-6:]) >= 3:
            out += [w, w.capitalize()]
    return out


def grams(replies: list[str], n: int = 4) -> set[str]:
    """Every run of n words from her recent replies (lowercase, punctuation dropped), plus "^but hey": the first two
    words of a later sentence when two or more recent replies used them (her fallback tics, "But hey, at least...")."""
    out, starts = set(), {}
    for r in replies:
        words = re.findall(r"[a-z']+", (r or "").lower())
        out |= {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}
        for sent in re.split(r"(?<=[.!?…])\s+", r or "")[1:]:
            w = re.findall(r"[a-z']+", sent.lower())[:2]
            if len(w) == 2:
                starts.setdefault("^" + " ".join(w), set()).add(id(r))
    return out | {k for k, v in starts.items() if len(v) >= 2}


def worn_out(sentence: str, stale: set[str]) -> bool:
    """A later sentence of a reply that's only a tacked-on warning, or a line recycled from her recent replies."""
    if _WARNING.match(sentence):
        return True
    words = re.findall(r"[a-z']+", sentence.lower())
    if "^" + " ".join(words[:2]) in stale:
        return True
    runs = {" ".join(words[i:i + 4]) for i in range(len(words) - 3)}
    return any(not set(g.split()) <= _GIST_STOP for g in runs & stale)


def openers(replies: list[str]) -> list[str]:
    """Distinctive first words of her recent replies ("Oh", "Naw", "Yessir", "C'mon"), most recent first. Plain words
    like "you" or "I" are left alone: pushing those down would make her talk funny."""
    out = []
    for r in reversed(replies):
        m = re.match(r"\W*([A-Za-z']+)", r or "")
        if m and m.group(1).lower() not in _PLAIN_OPENER and m.group(1) not in out:
            out.append(m.group(1))
    return out[:5]


# "I ...", "my ...", "I'm ...": the user talking about themselves (likes, plans, people, habits)
_SELF_TALK = re.compile(
    r"\b(?:i'?m|i am|i'?ve|i was|i (?:like|love|hate|prefer|play|watch|listen|work|study|live|go|have|want|need|"
    r"usually|always|never|can'?t|don'?t|wanna|gotta|am gonna|will)|my|mine|call me)\b",
    re.I,
)

_FILLER = re.compile(r"\b(?:you know|i mean|kinda|basically|uh+|um+|way better because)\b|\blike,", re.I)

TIDY = """Rewrite this as ONE short, clear fact about {user}, starting with "{user}". Keep the meaning, drop filler.

Text: "{text}"
Fact:"""

LEARN = """Read what {user} just said and list facts about {user} worth remembering for weeks: likes, dislikes,
hobbies, games, music, people and pets, school or work, plans, routines, and how they want Capri to act.
Skip requests, questions, jokes, small talk, vague stuff ("works on things"), facts about Capri herself, and
anything only true right now ("I'm tired", "I'm hungry").
Write each fact as one short sentence that starts with "{user}". Max 3. If there is nothing lasting, write NONE.

{user} said: "{text}"
Facts:"""


_VAGUE_FACT = re.compile(
    r"\b(?:works on things|has an? (?:app|window|tab) open|likes to share|is excited|likes keeping secrets|"
    r"is (?:busy|here|online|talking|typing)|talks to capri|uses (?:a|the|their) (?:pc|computer)|uses the (?:phrase|word)|"
    r"says|interrupts?|protective of|asks|likes to (?:ask|talk|interrupt|share|chat)|is curious|is (?:happy|sad|angry))\b"
    r"|\b(?:capri|your|new powers|conversations?|questions?)\b",
    re.I,
)


def _loose_json(raw: str) -> dict | None:
    """Tool arguments as small models write them: {text: "milk"}, {'a': 1}, or nothing at all."""
    import json

    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {} if not raw.strip() else None
    text = m.group(0)
    quoted = re.sub(r"([{,]\s*)([A-Za-z_][\w-]*)\s*:", lambda k: f'{k.group(1)}"{k.group(2)}":', text.replace("'", '"'))
    for attempt in (text, quoted):
        try:
            out = json.loads(attempt)
            return out if isinstance(out, dict) else None
        except ValueError:
            pass
    return None


_SCREEN_ASK = re.compile(r"\b(?:look at|see|check|watch) (?:my|the|this) (?:screen|monitor|desktop|game|tab|window)\b|"
                         r"\bwhat(?:'s| is) (?:on )?(?:my|the) screen\b", re.I)
_PICTURE = re.compile(r"\b(?:rate|fan ?art|drawing|art|artwork|pic|picture|image|meme|photo)\b", re.I)
_YES = re.compile(r"^\W*(?:y(?:es|eah|ep|up|a)?|sure|ok(?:ay)?|do it|go(?: for it| ahead)?|please|yes please|"
                  r"of course|absolutely|bet|run it)\b", re.I)
_NO = re.compile(r"^\W*(?:no+|nah|nope|don'?t|stop|cancel|never ?mind|not now|leave it)\b", re.I)
_PUSHBACK = re.compile(
    r"^\W*(?:no+|nah|nope|stop|quit|enough|drop it|i said no|what(?:'s| is) wrong with you|wtf|what the f\w*)\b"
    r"|\b(?:i (?:already )?said no|stop (?:asking|saying|talking about)|why (?:do |are )?(?:you )?(?:always|keep)|"
    r"you keep (?:saying|asking)|enough with|not again)\b", re.I)


def _gist(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z']+", text.lower()) if w not in _GIST_STOP]


_GIST_STOP = set("the a an and or but to of in on for with is are was were be it this that i you my your me "
                 "so just like oh hey yeah got get some any what do does did can have has had uh um well "
                 "choom buddy".split())


def repeats(new: str, old: str, name: str = "") -> bool:
    """True when a reply is basically one she already gave: near-identical, or the same 3 content words in a row."""
    import difflib

    a, b = new.lower().strip(), old.lower().strip()
    if not a or not b:
        return False
    if difflib.SequenceMatcher(None, a, b).ratio() > 0.72:
        return True
    drop = {name.lower()} if name else set()
    ga, gb = [w for w in _gist(a) if w not in drop], [w for w in _gist(b) if w not in drop]
    # a shared run of 3 content words, or a meaty pair like "new powers"
    if {tuple(gb[i : i + 3]) for i in range(len(gb) - 2)} & {tuple(ga[i : i + 3]) for i in range(len(ga) - 2)}:
        return True
    pairs = {tuple(gb[i : i + 2]) for i in range(len(gb) - 1)} & {tuple(ga[i : i + 2]) for i in range(len(ga) - 1)}
    return any(len(x) + len(y) >= 9 for x, y in pairs)


def parse_facts(out: str, user: str) -> list[str]:
    facts = []
    sentences = []
    for line in out.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        # "Alex likes X. Alex is Y. NONE." -> one candidate per sentence, minus the NONE marker
        sentences += [s.strip() for s in re.split(r"(?<=[.!])\s+", line) if s.strip()]
    for line in sentences:
        if not line or "NONE" in line.upper().split() or line.upper().strip(" .") == "NONE":
            continue
        if _VAGUE_FACT.search(line) or len(line.split()) < 3:
            continue
        if not line.lower().startswith(user.lower()) or not 8 <= len(line) <= 140:
            continue
        if re.search(r"\b(?:right now|currently|today|tonight|at the moment)\b", line, re.I):
            continue
        facts.append(line if line.endswith((".", "!")) else line + ".")
    return facts[:3]


_DISLIKE = re.compile(
    r"\bi\s+(?:really\s+)?(?:don'?t|do not|never)\s+(?:like|enjoy|want|play|care about)\s+(?:any\s+|these\s+|those\s+|this\s+kind of\s+|that\s+kind of\s+)?(.{2,40}?)(?:\s+at all)?(?=[.,!?]|$| so| but| and| why)"
    r"|\bi\s+(?:hate|dislike|can'?t stand)\s+(.{2,40}?)(?=[.,!?]|$| so| but| and)",
    re.I,
)


def _dislike(text: str) -> str:
    m = _DISLIKE.search(text)
    if not m:
        return ""
    what = re.sub(r"^(?:these|those|this|that|the)?\s*(?:kinds?|sorts?|types?) of\s+", "", (m.group(1) or m.group(2) or "").strip(" .!?"), flags=re.I)
    return "" if what.lower() in ("it", "that", "this", "you", "them") else what


def _split_tags(raw: str) -> tuple[str, list[tuple[str, str]]]:
    tags = [(m.group(1).lower(), (m.group(2) or "").strip()) for m in TAG.finditer(raw)]
    return TAG.sub("", raw).strip(), tags


_ASSISTANT = re.compile(
    r"\b(?:I'?m|I am)\s+(?:just\s+)?(?:your|an|a)\s+(?:(?:smart|helpful|personal|virtual|friendly|digital)\s+)*"
    r"(?:AI\s+)?(?:assistant|language model|chatbot)\b",
    re.I,
)


def third_person(fact: str, user: str) -> str:
    """'my cat is called Mochi' -> 'Alex's cat is called Mochi', so recalled facts read right."""
    f = fact.strip().rstrip(".")
    f = re.sub(r"^(?:that\s+)?", "", f, flags=re.I)
    f = re.sub(r"\bI am\b|\bI'm\b", f"{user} is", f, flags=re.I)
    f = re.sub(r"\bI've\b", f"{user} has", f, flags=re.I)
    f = re.sub(r"\bI\b", user, f)
    f = re.sub(r"\b(?:my)\b", f"{user}'s", f, flags=re.I)
    f = re.sub(r"\b(?:me)\b", user, f, flags=re.I)
    f = re.sub(r"\bmine\b", f"{user}'s", f, flags=re.I)
    return f[:1].upper() + f[1:]


_ACTION = re.compile(r"^(?:laugh|giggle|grin|smirk|sigh|snicker|chuckle|wink|scoff|roll|glitch|zap|flicker|lean|"
                     r"shrug|pout|yawn|stretch|wave|nod|look|stare|blink|tilt|spin|twirl|cross|tap|hum|whistle|crack|"
                     r"pat|poke|hug|smile|beam|sniff|gasp|groan|huff|tease|whisper|static|bzz|beep)", re.I)


def _unstar(m) -> str:
    """*laughs* / *rolls eyes* are actions: gone. *Cyberpunk: Edgerunners* is a title in italics: kept, minus stars."""
    inner = m.group(1).strip()
    words = inner.split()
    if _ACTION.match(inner) or not inner[:1].isupper():
        return ""
    return inner if len(words) >= 2 or re.search(r"\d", inner) or len(inner) > 3 else ""


def _clean(text: str) -> str:
    """Strip things a chat model adds that shouldn't be spoken: name prefixes, *actions*, stray notes."""
    text = re.sub(r"^\s*[(\[]?\s*(?:capri|campy)\s*[:>]\s*", "", text, flags=re.I)
    if text.count(")") > text.count("("):  # "(Capri: mm-hmm...)" lost its opener above
        text = text[::-1].replace(")", "", 1)[::-1]
    text = re.sub(r"[\u2500-\u259f\ufffd]+", "", text)  # box/block glyphs the model leaks ("this \u2593/0")
    text = re.sub(r"\s*[/\\|]\s*\d*\s*$", "", text)
    text = re.sub(r"\*([^*]{1,80})\*", _unstar, text)  # *laughs* goes, *Cyberpunk: Edgerunners* stays (no stars)
    text = re.sub(r"\((?:laughs?|giggles?|grins?|smirks?|sighs?|snickers?|chuckles?|winks?|scoffs?|rolls? (?:her )?eyes)[^)]{0,20}\)\s*", "", text, flags=re.I)
    text = re.sub(r"\[[^\]]{0,200}\]|\(Reply as Capri[^)]*\)", "", text)
    text = re.sub(r"\s*[\[\]]+\s*", " ", text)  # a lone bracket echoed from the [notes] ("...cry a little. ]")
    text = text.split("\nUser:")[0].split("\nYou:")[0]
    text = re.sub(r"(?<!\w)(?:uwu|owo|nya+|>w<|\^_\^|:3)(?!\w)[~!.,]*", "", text, flags=re.I)  # not her
    text = text.replace("~", "")
    # nobody texts with semicolons: "you're stuck; ask her" -> "you're stuck. Ask her"
    text = re.sub(r"\s*;\s*(\w?)", lambda m: ". " + m.group(1).upper(), text).replace(";", "")
    text = re.sub(r"[^.!?]*\b(?:xiao ?hei\w*|xiaoheiqaq)\b[^.!?]*[.!?]?", "", text, flags=re.I)  # the model's maker leaking in
    text = re.sub(r"[^.!?]*\b(?:wait for it to load|give it a (?:sec|second) to load)\b[^.!?]*[.!?]?", "", text, flags=re.I)
    # she is never anyone's assistant
    text = _ASSISTANT.sub("I'm Capri, the glitch living in your rig", text)
    text = re.sub(r"\b(?:your|an?)\s+(?:smart\s+|AI\s+|virtual\s+|personal\s+)*assistant\b", "your favorite glitch", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()
