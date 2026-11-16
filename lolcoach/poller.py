"""Background thread: watches the League client and produces view states for the UI."""
import json
import threading
import time
import traceback

from .champselect import ChampSelectAnalyzer
from .ddragon import CACHE_DIR, DataDragon
from .ingame import GameAnalyzer
from .items import ItemDB
from .recommendations import Recommendations
from .riot_local import LCU, fetch_live_game

PHASE_DE = {
    "None": "Im Client", "Lobby": "In der Lobby", "Matchmaking": "Suche Spiel…", "ReadyCheck": "Spiel gefunden!",
    "ChampSelect": "Champ Select", "GameStart": "Spiel lädt…", "InProgress": "Spiel läuft",
    "WaitingForStats": "Spiel vorbei", "PreEndOfGame": "Spiel vorbei", "EndOfGame": "Spiel vorbei",
}
INTERVAL = 2.0
SNAPSHOT_EVERY = 30  # seconds of game time; last snapshot is kept for debugging bad recommendations


class Poller(threading.Thread):
    def __init__(self, out_queue):
        super().__init__(daemon=True)
        self.q = out_queue
        self.last_role = ""
        self._snap_time = -SNAPSHOT_EVERY

    def emit(self, client, status, view):
        self.q.put({"client": client, "status": status, "view": view})

    def run(self):
        while True:
            try:
                self.emit(False, "Lade Spieldaten (Data Dragon)…", {"kind": "message", "text": "Einen Moment…"})
                dd = DataDragon()
                idb = ItemDB(dd)
                break
            except Exception as exc:
                self.emit(False, "Spieldaten konnten nicht geladen werden", {
                    "kind": "message", "text": f"Kein Internet? Neuer Versuch in 30s.\n\n{exc}"})
                time.sleep(30)
        lcu = LCU()
        recs = Recommendations(dd, idb)
        cs = ChampSelectAnalyzer(dd, lcu)
        game = GameAnalyzer(dd, idb, recs)
        while True:
            try:
                self.tick(dd, lcu, cs, game, recs)
            except Exception:
                self.emit(True, "Fehler", {"kind": "message", "text": traceback.format_exc(limit=3)})
            time.sleep(INTERVAL)

    def _snapshot(self, live, view):
        t = view["game_time"]
        if abs(t - self._snap_time) < SNAPSHOT_EVERY:
            return
        self._snap_time = t
        try:
            (CACHE_DIR / "last_game.json").write_text(json.dumps({"live": live, "view": view}), encoding="utf-8")
        except OSError:
            pass

    def tick(self, dd, lcu, cs, game, recs):
        running = lcu.refresh()
        live = fetch_live_game()
        if live:
            view = game.analyze(live, self.last_role)
            self._snapshot(live, view)
            mins, secs = divmod(view["game_time"], 60)
            self.emit(True, f"Im Spiel · {mins}:{secs:02d}", view)
            return
        if not running:
            self.emit(False, "League of Legends ist nicht offen", {
                "kind": "message", "text": "Warte auf den League-Client…"})
            return
        phase = lcu.phase() or "None"
        if phase == "ChampSelect":
            try:
                session = lcu.get("/lol-champ-select/v1/session")
                pickable = lcu.get("/lol-champ-select/v1/pickable-champion-ids")
            except Exception:
                session, pickable = None, None
            if session:
                view = cs.analyze(session, pickable)
                self.last_role = view["role_key"]
                champ = dd.champ(view["hover_id"]) if view["hover_id"] else None
                if champ:
                    recs.get(champ, self.last_role)  # prefetch build data in the background
                self.emit(True, "Champ Select", view)
                return
        self.emit(True, PHASE_DE.get(phase, phase), {
            "kind": "message", "text": "Sobald Champ Select oder ein Spiel startet, geht's hier los."})
