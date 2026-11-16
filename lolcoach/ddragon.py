"""Loads champion and item data from Riot's public Data Dragon (cached per patch)."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import settings
from .net import get_json

BASE = "https://ddragon.leagueoflegends.com"
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
_TAGS = re.compile(r"<[^>]+>")

_HEAL_RE = re.compile(r"\bheal(?:s|ing|ed)?\b|restores? [^.]{0,30}health|life ?steal|omnivamp|\bdrain")
# Kit keywords used to find champions that play (and therefore build) alike.
KIT_KEYS = {
    "crit": re.compile(r"critical|crits?"), "as": re.compile(r"attack speed"),
    "ls": re.compile(r"life ?steal|heal|omnivamp"), "onhit": re.compile(r"on-hit"),
    "ap": re.compile(r"ability power|magic damage"), "ad": re.compile(r"physical damage|attack damage"),
    "dash": re.compile(r"dash|blink|leap"),
}
_CC_RE = re.compile(
    r"\bstun|\broot|knock(?:s|ing)? (?:up|back|aside)|airborne|\bcharm|\bfear|\btaunt|suppress|\bsleep|polymorph|\bpull"
)


@dataclass
class ChampTraits:
    id: str
    key: int
    names: dict  # {"en": ..., "de": ...}
    tags: frozenset
    attack: int
    magic: int
    defense: int
    ranged: bool
    partype: str
    heals: float  # 0..1 how much sustain/healing its kit has
    cc: float  # 0..1 how much hard CC its kit has
    primary: str = ""  # first (main) class tag
    attackrange: float = 125
    kit: dict = None  # keyword counts from ability texts

    @property
    def name(self):
        return self.names[settings.lang()]

    @property
    def ad_share(self):
        total = self.attack + self.magic
        return self.attack / total if total else 0.5


def _cached(name, url):
    path = CACHE_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = get_json(url, timeout=60)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _latest_version():
    marker = CACHE_DIR / "version.txt"
    try:
        version = get_json(f"{BASE}/api/versions.json", timeout=10)[0]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(version, encoding="utf-8")
        return version
    except Exception:
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip()
        raise


def _plain(text):
    return _TAGS.sub(" ", text or "").lower()


class DataDragon:
    def __init__(self):
        v = self.version = _latest_version()
        champs_en = _cached(f"{v}_championFull_en.json", f"{BASE}/cdn/{v}/data/en_US/championFull.json")["data"]
        champs_de = _cached(f"{v}_champion_de.json", f"{BASE}/cdn/{v}/data/de_DE/champion.json")["data"]
        self.items_en = _cached(f"{v}_item_en.json", f"{BASE}/cdn/{v}/data/en_US/item.json")["data"]
        self.items_de = _cached(f"{v}_item_de.json", f"{BASE}/cdn/{v}/data/de_DE/item.json")["data"]

        self.by_id, self.by_key = {}, {}
        for cid, c in champs_en.items():
            kit = _plain(c.get("passive", {}).get("description"))
            for spell in c.get("spells", []):
                kit += " " + _plain(spell.get("description")) + " " + _plain(spell.get("tooltip"))
            traits = ChampTraits(
                id=cid,
                key=int(c["key"]),
                names={"en": c["name"], "de": champs_de.get(cid, c)["name"]},
                tags=frozenset(c.get("tags", [])),
                attack=c["info"]["attack"],
                magic=c["info"]["magic"],
                defense=c["info"]["defense"],
                ranged=c["stats"].get("attackrange", 125) >= 300,
                partype=c.get("partype", ""),
                heals=min(1.0, len(_HEAL_RE.findall(kit)) / 3),
                cc=min(1.0, len(_CC_RE.findall(kit)) / 3),
                primary=(c.get("tags") or [""])[0],
                attackrange=c["stats"].get("attackrange", 125),
                kit={k: len(rx.findall(kit)) for k, rx in KIT_KEYS.items()},
            )
            self.by_id[cid] = traits
            self.by_key[traits.key] = traits
        self._by_name = {n.lower(): t for t in self.by_id.values() for n in t.names.values()}

    def champ(self, key_or_id):
        if isinstance(key_or_id, int):
            return self.by_key.get(key_or_id)
        return self.by_id.get(key_or_id)

    def champ_from_live(self, player):
        raw = player.get("rawChampionName", "")
        if raw:
            t = self.by_id.get(raw.rsplit("_", 1)[-1])
            if t:
                return t
        return self._by_name.get((player.get("championName") or "").lower())
