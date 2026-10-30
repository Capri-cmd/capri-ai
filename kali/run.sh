#!/usr/bin/env bash
# Capri on Kali / Debian / Ubuntu, from source. First run: offers to install the system bits she needs (apt), makes a Python
# environment in .venv and installs the packages (PySide6, numpy, sound; no torch). Then she starts; her brain,
# ears and voice download from her right-click menu.
#   bash kali/run.sh           start her
#   bash kali/run.sh --setup   pick and download everything in the terminal instead
# Talk key on Wayland: sudo usermod -aG input "$USER"   (then log out and back in)
cd "$(dirname "$0")/.." || exit 1

ask() {  # ask "question" -> 0 for yes (Enter = yes)
  local a
  read -r -p "? $1 [Y/n] " a
  [[ -z "$a" || "$a" =~ ^[Yy] ]]
}

if [ ! -f .venv/installed.txt ]; then
  PY=""
  for p in python3.12 python3.13 python3.11 python3.10 python3.14 python3; do
    if command -v "$p" >/dev/null && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY="$p"; break; fi
  done
  if command -v apt-get >/dev/null; then
    missing=()
    for pkg in python3-venv python3-pip libportaudio2 libxcb-cursor0 libvulkan1 tesseract-ocr playerctl; do
      dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if [ ${#missing[@]} -gt 0 ]; then
      echo "Capri needs these system packages: ${missing[*]}"
      if ask "Install them with apt now (asks for your password)?"; then
        sudo apt-get update && sudo apt-get install -y "${missing[@]}" || exit 1
        [ -z "$PY" ] && PY=python3
      fi
    fi
  fi
  if [ -z "$PY" ]; then echo "Capri needs Python 3.10 or newer (sudo apt install python3)"; exit 1; fi
  if [ ! -x .venv/bin/python ]; then
    echo "Making the Python environment with $PY ..."
    "$PY" -m venv .venv || { echo "Setup failed."; exit 1; }
  fi
  .venv/bin/python -m pip install --upgrade pip --quiet
  echo "Installing packages (a few minutes the first time) ..."
  .venv/bin/python -m pip install -r portable/requirements.txt || { echo "Setup failed. Run it again to retry."; exit 1; }
  # her cloned voice (its Chinese extra jieba_fast isn't needed: she speaks English)
  .venv/bin/python -m pip install --no-deps genie-tts==2.0.2 || { echo "Setup failed. Run it again to retry."; exit 1; }
  # her ears: there's no whisper.cpp package here, so faster-whisper (CPU) does the listening
  .venv/bin/python -m pip install faster-whisper || { echo "Setup failed. Run it again to retry."; exit 1; }
  echo ok > .venv/installed.txt
fi
# her brain, ears and voice download from her right-click menu; bash kali/run.sh --setup still asks in the terminal
if [ "$1" = "--setup" ]; then
  .venv/bin/python -m capri.setup_cli --setup
  [ $? -eq 2 ] && exit 0
fi
exec .venv/bin/python capri_dev.py
