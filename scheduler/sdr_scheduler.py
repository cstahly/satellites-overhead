#!/usr/bin/env python3
"""SDR pass scheduler. Run once, handles everything, logs everything."""
import json, subprocess, time, os, datetime, threading

HOME = os.path.expanduser("~")
CAPDIR = os.path.join(HOME, "cosmos_captures")
NOAADIR = os.path.join(HOME, "noaa_captures")
os.makedirs(CAPDIR, exist_ok=True)
os.makedirs(NOAADIR, exist_ok=True)

LOG = os.path.join(HOME, "sdr_scheduler.log")
PREDICTOR = os.path.join(HOME, "src", "satellites-overhead", "predict.py")
RULES_PATH = os.path.join(HOME, "sdr_scheduler_rules.json")
LAT = 40.42
LON = -86.88
ALT_M = 180

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def seconds_until(timestr):
    now = datetime.datetime.now()
    h, m = map(int, timestr.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()

def hackrf_capture(freq_hz, outfile, duration_s, lna=32, vga=40, amp=1, label=""):
    logfile = outfile + ".log"
    log(f"START {label} — {freq_hz/1e6:.3f} MHz → {outfile} (tail -f {logfile})")
    cmd = ["hackrf_transfer", "-r", outfile, "-f", str(freq_hz),
           "-s", "2000000", "-l", str(lna), "-g", str(vga), "-a", str(amp)]

    def heartbeat(proc, outfile, stop_evt):
        while not stop_evt.wait(30):
            if proc.poll() is not None:
                break
            size = os.path.getsize(outfile) / 1e6 if os.path.exists(outfile) else 0
            log(f"  {label} — {size:.0f} MB written")

    try:
        with open(logfile, "w") as lf:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=lf)
        stop_evt = threading.Event()
        t = threading.Thread(target=heartbeat, args=(proc, outfile, stop_evt), daemon=True)
        t.start()
        try:
            proc.wait(timeout=duration_s)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
        finally:
            stop_evt.set()
        size = os.path.getsize(outfile) if os.path.exists(outfile) else 0
        log(f"DONE  {label} — {size/1e6:.0f} MB captured")
        return outfile if size > 0 else None
    except Exception as e:
        log(f"FAIL  {label} — {e}")
        return None

def satdump_capture(capdir, duration_s, freq=137.1e6, lna=32, vga=48, label=""):
    logfile = capdir + ".log"
    log(f"START {label} — satdump LRPT {freq/1e6:.1f} MHz → {capdir} (tail -f {logfile})")
    cmd = ["satdump", "live", "meteor_m2-x_lrpt", capdir,
           "--source", "hackrf", "--samplerate", "2e6",
           "--frequency", str(freq),
           "--lna_gain", str(lna), "--vga_gain", str(vga),
           "--timeout", str(duration_s)]
    os.makedirs(capdir, exist_ok=True)
    try:
        with open(logfile, "w") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf)
            proc.wait()
        cadu = os.path.join(capdir, "meteor_m2-x_lrpt.cadu")
        size = os.path.getsize(cadu) if os.path.exists(cadu) else 0
        if size > 0:
            log(f"DONE  {label} — {size} bytes CADU — IMAGES LIKELY")
        else:
            log(f"DONE  {label} — 0 bytes CADU — no lock — check {logfile}")
        return size
    except Exception as e:
        log(f"FAIL  {label} — {e}")
        return 0

def analyze_150mhz(iqfile, label):
    try:
        result = subprocess.check_output(
            ["python3", "/tmp/analyze_150mhz.py", iqfile, label],
            stderr=subprocess.DEVNULL, text=True)
        log(result.strip())
    except Exception as e:
        log(f"ANALYZE FAIL {label}: {e}")

def iso_to_local_dt(value):
    dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone()

def iso_to_local_hhmm(value):
    return iso_to_local_dt(value).strftime("%H:%M")

def safe_name(value):
    keep = []
    for ch in value:
        keep.append(ch if ch.isalnum() else "_")
    return "_".join("".join(keep).strip("_").lower().split("_"))[:40] or "capture"

def m2_4_gain(max_el):
    if max_el >= 60:
        return 24, 36
    return 32, 48

def load_scheduler_rules():
    if not os.path.exists(RULES_PATH):
        return []
    with open(RULES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []

def predict_rule_passes(rule, hours=24, limit=4):
    cmd = [
        "python3", PREDICTOR,
        "--lat", str(LAT), "--lon", str(LON), "--alt-m", str(ALT_M),
        "--hours", str(hours), "--min-el", str(rule.get("min_peak_el", 10)),
        "--norad", str(int(rule["norad"])), "--track-step-s", "60",
        "--limit", str(limit),
    ]
    raw = subprocess.check_output(cmd, text=True)
    return json.loads(raw)

def build_rule_jobs(rule, hours=24, limit=4):
    passes = predict_rule_passes(rule, hours=hours, limit=limit)
    jobs = []
    for p in passes:
        start_offset_s = int(rule.get("start_offset_s", -30))
        end_offset_s = int(rule.get("end_offset_s", 60))
        fire_dt = iso_to_local_dt(p["aos"]) + datetime.timedelta(seconds=start_offset_s)
        fire_time = fire_dt.strftime("%H:%M")
        max_el = float(p["max_el"])
        lna, vga = m2_4_gain(max_el)
        aos_local = fire_time.replace(":", "")
        duration_s = max(1, int(p["duration_s"]) - start_offset_s + end_offset_s)
        freq = float(rule["frequency_hz"])
        label = f"{rule.get('name', p['name'])} {max_el:.1f}deg"
        slug = safe_name(rule.get("name") or p["name"])
        if rule.get("profile") == "meteor_lrpt_hackrf":
            jobs.append((
                fire_time,
                "satdump",
                dict(
                    capdir=f"{NOAADIR}/{slug}_{aos_local}",
                    duration_s=duration_s,
                    freq=freq,
                    lna=lna,
                    vga=vga,
                    label=f"{label} LRPT",
                ),
            ))
        else:
            jobs.append((
                fire_time,
                "iq",
                dict(
                    freq_hz=int(freq),
                    duration_s=duration_s,
                    lna=lna,
                    vga=vga,
                    amp=1,
                    outfile=f"{CAPDIR}/{slug}_{aos_local}.iq",
                    label=f"{label} IQ",
                ),
            ))
    return jobs

def optional_rule_jobs():
    jobs = []
    for rule in load_scheduler_rules():
        if not rule.get("enabled", True):
            continue
        if rule.get("type") != "satellite_recurring":
            continue
        try:
            rule_jobs = build_rule_jobs(rule)
            jobs.extend(rule_jobs)
            log(f"Loaded {len(rule_jobs)} jobs from rule {rule.get('id')}")
        except Exception as e:
            log(f"RULE PREDICT FAIL {rule.get('id', '?')} — no jobs added: {e}")
    return jobs

# ── SCHEDULE ─────────────────────────────────────────────────────────────────
if __name__ != '__main__':
    raise ImportError("sdr_scheduler is not importable — run it directly")

MANUAL_JOBS = [
    # Agent/user-created radio jobs belong here. They do not need to be
    # satellites and do not depend on TLEs, CelesTrak, the map, or serve.py.
]

JOBS = MANUAL_JOBS + optional_rule_jobs()
JOBS.sort(key=lambda job: job[0])
log(f"SDR scheduler running — {len(MANUAL_JOBS)} manual jobs, {len(JOBS) - len(MANUAL_JOBS)} rule jobs")

for fire_time, ptype, kwargs in JOBS:
    wait = seconds_until(fire_time)
    log(f"Next: {kwargs['label']} at {fire_time} (in {wait:.0f}s)")
    time.sleep(wait)

    if ptype == "iq":
        outfile = hackrf_capture(**kwargs)
        if outfile:
            analyze_150mhz(outfile, kwargs["label"])
    elif ptype == "satdump":
        satdump_capture(**kwargs)

log("All passes complete.")
