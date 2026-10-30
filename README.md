<p align="center">
  <img src="docs/images/entrance.gif" height="260" alt="Capri's entrance: a signal-lock screen in the corner, then she pours out of it as pixels">
  <img src="docs/images/talking.gif" height="260" alt="Capri talking in her speech bubble">
</p>
<p align="center">
  <img src="docs/images/teleport.gif" width="640" alt="Capri teleports across the screen as a ribbon of her own pixels">
</p>

<h1 align="center">Capri</h1>

<p align="center">
  <b>Capri from <i>Cyberpunk: Edgerunners 2</i>, living on your desktop.</b><br>
  She roams your screen, sits on your windows, peeks from the edges, talks back out loud,<br>
  hears you, sees your screen when you ask, and does little jobs on your PC.<br>
  100% local: no API keys, no cloud, no subscription.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0e0616?style=flat-square&logo=windows&logoColor=white" alt="Windows 10 | 11">
  <img src="https://img.shields.io/badge/also-Arch%20Linux-0e0616?style=flat-square&logo=archlinux&logoColor=white" alt="Arch Linux">
  <img src="https://img.shields.io/badge/runs-100%25%20local-2bff9a?style=flat-square" alt="Runs 100% local">
  <img src="https://img.shields.io/badge/brain-llama.cpp-ff2e70?style=flat-square" alt="Brain: llama.cpp">
  <img src="https://img.shields.io/badge/voice-GPT--SoVITS-78faff?style=flat-square" alt="Voice: GPT-SoVITS">
  <a href="https://www.virustotal.com/gui/file/a9aa4bebe35bd4a2d801bed789a9c6cb5485be5446347abe291cfdc0a26c9799"><img src="https://img.shields.io/badge/VirusTotal-0%2F40%20clean-2bff9a?style=flat-square&logo=virustotal&logoColor=white" alt="VirusTotal: 0/40 clean"></a>
  <img src="https://img.shields.io/badge/choom-approved-ff2e70?style=flat-square" alt="Choom approved">
</p>

<p align="center">
  <a href="#install-windows">Install</a> ·
  <a href="#first-start">First start</a> ·
  <a href="#what-she-does">What she does</a> ·
  <a href="#what-you-need">What you need</a> ·
  <a href="#linux-arch--cachyos">Linux</a> ·
  <a href="#troubleshooting">Troubleshooting</a> ·
  <a href="#for-developers">Developers</a>
</p>

---

## Install (Windows)

1. Download **`Capri-Setup.exe`** from the [latest release](../../releases/latest).
2. Double-click it. If Windows SmartScreen says *"Windows protected your PC"*, click **More info** → **Run anyway**
   (the installer isn't code-signed yet; it scans clean, see below).

> **Is it safe?** [**0 / 40 security vendors flag it on VirusTotal**](https://www.virustotal.com/gui/file/a9aa4bebe35bd4a2d801bed789a9c6cb5485be5446347abe291cfdc0a26c9799).
> Check that your download is that exact file: in PowerShell, run `Get-FileHash Capri-Setup.exe` and compare with
> `A9AA4BEBE35BD4A2D801BED789A9C6CB5485BE5446347ABE291CFDC0A26C9799`.
3. Follow the wizard. A little synthwave track plays while you set up; the **Music** button in the corner turns it
   off.

### Step by step

| | |
| --- | --- |
| <img src="docs/images/setup/1-welcome.png" width="420" alt="Welcome page"> | **1. Welcome.** Click **Next**. |
| <img src="docs/images/setup/2-license.png" width="420" alt="License page"> | **2. License.** Capri is a free, fan-made, non-commercial project. Pick *I accept the agreement*, then **Next**. |
| <img src="docs/images/setup/3-folder.png" width="420" alt="Install folder page"> | **3. Install folder.** The default needs no admin rights. Her models go in this folder too (about 6-8 GB with a brain), so pick a drive with room. |
| <img src="docs/images/setup/4-components.png" width="420" alt="Components page"> | **4. Pick what she gets.** <br>• **Brain**: the AI model she thinks with. *Nemotron Heretic E4B* is recommended (smart, and it can see your screen). Smaller cards: *CapriAI2 (4B)*. Untick it to run her without AI.<br>• **Brain engine**: *CUDA* for NVIDIA cards (picked for you if you have one), *Vulkan* for any card.<br>• **Ears**: talk to her with your mic. *Small* is the sweet spot.<br>• **Voice**: she talks out loud, in a voice close to hers.<br>The dropdown at the top has ready-made picks: *Everything* or *Light*. |
| <img src="docs/images/setup/5-name.png" width="420" alt="Name page"> | **5. Your name.** What she calls you. |
| <img src="docs/images/setup/6-tasks.png" width="420" alt="Tasks page"> | **6. Extras.** Let her look at your screen when you ask (her eyes), and a desktop shortcut. |
| <img src="docs/images/setup/7-ready.png" width="420" alt="Ready page"> | **7. Install.** Everything you picked downloads straight into her folder, then she installs. Tick **Start Capri** on the last page and she drops onto your desktop. |

> **Downloads:** the brain model is big (3-6 GB) and Windows stages downloads in your Temp folder on `C:` first, so
> keep that much free on `C:` while it installs. If a download fails, run the installer again; it skips what's
> already there.

**Uninstall:** Windows Settings → Apps → Capri → Uninstall (removes her memory and models too).

## First start

- She drops in through a little signal-lock screen in the top-right corner and says hi.
- **Click her** to type to her. **Hold `Ctrl+1`** to talk (change the key: right-click her → *Ears*).
- **Right-click her** and a door opens beside her with her menu inside: her brain (swap models live, or download a
  new one right there), ears, voice on/off, size, *Go mini*, roam, quit.
- **Drag her** around. Drop her near the left, right or top edge and she peeks out from it. Throw her and she falls.
- Her voice takes a minute or two to warm up the first time she starts. Until then she types without talking.

## What she does

- **Lives on your desktop.** Stands on the taskbar, sits on your window tops and desktop icons, rides along when you
  move a window, peeks from the screen edges, naps in her biochip in the corner, and teleports around as a stream of
  her own pixels.
- **Talks like a person.** A local LLM (llama.cpp) with her personality: short, teasing, real answers. She remembers
  things about you between chats.
- **A voice close to hers.** Capri's official voice actor is against cloning her voice with AI, so we don't use
  it. We made a new AI voice that sounds close to Capri instead (GPT-SoVITS, run on your CPU with Genie-TTS). She
  says her slang right (choom, preem, gonk) and reads text-speak like a person (*ngl* → "not gonna lie").
- **Hears you.** Speech to text with whisper.cpp, on your CPU, so your graphics card stays free for her brain.
- **Sees your screen when you ask.** "What do you think of this?", "what should I answer here?" (her eyes need the
  Nemotron brain).
- **Does jobs on your PC.** Ask in plain words:
  - "open Spotify", "open Discord", "open a new tab and look for green yuri"
  - "play something chill", "skip this song", "what's playing?"
  - "set a timer for 10 minutes", "remind me at 6 to eat"
  - "what's the weather in Tokyo?", "any news on Edgerunners 2?"
  - "make me a txt with a packing list", "add milk to my todo"
- **Vibes to your music.** Her hair bops to the beat of whatever your PC is playing.

<p align="center">
  <img src="docs/images/peek.gif" height="200" alt="Capri peeks down from the top of the screen">
  <img src="docs/images/outro.gif" height="200" alt="Capri leaves: she streams up into the little screen and it switches off">
</p>
<p align="center"><i>Peeking from the top edge · leaving when you quit</i></p>

Everything runs on your PC. Nothing you say to her is sent anywhere.

## What you need

| | Minimum | Good |
| --- | --- | --- |
| **System** | Windows 10 / 11, 64-bit | |
| **Graphics card** | 4 GB VRAM (CapriAI2 4B) | 6-8 GB VRAM (Nemotron E4B, Mistral-Nemo 12B) |
| **Disk** | 2 GB (no brain) | 10 GB (brain + ears + voice) |
| **CPU** | any 4-core | 6+ cores (her voice and ears run here) |

No graphics card? Untick the brain: she still roams, peeks, plays and answers with short lines of her own.

**Bring your own model:** any `.gguf` that llama.cpp runs works. Put it in her `models\llm` folder, then right-click
her → *Brain* and pick it. It swaps live.

## Linux

```bash
git clone https://github.com/Capri-cmd/Capri-AI.git
cd Capri-AI
bash arch/run.sh     # Arch / CachyOS
bash kali/run.sh     # Kali / Debian / Ubuntu
```

The first run offers to install what she needs with your package manager (python, portaudio, xcb-util-cursor,
vulkan, and tesseract / playerctl for her eyes and music; whisper-cpp and grim on Arch), makes its own Python
environment, then starts her. Her brain, ears and voice download from her right-click menu (*Brain* → *Get ...*).
`--setup` picks everything in the terminal instead. On Kali her ears use faster-whisper (no whisper.cpp package there).

On Wayland she runs through XWayland and sees your screen with grim (Hyprland / Sway), Spectacle (KDE) or
gnome-screenshot (GNOME). The hold-to-talk key reads the keyboard from `/dev/input`, which needs
`sudo usermod -aG input $USER` (then log out and back in).

## Troubleshooting

| Problem | Fix |
| --- | --- |
| She doesn't talk out loud | Her voice warms up for 1-2 minutes after she starts. Check right-click → *Her voice* is ticked. |
| She doesn't hear me | Right-click → *Ears*: pick your mic, check the talk key. Hold the key while you speak. |
| "Windows protected your PC" | More info → Run anyway. The installer isn't code-signed yet. |
| She can't sit on my apps | She sits on window tops; a maximized window's top is the edge of the screen. Shrink the window a bit. |
| Something broke | Logs are in her folder: `data\capri.log`, `data\llama-server.log`, `data\whisper-server.log`. |
| Forget everything | Delete `data\memory.json` in her folder. |

## For developers

**Run from source (Windows):** `windows\start.bat`. The first run makes a `.venv` (Python 3.10-3.13, no torch),
installs `portable\requirements.txt`, then starts her; downloads are in her right-click menu. Her voice model
(`models\voice\capri-clone`, 237 MB) is too big for git: download `capri-clone.zip` from the release and unzip it into
`models\voice\`.

**Build the installer:** `.venv\Scripts\python.exe tools\build_release.py`. Needs
[Inno Setup 6](https://jrsoftware.org/isinfo.php) and the voice model above. It builds `Capri.exe` with PyInstaller
and wraps it in the setup wizard (`tools\installer\capri.iss`); the wizard's component list and downloads are
generated from `capri\portable.py`, so the app and the installer always offer the same things.

**Tests:** `.venv\Scripts\python.exe -m pytest tests`

```
capri/              her code
  desk/             her body: sprites, moves, effects, entrance, speech bubble, menus
  brain/            chat, personality, intent detection, the llama.cpp backend
  voice/            voices (GPT-SoVITS / Kokoro), ears, slang pronunciations (words.py)
  abilities/        jobs: apps, browser, music, weather, reminders, notes, screen
  portable.py       what she can download (brains, ears, engines, voice), and the downloader
  setup_cli.py      terminal setup (y/n), for --setup
capri_dev.py        entry point
windows/  arch/  kali/   start.bat / run.sh: run from source on each system
portable/           default config, requirements
tools/              build_release.py (installer), make_door_sfx.py (menu door sounds), installer/ (wizard, art, music)
assets/             sprites, the menu's door art, font, icons, her recorded hellos
```

See [CONTRIBUTING.md](CONTRIBUTING.md) to help out.

## Credits

- **Her sprites and recorded hellos:** [Lachy](https://github.com/lachydotmcg), PolyForm Noncommercial 1.0.0
  (see `assets/desk/LICENSE.md`).
- **Her menu's door art** (the portal that opens, its glitch loop): **xilia_world00** on Discord, drawn for Capri
  (`assets/desk/door`).
- **Brain models:** [CapriAI2](https://huggingface.co/Ghasty3/CapriAI2) and the Nemotron Heretic build were trained
  by [Ghasty](https://github.com/ghasty3).
- **Brain:** [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT) · **Ears:**
  [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (MIT)
- **Voice:** [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) (MIT), [Genie-TTS](https://github.com/High-Logic/Genie-TTS)
  (MIT), [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) + [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
  (Apache-2.0)
- **UI:** Qt for Python / PySide6 (LGPL), Share Tech Mono (OFL)
- **Setup music:** "Night Drive", an original track made for Capri.

## License

Capri's code is MIT (see [LICENSE](LICENSE)). Her art and recorded hellos are PolyForm Noncommercial: free to use, not to sell.

**Fan-made.** Capri and *Cyberpunk: Edgerunners* belong to CD PROJEKT RED. This project isn't affiliated with or
endorsed by them.
