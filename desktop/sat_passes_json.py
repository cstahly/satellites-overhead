#!/usr/bin/env python3
"""Write upcoming satellite passes to ~/.local/share/sat-passes/passes.json for
the GNOME top-bar extension. Reuses the scheduler's predict.py + enabled rules so
it matches what the scheduler will actually capture. Run by a systemd --user timer."""
import json, os, subprocess, datetime
from concurrent.futures import ThreadPoolExecutor

HOME = os.path.expanduser("~")
RULES = os.path.join(HOME, "sdr_scheduler_rules.json")
PREDICT = os.path.join(HOME, "src/satellites-overhead/predict.py")
OUT_DIR = os.path.join(HOME, ".local/share/sat-passes")
LAT, LON, ALT_M = 40.42, -86.88, 180


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
        return [{"name": name, "aos": p["aos"], "max_el": round(float(p.get("max_el", 0)), 1)}
                for p in json.loads(raw)]
    except Exception:
        return []


def main():
    sats = enabled_sats()
    allp = []
    if sats:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for ps in ex.map(_predict_one, sats):
                allp += ps
    allp.sort(key=lambda p: p["aos"])
    os.makedirs(OUT_DIR, exist_ok=True)
    data = {"generated": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"), "passes": allp}
    tmp = os.path.join(OUT_DIR, "passes.json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(OUT_DIR, "passes.json"))
    print(f"wrote {len(allp)} passes")


if __name__ == "__main__":
    main()
