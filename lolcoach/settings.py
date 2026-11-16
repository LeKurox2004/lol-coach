"""Small persistent settings (settings.json next to main.py)."""
import json
import threading
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "settings.json"
DEFAULTS = {"lang": "en"}  # name language for items/champions: "en" or "de"
_lock = threading.Lock()
_data = None


def _load():
    global _data
    if _data is None:
        try:
            _data = {**DEFAULTS, **json.loads(PATH.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            _data = dict(DEFAULTS)
    return _data


def get(key):
    with _lock:
        return _load().get(key, DEFAULTS.get(key))


def set(key, value):  # noqa: A001 - module-level API
    with _lock:
        data = _load()
        data[key] = value
        try:
            PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass


def lang():
    return "de" if get("lang") == "de" else "en"
