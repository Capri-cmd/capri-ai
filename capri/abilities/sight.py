"""Her real eyes: a small vision-language model (InternVL3.5-1B, ERU AI's copy) that looks at a picture and writes down
what's in it. It doesn't talk for her: her own brain reacts to the description in her voice.

A few short, focused looks work much better than one long one with a 1B model: what the picture is (style, character,
colours, mood), any words in it, and whether it's fan art of her (her spiky hot-pink hair, the neon green glow).
"""
from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass, field

DESCRIBE = ("Describe this picture for someone who can't see it, in 3 or 4 sentences: what it is (a drawing, photo, "
            "meme, screenshot...), the art style, the main character if there is one (hair, face, outfit, pose), the "
            "colours and the mood. If there are words written in it, quote them.")
HER = "Does the main character have wild spiky bright pink or red hair AND neon green glowing parts? Answer only yes or no."


@dataclass
class Sight:
    """What she saw in one picture."""
    description: str
    text: str = ""
    her: list = field(default_factory=list)
    seconds: float = 0.0

    @property
    def is_her(self) -> bool:
        return len(self.her) >= 2

    def note(self, user: str) -> str:
        parts = [f"(You're looking at a picture on {user}'s screen with your own eyes. You see: {self.description}"]
        if self.text:
            parts.append(f'words in it: "{self.text}"')
        if self.is_her:
            parts.append(f"it's fan art of YOU: it has your {', '.join(self.her)}")
        parts.append("react like you're really looking at it: what you notice, your honest take, a rating out of 10 "
                     "if they asked. Don't list everything, don't describe it like a robot)")
        return ". ".join(p.rstrip(".") for p in parts)


class Eyes:
    def __init__(self, model_dir: str, gpu_lock):
        self.dir = model_dir
        self.lock = gpu_lock  # one CUDA user at a time with the brain and the ears
        self.model = self.processor = None
        self.error = None
        self.ready = threading.Event()

    def load(self):
        """Blocking (~20 s). Leaves self.error set instead of raising, so she just can't see if it fails."""
        t = time.monotonic()
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor

            free = torch.cuda.mem_get_info()[0] / 2 ** 20 if torch.cuda.is_available() else 0
            if free < 2600:
                raise RuntimeError(f"only {free:.0f} MB of GPU memory free, her eyes need ~2600 MB")
            self.processor = AutoProcessor.from_pretrained(self.dir)
            ip = getattr(self.processor, "image_processor", None)
            if ip is not None and hasattr(ip, "max_patches"):
                ip.max_patches = 4  # 448 px tiles: more = sharper but slower (4 keeps a look to a few seconds)
            self.model = AutoModelForImageTextToText.from_pretrained(self.dir, torch_dtype=torch.bfloat16).to("cuda").eval()
            self.torch = torch
            gc = self.model.generation_config
            eos = gc.eos_token_id if isinstance(gc.eos_token_id, list) else [gc.eos_token_id]
            self.model.generation_config.pad_token_id = self.processor.tokenizer.pad_token_id or eos[0]
            from PIL import Image

            self.ready.set()
            self.look(Image.new("RGB", (64, 64), (128, 128, 128)), quiet=True)  # warm-up: the first real look is fast too
            print(f"[capri] sight: InternVL ready in {time.monotonic() - t:.1f}s")
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.model = None
            print(f"[capri] sight unavailable ({self.error}); she'll only read text on screen")
        finally:
            self.ready.set()

    @property
    def ok(self) -> bool:
        return self.model is not None

    def _ask(self, image, question: str, max_new_tokens: int) -> str:
        torch = self.torch
        messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": question}]}]
        inputs = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                                    return_dict=True, return_tensors="pt")
        inputs = {k: (v.to("cuda", dtype=torch.bfloat16) if v.is_floating_point() else v.to("cuda")) for k, v in inputs.items()}
        with torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        text = self.processor.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return " ".join(re.sub(r"<think>.*?</think>", "", text, flags=re.S).split())

    def look(self, image, quiet: bool = False) -> Sight:
        """A PIL image -> Sight. A few seconds on the GPU."""
        if not self.ready.wait(60) or not self.ok:
            raise RuntimeError(self.error or "her eyes aren't loaded yet")
        image = _rgb(image, 1280)
        t = time.monotonic()
        with self.lock:
            description = self._ask(image, DESCRIBE, 130)
            her = ["spiky hot-pink hair", "neon green glow"] if self._ask(image, HER, 3).lower().startswith("yes") else []
        quoted = re.findall(r'"([^"]{2,200})"', description)
        sight = Sight(description, max(quoted, key=len) if quoted else "", her, time.monotonic() - t)
        if quiet:
            return sight
        print(f"[capri] sight: looked in {sight.seconds:.1f}s{' (fan art of her)' if sight.is_her else ''}: {description[:140]}")
        return sight


SCREEN = ("This is a screenshot of someone's computer screen. In 3 or 4 sentences: which app, game or website it "
          "is, what they're doing or what's happening in it right now, and any important text (quote it). Be "
          "specific: names of things you can read, not just 'a game'.")


class BrainEyes:
    """Eyes through her own brain, when its GGUF came with a vision projector (llama-server --mmproj): no second
    model, no torch, no extra VRAM. Same Sight result as Eyes, so the rest of her doesn't care which one it is."""

    error = ""

    def __init__(self, llm):
        self.llm = llm

    @property
    def ok(self) -> bool:
        return bool(getattr(self.llm, "vision", False))

    def read_chat(self, image, user: str) -> str:
        """A screenshot of a chat (Discord, WhatsApp, DMs...) written out as text, oldest first, "Name: message" per
        line, so her brain can answer about it for real instead of from a one-line summary."""
        import base64
        import io

        image = _rgb(image, 1600)
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=88)
        url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        ask = (f"This is a screenshot of a chat on {user}'s computer. Write out the conversation you can read in it, "
               "oldest to newest, one message per line as 'Name: message'. Messages from the person using this "
               f"computer are from {user} (on the right in phone-style chats, or under {user}'s own name). Quote "
               "every message exactly as written, including short ones. Include what's typed in the message box "
               "but not sent yet as 'DRAFT: ...'. Only the conversation: no channel lists, no descriptions. "
               "At most 15 lines.")
        t = time.monotonic()
        out = self.llm.chat([{"role": "user", "content": [{"type": "text", "text": ask},
                                                          {"type": "image_url", "image_url": {"url": url}}]}],
                            max_tokens=420, temperature=0.1)
        print(f"[capri] sight (chat): read in {time.monotonic() - t:.1f}s: {out[:160]!r}")
        return out.strip()

    def look(self, image, quiet: bool = False, screen: bool = True) -> Sight:
        import base64
        import io

        image = _rgb(image, 1280)
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=85)
        url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        t = time.monotonic()

        def ask(question, n):
            return self.llm.chat([{"role": "user", "content": [{"type": "text", "text": question},
                                                                 {"type": "image_url", "image_url": {"url": url}}]}],
                                 max_tokens=n, temperature=0.2)

        description = ask(SCREEN if screen else DESCRIBE, 180)
        her = ["spiky hot-pink hair", "neon green glow"] if not screen and ask(HER, 3).lower().startswith("yes") else []
        quoted = re.findall(r'"([^"]{2,200})"', description)
        sight = Sight(description, max(quoted, key=len) if quoted else "", her, time.monotonic() - t)
        if not quiet:
            print(f"[capri] sight (brain): looked in {sight.seconds:.1f}s: {description[:140]}")
        return sight


def screenshot_front(skip_titles=("Capri",)):
    """The window in front of you, as a PIL image (the whole screen if that window can't be found). Never saved."""
    if sys.platform.startswith("linux"):
        from .. import linux

        return linux.grab_active() or linux.grab_screen()
    from PIL import ImageGrab

    from . import vision

    r = vision.foreground_rect()
    title = vision.active_window_title()
    if r and r[2] - r[0] > 200 and r[3] - r[1] > 150 and title not in skip_titles:
        return ImageGrab.grab(bbox=r, all_screens=True)
    return ImageGrab.grab(all_screens=True)


def _just_the_words(answer: str) -> str:
    """'The text in the image reads: "WHEN THE CODE..."' -> 'WHEN THE CODE...'; '' if it says there are none."""
    a = answer.strip()
    if re.search(r"\b(?:no (?:words|text)|none|there are no|does not contain|doesn't contain)\b", a, re.I) \
            and not re.search(r'"[^"]{2,}', a):
        return ""
    quoted = re.findall(r'"([^"]{1,200})"?', a)
    if quoted:
        return max(quoted, key=len).strip()
    a = re.sub(r"^(?:the )?(?:text|words?)(?: in the (?:image|picture))?(?: (?:reads|says|is|are))?:?\s*", "", a, flags=re.I)
    return a.strip(' ."')


def _rgb(image, max_side: int):
    """Transparent pictures on a grey background (a 1B model reads black-on-nothing badly), not bigger than needed."""
    from PIL import Image

    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        bg = Image.new("RGBA", image.size, (200, 200, 205, 255))
        bg.alpha_composite(image)
        image = bg
    image = image.convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    return image
