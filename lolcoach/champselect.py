"""Champion select analysis: rates hovered champion and suggests picks."""
import math
import time
from collections import defaultdict

ROLE_DE = {"top": "Top", "jungle": "Jungle", "middle": "Mid", "bottom": "ADC", "utility": "Support", "": "keine feste Rolle"}
ROLE_TAGS = {
    "top": {"Fighter", "Tank"}, "jungle": {"Fighter", "Assassin", "Tank"}, "middle": {"Mage", "Assassin"},
    "bottom": {"Marksman"}, "utility": {"Support", "Tank", "Mage"},
}
PROFILE_TTL = 600


def _lane_of(participant):
    tl = participant.get("timeline", {})
    lane, role = (tl.get("lane") or "").upper(), (tl.get("role") or "").upper()
    if lane == "TOP":
        return "top"
    if lane == "JUNGLE":
        return "jungle"
    if lane in ("MIDDLE", "MID"):
        return "middle"
    if lane in ("BOTTOM", "BOT"):
        return "utility" if "SUPPORT" in role else "bottom"
    return ""


class ChampSelectAnalyzer:
    def __init__(self, dd, lcu):
        self.dd, self.lcu = dd, lcu
        self.mastery, self.history = {}, defaultdict(lambda: [0, 0])
        self._loaded_at = 0

    # ---- personal data from the client (no API key needed) -------------------
    def _load_profile(self):
        if time.time() - self._loaded_at < PROFILE_TTL:
            return
        self._loaded_at = time.time()
        try:
            self.mastery = {m["championId"]: m.get("championPoints", 0)
                            for m in self.lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery")}
        except Exception:
            self.mastery = {}
        self.history = defaultdict(lambda: [0, 0])
        try:
            me = self.lcu.get("/lol-summoner/v1/current-summoner")
            data = self.lcu.get("/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=99",
                                timeout=8)
        except Exception:
            return
        for game in data.get("games", {}).get("games", []):
            if game.get("mapId") != 11:
                continue
            idents = game.get("participantIdentities", [])
            pid = None
            for ident in idents:
                player = ident.get("player", {})
                if player.get("puuid") == me.get("puuid") or player.get("summonerId") == me.get("summonerId"):
                    pid = ident.get("participantId")
            for p in game.get("participants", []):
                if pid is not None and p.get("participantId") != pid:
                    continue
                if pid is None and len(game.get("participants", [])) != 1:
                    continue
                win = 1 if p.get("stats", {}).get("win") else 0
                for key in ((_lane_of(p), p["championId"]), ("*", p["championId"])):
                    self.history[key][0] += 1
                    self.history[key][1] += win

    # ---- scoring --------------------------------------------------------------
    def _score(self, cid, role, allies, enemies):
        t = self.dd.champ(cid)
        if not t:
            return 0, []
        s, reasons = 50.0, []
        pts = self.mastery.get(cid, 0)
        if pts:
            s += min(12, 2.0 * math.log10(pts + 1))
            if pts >= 50000:
                reasons.append(("+", f"Hohe Meisterschaft ({pts // 1000}k Punkte)"))
        else:
            s -= 4
            reasons.append(("-", "Kaum/nie gespielt"))
        games, wins = self.history.get((role, cid), (0, 0)) if role else self.history.get(("*", cid), (0, 0))
        if games:
            wr = wins / games
            s += (wr - 0.5) * 30 * min(1, games / 8) + min(5, games * 0.5)
            where = f" als {ROLE_DE[role]}" if role else ""
            reasons.append(("+" if wr >= 0.5 else "-", f"Deine Bilanz{where}: {wins}/{games} Siege ({wr:.0%})"))
        if role and not (t.tags & ROLE_TAGS.get(role, set())) and not games:
            s -= 8
            reasons.append(("-", f"Untypisch auf {ROLE_DE[role]}"))

        ally_t = [a for a in (self.dd.champ(c) for c in allies) if a]
        if ally_t:
            ap_frac = sum(1 - a.ad_share for a in ally_t) / len(ally_t)
            if ap_frac < 0.3 and len(ally_t) >= 2:
                if t.ad_share <= 0.4:
                    s += 10
                    reasons.append(("+", "Team braucht Magieschaden"))
                elif t.ad_share >= 0.6:
                    s -= 6
                    reasons.append(("-", "Team ist schon fast nur AD"))
            elif ap_frac > 0.7 and len(ally_t) >= 2:
                if t.ad_share >= 0.6:
                    s += 10
                    reasons.append(("+", "Team braucht physischen Schaden"))
                elif t.ad_share <= 0.4:
                    s -= 6
                    reasons.append(("-", "Team ist schon fast nur AP"))
            has_front = any("Tank" in a.tags or a.defense >= 7 for a in ally_t)
            if not has_front and len(ally_t) >= 2 and ("Tank" in t.tags or t.defense >= 7):
                s += 8
                reasons.append(("+", "Team hat noch keine Frontline"))
            if sum(a.cc for a in ally_t) / len(ally_t) < 0.35 and t.cc >= 0.6:
                s += 5
                reasons.append(("+", "Bringt CC ins Team"))

        enemy_t = [e for e in (self.dd.champ(c) for c in enemies) if e]
        if enemy_t:
            divers = sum(1 for e in enemy_t if e.tags & {"Assassin", "Fighter"})
            tanks = sum(1 for e in enemy_t if "Tank" in e.tags)
            if divers >= 3 and ("Tank" in t.tags or t.defense >= 6):
                s += 5
                reasons.append(("+", "Hält gut gegen viele Diver/Assassinen"))
            elif divers >= 3 and t.defense <= 3:
                s -= 5
                reasons.append(("-", "Sehr squishy gegen viele Diver/Assassinen"))
            if tanks >= 2 and ("Marksman" in t.tags or t.magic >= 8):
                s += 4
                reasons.append(("+", "Gut gegen mehrere Tanks"))
            enemy_heal = sum(e.heals for e in enemy_t) / len(enemy_t)
            if enemy_heal >= 0.6 and t.heals >= 0.6:
                s += 2
                reasons.append(("+", "Kann Sustain-Duelle mithalten"))
        return max(0, min(100, round(s))), reasons

    def analyze(self, session, pickable):
        self._load_profile()
        local = session.get("localPlayerCellId")
        my_team = session.get("myTeam", [])
        me = next((p for p in my_team if p.get("cellId") == local), {})
        role = (me.get("assignedPosition") or "").lower()
        if role not in ROLE_DE:
            role = ""

        hover, locked = me.get("championId") or me.get("championPickIntent") or 0, bool(me.get("championId"))
        bans = set(session.get("bans", {}).get("myTeamBans", []) + session.get("bans", {}).get("theirTeamBans", []))
        for group in session.get("actions", []):
            for a in group:
                if a.get("type") == "ban" and a.get("completed"):
                    bans.add(a.get("championId"))
                if a.get("actorCellId") == local and a.get("type") == "pick" and a.get("championId"):
                    hover = a["championId"]
                    locked = bool(a.get("completed"))
        allies = [p.get("championId") or p.get("championPickIntent") for p in my_team if p.get("cellId") != local]
        allies = [c for c in allies if c]
        enemies = [p.get("championId") for p in session.get("theirTeam", []) if p.get("championId")]
        taken = set(allies) | set(enemies) | bans

        pool = set()
        for (r, cid), (g, _) in self.history.items():
            if g and (r == role if role else r == "*"):
                pool.add(cid)
        for cid, _ in sorted(self.mastery.items(), key=lambda kv: -kv[1])[:25]:
            t = self.dd.champ(cid)
            if t and (not role or t.tags & ROLE_TAGS[role]):
                pool.add(cid)
        if len(pool) < 5:  # new account / no data: fall back to every class-fitting champion
            pool |= {t.key for t in self.dd.by_key.values() if not role or t.tags & ROLE_TAGS[role]}
        if pickable:
            pool &= set(pickable)
        pool -= taken

        scored = sorted(((self._score(c, role, allies, enemies), c) for c in pool), key=lambda x: -x[0][0])
        suggestions = [{"name": self.dd.champ(c).name, "score": sc, "reasons": [r for r in rs if r[0] == "+"][:2]}
                       for (sc, rs), c in scored[:6]]
        best = scored[0][0][0] if scored else 50

        hover_view = None
        if hover and self.dd.champ(hover):
            hs, hr = self._score(hover, role, allies, enemies)
            if hs >= best - 6 or hs >= 72:
                verdict, tone = "Gute Wahl", "good"
            elif hs >= best - 16:
                verdict, tone = "Okay", "ok"
            else:
                verdict, tone = "Eher schlecht", "bad"
            hover_view = {"name": self.dd.champ(hover).name, "score": hs, "verdict": verdict, "tone": tone,
                          "reasons": hr, "locked": locked}

        names = lambda ids: [self.dd.champ(c).name for c in ids if self.dd.champ(c)]  # noqa: E731
        return {
            "kind": "champselect",
            "role": ROLE_DE[role],
            "role_key": role,
            "hover_id": hover,
            "hover": hover_view,
            "suggestions": [] if locked else suggestions,
            "allies": names(allies),
            "enemies": names(enemies),
        }
