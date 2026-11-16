"""Item database parsed from Data Dragon. Stats are read from the item text of the current patch."""
import re
from collections import Counter
from dataclasses import dataclass, field

from . import settings

# Item stat text -> internal dimension
STAT_NAMES = {
    "attack damage": "AD", "ability power": "AP", "attack speed": "AS",
    "critical strike chance": "CRIT", "critical strike damage": "CRIT",
    "lethality": "LETH", "armor penetration": "ARPEN", "magic penetration": "MPEN",
    "health": "HP", "armor": "ARMOR", "magic resist": "MR", "ability haste": "AH",
    "mana": "MANA", "life steal": "LS", "omnivamp": "OMNI", "move speed": "MS",
    "heal and shield power": "HSP", "tenacity": "TEN",
    "base health regen": "HREGEN", "base mana regen": "MREGEN",
}
# Approximate gold value of one point of each stat (standard gold-efficiency baselines).
GOLD_PER_POINT = {
    "AD": 35, "AP": 20, "AS": 25, "CRIT": 40, "LETH": 30, "ARPEN": 42, "MPEN": 31, "MPEN%": 46,
    "HP": 2.67, "ARMOR": 20, "MR": 18, "AH": 26.7, "MANA": 1.4, "LS": 37.5, "OMNI": 40,
    "MS": 12, "MS%": 39.5, "HSP": 50, "TEN": 15, "HREGEN": 3, "MREGEN": 4,
}
FALLBACK_STATS = {
    "FlatPhysicalDamageMod": ("AD", 1), "FlatMagicDamageMod": ("AP", 1), "FlatHPPoolMod": ("HP", 1),
    "FlatArmorMod": ("ARMOR", 1), "FlatSpellBlockMod": ("MR", 1), "PercentAttackSpeedMod": ("AS", 100),
    "FlatCritChanceMod": ("CRIT", 100), "FlatMovementSpeedMod": ("MS", 1), "FlatMPPoolMod": ("MANA", 1),
    "PercentLifeStealMod": ("LS", 100),
}
OFFENSE = {"AD", "AP", "AS", "CRIT", "LETH", "ARPEN", "MPEN"}

_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.S | re.I)
_STAT_LINE = re.compile(r"<attention>\s*([\d.]+)\s*(%?)\s*</attention>\s*([A-Za-z' ]+)")
_PASSIVE = re.compile(r"<passive>([^<]+)</passive>")


@dataclass
class Item:
    id: int
    names: dict  # {"en": ..., "de": ...}
    gold_total: int
    gold_base: int
    tags: frozenset
    frm: list
    into: list
    vec: dict = field(default_factory=dict)  # dimension -> gold value
    passives: frozenset = frozenset()
    anti_heal: bool = False
    is_boots: bool = False
    is_legendary: bool = False

    @property
    def name(self):
        return self.names[settings.lang()]


def _parse_vec(raw):
    vec = Counter()
    block = _STATS_BLOCK.search(raw.get("description", ""))
    if block:
        for amount, pct, name in _STAT_LINE.findall(block.group(1)):
            dim = STAT_NAMES.get(name.strip().lower())
            if not dim:
                continue
            key = dim + "%" if pct and dim in ("MS", "MPEN") else dim
            vec[dim] += float(amount) * GOLD_PER_POINT.get(key, GOLD_PER_POINT[dim])
    if not vec:
        for key, value in (raw.get("stats") or {}).items():
            if key in FALLBACK_STATS and value:
                dim, mult = FALLBACK_STATS[key]
                vec[dim] += value * mult * GOLD_PER_POINT[dim]
    return dict(vec)


class ItemDB:
    def __init__(self, dd):
        self.items = {}
        for sid, raw in dd.items_en.items():
            iid = int(sid)
            gold = raw.get("gold", {})
            if iid >= 10000 or not raw.get("maps", {}).get("11"):
                continue
            if not gold.get("purchasable") or raw.get("inStore") is False:
                continue
            if raw.get("requiredChampion") or raw.get("requiredAlly") or raw.get("specialRecipe"):
                continue
            tags = frozenset(raw.get("tags", []))
            desc = raw.get("description", "")
            self.items[iid] = Item(
                id=iid,
                names={"en": raw["name"], "de": dd.items_de.get(sid, raw)["name"]},
                gold_total=gold.get("total", 0),
                gold_base=gold.get("base", 0),
                tags=tags,
                frm=[int(x) for x in raw.get("from", [])],
                into=[int(x) for x in raw.get("into", [])],
                vec=_parse_vec(raw),
                passives=frozenset(p.strip().lower() for p in _PASSIVE.findall(desc)),
                anti_heal=bool(re.search(r"grievous wounds|<keyword>[^<]*wounds</keyword>", desc, re.I)),
            )
        for it in self.items.values():
            if it.tags & {"Consumable", "Trinket", "GoldPer", "Jungle"}:
                continue  # kept for price lookups, never recommended
            sr_into = [i for i in it.into if i in self.items]
            it.is_boots = "Boots" in it.tags and it.gold_total > 300
            it.is_legendary = not it.is_boots and not sr_into and it.gold_total >= 2000 and bool(it.frm)

    def get(self, iid):
        return self.items.get(iid)

    def tree(self, iid):
        """All component ids (recursive) of an item."""
        out, stack = set(), list(self.items[iid].frm) if iid in self.items else []
        while stack:
            c = stack.pop()
            out.add(c)
            if c in self.items:
                stack.extend(self.items[c].frm)
        return out

    def after_buy(self, iid, owned_ids):
        """Inventory after buying `iid` (owned components get used up). Returns (new_list, slots_freed)."""
        owned = Counter(owned_ids)
        freed = 0

        def consume(cid):
            nonlocal freed
            if owned[cid] > 0:
                owned[cid] -= 1
                freed += 1
                return
            comp = self.items.get(cid)
            for sub in (comp.frm if comp else []):
                consume(sub)

        for c in (self.items[iid].frm if iid in self.items else []):
            consume(c)
        return list(owned.elements()) + [iid], freed

    def remaining_cost(self, iid, owned):
        """Gold still needed for `iid`, consuming owned components from the Counter `owned`."""
        if owned[iid] > 0:
            owned[iid] -= 1
            return 0
        it = self.items.get(iid)
        if not it:
            return 0
        return it.gold_base + sum(self.remaining_cost(c, owned) for c in it.frm)

    def next_component(self, iid, owned_ids, gold):
        """Best affordable step toward `iid`: (item, cost) or (None, missing_gold)."""
        pool = Counter(owned_ids)

        def build(cid, root=False):  # assign owned items to tree nodes once, then price every node
            if not root and pool[cid] > 0:
                pool[cid] -= 1
                return {"id": cid, "cost": 0, "kids": []}
            comp = self.items.get(cid)
            kids = [build(c) for c in (comp.frm if comp else [])]
            return {"id": cid, "cost": (comp.gold_base if comp else 0) + sum(k["cost"] for k in kids), "kids": kids}

        tree = build(iid, root=True)
        if tree["cost"] <= gold:
            return self.items[iid], tree["cost"]
        best, stack = None, list(tree["kids"])
        while stack:
            node = stack.pop()
            if 0 < node["cost"] <= gold and (best is None or node["cost"] > best[1]):
                best = (self.items[node["id"]], node["cost"])
            stack.extend(node["kids"])
        return best if best else (None, tree["cost"] - gold)
