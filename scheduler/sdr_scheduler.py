#!/usr/bin/env python3
"""SDR pass scheduler. Run once, handles everything, logs everything."""
import json, subprocess, time, os, datetime, threading, uuid, sys

HOME = os.path.expanduser("~")
CAPDIR = os.path.join(HOME, "cosmos_captures")
NOAADIR = os.path.join(HOME, "noaa_captures")
os.makedirs(CAPDIR, exist_ok=True)
os.makedirs(NOAADIR, exist_ok=True)

LOG = os.path.join(HOME, "sdr_scheduler.log")
PREDICTOR = os.path.join(HOME, "src", "satellites-overhead", "predict.py")
MONITOR_SCRIPT = os.path.join(HOME, "src", "satellites-overhead", "monitor_capture.py")
REPO_DIR = os.path.join(HOME, "src", "satellites-overhead")
ANALYZER_SCRIPT = os.path.join(REPO_DIR, "analyze_150mhz.py")
RULES_PATH = os.path.join(HOME, "sdr_scheduler_rules.json")
COMMANDS_PATH = os.path.join(HOME, "sdr_scheduler_commands.json")
STATUS_PATH = os.path.join(HOME, "sdr_scheduler_status.json")
HISTORY_PATH = os.path.join(HOME, "sdr_capture_history.json")
LAT = 40.42
LON = -86.88
ALT_M = 180
RELOAD_INTERVAL_S = 60
POLL_INTERVAL_S = 10
MONITOR_DELAY_S = 90

if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from sdr_runtime import emit_event

# Retry variants ordered by P(success). First entry is the initial capture default.
# dc_block=True is required — without it the PLL false-locks on HackRF LO leakage at 137.1 MHz.
# nrzm=False (meteor_m2-4_lrpt_nrzl) is the primary hypothesis: June 4 confirms nrzm=True (variants
# 0 and 1) gives NOSYNC on every pass regardless of iq_swap. NRZ-L variants are now front-loaded.
# rs_usecheck=False variant is a diagnostic: frames through even if RS fails, reveals framing state.
# dc_block=False is last resort — known to produce false Viterbi lock, but retained if all else fails.
LRPT_RETRY_VARIANTS = [
    {"iq_swap": True,  "samplerate": "1e6", "pipeline": "meteor_m2-4_lrpt_nrzl",       "dc_block": True},   # nrzl+iq_swap (primary hypothesis)
    {"iq_swap": False, "samplerate": "1e6", "pipeline": "meteor_m2-4_lrpt_nrzl",       "dc_block": True},   # nrzl+no_iq_swap
    {"iq_swap": True,  "samplerate": "1e6", "pipeline": "meteor_m2-4_lrpt_nrzl_nors",  "dc_block": True},   # nrzl, RS off (diagnostic)
    {"iq_swap": True,  "samplerate": "1e6", "pipeline": "meteor_m2-x_lrpt",            "dc_block": True},   # nrzm+iq_swap (known NOSYNC, kept as fallback)
    {"iq_swap": False, "samplerate": "1e6", "pipeline": "meteor_m2-x_lrpt",            "dc_block": True},   # nrzm+no_iq_swap (known NOSYNC)
    {"iq_swap": True,  "samplerate": "1e6", "pipeline": "meteor_m2-x_lrpt",            "dc_block": False},  # last resort fallback
]

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def scheduler_event(event_type, data=None, notification=None):
    try:
        return emit_event(event_type, "sdr_scheduler.py", data, notification)
    except Exception as e:
        log(f"EVENT WRITE FAIL {event_type} — {e}")
        return None


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

def satdump_capture(capdir, duration_s, freq=137.1e6, lna=32, vga=48, amp=1, label="",
                    samplerate="1e6", iq_swap=True, pipeline="meteor_m2-x_lrpt",
                    dc_block=True):
    logfile = capdir + ".log"
    pidfile = capdir + ".pid"
    # Convert samplerate to integer — satdump rejects scientific notation strings
    sr_int = int(float(samplerate)) if samplerate else 1_000_000
    flags = ("--iq_swap " if iq_swap else "") + f"sr={sr_int}" + (" dc_block" if dc_block else "")
    log(f"START {label} — satdump {pipeline} {freq/1e6:.1f} MHz [{flags}] → {capdir} (tail -f {logfile})")
    cmd = ["satdump", "live", pipeline, capdir,
           "--source", "hackrf", "--samplerate", str(sr_int),
           "--frequency", str(freq),
           "--lna_gain", str(lna), "--vga_gain", str(vga),
           "--amp", str(amp),
           "--timeout", str(duration_s)]
    if iq_swap:
        cmd.append("--iq_swap")
    if dc_block:
        cmd.append("--dc_block")
    os.makedirs(capdir, exist_ok=True)
    try:
        with open(logfile, "w") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf)
        with open(pidfile, "w") as pf:
            pf.write(str(proc.pid))
        proc.wait()
        cadu = os.path.join(capdir, f"{pipeline}.cadu")
        size = os.path.getsize(cadu) if os.path.exists(cadu) else 0
        if size > 0:
            log(f"DONE  {label} — {size} bytes CADU — IMAGES LIKELY")
        else:
            log(f"DONE  {label} — 0 bytes CADU — no lock — check {logfile}")
        return size
    except Exception as e:
        log(f"FAIL  {label} — {e}")
        return 0
    finally:
        try:
            os.unlink(pidfile)
        except FileNotFoundError:
            pass

def analyze_150mhz(iqfile, label, center_hz):
    try:
        result = subprocess.check_output(
            ["python3", ANALYZER_SCRIPT, iqfile, label, str(center_hz)],
            stderr=subprocess.DEVNULL, text=True, timeout=300)
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


def utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def write_scheduler_status(state, current_job=None, message=""):
    payload = {
        "state": state,
        "live": state == "running",
        "pid": os.getpid(),
        "updated_at": utc_now_iso(),
        "current_job": current_job,
        "message": message,
    }
    try:
        atomic_write_json(STATUS_PATH, payload)
    except Exception as e:
        log(f"STATUS WRITE FAIL — {e}")


def append_capture_record(record):
    history = []
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.append(record)
    atomic_write_json(HISTORY_PATH, history)


def _invoke_claude_monitor(capdir, monitor_result):
    """Spawn a claude --print agent to diagnose and act on a failed capture."""
    status = monitor_result.get("status", "unknown")
    report = os.path.join(capdir, "diagnostic_report.md")
    claude_log = capdir + ".claude_monitor.log"
    prompt = (
        f"SDR capture monitor alert. Capture at {capdir} has status '{status}'. "
        f"Diagnostic report: {report}. Log: {capdir}.log. "
        f"Read CLAUDE.md at {REPO_DIR}/CLAUDE.md for full context. "
        f"Diagnose the problem, take corrective action if possible (use the "
        f"satellites-overhead-scheduler MCP to queue captures or adjust rules), "
        f"and append your findings to the diagnostic report."
    )
    try:
        with open(claude_log, "w") as lf:
            subprocess.Popen(
                ["claude", "--print", "-p", prompt],
                cwd=REPO_DIR,
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
        log(f"MONITOR Claude agent invoked for {os.path.basename(capdir)} — {claude_log}")
        scheduler_event(
            "claude.invoked",
            {
                "capture": os.path.basename(capdir),
                "capture_path": capdir,
                "status": status,
                "log": claude_log,
            },
            {
                "title": "Claude SDR diagnosis started",
                "body": os.path.basename(capdir),
            },
        )
    except Exception as e:
        log(f"MONITOR Claude invoke FAIL — {e}")


def _queue_monitor_retry(orig_kwargs, variant, retry_idx):
    """Queue a retry scan-now command with the given variant settings."""
    norad = orig_kwargs.get("_norad")
    name = orig_kwargs.get("_name") or orig_kwargs.get("label", "unknown")
    freq = orig_kwargs.get("freq") or orig_kwargs.get("freq_hz") or 137_100_000
    lna = orig_kwargs.get("lna", 16)
    vga = orig_kwargs.get("vga", 36)
    amp = orig_kwargs.get("amp", 1)
    duration_s = orig_kwargs.get("duration_s", 300)
    command = {
        "id": f"scan-retry-{norad or 'x'}-{int(time.time())}",
        "type": "scan_now",
        "queued_at": utc_now_iso(),
        "name": name,
        "norad": norad,
        "group": "radio",
        "profile": "meteor_lrpt_hackrf",
        "frequency_hz": int(float(freq)),
        "lna_gain": lna,
        "vga_gain": vga,
        "amp": amp,
        "duration_s": duration_s,
        "samplerate": variant["samplerate"],
        "iq_swap": variant["iq_swap"],
        "pipeline": variant["pipeline"],
        "dc_block": variant.get("dc_block", True),
        "_retry_idx": retry_idx,
        "source": "monitor_retry",
    }
    cmds = load_command_queue()
    cmds.append(command)
    write_command_queue(cmds)
    log(f"MONITOR retry {retry_idx + 1}/{len(LRPT_RETRY_VARIANTS)}: "
        f"iq_swap={variant['iq_swap']} samplerate={variant['samplerate']} "
        f"pipeline={variant['pipeline']} dc_block={variant.get('dc_block', True)}")
    scheduler_event(
        "capture.retry_queued",
        {
            "command_id": command["id"],
            "norad": norad,
            "name": name,
            "retry_idx": retry_idx,
            "variant": variant,
        },
        {
            "title": "SDR capture retry queued",
            "body": name,
            "data": {"command_id": command["id"], "norad": norad},
        },
    )


def _monitor_satdump(capdir, kwargs):
    """Background thread: check capture health at T+90s, kill/retry/escalate."""
    time.sleep(MONITOR_DELAY_S)
    if not os.path.exists(capdir + ".pid"):
        return  # capture already finished before we woke up
    try:
        raw = subprocess.check_output(
            ["python3", MONITOR_SCRIPT, capdir],
            text=True, stderr=subprocess.DEVNULL,
        )
        result = json.loads(raw)
    except subprocess.CalledProcessError as e:
        # exit code 1 means intervention taken — output still has JSON
        try:
            result = json.loads(e.output)
        except Exception:
            log(f"MONITOR parse FAIL {os.path.basename(capdir)}")
            return
    except Exception as e:
        log(f"MONITOR FAIL {os.path.basename(capdir)} — {e}")
        return

    status = result.get("status", "unknown")
    log(f"MONITOR {os.path.basename(capdir)} — {status}: {str(result.get('notes', ''))[:100]}")
    scheduler_event(
        "monitor.result",
        {
            "capture": os.path.basename(capdir),
            "capture_path": capdir,
            "status": status,
            "result": result,
        },
        None if status == "synced" else {
            "title": "SDR monitor needs attention",
            "body": f"{os.path.basename(capdir)}: {status}",
        },
    )

    if status == "synced":
        return  # healthy, nothing to do

    _ri = kwargs.get("_retry_idx")
    retry_idx = int(_ri) if _ri is not None else -1  # -1 so next_idx=0 picks variant[0]

    if result.get("killed_pid"):
        next_idx = retry_idx + 1
        if next_idx < len(LRPT_RETRY_VARIANTS):
            _queue_monitor_retry(kwargs, LRPT_RETRY_VARIANTS[next_idx], next_idx)
        else:
            log(f"MONITOR all {len(LRPT_RETRY_VARIANTS)} variants exhausted — escalating")
            _invoke_claude_monitor(capdir, result)
    elif status not in ("no_signal", "no_log", "synced"):
        # Monitor couldn't kill (pid gone) but something is wrong — escalate
        _invoke_claude_monitor(capdir, result)


def load_command_queue():
    if not os.path.exists(COMMANDS_PATH):
        return []
    try:
        with open(COMMANDS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        log(f"COMMAND READ FAIL — {e}")
        return []


def write_command_queue(commands):
    atomic_write_json(COMMANDS_PATH, commands)


def remove_command(command_id):
    commands = load_command_queue()
    next_commands = [cmd for cmd in commands if str(cmd.get("id")) != str(command_id)]
    if len(next_commands) != len(commands):
        write_command_queue(next_commands)


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
        lna = int(rule.get("lna_gain", 32))
        vga = int(rule.get("vga_gain", 48))
        amp = int(rule.get("amp", 1))
        if float(p.get("max_el", 0)) >= 60:
            vga = max(0, vga - 12)
        aos_local = fire_time.replace(":", "")
        duration_s = max(1, int(p["duration_s"]) - start_offset_s + end_offset_s)
        freq = float(rule["frequency_hz"])
        label = f"{rule.get('name', p['name'])} {float(p['max_el']):.1f}deg"
        slug = safe_name(rule.get("name") or p["name"])
        meta = dict(
            _norad=int(rule["norad"]),
            _name=rule.get("name") or p["name"],
            _profile=rule.get("profile", "raw_iq_hackrf"),
            _source="rule",
            _max_el=float(p.get("max_el", 0)),
        )
        if rule.get("profile") in ("meteor_lrpt_hackrf", "satdump_hackrf"):
            default_pipeline = "meteor_m2-x_lrpt" if rule.get("profile") == "meteor_lrpt_hackrf" else "orbcomm_stx_auto_plotter"
            suffix = "LRPT" if rule.get("profile") == "meteor_lrpt_hackrf" else "SDR"
            jobs.append((
                fire_time,
                "satdump",
                dict(
                    capdir=f"{NOAADIR}/{slug}_{aos_local}",
                    duration_s=duration_s,
                    freq=freq,
                    lna=lna,
                    vga=vga,
                    amp=amp,
                    label=f"{label} {suffix}",
                    samplerate=str(rule.get("samplerate", LRPT_RETRY_VARIANTS[0]["samplerate"])),
                    iq_swap=bool(rule.get("iq_swap", LRPT_RETRY_VARIANTS[0]["iq_swap"])),
                    dc_block=bool(rule.get("dc_block", LRPT_RETRY_VARIANTS[0].get("dc_block", True))),
                    pipeline=str(rule.get("pipeline", default_pipeline)),
                    _retry_idx=0,
                    **meta,
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
                    amp=amp,
                    outfile=f"{CAPDIR}/{slug}_{aos_local}.iq",
                    label=f"{label} IQ",
                    **meta,
                ),
            ))
    return jobs


def build_scan_now_job(command):
    if command.get("type") != "scan_now":
        return None
    command_id = str(command.get("id") or uuid.uuid4())
    frequency_hz = int(float(command["frequency_hz"]))
    duration_s = max(1, int(command.get("duration_s", 300)))
    lna = int(command.get("lna_gain", 32))
    vga = int(command.get("vga_gain", 48))
    amp = int(command.get("amp", 1))
    profile = str(command.get("profile") or "raw_iq_hackrf")
    name = str(command.get("name") or f"NORAD {command.get('norad', 'unknown')}")
    label = f"{name} scan now"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = safe_name(name)
    samplerate = str(command.get("samplerate") or LRPT_RETRY_VARIANTS[0]["samplerate"])
    iq_swap = bool(command.get("iq_swap", LRPT_RETRY_VARIANTS[0]["iq_swap"]))
    dc_block = bool(command.get("dc_block", LRPT_RETRY_VARIANTS[0].get("dc_block", True)))
    default_pipeline = "meteor_m2-x_lrpt" if profile == "meteor_lrpt_hackrf" else "orbcomm_stx_auto_plotter"
    pipeline = str(command.get("pipeline") or default_pipeline)
    _ri = command.get("_retry_idx")
    retry_idx = int(_ri) if _ri is not None else -1  # -1 so first retry picks variant[0]
    common = {
        "_command_id": command_id,
        "_queued_at": command.get("queued_at"),
        "_norad": int(command["norad"]) if command.get("norad") else None,
        "_name": name,
        "_profile": profile,
        "_source": str(command.get("source", "scan_now")),
        "_retry_idx": retry_idx,
        "duration_s": duration_s,
        "lna": lna,
        "vga": vga,
        "amp": amp,
        "label": label,
    }
    if profile in ("meteor_lrpt_hackrf", "satdump_hackrf"):
        return (
            datetime.datetime.now().astimezone(),
            "satdump",
            {
                **common,
                "capdir": f"{NOAADIR}/{slug}_{stamp}",
                "freq": frequency_hz,
                "samplerate": samplerate,
                "iq_swap": iq_swap,
                "pipeline": pipeline,
                "dc_block": dc_block,
            },
        )
    return (
        datetime.datetime.now().astimezone(),
        "iq",
        {
            **common,
            "outfile": f"{CAPDIR}/{slug}_{stamp}.iq",
            "freq_hz": frequency_hz,
        },
    )


def command_jobs():
    jobs = []
    for command in load_command_queue():
        try:
            job = build_scan_now_job(command)
            if job:
                jobs.append(job)
        except Exception as e:
            log(f"COMMAND BUILD FAIL {command.get('id', '?')} — {e}")
    return jobs

def optional_rule_jobs(log_loaded=True):
    jobs = []
    for rule in load_scheduler_rules():
        if not rule.get("enabled", True):
            continue
        if rule.get("type") != "satellite_recurring":
            continue
        try:
            rule_jobs = build_rule_jobs(rule)
            jobs.extend(rule_jobs)
            if log_loaded:
                log(f"Loaded {len(rule_jobs)} jobs from rule {rule.get('id')}")
        except Exception as e:
            log(f"RULE PREDICT FAIL {rule.get('id', '?')} — no jobs added: {e}")
    return jobs

def job_fire_dt(fire_time):
    if isinstance(fire_time, datetime.datetime):
        return fire_time.astimezone()
    now = datetime.datetime.now().astimezone()
    h, m = map(int, str(fire_time).split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    # Only wrap to tomorrow if we're more than 90s past the fire minute.
    # Without this, a poll landing at HH:MM:00.xxx would wrongly push the
    # job to the next day because target (HH:MM:00.000) <= now.
    if target + datetime.timedelta(seconds=90) < now:
        target += datetime.timedelta(days=1)
    return target

def job_time_label(fire_time):
    return job_fire_dt(fire_time).strftime("%H:%M")

def job_key(job):
    fire_time, ptype, kwargs = job
    return (job_fire_dt(fire_time).isoformat(timespec="minutes"), ptype, kwargs.get("label", ""))

def collect_jobs(log_loaded=False):
    jobs = command_jobs() + MANUAL_JOBS + optional_rule_jobs(log_loaded=log_loaded)
    jobs.sort(key=lambda job: job_fire_dt(job[0]))
    return jobs

def jobs_signature(jobs):
    return tuple((job_fire_dt(j[0]).isoformat(timespec="minutes"), j[1], j[2].get("label", "")) for j in jobs)

def run_job(ptype, kwargs):
    run_kwargs = dict(kwargs)
    for key in ("_command_id", "_queued_at", "_norad", "_name", "_profile", "_source", "_max_el", "_retry_idx"):
        run_kwargs.pop(key, None)
    if ptype == "satdump":
        capdir = run_kwargs.get("capdir")
        if capdir and os.path.exists(MONITOR_SCRIPT):
            t = threading.Thread(target=_monitor_satdump, args=(capdir, kwargs), daemon=True)
            t.start()
    if ptype == "iq":
        outfile = hackrf_capture(**run_kwargs)
        if outfile:
            analyze_150mhz(outfile, run_kwargs["label"], run_kwargs["freq_hz"])
            norad = kwargs.get("_norad")
            if norad == 27607:  # SO-50 — FM demod + Whisper transcript
                script = os.path.join(REPO_DIR, "so50_process.py")
                if os.path.exists(script):
                    log(f"SO-50 post-process: {os.path.basename(outfile)}")
                    threading.Thread(
                        target=lambda: subprocess.run(
                            ["python3", script, outfile],
                            capture_output=False,
                        ),
                        daemon=True,
                    ).start()
        return {"ok": bool(outfile), "output": outfile}
    elif ptype == "satdump":
        cadu_bytes = satdump_capture(**run_kwargs)
        return {"ok": cadu_bytes > 0, "cadu_bytes": cadu_bytes}
    else:
        log(f"UNKNOWN JOB TYPE {ptype} — {run_kwargs}")
        return {"ok": False, "error": f"unknown job type: {ptype}"}


def status_job_payload(fire_time, ptype, kwargs):
    return {
        "type": ptype,
        "label": kwargs.get("label", ""),
        "fire_time": job_fire_dt(fire_time).isoformat(),
        "command_id": kwargs.get("_command_id"),
        "queued_at": kwargs.get("_queued_at"),
        "frequency_hz": kwargs.get("freq_hz") or kwargs.get("freq"),
        "duration_s": kwargs.get("duration_s"),
        "lna_gain": kwargs.get("lna"),
        "vga_gain": kwargs.get("vga"),
        "amp": kwargs.get("amp"),
        "output": kwargs.get("outfile") or kwargs.get("capdir"),
    }

def scheduler_loop():
    completed = set()
    jobs = []
    last_sig = None
    last_next = None
    last_status_update = 0.0
    next_reload = 0.0
    log("SDR scheduler running — dynamic rule reload enabled")
    write_scheduler_status("idle", message="scheduler started")
    scheduler_event("scheduler.started", {"pid": os.getpid()})

    while True:
        now_ts = time.time()
        now = datetime.datetime.now().astimezone()
        if now_ts >= next_reload:
            jobs = collect_jobs(log_loaded=False)
            sig = jobs_signature(jobs)
            if sig != last_sig:
                rule_jobs = max(0, len(jobs) - len(MANUAL_JOBS))
                log(f"Schedule loaded — {len(MANUAL_JOBS)} manual jobs, {rule_jobs} rule jobs")
                scheduler_event(
                    "schedule.changed",
                    {
                        "manual_jobs": len(MANUAL_JOBS),
                        "dynamic_jobs": rule_jobs,
                        "total_jobs": len(jobs),
                    },
                )
                last_sig = sig
                last_next = None
            next_reload = now_ts + RELOAD_INTERVAL_S

        due = [job for job in jobs if job_key(job) not in completed and job_fire_dt(job[0]) <= now]
        if due:
            job = sorted(due, key=lambda item: job_fire_dt(item[0]))[0]
            completed.add(job_key(job))
            fire_time, ptype, kwargs = job
            command_id = kwargs.get("_command_id")
            if command_id:
                remove_command(command_id)
            write_scheduler_status("running", status_job_payload(fire_time, ptype, kwargs), "capture running")
            log(f"Running: {kwargs['label']} scheduled for {job_time_label(fire_time)}")
            started_at = utc_now_iso()
            scheduler_event(
                "capture.started",
                {
                    "job": status_job_payload(fire_time, ptype, kwargs),
                    "norad": kwargs.get("_norad"),
                    "name": kwargs.get("_name") or kwargs.get("label", ""),
                    "profile": kwargs.get("_profile") or ptype,
                    "source": kwargs.get("_source", "manual"),
                    "started_at": started_at,
                },
                {
                    "title": "SDR capture started",
                    "body": kwargs.get("_name") or kwargs.get("label", ""),
                },
            )
            run_result = None
            run_error = None
            try:
                run_result = run_job(ptype, kwargs)
            except Exception as e:
                run_error = str(e)
                log(f"JOB FAIL {kwargs.get('label', '')} — {e}")
            finally:
                ended_at = utc_now_iso()
                failed = bool(run_error) or not bool(run_result and run_result.get("ok"))
                write_scheduler_status(
                    "idle",
                    message="last capture failed" if failed else "last capture finished",
                )
                output = kwargs.get("outfile") or kwargs.get("capdir")
                size_bytes = 0
                cadu_bytes = None
                if output and os.path.exists(output):
                    if os.path.isdir(output):
                        cadu = os.path.join(output, "meteor_m2-x_lrpt.cadu")
                        cadu_bytes = os.path.getsize(cadu) if os.path.exists(cadu) else 0
                        size_bytes = sum(
                            os.path.getsize(os.path.join(dp, fn))
                            for dp, _, fns in os.walk(output) for fn in fns
                        )
                    else:
                        size_bytes = os.path.getsize(output)
                report_path = os.path.join(output, "diagnostic_report.md") if output else None
                record = {
                    "id": str(uuid.uuid4()),
                    "norad": kwargs.get("_norad"),
                    "name": kwargs.get("_name") or kwargs.get("label", ""),
                    "profile": kwargs.get("_profile") or ptype,
                    "source": kwargs.get("_source", "manual"),
                    "frequency_hz": kwargs.get("freq_hz") or kwargs.get("freq"),
                    "lna_gain": kwargs.get("lna"),
                    "vga_gain": kwargs.get("vga"),
                    "amp": kwargs.get("amp"),
                    "samplerate": kwargs.get("samplerate"),
                    "iq_swap": kwargs.get("iq_swap"),
                    "pipeline": kwargs.get("pipeline"),
                    "max_el": kwargs.get("_max_el"),
                    "label": kwargs.get("label", ""),
                    "command_id": kwargs.get("_command_id"),
                    "retry_idx": kwargs.get("_retry_idx"),
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "output": output,
                    "output_type": "directory" if (output and os.path.isdir(output)) else "file",
                    "size_bytes": size_bytes,
                    "cadu_bytes": cadu_bytes,
                    "report_path": report_path if (report_path and os.path.exists(report_path)) else None,
                    "success": bool(run_result and run_result.get("ok")) and not run_error,
                    "error": run_error or (run_result or {}).get("error"),
                }
                try:
                    append_capture_record(record)
                except Exception as e:
                    log(f"HISTORY WRITE FAIL — {e}")
                scheduler_event(
                    "capture.failed" if failed else "capture.completed",
                    {"capture": record, "result": run_result or {}},
                    {
                        "title": "SDR capture failed" if failed else "SDR capture completed",
                        "body": record["name"],
                        "data": {"capture_id": record["id"], "norad": record["norad"]},
                    },
                )
            next_reload = 0.0
            continue

        future = [job for job in jobs if job_key(job) not in completed and job_fire_dt(job[0]) > now]
        if future:
            job = sorted(future, key=lambda item: job_fire_dt(item[0]))[0]
            fire_dt = job_fire_dt(job[0])
            wait = max(0, (fire_dt - now).total_seconds())
            next_id = job_key(job)
            if next_id != last_next:
                log(f"Next: {job[2]['label']} at {fire_dt.strftime('%H:%M')} (in {wait:.0f}s)")
                write_scheduler_status("idle", status_job_payload(job[0], job[1], job[2]), "next capture pending")
                last_status_update = now_ts
                last_next = next_id
            elif now_ts - last_status_update >= 30:
                write_scheduler_status("idle", status_job_payload(job[0], job[1], job[2]), "next capture pending")
                last_status_update = now_ts
            sleep_s = min(POLL_INTERVAL_S, wait, max(1, next_reload - now_ts))
        else:
            if last_next is not None:
                log("No scheduled jobs pending.")
                write_scheduler_status("idle", message="no scheduled jobs pending")
                last_status_update = now_ts
                last_next = None
            elif now_ts - last_status_update >= 30:
                write_scheduler_status("idle", message="no scheduled jobs pending")
                last_status_update = now_ts
            sleep_s = min(POLL_INTERVAL_S, max(1, next_reload - now_ts))
        time.sleep(max(1, sleep_s))

# ── SCHEDULE ─────────────────────────────────────────────────────────────────
if __name__ != '__main__':
    raise ImportError("sdr_scheduler is not importable — run it directly")

MANUAL_JOBS = [
    # Agent/user-created radio jobs belong here. They do not need to be
    # satellites and do not depend on TLEs, CelesTrak, the map, or serve.py.
]

scheduler_loop()
