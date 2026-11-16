"""Riot's own per-champion item recommendations (from the game files via CommunityDragon).

Each champion has ordered "ranges" for Summoner's Rift, e.g. Garen:
  [Stridebreaker | Trinity]  ->  [Boots]  ->  [Shojin | Rageblade]  ->  ...  ->  [situational list]
The order is the intended buy order, so it also tells us *when* boots come.
Champions without own data borrow from similar champions.
"""
import json
import math
import statistics
import threading
from collections import Counter, defaultdict

from .ddragon import CACHE_DIR
from .net import get_json

URL = "https://raw.communitydragon.org/latest/game/data/characters/{c}/{c}.bin.json"


def _parse_overrides(data):
    found = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("__type") == "ItemRecommendationOverride":
                found.append(o)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    result = []
    for o in found:
        ctx = next((c for c in o.get("mOverrideContexts", []) if c.get("mMapID") == 11), None)
        if not ctx:
            continue
        ranges = []
        for r in o.get("mRecItemRanges", []):
            ids = [int(x.split("/")[-1]) for x in r.get("items", []) if x.split("/")[-1].isdigit()]
            if ids:
                ranges.append(ids)
        result.append({"position": (ctx.get("mPosition") or "").lower(), "ranges": ranges})
    return result


class Recommendations:
    def __init__(self, dd, idb):
        self.dd, self.idb = dd, idb
        self._raw = {}  # champ id -> parsed overrides (list) or [] if none
        self._results = {}  # (champ id, role) -> (ranges, source)
        self._loading = set()
        self._lock = threading.Lock()

    # ---- fetching ---------------------------------------------------------------
    def _path(self, cid):
        return CACHE_DIR / f"{self.dd.version}_rec_{cid}.json"

    def _load(self, cid):
        """Blocking load of one champion's overrides (cached per patch)."""
        if cid in self._raw:
            return self._raw[cid]
        path = self._path(cid)
        if path.exists():
            parsed = json.loads(path.read_text(encoding="utf-8"))
        else:
            c = cid.lower()
            try:
                parsed = _parse_overrides(get_json(URL.format(c=c), timeout=20))
            except Exception as exc:
                if "404" not in str(exc):
                    return None  # network problem – try again later
                parsed = []
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(parsed), encoding="utf-8")
        self._raw[cid] = parsed
        return parsed

    def _similar(self, champ, k=12):
        """Same class and damage side, then closest by stats, tags, attack range and ability-text keywords."""
        side = champ.ad_share >= 0.5
        cands = [t for t in self.dd.by_id.values()
                 if t.id != champ.id and t.primary == champ.primary and (t.ad_share >= 0.5) == side]

        def kit_cos(a, b):
            dot = sum(a[x] * b[x] for x in a)
            na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
            return dot / (na * nb) if na and nb else 0

        cands.sort(key=lambda t: abs(t.attack - champ.attack) + abs(t.magic - champ.magic)
                   + abs(t.defense - champ.defense) + 3 * len(t.tags ^ champ.tags)
                   + abs(t.attackrange - champ.attackrange) / 50 - 6 * kit_cos(champ.kit, t.kit))
        return cands[:k]

    def _build(self, champ, role):
        own = self._load(champ.id)
        if own is None:
            return None
        ranges = self._pick_override(own, role)
        if ranges:
            return ranges, "Riot-Empfehlung"
        donors = []
        for t in self._similar(champ):
            data = self._load(t.id)
            r = self._pick_override(data or [], role)
            if r:
                donors.append((t, r))
            if len(donors) >= 6:
                break
        if not donors:
            return [], ""
        return self._merge(donors), "wie ähnliche Champions (" + ", ".join(t.name for t, _ in donors[:3]) + ")"

    def _pick_override(self, overrides, role):
        if not overrides:
            return []
        chosen = next((o for o in overrides if role and o["position"] == role), None)
        chosen = chosen or next((o for o in overrides if not o["position"]), overrides[0])
        ranges = []
        for r in chosen["ranges"]:
            ids = [i for i in r if self.idb.get(i) and (self.idb.get(i).is_legendary or self.idb.get(i).is_boots)]
            if ids:
                ranges.append(ids)
        return ranges

    def _merge(self, donors):
        stages, boots, boot_pos = defaultdict(Counter), Counter(), []
        for _, ranges in donors:
            idx = 0
            for r in ranges:
                if all(self.idb.get(i).is_boots for i in r):
                    boots.update(r)
                    boot_pos.append(idx)
                    continue
                stages[idx].update(i for i in r if not self.idb.get(i).is_boots)
                idx += 1
        merged = []
        for idx in sorted(stages):
            items = [i for i, c in stages[idx].most_common(6) if c >= 2] or [i for i, _ in stages[idx].most_common(3)]
            merged.append(items)
        if boots:
            pos = int(statistics.median(boot_pos)) if boot_pos else 1
            merged.insert(min(pos, len(merged)), [i for i, _ in boots.most_common(3)])
        return merged

    # ---- public -----------------------------------------------------------------
    def get(self, champ, role=""):
        """Non-blocking. Returns (ranges, source) or None while still loading in the background."""
        key = (champ.id, role)
        with self._lock:
            if key in self._results:
                return self._results[key]
            if key in self._loading:
                return None
            self._loading.add(key)
        threading.Thread(target=self._bg, args=(champ, role, key), daemon=True).start()
        return None

    def _bg(self, champ, role, key):
        try:
            res = self._build(champ, role)
            if res is not None:
                with self._lock:
                    self._results[key] = res
        finally:
            with self._lock:
                self._loading.discard(key)
