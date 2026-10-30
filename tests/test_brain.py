"""Run with: python -m pytest tests  (no model or GPU needed)."""
from capri.brain import intents
from capri.brain.agent import _clean
from capri.brain.llm import _alternate
from capri.brain import persona


def kind(t):
    i = intents.detect(t)
    return (i.kind, i.arg) if i else None


def test_play():
    assert kind("Play Rebel Yell by Billy Idol on Spotify") == ("play", "spotify|Rebel Yell by Billy Idol")
    assert kind("hey capri, can you put on some synthwave") == ("play", "synthwave")
    assert kind("play some music") == ("pick", "")
    assert kind("play lofi on youtube") == ("youtube", "lofi")
    assert kind("youtube nightcall kavinsky") == ("youtube", "nightcall kavinsky")


def test_controls():
    assert kind("skip the song") == ("spotify", "next")
    assert kind("skip this song") == ("spotify", "next")  # clear control: no planner round trip
    assert kind("pause the music") == ("spotify", "pause")
    assert kind("next track") == ("spotify", "next")


def test_remember_idle():
    assert kind("Remember that my cat is called Mochi") == ("remember", "my cat is called Mochi")
    assert kind("go take a nap")[0] == "idle"
    assert kind("Capri, can you go?") == ("idle", "bye")
    assert kind("I love you, Campy.") is None




def test_alternate_and_persona():
    msgs = persona.build("Alex") + [
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "note"},
    ]
    out = _alternate(msgs)
    assert out[0]["role"] == "user" and "Alex" in out[0]["content"]
    assert persona.build("Alex") == persona.build("Alex")  # fixed prefix: llama.cpp's cache depends on it
    assert all(a["role"] != b["role"] for a, b in zip(out, out[1:]))
    assert out[-1]["content"].endswith("note")


def test_clean():
    assert _clean("Capri: *smirks* Gonk. [note]") == "Gonk."


def test_identity_and_memory_wording():
    from capri.brain.agent import third_person

    assert "assistant" not in _clean("I'm your smart assistant. But you can call me Capri if you want.")
    assert third_person("my cat is called Mochi", "Alex") == "Alex's cat is called Mochi"
    assert third_person("I'm allergic to cats", "Alex") == "Alex is allergic to cats"


def test_open_and_browse():
    assert kind("Open Spotify") == ("open", "Spotify")
    assert kind("hey capri can you open discord for me") == ("open", "discord")
    assert kind("open spotify and play rebel yell") == ("play", "spotify|rebel yell")
    assert kind("play this in spotify pls") == ("play", "spotify|@now")
    assert kind("Capri, can you play this song on Spotify, please?") == ("play", "spotify|@now")
    assert kind("put that on spotify") == ("play", "spotify|@now")
    assert kind("play Symphony by Clean Bandit in spotify") == ("play", "spotify|Symphony by Clean Bandit")
    assert kind("spotify play never fade away") == ("play", "spotify|never fade away")
    assert kind("play some music on spotify") == ("play", "spotify|@pick")
    assert kind("play this") is None  # no Spotify: vague, the planner decides
    assert kind("start talking to me") is None
    p = intents.parse_plan
    assert p("ACTION: SPOTIFY next") == intents.Intent("spotify", "next")
    assert p("ACTION: NONE") is None
    assert p("ACTION: OPEN discord") == intents.Intent("open", "planned|discord")
    assert p("ACTION: PLAY bbno$ on Spotify (if not already playing)") == intents.Intent("play", "bbno$")
    assert p("ACTION: PLAY something else") == intents.Intent("pick")
    assert p("ACTION: PICK") == intents.Intent("pick")








def test_dislike():
    from capri.brain.agent import _dislike

    assert _dislike("I said I don't like these kind of games at all, why are you talking like I like them?") == "games"
    assert _dislike("i hate horror movies") == "horror movies"
    assert _dislike("I don't like it") == ""
    assert _dislike("I love you, Campy.") == ""


def test_to_you_rewrites_third_person_only():
    from capri.brain.persona import to_you

    assert to_you("Alex doesn't want to update my code.", "Alex") == "You don't want to update my code."
    assert to_you("Alex does not like games. Never suggest it.", "Alex") == "You do not like games. Never suggest it."
    assert to_you("Alex's cat is called Mochi", "Alex") == "Your cat is called Mochi"
    assert to_you("Hey Alex, wanna play?", "Alex") == "Hey Alex, wanna play?"
    assert to_you("I made this for Alex.", "Alex") == "I made this for you."


def test_parse_facts():
    from capri.brain.agent import parse_facts

    out = "1. Alex plays Valorant.\n- Alex is tired right now\nCapri is cool\nNONE"
    assert parse_facts(out, "Alex") == ["Alex plays Valorant."]
    assert parse_facts("NONE", "Alex") == []


def test_memory_relevant_and_dedupe(tmp_path):
    from capri.abilities.memory import Memory

    cfg = {"memory": {"file": str(tmp_path / "m.json"), "history_turns": 4}, "eru": {"memory": False}}
    m = Memory(cfg)
    m.remember("Alex does not like games. Never suggest it.")
    for i in range(20):
        m.remember(f"Filler fact number {i} about stuff{i}.")
    m.remember("Alex's cat is called Mochi.")
    m.remember("Alex plays Valorant.")
    m.remember("Alex plays Valorant a lot.")
    facts = m.relevant("how is my cat doing", "Alex", limit=6)
    assert facts[0].startswith("Alex does not like games")
    assert "Alex's cat is called Mochi." in facts
    assert sum("Valorant" in f for f in m.facts()) == 1










def test_learner_drops_junk():
    from capri.brain.agent import parse_facts

    assert parse_facts("Alex likes keeping secrets. Alex is excited about their new powers. NONE.", "Alex") == []
    assert parse_facts("Alex works on things. Alex has an app open often.", "Alex") == []


def test_planner_guard():
    I = intents.Intent
    assert intents.allowed(I("play", "Alex's favorite song"), "Hey, wait, are you sneaking a look at my code?") is None
    assert intents.allowed(I("play", "Rebel Yell"), "this is boring, play something by Billy Idol").kind == "play"
    assert intents.allowed(I("open", "planned|spotify"), "what is that on my screen?") is None
    assert intents.allowed(I("play", '"What game do I play?"'), "What game do I play?") is None
    assert intents.allowed(I("play", "lofi"), "can you play something chill, like lofi?").kind == "play"


def test_repeats_catches_her_loop():
    from capri.brain.agent import repeats

    a = "Uh... Alex? You have new powers for me?"
    assert repeats("Hey, Alex! You got some new powers for me?", a, "Alex")
    assert repeats("What's new with you? You got some new powers for me to play with?", a, "Alex")
    assert not repeats("Fine, fine. So what are you working on tonight?", a, "Alex")
    assert not repeats("Hey Alex, what's up?", "Alex! You good?", "Alex")


def test_pushback_and_negated_actions():
    from capri.brain.agent import _PUSHBACK
    from capri.brain.intents import Intent as I

    assert _PUSHBACK.search("No, I don't have any new power for you, Twin")
    assert _PUSHBACK.search("We're not listening to anything. Why always you're talking about listening to stuff?")
    assert not _PUSHBACK.search("Nothing much, just coding")
    assert intents.allowed(I("play", "x"), "We're not listening to anything. What is wrong with you?") is None
    assert intents.allowed(I("play", "Rebel Yell"), "don't play that") is None
    assert intents.allowed(I("play", "Rebel Yell"), "why don't you play Rebel Yell").kind == "play"


def test_clean_strips_afk_junk():
    assert _clean("(Capri: mm-hmm-hmm, da da da. Bored outta my skull)") == "mm-hmm-hmm, da da da. Bored outta my skull"
    assert _clean("Capri: hey") == "hey"
    assert _clean("Still there? this \u2593/0") == "Still there? this"


def test_voice_pronunciation():
    from capri.voice.tts import spoken

    assert spoken("Hey chooms, that's preem.") == "Hey chooms, that's preem."  # the voice server knows her words
    assert spoken("ngl u got this lol") == "not gonna lie you got this"
    assert spoken("idk why ur stressing rn") == "I don't know why you're stressing right now"


def test_browser_search_asks():
    from capri.brain.intents import Intent, allowed, detect

    t = "okay can you at least open like a new tab in my browser and look for it like in like look for green Yuri"
    assert detect(t) == Intent("search", "web|green Yuri")
    assert detect("open a new tab and search for edgerunners 2 release date").arg == "web|edgerunners 2 release date"
    assert detect("I'm looking for a job tbh") is None  # not a song
    assert allowed(Intent("search", "green yuri"), "can you look it up in my browser") == Intent("search", "web|green yuri")


def test_hotkeys_and_youtube_titles():
    from capri.abilities.vision import youtube_song
    from capri.voice import hotkey

    assert hotkey.parse("ctrl+1") == [0x11, 0x31]
    assert hotkey.parse("Ctrl + Space") == [0x11, 0x20]
    assert hotkey.name({0x11, 0x41}) == "ctrl+a"
    assert youtube_song(["Claude", "(3) Kavinsky - Nightcall (Official Video) - YouTube - Brave"]) == "Kavinsky - Nightcall"
    assert youtube_song(["YouTube - Brave"]) == ""


def test_whisper_hallucination_filter():
    from capri.voice.stt import hallucination

    hot = "Capri, Campy, Capricorn, choom"
    assert hallucination("Capri, Capri, Capri, Capri, Capri, Capri", 3, hot)
    assert hallucination("Thanks for watching!", 1.0, hot)
    assert not hallucination("hey Capri what song is this", 2, hot)


def test_real_phrases_from_the_log():
    # what was actually said to her, and what went wrong before
    assert kind("Can you play some music for me, Capri, please?") == ("pick", "")  # was: played "Please Please Please"
    assert kind("Yo, just change the music for me please") == ("pick", "")  # was: a made-up "Bank Account"
    assert kind("play rebel yell for me capri") == ("play", "rebel yell")
    assert kind("Yo Capri, can you play that song that is like I just wanna be part of your symphony?") == (
        "play", "I just wanna be part of your symphony")
    assert kind("soo hru") is None
    assert kind("change the wallpaper") is None


def test_no_signature_endings():
    from capri.brain import agent as A

    recent = ["Nah nah nah, don't go all corpo on me now. Just spit it out, choom.",
              "Putting on Never Fade Away, choom. Don't go cryin' in your keyboard now.",
              "You tryna climb Arasaka Tower now? Take baby steps, choom."]
    assert A.worn_out("Don't go all corpo on me now.", set())
    assert A.worn_out("Just don't flatline on me, choom.", set())
    assert not A.worn_out("Corpos can choke on their eddies.", set())
    assert A.worn_out("Just spit it out, choom, I'm waiting.", A.grams(recent))  # recycled four-word run
    assert not A.worn_out("Show me the clip first.", A.grams(recent))
    assert "choom" in A.tics(recent) and "Choom" in A.tics(recent)
    assert "gonk" not in A.tics(recent)
    assert A.worn_out("Don't go Lucy on me now, can't have you dreaming of the Moon when we've got gigs.", set())
    hey = ["Tori? Gonk. But hey, at least I'm preem.", "VPN? Cute. But hey, free is free."]
    assert A.worn_out("But hey, dream big like David.", A.grams(hey))


def test_next_needs_music():
    assert intents.detect("what should we do next") is None
    assert intents.detect("next song pls") == intents.Intent("spotify", "next")
    assert intents.detect("skip") == intents.Intent("spotify", "next")


def test_artist_hints():
    k = lambda t: (lambda i: (i.kind, i.arg) if i else None)(intents.detect(t))  # noqa: E731
    assert k("hey, can you play me something like, you know, like Ado on Spotify?") == ("play", "spotify|Ado")
    assert k("anyways can you please like play some music for me in Spotify I don't know I'm looking for "
             "something like Ado") == ("play", "spotify|Ado")
    assert k("play me something like ado") == ("play", "ado")
    assert k("can you play some Ado") == ("play", "Ado")
    assert k("play some music on spotify") == ("play", "spotify|@pick")
    assert k("play something chill") == ("pick", "")
    assert k("what do you think of songs by ado") is None
    assert k("play some ado for me in spotify") == ("play", "spotify|ado")


def test_short_first_sentence_still_cuts_the_warning():
    from capri.brain import agent as A

    ag = A.Agent.__new__(A.Agent)
    ag.user, ag._stale, ag._avoid, ag._stream_raw = "Alex", set(), [], ""

    class FakeLLM:
        def stream(self, msgs, **kw):
            yield from ["Nova track! But don't go all netrunner on me and jack ", "into Ado's account now, choom."]

    ag.llm = FakeLLM()
    shown = []
    assert ag._stream([], shown.append) == "Nova track!"


def task(t):
    i = intents.detect_task(t)
    return (i.kind, i.arg) if i else None


def test_tasks_search_files_email():
    assert task("search up the best cyberware in cyberpunk 2077") == ("search", "web|the best cyberware in cyberpunk 2077")
    assert task("hey capri, can you google weather in tokyo") == ("search", "web|weather in tokyo")
    assert task("look the new edgerunners trailer up") == ("search", "web|the new edgerunners trailer")
    assert task("make me a txt with my grocery list: eggs, milk")[0] == "note"
    assert task("write a to-do list for tomorrow")[0] == "note"
    assert task("draft an email to my boss saying I'm sick")[0] == "email"
    assert task("summarize https://example.com/post for me") == ("read", "https://example.com/post")
    assert task("how are you doing today") is None
    assert task("i'm looking at my files") is None
    # the planner's new verbs, and the gate: a search needs a question or an info ask, a file a write-ish word
    assert intents.parse_plan("ACTION: SEARCH cyberware prices night city").kind == "search"
    assert intents.parse_plan('ACTION: TOOL files.read {"path": "a.txt"}').arg == 'files.read {"path": "a.txt"}'
    assert intents.allowed(intents.Intent("search", "x"), "what can I get for 200k eddies?") is not None
    assert intents.allowed(intents.Intent("note", "x"), "you're funny") is None
    assert intents.allowed(intents.Intent("email", "x"), "tell me a joke") is None
    assert intents.wants_action("any good chrome I should buy?")
    from capri.brain.agent import _loose_json

    assert _loose_json('{text: "Buy milk"}') == {"text": "Buy milk"}
    assert _loose_json("{'a': 1, b: 2}") == {"a": 1, "b": 2}
    assert _loose_json("") == {} and _loose_json("{oops") is None


def test_mcp_client_and_confirmation(tmp_path):
    import sys
    import time

    from capri.abilities.mcp import Hub

    server = tmp_path / "fake_mcp.py"
    server.write_text('''import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    m, p = msg["method"], msg.get("params", {})
    if m == "initialize":
        res = {"protocolVersion": p["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "f"}}
    elif m == "tools/list":
        res = {"tools": [{"name": "add", "description": "Add two numbers.", "annotations": {"readOnlyHint": True},
                          "inputSchema": {"properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
                         {"name": "save", "description": "Save a reminder.", "inputSchema": {"properties": {}}}]}
    else:
        a = p["arguments"]
        res = {"content": [{"type": "text", "text": str(a["a"] + a["b"]) if p["name"] == "add" else "saved"}]}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
''')
    hub = Hub({"mcp": {"servers": {"calc": {"command": sys.executable, "args": [str(server)]}}}})
    for _ in range(100):
        if hub.tools():
            break
        time.sleep(0.1)
    try:
        assert 'TOOL calc.add {"a": <number>, "b": <number>}' in hub.menu()
        full, tool, s = hub.find("calc.add")
        assert s.call("add", {"a": 2, "b": 40}) == "42"
        assert hub.safe(tool, s) and not hub.safe(hub.find("save")[1], s)  # read-only runs, the rest asks first
    finally:
        hub.close()


def test_everyday():
    from datetime import datetime

    from capri.abilities import reminders
    from capri.brain import daily

    now = datetime(2026, 10, 28, 14, 30)
    assert reminders.parse("set a timer for an hour and a half", now)["due"] == datetime(2026, 10, 28, 16, 0)
    assert reminders.parse("remind me to stretch in 20 minutes please", now)["what"] == "stretch"
    assert reminders.parse("wake me up at 7:30 tomorrow", now)["due"] == datetime(2026, 10, 29, 7, 30)
    assert reminders.parse("I set a timer earlier lol", now) is None
    assert kind("I want to listen to some Kendrick Lamar") == ("play", "Kendrick Lamar")
    assert kind("can you use my spotify and play Not Like Us") == ("play", "spotify|Not Like Us")
    assert kind("what time is it")[0] == "time"
    assert kind("what time do you sleep") is None
    assert kind("any news about cyberpunk") == ("news", "cyberpunk")
    d = lambda t: (lambda i: (i.kind, i.arg) if i else None)(daily.detect(t))  # noqa: E731
    assert d("leave me alone") == ("privacy", "on")
    assert d("I hate when people leave me alone lol") is None
    assert d("never look at my discord") == ("privacy", "never|discord")
    assert d("help me focus for 45 minutes") == ("focus", "2700")
    assert d("translate this to Spanish") == ("clip", "translate|Spanish")
    assert d("add milk, eggs and bread to my shopping list") == ("todo", "add|milk, eggs and bread|my shopping list")
    assert d("set the volume to 30") == ("pc", "volume|set|30")
    assert d("shut down my pc in an hour") == ("pc", "shutdown|3600")
