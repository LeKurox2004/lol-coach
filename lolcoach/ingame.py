"""Live game analysis: enemy threat model + a 6-slot build plan based on Riot's champion recommendations."""
from collections import Counter

from .items import OFFENSE

DIM_DE = {
    "AD": "Angriffsschaden", "AP": "Fähigkeitsstärke", "AS": "Angriffstempo", "CRIT": "Krit",
    "LETH": "Tödlichkeit", "ARPEN": "Rüstungsdurchdringung", "MPEN": "Magiedurchdringung",
    "HP": "Leben", "ARMOR": "Rüstung", "MR": "Magieresistenz", "AH": "Fähigkeitstempo",
    "MANA": "Mana", "LS": "Lebensraub", "OMNI": "Omnivampir", "MS": "Lauftempo",
    "HSP": "Heil-/Schildstärke", "TEN": "Zähigkeit", "HREGEN": "Lebensreg.", "MREGEN": "Manareg.",
}
POSITION = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "middle", "BOTTOM": "bottom", "UTILITY": "utility"}
POS_ORDER = {"TOP": 0, "JUNGLE": 1, "MIDDLE": 2, "BOTTOM": 3, "UTILITY": 4}
STABILITY = 0.08  # a new option must beat the current plan by this much before the plan changes


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _find_me(data):
    ap = data["activePlayer"]
    keys = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
    for p in data["allPlayers"]:
        if keys & {p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")}:
            return p
    return data["allPlayers"][0]


def _vec_sum(ids, idb):
    vec = Counter()
    for iid in ids:
        it = idb.get(iid)
        if it:
            vec.update(it.vec)
    return vec


def _strength(p, idb):
    s = p.get("scores", {})
    gold = sum((idb.get(i["itemID"]).gold_total if idb.get(i["itemID"]) else 0) * i.get("count", 1)
               for i in p.get("items", []))
    raw = 1 + 0.35 * s.get("kills", 0) + 0.15 * s.get("assists", 0) - 0.25 * s.get("deaths", 0)
    return max(0.4, raw + 0.08 * p.get("level", 1) + gold / 3000)


def threat_model(data, me, dd, idb):
    allies = [p for p in data["allPlayers"] if p.get("team") == me.get("team")]
    enemies = [p for p in data["allPlayers"] if p.get("team") != me.get("team")]
    rows, ad_t, ap_t, heal, cc, total, armor, mr, sustain = [], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    for p in enemies:
        t = dd.champ_from_live(p)
        st = _strength(p, idb)
        ivec = _vec_sum([i["itemID"] for i in p.get("items", [])], idb)
        ad_share = t.ad_share if t else 0.5
        item_ad = sum(ivec[d] for d in ("AD", "LETH", "CRIT", "AS", "ARPEN"))
        item_ap = ivec["AP"] + ivec["MPEN"]
        if item_ad + item_ap > 1500:
            ad_share = 0.5 * ad_share + 0.5 * item_ad / (item_ad + item_ap)
        dmg = 0.55 if t and t.primary == "Tank" else 1.0
        ad_t += st * dmg * ad_share
        ap_t += st * dmg * (1 - ad_share)
        total += st
        heal += (t.heals if t else 0) * st
        cc += (t.cc if t else 0) * st
        tank = 400 if t and "Tank" in t.tags else 0
        armor += ivec["ARMOR"] + tank
        mr += ivec["MR"] + tank
        sustain += ivec["LS"] + ivec["OMNI"]
        s = p.get("scores", {})
        rows.append({"name": t.name if t else p.get("championName", "?"),
                     "kda": f"{s.get('kills', 0)}/{s.get('deaths', 0)}/{s.get('assists', 0)}",
                     "level": p.get("level", 1),
                     "dmg": "AD" if ad_share >= 0.65 else "AP" if ad_share <= 0.35 else "Mix",
                     "strength": st, "heals": t.heals if t else 0,
                     "pos": POS_ORDER.get((p.get("position") or "").upper(), 9), "idx": len(rows)})
    n = max(1, len(enemies))
    ally_avg = sum(_strength(p, idb) for p in allies) / max(1, len(allies))
    avg = sum(r["strength"] for r in rows) / max(1, len(rows))
    for r in rows:  # relative to the enemy average: average ≈ yellow, clearly fed ≈ red
        r["threat"] = round(_clamp(r["strength"] / (avg * 1.5), 0.1, 1.0), 2)
    rows.sort(key=lambda r: (r["pos"], r["idx"]))  # same order as the in-game Tab scoreboard
    return {
        "rows": rows,
        "ad_pct": ad_t / max(0.01, ad_t + ap_t),
        "heal": _clamp(heal / max(0.01, total) * 1.5 + sustain / 6000, 0, 1),
        "cc": _clamp(cc / max(0.01, total), 0, 1),
        "pressure": _clamp(total / n / ally_avg, 0.6, 1.8),
        "armor_lvl": _clamp(armor / n / 1200, 0, 1),
        "mr_lvl": _clamp(mr / n / 1200, 0, 1),
        "healers": [r["name"] for r in rows if r["heals"] >= 0.6][:3],
    }


class GameAnalyzer:
    def __init__(self, dd, idb, recs):
        self.dd, self.idb, self.recs = dd, idb, recs
        self._prev = {}  # (stage, pick#) -> item id, keeps the plan stable between updates
        self._key = None
        self._last_time = 0

    # ---- weights ------------------------------------------------------------------
    def _weights(self, pool, my_t, owned_ids, ctx):
        w = Counter()
        for it in pool:  # what this champion actually builds, according to Riot's recommendations
            tot = sum(it.vec.values())
            for d, v in it.vec.items():
                w[d] += v / tot
        if not w:
            w = Counter({"AD": 1, "AP": 1, "HP": .5}) if not my_t else Counter(
                {"AD": my_t.ad_share, "AP": 1 - my_t.ad_share, "HP": .4, "AH": .4})
        top = max(w.values())
        w = Counter({d: v / top for d, v in w.items()})
        owned = _vec_sum(owned_ids, self.idb)
        off = sum(owned[d] for d in OFFENSE)
        if off:
            for d in OFFENSE:
                w[d] += 0.25 * owned[d] / off
        squishy = 1 - (my_t.defense / 10 if my_t else 0.5)
        base = (0.15 + 0.35 * squishy) * ctx["pressure"]
        w["ARMOR"] += base * ctx["ad_pct"] * 1.4
        w["MR"] += base * (1 - ctx["ad_pct"]) * 1.4
        w["TEN"] += 0.5 * ctx["cc"]
        if w["AD"] >= 0.5:
            w["ARPEN"] += 0.4 * ctx["armor_lvl"]
        if w["AP"] >= 0.5:
            w["MPEN"] += 0.4 * ctx["mr_lvl"]
        top = max(w.values())
        return {d: v / top for d, v in w.items()}

    def _scorer(self, w, ctx, has_anti_heal):
        def score(it):
            tot = sum(it.vec.values())
            if not tot:
                return 0.3, []
            contrib = {d: w.get(d, 0) * v for d, v in it.vec.items()}
            fit = sum(contrib.values()) / tot
            s = 0.7 * fit + 0.3 * min(1.3, sum(contrib.values()) / max(1, it.gold_total)) / 1.3
            reasons = []
            for d, _ in sorted(contrib.items(), key=lambda kv: -kv[1])[:2]:
                if w.get(d, 0) < 0.15:
                    continue
                label = DIM_DE.get(d, d)
                if d == "ARMOR" and ctx["ad_pct"] >= 0.55:
                    label += f" (Gegner {ctx['ad_pct']:.0%} AD)"
                elif d == "MR" and ctx["ad_pct"] <= 0.45:
                    label += f" (Gegner {1 - ctx['ad_pct']:.0%} AP)"
                elif d in ("ARPEN", "LETH") and ctx["armor_lvl"] > 0.4:
                    label += " (Gegner stacken Rüstung)"
                elif d == "MPEN" and ctx["mr_lvl"] > 0.4:
                    label += " (Gegner stacken MR)"
                elif d == "TEN" and ctx["cc"] > 0.5:
                    label += " (viel CC beim Gegner)"
                reasons.append(label)
            if it.anti_heal and not has_anti_heal and ctx["heal"] > 0.3 and fit > 0.35:
                s += 0.4 * ctx["heal"] * fit
                reasons.insert(0, "Anti-Heilung" + (f" gegen {', '.join(ctx['healers'])}" if ctx["healers"] else ""))
            return s, reasons
        return score

    # ---- plan -----------------------------------------------------------------------
    def _plan(self, ranges, owned_full, score):
        idb = self.idb
        picks_left = max(0, 6 - len(owned_full))
        consumed, chosen, plan = set(), [], []
        used_passives = set().union(*(idb.get(i).passives for i in owned_full)) if owned_full else set()
        boots_owned = any(idb.get(i).is_boots for i in owned_full)
        boots_planned = boots_owned

        for idx, opts in enumerate(ranges):
            last = idx == len(ranges) - 1
            boots_stage = all(idb.get(i).is_boots for i in opts)
            hit = next((o for o in owned_full if o not in consumed and
                        (o in opts or (boots_stage and idb.get(o).is_boots))), None)
            if hit is not None:
                consumed.add(hit)
                plan.append(self._entry(hit, owned=True))
                if not last:
                    continue
            if boots_stage and boots_planned:
                continue
            want = (picks_left - len(chosen)) if last else 1
            for k in range(want):
                if len(chosen) >= picks_left:
                    break
                cands = [idb.get(i) for i in opts if i not in owned_full and i not in chosen
                         and not (idb.get(i).passives & used_passives)
                         and not (idb.get(i).is_boots and boots_planned)]
                if not cands:
                    break
                prev = self._prev.get((idx, k))

                def rank(it, opts=opts, prev=prev):
                    return score(it)[0] + 0.03 * (1 - opts.index(it.id) / len(opts)) + (STABILITY if it.id == prev else 0)

                best = max(cands, key=rank)
                self._prev[(idx, k)] = best.id
                chosen.append(best.id)
                used_passives |= best.passives
                boots_planned = boots_planned or best.is_boots
                plan.append(self._entry(best.id, owned=False, reasons=score(best)[1]))

        # Riot's list was shorter than our free slots -> fill with the best fitting legendaries.
        if len(chosen) < picks_left:
            pool = sorted((it for it in idb.items.values() if it.is_legendary and it.id not in owned_full
                           and it.id not in chosen and not (it.passives & used_passives)),
                          key=lambda it: -score(it)[0])
            for it in pool[:picks_left - len(chosen)]:
                chosen.append(it.id)
                used_passives |= it.passives
                plan.append(self._entry(it.id, owned=False, reasons=score(it)[1]))
        # owned items that aren't in Riot's list still take a slot – show them first
        extra_owned = [self._entry(i, owned=True) for i in owned_full if i not in consumed]
        return extra_owned + plan, used_passives

    def _situational_swap(self, plan, pool_ids, w, score, used_passives, ctx):
        """Replace the weakest late pick with an off-list item if the game really calls for it."""
        open_late = [(i, e) for i, e in enumerate(plan) if not e["owned"] and i >= 2 and not self.idb.get(e["id"]).is_boots]
        if not open_late:
            return plan
        weakest_i, weakest = min(open_late, key=lambda ie: score(self.idb.get(ie[1]["id"]))[0])
        weakest_s = score(self.idb.get(weakest["id"]))[0]
        planned = {e["id"] for e in plan}
        best, best_s = None, weakest_s + 0.12
        for it in self.idb.items.values():
            if not it.is_legendary or it.id in pool_ids or it.id in planned or (it.passives & used_passives):
                continue
            if not (it.anti_heal or it.vec.get("ARMOR") or it.vec.get("MR")):
                continue
            off = {d: v for d, v in it.vec.items() if d in OFFENSE}
            if off and sum(w.get(d, 0) * v for d, v in off.items()) / sum(off.values()) < 0.5:
                continue  # offensive stats this champion doesn't use
            s, _ = score(it)
            if s > best_s:
                best, best_s = it, s
        if best:
            plan[weakest_i] = self._entry(best.id, owned=False, reasons=["situativ"] + score(best)[1])
        return plan

    def _entry(self, iid, owned, reasons=None):
        it = self.idb.get(iid)
        return {"id": iid, "name": it.name, "gold": it.gold_total, "owned": owned,
                "boots": it.is_boots, "reasons": reasons or []}

    # ---- shopping -------------------------------------------------------------------
    def _shopping(self, plan, inv_ids, gold, free_slots):
        todo = [e for e in plan if not e["owned"]]
        if not todo:
            return ["Build komplett ✔"]
        lines, owned, t = [], list(inv_ids), 0
        while t < len(todo) and len(lines) < 3:
            target = todo[t]
            comp, cost = self.idb.next_component(target["id"], owned, gold)
            if comp is None:
                if not lines:
                    lines.append(f"Spare auf {target['name']} – dir fehlen {cost} Gold")
                break
            new_owned, freed = self.idb.after_buy(comp.id, owned)
            if free_slots - 1 + freed < 0:
                lines.append("Inventar voll – verkaufe ein Startitem")
                break
            free_slots += freed - 1
            lines.append(f"{comp.name} – {cost} G" + ("" if comp.id == target["id"] else f"  (für {target['name']})"))
            gold -= cost
            owned = new_owned
            if comp.id == target["id"]:
                t += 1
        has_any_boots = any(self.idb.get(i) and "Boots" in self.idb.get(i).tags for i in owned)
        boots_soon = any(e["boots"] for e in todo[:2])
        if not has_any_boots and boots_soon and gold >= 300 and free_slots > 0 and 1001 in self.idb.items:
            lines.append(f"{self.idb.get(1001).name} – 300 G  (früh fürs Lauftempo)")
        return lines

    @staticmethod
    def _boots_hint(plan):
        todo = [e for e in plan if not e["owned"]]
        if any(e["owned"] and e["boots"] for e in plan):
            return None
        for n, e in enumerate(todo):
            if e["boots"]:
                if n == 0:
                    return f"Stiefel jetzt: {e['name']} ist dein nächstes Item"
                return f"Stiefel nach deinem {n}. Item fertig machen ({e['name']})"
        return None

    # ---- main -----------------------------------------------------------------------
    def analyze(self, data, role_hint=""):
        idb = self.idb
        me = _find_me(data)
        my_t = self.dd.champ_from_live(me)
        game_time = int(data.get("gameData", {}).get("gameTime", 0))
        inv = [i for i in me.get("items", []) if i.get("slot", 0) < 6]
        inv_ids = [i["itemID"] for i in inv]
        owned_full = [i for i in inv_ids if idb.get(i) and (idb.get(i).is_legendary or idb.get(i).is_boots)]
        role = role_hint or POSITION.get((me.get("position") or "").upper(), "")
        gold = int(data["activePlayer"].get("currentGold", 0))

        rec = self.recs.get(my_t, role) if my_t else ([], "")
        loading = rec is None
        ranges, source = rec if rec else ([], "")
        if not ranges:  # no data (yet): generic order – one item, boots, then items
            legs = [it.id for it in idb.items.values() if it.is_legendary]
            ranges = [legs, [it.id for it in idb.items.values() if it.is_boots], legs]
            source = "lade Riot-Empfehlung…" if loading else "allgemein (keine Champion-Daten)"
            pool = []
        else:
            pool = [idb.get(i) for r in ranges for i in r if not idb.get(i).is_boots]
        key = (my_t.id if my_t else "", tuple(map(tuple, ranges)))
        if key != self._key or game_time < self._last_time - 5:
            self._prev, self._key = {}, key
        self._last_time = game_time

        ctx = threat_model(data, me, self.dd, idb)
        w = self._weights(pool, my_t, owned_full, ctx)
        has_anti_heal = any(idb.get(i).anti_heal for i in inv_ids if idb.get(i))
        score = self._scorer(w, ctx, has_anti_heal)
        plan, used_passives = self._plan(ranges, owned_full, score)
        if pool:
            plan = self._situational_swap(plan, {i for r in ranges for i in r}, w, score, used_passives, ctx)

        # components you already hold, shown next to the item they belong to
        spare = Counter(i for i in inv_ids if idb.get(i) and not (idb.get(i).is_legendary or idb.get(i).is_boots))
        for e in plan:
            e["parts"] = []
            if e["owned"]:
                continue
            for cid in idb.tree(e["id"]):
                if spare[cid] > 0:
                    spare[cid] -= 1
                    e["parts"].append(idb.get(cid).name)
            e["tags"] = [t for t in ("situativ", "Anti-Heal")
                         if any(r.startswith(t if t == "situativ" else "Anti-Heilung") for r in e["reasons"])]

        return {
            "kind": "ingame",
            "gold": gold,
            "game_time": game_time,
            "source": source,
            "shopping": self._shopping(plan, inv_ids, gold, 6 - len(inv)),
            "boots_hint": self._boots_hint(plan),
            "plan": plan,
            "enemies": [{k: r[k] for k in ("name", "kda", "dmg", "threat")} for r in ctx["rows"]],
        }
