"""Capri, the portable dev build (Capri.exe): starts her straight away. Brains, ears and her voice download from her
right-click menu (Brain / Ears / Her voice), no setup window."""
import os
import sys
import time


def _log():
    """No console in the exe: everything she prints goes to data\\capri.log, timestamped."""
    from capri.config import DATA

    DATA.mkdir(exist_ok=True)

    class Log:
        def __init__(self, f):
            self.f, self.fresh = f, True

        def write(self, s):
            for part in s.splitlines(keepends=True):
                if self.fresh:
                    self.f.write(time.strftime("%H:%M:%S "))
                self.f.write(part)
                self.fresh = part.endswith("\n")

        def flush(self):
            self.f.flush()

    sys.stdout = sys.stderr = Log(open(DATA / "capri.log", "a", encoding="utf-8", buffering=1))
    import faulthandler

    faulthandler.enable(open(DATA / "crash.log", "a", encoding="utf-8"), all_threads=True)


def _first_config():
    """Fresh from source: start from the dev build's settings (portable/config.yaml) if there's no config.yaml yet."""
    import shutil
    from pathlib import Path

    from capri.config import ROOT

    template = Path(__file__).resolve().parent / "portable" / "config.yaml"
    if not (ROOT / "config.yaml").exists() and template.exists():
        shutil.copy(template, ROOT / "config.yaml")


def installed(args: list[str]) -> None:
    """Capri-Setup.exe's last step: `Capri.exe --installed brain=nemotron engine=cuda ears=small voice=1 eyes=1
    name=Alex`. Saves what you picked in the wizard and unpacks the engines it downloaded; shows nothing."""
    from pathlib import Path

    from capri import portable
    from capri.config import ROOT, load
    from capri.desk.settings import Settings

    pick = dict(a.split("=", 1) for a in args if "=" in a)
    s = Settings(load())
    brain = next((it for it in portable.BRAINS if it.key == pick.get("brain")), None)
    if brain is not None:
        s.set("brain", str(ROOT / brain.files[0][1]))
    elif not s["brain"] or not Path(s["brain"]).exists():
        s.set("brain", "none")
    ears = next((it for it in portable.EARS if it.key == pick.get("ears")), None)
    if ears is not None:
        s.set("whisper_model", Path(ears.files[0][1]).name)
        s.set("ears", s["ears"] if s["ears"] != "off" else "hold")
    elif not portable.ears_models():
        s.set("ears", "off")
    s.set("voice", pick.get("voice") == "1")
    s.set("eyes", pick.get("eyes", "1") == "1")
    if pick.get("name"):
        portable.set_config_name(pick["name"])
    for it in portable.ENGINE_GPU + [portable.ENGINE_EARS]:
        folder = ROOT / Path(it.files[0][1]).parent
        if all((ROOT / p).exists() for _, p, _ in it.files):  # zips still packed: unpack them
            portable.finish(it)
        elif it.key in (pick.get("engine"), "whisper") and any(folder.rglob("*.exe")):  # the installer unpacked it
            for other in portable.ENGINE_GPU:
                folder.joinpath(".done-" + other.key).unlink(missing_ok=True)
            folder.joinpath(".done-" + it.key).write_text("ok")


def main():
    if "--installed" in sys.argv:
        _first_config()
        _log()
        return installed(sys.argv[sys.argv.index("--installed") + 1:])
    if sys.platform.startswith("linux"):
        # Wayland won't let an app place its own windows (she walks by moving hers), so run her through XWayland.
        # CAPRI_WAYLAND=1 skips this (she'll still show, but stays put).
        if not os.environ.get("CAPRI_WAYLAND"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"
    _first_config()
    if sys.stdout is None or getattr(sys, "frozen", False):
        _log()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication

    from capri import portable
    from capri.config import ASSETS

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(ASSETS / "icons" / "capri.png")))
    keep = {}

    def start():
        from capri.desk.app import DeskApp

        keep["desk"] = DeskApp()

    if portable.needs_setup():  # no setup window: she starts brainless, and her Brain menu gets her one
        from capri.config import load
        from capri.desk.settings import Settings

        have = portable.brains()
        Settings(load()).set("brain", str(have[0]) if have and portable.find_exe("llama-server") else "none")
    start()
    code = app.exec()
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
