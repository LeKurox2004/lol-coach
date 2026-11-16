"""Tkinter window. Widgets are created once per view and only updated in place (no flicker)."""
import queue
import tkinter as tk

from . import settings
from .poller import Poller

BG, CARD, FG, MUTED, ACCENT = "#101318", "#1a1f27", "#e8e8e8", "#8b93a1", "#c8aa6e"
GOOD, OK, BAD, DIM = "#4caf50", "#e0b03c", "#e05555", "#d9a0a0"
TONE = {"good": GOOD, "ok": OK, "bad": BAD}
FONT = "Segoe UI"
WRAP = 390

LAYOUTS = {
    "message": ["msg"],
    "champselect": ["role", "hover", "suggestions", "teams"],
    "ingame": ["shopping", "plan", "enemies"],
}
TITLES = {
    "hover": "Dein Champion", "suggestions": "Vorschläge für dich", "teams": "Teams",
    "shopping": "Jetzt kaufen", "plan": "Build", "enemies": "Gegner  ·  ziehen zum Sortieren, Doppelklick = Standard",
}


def row(text, fg=FG, size=10, bold=False, indent=0):
    return (text, fg, size, bold, indent)


class Section:
    """A card whose rows are updated in place; only changed labels are touched."""

    def __init__(self, parent, title):
        self.frame = tk.Frame(parent, bg=CARD, padx=10, pady=8)
        self.title = None
        if title:
            self.title = tk.Label(self.frame, text=title, fg=ACCENT, bg=CARD, font=(FONT, 10, "bold"), anchor="w")
            self.title.pack(fill="x")
        self.labels, self.specs, self.visible = [], [], False

    def set_title(self, title):
        if self.title is not None and self.title.cget("text") != title:
            self.title.config(text=title)

    def set(self, rows):
        self.visible = bool(rows)  # App packs visible sections in layout order
        for i, spec in enumerate(rows):
            if i < len(self.labels):
                if self.specs[i] != spec:
                    self._configure(self.labels[i], spec)
                    self.specs[i] = spec
            else:
                lbl = tk.Label(self.frame, bg=CARD, anchor="w", justify="left")
                lbl.pack(fill="x")
                self._configure(lbl, spec)
                self.labels.append(lbl)
                self.specs.append(spec)
        while len(self.labels) > len(rows):
            self.labels.pop().destroy()
            self.specs.pop()

    @staticmethod
    def _configure(lbl, spec):
        text, fg, size, bold, indent = spec
        lbl.config(text=text, fg=fg, font=(FONT, size, "bold" if bold else "normal"), wraplength=WRAP - indent)
        lbl.pack_configure(padx=(indent, 0))


class App:
    def __init__(self, start_hidden=False):
        self.autostarted = start_hidden
        self.root = tk.Tk()
        self.root.title("LoL Coach")
        self.root.geometry("440x820")
        self.root.minsize(360, 400)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        if start_hidden:
            self.root.withdraw()

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text="LoL Coach", fg=ACCENT, bg=BG, font=(FONT, 15, "bold")).pack(side="left")
        tk.Button(head, text="Beenden", command=self.root.destroy, bg=CARD, fg=MUTED, relief="flat",
                  activebackground="#2a313c", activeforeground=FG).pack(side="right")
        self.lang_btn = tk.Button(head, command=self.toggle_lang, bg=CARD, fg=FG, relief="flat", width=8,
                                  activebackground="#2a313c", activeforeground=FG)
        self.lang_btn.pack(side="right", padx=(6, 0))
        self._lang_label()
        self.topmost = tk.BooleanVar(value=False)
        tk.Checkbutton(head, text="Immer oben", variable=self.topmost,
                       command=lambda: self.root.attributes("-topmost", self.topmost.get()), bg=BG, fg=MUTED,
                       selectcolor=CARD, activebackground=BG, activeforeground=FG).pack(side="right", padx=6)
        self.status = tk.Label(self.root, text="Starte…", fg=MUTED, bg=BG, font=(FONT, 10), anchor="w")
        self.status.pack(fill="x", padx=12)

        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=8, pady=6)
        self.body = tk.Frame(canvas, bg=BG)
        self.body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        body_win = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(body_win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        self.q = queue.Queue()
        self.client_was_running = False
        self.kind, self.sections, self.packed = None, {}, None
        self.enemy_order, self._enemy_set, self._last_ingame = [], None, None
        Poller(self.q).start()
        self.root.after(300, self.pump)

    # ---- name language ---------------------------------------------------------------
    def _lang_label(self):
        self.lang_btn.config(text="Namen: " + settings.lang().upper())

    def toggle_lang(self):
        settings.set("lang", "de" if settings.lang() == "en" else "en")
        self._lang_label()  # names switch with the next update (≤ 2 s)

    # ---- window state ---------------------------------------------------------------
    def hide(self):
        """Closing only hides the window; it pops up again the next time League starts."""
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def pump(self):
        latest = None
        while True:
            try:
                latest = self.q.get_nowait()
            except queue.Empty:
                break
        if latest:
            self.apply(latest)
        self.root.after(400, self.pump)

    def apply(self, state):
        running = state["client"]
        if running and not self.client_was_running:
            self.show()
        elif not running and self.client_was_running and self.autostarted:
            self.hide()
        self.client_was_running = running
        if self.status.cget("text") != state["status"]:
            self.status.config(text=state["status"])
        view = state["view"]
        kind = view.get("kind", "message")
        if kind != self.kind:  # only rebuild when switching between views
            for sec in self.sections.values():
                sec.frame.destroy()
            self.sections = {name: Section(self.body, TITLES.get(name)) for name in LAYOUTS[kind]}
            self.kind, self.packed = kind, None
        getattr(self, f"update_{kind}")(view)
        visible = tuple(n for n, sec in self.sections.items() if sec.visible)
        if visible != self.packed:
            for sec in self.sections.values():
                sec.frame.pack_forget()
            for n in visible:
                self.sections[n].frame.pack(fill="x", padx=4, pady=5)
            self.packed = visible

    # ---- views ----------------------------------------------------------------------
    def update_message(self, v):
        self.sections["msg"].set([row(v.get("text", ""), fg=MUTED)])

    def update_champselect(self, v):
        s = self.sections
        s["role"].set([row(f"Deine Rolle: {v['role']}", bold=True)])
        h = v.get("hover")
        if h:
            s["hover"].set_title("Dein Champion" + (" (gelockt)" if h["locked"] else " (Hover)"))
            rows = [row(f"{h['name']} – {h['verdict']} ({h['score']}/100)", fg=TONE[h["tone"]], size=13, bold=True)]
            rows += [row(f"{'✔' if sg == '+' else '✘'} {r}", fg=FG if sg == "+" else DIM) for sg, r in h["reasons"]]
        else:
            rows = [row("Fahre über einen Champion, um ihn bewerten zu lassen.", fg=MUTED)]
        s["hover"].set(rows)
        rows = []
        for sug in v["suggestions"]:
            rows.append(row(f"{sug['name']}  ·  {sug['score']}/100", bold=True))
            rows += [row(f"– {r}", fg=MUTED, indent=12) for _, r in sug["reasons"]]
        s["suggestions"].set(rows)
        s["teams"].set([row("Dein Team: " + (", ".join(v["allies"]) or "–")),
                        row("Gegner: " + (", ".join(v["enemies"]) or "noch unbekannt"))])

    def update_ingame(self, v):
        s = self.sections
        s["shopping"].set_title(f"Jetzt kaufen  ·  {v['gold']} Gold")
        rows = [row(line, fg=GOOD, size=13, bold=True) for line in v["shopping"]]
        if v.get("boots_hint"):
            rows.append(row("👟 " + v["boots_hint"], fg=OK, size=11))
        s["shopping"].set(rows)
        rows = []
        for n, e in enumerate(v["plan"], 1):
            if e["owned"]:
                rows.append(row(f"✔  {e['name']}", fg=MUTED, size=11))
                continue
            extra = "".join(f"  [{t}]" for t in e.get("tags", []))
            rows.append(row(f"{n}.  {e['name']}{extra}", size=12, bold=True))
            if e.get("parts"):
                rows.append(row("◐ " + ", ".join(e["parts"]), fg=MUTED, size=10, indent=22))
        rows.append(row(v["source"], fg=MUTED, size=8))
        s["plan"].set(rows)
        self._last_ingame = v
        self.render_enemies(v["enemies"])

    # ---- enemy list: drag to match your own Tab order ---------------------------------
    def render_enemies(self, enemies):
        names = [e["name"] for e in enemies]
        if set(names) != self._enemy_set:  # new game -> start with the default Tab order
            self._enemy_set, self.enemy_order = set(names), names[:]
        rank = {n: i for i, n in enumerate(self.enemy_order)}
        enemies = sorted(enemies, key=lambda e: rank.get(e["name"], 99))
        self.enemy_order = [e["name"] for e in enemies]
        rows = []
        for e in enemies:
            filled = round(e["threat"] * 8)
            color = BAD if e["threat"] > 0.75 else OK if e["threat"] > 0.45 else GOOD
            rows.append(row(f"≡  {'█' * filled}{'░' * (8 - filled)}   {e['name']}   {e['kda']}   {e['dmg']}",
                            fg=color, size=11))
        sec = self.sections["enemies"]
        sec.set(rows)
        for i, lbl in enumerate(sec.labels):
            lbl.config(cursor="fleur")
            lbl.bind("<ButtonPress-1>", lambda _e, i=i: setattr(self, "_drag_from", i))
            lbl.bind("<ButtonRelease-1>", self._drag_drop)
            lbl.bind("<Double-Button-1>", lambda _e: self._reset_enemy_order())

    def _drag_drop(self, event):
        labels = self.sections["enemies"].labels
        src = getattr(self, "_drag_from", None)
        if src is None or not labels:
            return
        y = event.y_root
        dst = len(labels) - 1 if y > labels[-1].winfo_rooty() else 0
        for i, lbl in enumerate(labels):
            if lbl.winfo_rooty() <= y < lbl.winfo_rooty() + lbl.winfo_height():
                dst = i
        self._drag_from = None
        if dst != src:
            self.enemy_order.insert(dst, self.enemy_order.pop(src))
            self.render_enemies(self._last_ingame["enemies"])

    def _reset_enemy_order(self):
        if self._last_ingame:
            self.enemy_order = [e["name"] for e in self._last_ingame["enemies"]]
            self.render_enemies(self._last_ingame["enemies"])

    def run(self):
        self.root.mainloop()
