"""Simulates a champ select + game (Samira ADC) through the real UI and records it as demo/demo.gif.

The simulated player always buys exactly what the app suggests, so you can follow the recommendations.
Run:  python demo/make_demo.py      (needs: pip install pillow)
"""
import ctypes
import sys
import time
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import lolcoach.ui as ui  # noqa: E402
from lolcoach.champselect import ChampSelectAnalyzer  # noqa: E402
from lolcoach.ddragon import DataDragon  # noqa: E402
from lolcoach.ingame import GameAnalyzer  # noqa: E402
from lolcoach.items import ItemDB  # noqa: E402
from lolcoach.recommendations import Recommendations  # noqa: E402

OUT = ROOT / "demo" / "demo.gif"
dd = DataDragon()
idb = ItemDB(dd)
recs = Recommendations(dd, idb)
cs_an = None
game = GameAnalyzer(dd, idb, recs)
K = {cid: t.key for cid, t in dd.by_id.items()}
BY_NAME = {it.names["en"]: it.id for it in idb.items.values()}


def item(name):
    return BY_NAME[name]


# ---------------------------------------------------------------- fake client data
class FakeLCU:
    def get(self, path, timeout=3):
        if "mastery" in path:
            return [{"championId": K["Samira"], "championPoints": 182000}, {"championId": K["Jinx"], "championPoints": 91000},
                    {"championId": K["Ezreal"], "championPoints": 38000}, {"championId": K["Caitlyn"], "championPoints": 21000}]
        if "current-summoner" in path and "matches" not in path:
            return {"puuid": "me"}
        games = []
        for champ, wins, losses in (("Samira", 14, 8), ("Jinx", 6, 7), ("Ezreal", 2, 5), ("Caitlyn", 3, 2)):
            for i in range(wins + losses):
                games.append({"mapId": 11, "participantIdentities": [{"participantId": 1, "player": {"puuid": "me"}}],
                              "participants": [{"participantId": 1, "championId": K[champ], "stats": {"win": i < wins},
                                                "timeline": {"lane": "BOTTOM", "role": "DUO_CARRY"}}]})
        return {"games": {"games": games}}


def session(hover=None, locked=False, allies=(), enemies=()):
    team = [{"cellId": 0, "assignedPosition": "top"}, {"cellId": 1, "assignedPosition": "jungle"},
            {"cellId": 2, "assignedPosition": "middle"}, {"cellId": 3, "assignedPosition": "bottom"},
            {"cellId": 4, "assignedPosition": "utility"}]
    for cell, champ in allies:
        team[cell]["championId"] = K[champ]
    if hover:
        team[3]["championId" if locked else "championPickIntent"] = K[hover]
    return {"localPlayerCellId": 3, "myTeam": team, "actions": [], "bans": {"myTeamBans": [], "theirTeamBans": []},
            "theirTeam": [{"championId": K[c]} for c in enemies]}


PICKABLE = [K[c] for c in ("Samira", "Jinx", "Ezreal", "Caitlyn", "Kaisa", "Lucian", "Ashe", "Varus", "MissFortune")]


POS = {"Darius": "TOP", "Warwick": "JUNGLE", "Zed": "MIDDLE", "Draven": "BOTTOM", "Soraka": "UTILITY",
       "Garen": "TOP", "LeeSin": "JUNGLE", "Ahri": "MIDDLE", "Samira": "BOTTOM", "Thresh": "UTILITY"}


def player(champ, team, kda, lvl, items, me=False):
    return {"championName": champ, "rawChampionName": f"game_character_displayname_{champ}", "team": team,
            "riotId": "Du#EUW" if me else f"{champ}#BOT", "level": lvl, "position": POS.get(champ, ""),
            "scores": {"kills": kda[0], "deaths": kda[1], "assists": kda[2]},
            "items": [{"itemID": i, "count": 1, "slot": n} for n, i in enumerate(items)]}


# ---------------------------------------------------------------- recording
font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 17)
font_b = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 18)
frames, durations = [], []
ui.Poller = type("NoPoller", (), {"__init__": lambda s, q: None, "start": lambda s: None})
app = ui.App()
app.root.attributes("-topmost", True)
app.root.geometry(f"470x{min(800, app.root.winfo_screenheight() - 120)}+40+40")


def shot(view, status, title, text, ms=3200):
    app.apply({"client": True, "status": status, "view": view})
    for _ in range(5):
        app.root.update()
        time.sleep(0.08)
    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    side = 420
    frame = Image.new("RGB", (w + side, h), "#0b0d11")
    frame.paste(img, (0, 0))
    d = ImageDraw.Draw(frame)
    d.text((w + 22, 30), title, font=font_b, fill="#c8aa6e")
    yy = 70
    for para in text.split("\n"):
        for line in textwrap.wrap(para, 38):
            d.text((w + 22, yy), line, font=font, fill="#e8e8e8")
            yy += 26
        yy += 12
    frames.append(frame)
    durations.append(ms)
    print(f"[{len(frames):02d}] {title}")


# ---------------------------------------------------------------- 1) champ select
cs = ChampSelectAnalyzer(dd, FakeLCU())
v = cs.analyze(session(), PICKABLE)
best = v["suggestions"][0]["name"]
shot(v, "Champ Select", "1 · Champ Select startet",
     f"Du bist ADC. Die App schlägt Champions aus deiner Meisterschaft und deiner Siegquote vor – ganz oben: {best}.")

allies = [(0, "Garen"), (1, "LeeSin"), (2, "Ahri")]
enemies = ["Darius", "Zed", "Warwick"]
v = cs.analyze(session("Ezreal", allies=allies, enemies=enemies), PICKABLE)
h = v["hover"]
shot(v, "Champ Select", "2 · Du fährst über Ezreal",
     f"Team und Gegner sind teilweise gepickt. Bewertung für Ezreal: „{h['verdict']}“ ({h['score']}/100) – siehe Gründe.")

v = cs.analyze(session("Samira", allies=allies, enemies=enemies), PICKABLE)
h = v["hover"]
shot(v, "Champ Select", "3 · Du fährst über Samira",
     f"Bewertung: „{h['verdict']}“ ({h['score']}/100). Hohe Meisterschaft und gute Bilanz auf ADC.")

allies_full = allies + [(4, "Thresh")]
v = cs.analyze(session("Samira", True, allies_full, enemies + ["Draven", "Soraka"]), PICKABLE)
recs.get(dd.champ("Samira"), "bottom")  # app prefetches the build while you're in champ select
shot(v, "Champ Select", "4 · Samira gelockt",
     "Alle Picks stehen. Im Hintergrund lädt die App schon die Build-Daten für Samira.")
while recs.get(dd.champ("Samira"), "bottom") is None:
    time.sleep(0.2)

# ---------------------------------------------------------------- 2) the game
me = {"inv": [item("Doran's Blade"), item("Health Potion")], "gold": 0, "kda": [0, 0, 0], "lvl": 1}


def snapshot(t, enemy_state, ally_lvl):
    allies_p = [player("Samira", "ORDER", me["kda"], me["lvl"], me["inv"], me=True)] + [
        player(c, "ORDER", (1, 2, 2), ally_lvl, [item("Long Sword")]) for c in ("Garen", "LeeSin", "Ahri", "Thresh")]
    enemy_p = [player(c, "CHAOS", kda, lvl, [item(i) for i in its]) for c, kda, lvl, its in enemy_state]
    return {"activePlayer": {"riotId": "Du#EUW", "currentGold": me["gold"]}, "gameData": {"gameTime": t},
            "allPlayers": allies_p + enemy_p}


def status(t):
    return f"Im Spiel · {t // 60}:{t % 60:02d}"


PREV = {"names": None}


def plan_changes(view):
    """Describe how the build plan differs from the previous back (generated from real data)."""
    names = [e["name"] for e in view["plan"]]
    prev, PREV["names"] = PREV["names"], names
    if prev is None:
        return ""
    new = [e for e in view["plan"] if not e["owned"] and e["name"] not in prev]
    if not new:
        return "Plan seit dem letzten Back unverändert – er springt nicht hin und her."
    return "Plan geändert: " + "; ".join(
        f"neu {e['name']}" + (f" ({', '.join(e['reasons'][:2])})" if e["reasons"] else "") for e in new)


def follow_app(view):
    """Buy exactly what 'Jetzt kaufen' suggests."""
    bought = []
    for _ in range(4):
        todo = [e for e in view["plan"] if not e["owned"]]
        if not todo:
            break
        comp, cost = idb.next_component(todo[0]["id"], me["inv"], me["gold"])
        if comp is None:
            break
        me["inv"], _ = idb.after_buy(comp.id, me["inv"])
        me["gold"] -= cost
        bought.append(comp.name)
        view = game.analyze(snap(), "bottom")
    boots = idb.get(1001)
    if me["gold"] >= 300 and any(boots.name in line for line in view["shopping"]):
        me["inv"].append(1001)
        me["gold"] -= 300
        bought.append(boots.name)
    return bought


timeline = [
    (75, 1, [0, 0, 0], 0, (2, 2, 2), [
        ("Darius", (0, 0, 0), 2, ["Doran's Blade"]), ("Warwick", (0, 0, 0), 2, []),
        ("Zed", (0, 0, 0), 2, ["Long Sword"]), ("Draven", (0, 0, 0), 2, ["Doran's Blade"]),
        ("Soraka", (0, 0, 0), 2, [])],
     "5 · Spielstart (1:15)", "Noch kein Gold. Die App zeigt den Build mit 6 Plätzen. Gegner stehen in derselben Reihenfolge wie in deiner Tab-Anzeige."),
    (430, 6, [2, 1, 1], 1350, (6, 1, 2), [
        ("Darius", (1, 1, 0), 6, ["Doran's Blade", "Caulfield's Warhammer"]), ("Warwick", (1, 2, 1), 6, []),
        ("Zed", (3, 0, 0), 7, ["Serrated Dirk"]), ("Draven", (1, 2, 0), 6, ["B. F. Sword"]),
        ("Soraka", (0, 1, 2), 5, [])],
     "6 · Erster Back (7:10)", "1350 Gold. Unter „Jetzt kaufen“ steht genau, was du dir jetzt leisten kannst, und wann die Stiefel dran sind."),
    (880, 10, [4, 2, 3], 1150, (9, 3, 5), [
        ("Darius", (2, 2, 1), 10, ["Black Cleaver", "Plated Steelcaps"]), ("Warwick", (2, 3, 3), 9, ["Blade of The Ruined King"]),
        ("Zed", (7, 1, 1), 11, ["Youmuu's Ghostblade", "Serrated Dirk"]), ("Draven", (2, 3, 1), 9, ["Bloodthirster"]),
        ("Soraka", (0, 2, 6), 8, ["Moonstone Renewer"])],
     "8 · Zweiter Back (14:40)", "Zed ist gefüttert (7/1) – sein Gefahrenbalken ist voll und rot. Soraka heilt das Gegnerteam."),
    (1260, 13, [6, 3, 6], 2900, (12, 4, 7), [
        ("Darius", (3, 3, 2), 13, ["Black Cleaver", "Plated Steelcaps", "Sterak's Gage"]),
        ("Warwick", (3, 4, 4), 12, ["Blade of The Ruined King", "Mercury's Treads"]),
        ("Zed", (9, 3, 2), 13, ["Youmuu's Ghostblade", "Edge of Night", "Ionian Boots of Lucidity"]),
        ("Draven", (3, 4, 2), 12, ["Bloodthirster", "Berserker's Greaves"]),
        ("Soraka", (0, 3, 9), 11, ["Moonstone Renewer", "Ionian Boots of Lucidity"])],
     "10 · Dritter Back (21:00)", "2900 Gold. Komponenten, die du schon hast, stehen eingerückt unter dem Item, für das sie gedacht sind."),
    (1680, 16, [9, 4, 9], 3300, (15, 5, 9), [
        ("Darius", (4, 5, 3), 16, ["Black Cleaver", "Plated Steelcaps", "Sterak's Gage", "Thornmail", "Randuin's Omen"]),
        ("Warwick", (4, 6, 5), 15, ["Blade of The Ruined King", "Mercury's Treads", "Dead Man's Plate"]),
        ("Zed", (10, 5, 3), 16, ["Youmuu's Ghostblade", "Edge of Night", "Ionian Boots of Lucidity", "Serylda's Grudge"]),
        ("Draven", (4, 6, 3), 15, ["Bloodthirster", "Berserker's Greaves", "Infinity Edge"]),
        ("Soraka", (0, 4, 11), 14, ["Moonstone Renewer", "Ionian Boots of Lucidity", "Redemption"])],
     "12 · Late Game (28:00)", "Darius und Warwick bauen jetzt viel Rüstung (Thornmail, Randuin's, Dead Man's Plate)."),
]

n = 5
for t, lvl, kda, gold, ally_info, enemy_state, title, text in timeline:
    me["lvl"], me["kda"], me["gold"] = lvl, kda, gold
    if t > 400 and item("Health Potion") in me["inv"]:
        me["inv"].remove(item("Health Potion"))

    def snap(t=t, enemy_state=enemy_state, lvl=lvl):
        return snapshot(t, enemy_state, lvl)

    view = game.analyze(snap(), "bottom")
    shot(view, status(t), title, text + "\n" + plan_changes(view), ms=5200)
    if gold:
        bought = follow_app(view)
        view = game.analyze(snap(), "bottom")
        n_title = f"{int(title.split(' ')[0]) + 1} · Gekauft, was die App vorgeschlagen hat"
        shot(view, status(t), n_title,
             f"Gekauft: {', '.join(bought) or 'nichts'}. Fertige Items sind im Build abgehakt.", ms=3600)

frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
sheet = Image.new("RGB", (frames[0].width * 4 // 2, (frames[0].height // 2) * ((len(frames) + 3) // 4)), "#000")
for i, f in enumerate(frames):
    sheet.paste(f.resize((f.width // 2, f.height // 2)), ((i % 4) * f.width // 2, (i // 4) * f.height // 2))
sheet.save(ROOT / "demo" / "contact_sheet.png")
app.root.destroy()
print("GIF:", OUT, "| frames:", len(frames))
