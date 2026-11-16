"""Adds/removes LoL Coach to the Windows startup folder.

    python install_autostart.py            -> install
    python install_autostart.py --remove   -> uninstall

The app then runs invisibly in the background and only shows its window when the League client opens.
"""
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/LoL Coach.lnk"


def pythonw():
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate if candidate.exists() else sys.executable)


def install():
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath=$env:TARGET;$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:WD;$s.Save()"
    )
    env = dict(os.environ, LNK=str(SHORTCUT), TARGET=pythonw(), ARGS=f'"{APP_DIR / "main.py"}" --hidden', WD=str(APP_DIR))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, env=env)
    print(f"Autostart eingerichtet: {SHORTCUT}")


def remove():
    if SHORTCUT.exists():
        SHORTCUT.unlink()
        print("Autostart entfernt.")
    else:
        print("Kein Autostart gefunden.")


if __name__ == "__main__":
    remove() if "--remove" in sys.argv else install()
