#!/usr/bin/env python3
"""Tiny always-on-top desktop widget: next satellite pass + live countdown.
Click the header to drop down the upcoming-pass list. Drag to move, right-click
to close. Reuses the scheduler's predict.py + enabled rules so it matches what
the scheduler will actually capture. No external deps (stdlib + tkinter)."""
import json, os, subprocess, threading, datetime
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

HOME = os.path.expanduser("~")
RULES = os.path.join(HOME, "sdr_scheduler_rules.json")
PREDICT = os.path.join(HOME, "src/satellites-overhead/predict.py")
LAT, LON, ALT_M = 40.42, -86.88, 180
REFRESH_S = 600          # re-predict every 10 min
SHOW = 12                # rows in the dropdown

BG, BG2, FG, MUT, ACC, HOT = "#0c0d0f", "#15161a", "#e6e6ea", "#6e6e80", "#7c6af7", "#ff7b72"
MONO = ("DejaVu Sans Mono", 11)
MONOS = ("DejaVu Sans Mono", 10)


def enabled_sats():
    try:
        d = json.load(open(RULES))
    except Exception:
        return []
    rules = d if isinstance(d, list) else d.get("rules", d)
    rl = rules if isinstance(rules, list) else list(rules.values())
    seen = {}
    for r in rl:
        if r.get("enabled") and str(r.get("type", "")).startswith("satellite") and r.get("norad"):
            n = int(r["norad"])
            seen.setdefault(n, (n, r.get("name", str(n)), float(r.get("min_peak_el", 10))))
    return list(seen.values())


def _predict_one(args):
    norad, name, minel = args
    try:
        raw = subprocess.check_output(
            ["python3", PREDICT, "--lat", str(LAT), "--lon", str(LON), "--alt-m", str(ALT_M),
             "--hours", "36", "--min-el", str(minel), "--norad", str(norad),
             "--limit", "6", "--track-step-s", "99999"],
            text=True, timeout=45, stderr=subprocess.DEVNULL)
        out = []
        for p in json.loads(raw):
            out.append({"name": name, "aos": p["aos"], "los": p["los"],
                        "max_el": float(p.get("max_el", 0))})
        return out
    except Exception:
        return []


def fetch_passes():
    sats = enabled_sats()
    allp = []
    if sats:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for ps in ex.map(_predict_one, sats):
                allp += ps
    allp.sort(key=lambda p: p["aos"])
    return allp


def parse(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def fmt_delta(td):
    s = int(td.total_seconds())
    if s < 0:
        return "now"
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


class Widget:
    def __init__(self):
        self.passes = []
        self.expanded = False
        self.moved = False
        self.root = tk.Tk()
        self.root.title("sat-passes")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.94)
        except Exception:
            pass
        self.root.configure(bg=BG, highlightbackground=ACC, highlightthickness=1)
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{sw-360}+44")

        self.header = tk.Frame(self.root, bg=BG)
        self.header.pack(fill="x")
        self.lbl = tk.Label(self.header, text="  ▸  loading passes…", bg=BG, fg=FG,
                            font=MONO, anchor="w", padx=10, pady=8, justify="left")
        self.lbl.pack(fill="x")

        self.listfr = tk.Frame(self.root, bg=BG2)
        for w in (self.header, self.lbl):
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<B1-Motion>", self._drag)
            w.bind("<ButtonRelease-1>", self._release)
            w.bind("<Button-3>", lambda e: self.root.destroy())

        self.refresh()
        self.tick()
        self.root.mainloop()

    # drag vs click
    def _press(self, e):
        self.ox, self.oy, self.moved = e.x, e.y, False

    def _drag(self, e):
        self.moved = True
        self.root.geometry(f"+{self.root.winfo_pointerx()-self.ox}+{self.root.winfo_pointery()-self.oy}")

    def _release(self, e):
        if not self.moved:
            self.toggle()

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.listfr.pack(fill="x")
            self.render_list()
        else:
            self.listfr.pack_forget()

    def refresh(self):
        def work():
            ps = fetch_passes()
            self.root.after(0, lambda: self._set(ps))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(REFRESH_S * 1000, self.refresh)

    def _set(self, ps):
        self.passes = ps
        if self.expanded:
            self.render_list()

    def render_list(self):
        for c in self.listfr.winfo_children():
            c.destroy()
        now = datetime.datetime.now(datetime.timezone.utc)
        upcoming = [p for p in self.passes if parse(p["aos"]) > now][:SHOW]
        if not upcoming:
            tk.Label(self.listfr, text="  no upcoming passes", bg=BG2, fg=MUT,
                     font=MONOS, anchor="w", padx=10, pady=6).pack(fill="x")
            return
        for i, p in enumerate(upcoming):
            aos = parse(p["aos"]).astimezone()
            row = tk.Frame(self.listfr, bg=BG2)
            row.pack(fill="x")
            txt = f"  {aos:%a %H:%M}   {p['name'][:14]:14s} {p['max_el']:4.0f}°   in {fmt_delta(parse(p['aos'])-now)}"
            tk.Label(row, text=txt, bg=BG2, fg=(FG if i == 0 else MUT),
                     font=MONOS, anchor="w", padx=10, pady=3, justify="left").pack(fill="x")

    def tick(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        nxt = next((p for p in self.passes if parse(p["aos"]) > now), None)
        arrow = "▾" if self.expanded else "▸"
        if nxt:
            td = parse(nxt["aos"]) - now
            cd = fmt_delta(td)
            col = HOT if td.total_seconds() < 600 else FG
            self.lbl.config(text=f"  {arrow}  {nxt['name'][:14]}  {nxt['max_el']:.0f}°   {cd}", fg=col)
        elif self.passes:
            self.lbl.config(text=f"  {arrow}  (refreshing…)", fg=MUT)
        self.root.after(1000, self.tick)


if __name__ == "__main__":
    Widget()
