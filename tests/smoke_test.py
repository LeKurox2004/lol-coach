"""Smoke test with simulated client data (needs internet once for Data Dragon / CommunityDragon)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lolcoach.ddragon import DataDragon  # noqa: E402
from lolcoach.ingame import GameAnalyzer  # noqa: E402
from lolcoach.items import ItemDB  # noqa: E402
from lolcoach.recommendations import Recommendations  # noqa: E402

dd = DataDragon()
idb = ItemDB(dd)
recs = Recommendations(dd, idb)
game = GameAnalyzer(dd, idb, recs)
print("Patch", dd.version)


def player(champ, team, k, d, a, lvl, items, me=False):
    return {"championName": champ, "rawChampionName": f"game_character_displayname_{champ}", "team": team,
            "riotId": "Me#EUW" if me else f"{champ}#X", "level": lvl,
            "scores": {"kills": k, "deaths": d, "assists": a},
            "items": [{"itemID": i, "count": 1, "slot": n} for n, i in enumerate(items)]}


def snapshot(me_champ, me_items, enemies, gold, t=1260):
    allies = [player(me_champ, "ORDER", 3, 2, 4, 11, me_items, me=True)] + [
        player(c, "ORDER", 2, 3, 5, 10, [3047]) for c in ("Garen", "Lux", "Thresh", "Vi")]
    return {"activePlayer": {"riotId": "Me#EUW", "currentGold": gold}, "gameData": {"gameTime": t},
            "allPlayers": allies + enemies}


def run(title, data, role=""):
    my = dd.champ_from_live(data["allPlayers"][0])
    for _ in range(100):  # wait for background download of Riot's recommendations
        if recs.get(my, role) is not None:
            break
        time.sleep(0.2)
    v = game.analyze(data, role)
    print(f"\n=== {title} | {v['gold']} Gold | Basis: {v['source']} ===")
    print("  Jetzt kaufen:", v["shopping"], "|", v["boots_hint"])
    for n, e in enumerate(v["plan"], 1):
        print(f"  {n}. {'✔' if e['owned'] else ' '} {e['name']:<30} {e.get('tags')} {e.get('parts')}")
    print("  Gegner:", [(e["name"], e["threat"]) for e in v["enemies"]])
    return v


ad_fed = [player("Zed", "CHAOS", 9, 1, 2, 13, [3142, 6692]), player("Draven", "CHAOS", 7, 2, 3, 12, [3031]),
          player("Darius", "CHAOS", 4, 3, 2, 12, [3071]), player("Soraka", "CHAOS", 0, 2, 10, 10, []),
          player("Warwick", "CHAOS", 3, 3, 4, 11, [])]
ap_team = [player("Malphite", "CHAOS", 2, 3, 6, 11, [3075]), player("Syndra", "CHAOS", 6, 2, 3, 12, [3089]),
           player("Brand", "CHAOS", 5, 3, 4, 11, [4645]), player("DrMundo", "CHAOS", 1, 2, 3, 11, [3065]),
           player("Ornn", "CHAOS", 1, 2, 7, 11, [3001])]

run("Garen, frisch aus der Base", snapshot("Garen", [1054, 2003], ad_fed, 1300, t=240), "top")
run("Garen mit Stridebreaker + Teil", snapshot("Garen", [6631, 1001, 1036], ad_fed, 1100), "top")
v1 = run("Ahri gegen fed Zed", snapshot("Ahri", [1056, 1052], ad_fed, 1400), "middle")
v2 = game.analyze(snapshot("Ahri", [1056, 1052], ad_fed, 1450, t=1262), "middle")
print("  Plan stabil zwischen Updates:", [e["id"] for e in v1["plan"]] == [e["id"] for e in v2["plan"]])
run("Jinx (keine eigene Riot-Liste)", snapshot("Jinx", [1055, 3006, 6672], ap_team, 3100), "bottom")
run("Malphite gegen fed AD", snapshot("Malphite", [1054], ad_fed, 900), "top")
full = run("Kai'Sa mit 6 Items", snapshot("Kaisa", [3006, 3124, 3115, 3089, 3157, 3135], ap_team, 500), "bottom")
assert len(full["plan"]) == 6, "plan must never exceed 6 slots"
