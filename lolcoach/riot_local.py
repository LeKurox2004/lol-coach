"""Access to the local League client (LCU) and the in-game Live Client Data API."""
from pathlib import Path

import psutil

from .net import get_json

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"


def _find_credentials():
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] != "LeagueClientUx.exe":
            continue
        port = token = None
        try:
            for arg in proc.cmdline():
                if arg.startswith("--app-port="):
                    port = arg.split("=", 1)[1]
                elif arg.startswith("--remoting-auth-token="):
                    token = arg.split("=", 1)[1]
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        if port and token:
            return port, token
        # Fallback: lockfile next to the client  ->  name:pid:port:password:protocol
        try:
            for folder in (Path(proc.exe()).parent, Path(proc.exe()).parent.parent):
                lock = folder / "lockfile"
                if lock.exists():
                    parts = lock.read_text().split(":")
                    return parts[2], parts[3]
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, IndexError):
            pass
    return None


class LCU:
    def __init__(self):
        self.creds = None

    def refresh(self):
        """Returns True if the League client is running and reachable."""
        if self.creds:
            try:
                self.get("/riotclient/ux-state")  # cheap ping
                return True
            except Exception:
                self.creds = None
        self.creds = _find_credentials()
        return self.creds is not None

    def get(self, path, timeout=3.0):
        if not self.creds:
            raise ConnectionError("League client not found")
        port, token = self.creds
        return get_json(f"https://127.0.0.1:{port}{path}", auth=("riot", token), timeout=timeout, local=True)

    def phase(self):
        try:
            return self.get("/lol-gameflow/v1/gameflow-phase")
        except Exception:
            return None


def fetch_live_game():
    """Returns allgamedata while a game is running, else None."""
    try:
        data = get_json(LIVE_URL, timeout=1.5, local=True)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("activePlayer") or not data.get("allPlayers"):
        return None
    return data
