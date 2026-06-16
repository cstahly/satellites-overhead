#!/usr/bin/env python3
"""SDR pass scheduler. Run once, handles everything, logs everything."""
import json, subprocess, time, os, datetime, threading, uuid, sys, glob

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
MIN_PARTIAL_CAPTURE_S = 60

if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from schedule_windows import priority_score, trim_overlapping_windows
from sdr_runtime import emit_event

# Retry variants ordered by P(success). First entry is the initial capture default.
# dc_block=True is required — without it the PLL false-locks on HackRF LO leakage at 137.1 MHz.
# nrzm=False (meteor_m2-4_lrpt_nrzl) is the primary hypothesis: June 4 confirms nrzm=True (variants
# 0 and 1) gives NOSYNC on every pass regardless of iq_swap. NRZ-L variants are now front-loaded.
# rs_usecheck=False variant is a diagnostic: frames through even if RS fails, reveals framing state.
# dc_block=False is last resort — known to produce false Viterbi lock, but retained if all else fails.
# NRZ-M (meteor_m2-x_lrpt) is PROVEN correct for both M2-3 and M2-4 — recovered a
# full 12-image M2-4 pass from a "0 CADU" capture on 2026-06-14 (the rule had been
# wrongly set to nrzl: Viterbi SYNCED but Deframer NOSYNC = coding mismatch). nrzm
# variants first; nrzl kept only as a last-ditch fallback.
LRPT_RETRY_VARIANTS = [
    {"iq_swap": True,  "samplerate": "2e6", "pipeline": "meteor_m2-x_lrpt",            "dc_block": True},   # nrzm+iq_swap (PROVEN — primary)
    {"iq_swap": True,  "samplerate": "2e6", "pipeline": "meteor_m2-x_lrpt",            "dc_block": False},  # nrzm+iq_swap, no dc_block (most CADU on the 06-14 recovery)
    {"iq_swap": False, "samplerate": "2e6", "pipeline": "meteor_m2-x_lrpt",            "dc_block": True},   # nrzm+no_iq_swap
    {"iq_swap": True,  "samplerate": "2e6", "pipeline": "meteor_m2-4_lrpt_nrzl",       "dc_block": True},   # nrzl fallback (was wrongly primary)
    {"iq_swap": False, "samplerate": "2e6", "pipeline": "meteor_m2-4_lrpt_nrzl",       "dc_block": True},   # nrzl+no_iq_swap fallback
]

# satdump pipelines that REQUIRE live decode (their demod throws if fed a file).
# ORBCOMM's auto STX demod is live-only — must decode straight off the RTL-SDR,
# not via the capture-IQ-then-offline path. (Found 2026-06-14: every ORBCOMM pass
# was 0 CADU because the offline decode threw "live-only".)
LIVE_ONLY_PIPELINES = {"orbcomm_stx_auto_plotter", "orbcomm_stx_auto"}

EC2_METEOR_USER = "ec2-user"
EC2_METEOR_HOST = "sadbabyrabbit.com"
EC2_METEOR_KEY = os.path.expanduser("~/.ssh/sadbabyrabbit.pem")
EC2_METEOR_REMOTE_DIR = "/var/www/meteor"
METEOR_MANIFEST_PATH = os.path.join(HOME, "meteor_push_manifest.json")
EMAIL_TO = "cstahly+sat@gmail.com"


def make_meteor_web_image(image_path, out_path):
    """Render a web-sized WebP (~1MB vs 4-14MB raw PNG) for the gallery carousel."""
    try:
        subprocess.run(
            ["magick", image_path, "-resize", "1600x1600>", "-quality", "82", out_path],
            check=True, timeout=120,
        )
        return True
    except Exception as exc:
        log(f"PUSH WARN — web image conversion failed ({exc}); pushing full PNG only")
        return False


def push_meteor_image(capdir, name, max_el, captured_at_iso):
    """Push a Meteor MSA image to sadbabyrabbit.com/meteor/ and update index.json."""
    # Prefer the MSA corrected+map image, but only if it actually has imagery.
    # When Meteor isn't transmitting the IR channel, MSA renders blank (~10KB)
    # while the visible AVHRR false-color composite is full — fall back to that so
    # the gallery never pushes a blank. Objective size check only; no editorial
    # choice (gradient/crossfade composites stay a manual, human decision).
    _msu = os.path.join(capdir, "MSU-MR")
    _msa = os.path.join(_msu, "msu_mr_rgb_MSA_corrected_map.png")
    _avhrr = os.path.join(_msu, "msu_mr_rgb_AVHRR_3a21_False_Color_corrected.png")
    _BLANK = 60000  # blank composites ~10KB; real imagery is 100KB+
    if os.path.exists(_msa) and os.path.getsize(_msa) > _BLANK:
        image_path = _msa
    elif os.path.exists(_avhrr) and os.path.getsize(_avhrr) > _BLANK:
        image_path = _avhrr
        log(f"PUSH — MSA blank, using AVHRR false-color for {os.path.basename(capdir)}")
    else:
        log(f"PUSH SKIP — no usable composite in {capdir}/MSU-MR/")
        return

    # Meteor LRPT renders upside-down on ASCENDING (northbound) passes. Re-predict
    # the pass direction from its start time and rotate 180° so the gallery is
    # always north-up (verified 2026-06-16: every user-flagged-inverted pass was
    # ascending; descending passes were already correct). Rotate into a temp so the
    # operation is idempotent and never mutates the satdump source.
    _norad = {"METEOR-M2 3": 57166, "METEOR-M2 4": 59051}.get(name)
    if _norad:
        try:
            _raw = subprocess.check_output(
                ["python3", PREDICTOR, "--lat", str(LAT), "--lon", str(LON), "--alt-m", str(ALT_M),
                 "--hours", "3", "--min-el", "5", "--norad", str(_norad),
                 "--start", captured_at_iso, "--limit", "1", "--track-step-s", "120"],
                text=True, timeout=30, stderr=subprocess.DEVNULL)
            _trk = json.loads(_raw)[0]["track"]
            if _trk[-1]["sub_lat"] > _trk[0]["sub_lat"]:   # ascending → upside down → flip
                _rot = os.path.join(_msu, "_push_oriented.png")
                subprocess.run(["magick", image_path, "-rotate", "180", _rot], check=True, timeout=60)
                image_path = _rot
                log(f"PUSH — ascending pass, rotated 180° for {os.path.basename(capdir)}")
        except Exception as _e:
            log(f"PUSH — orient check failed ({_e}); pushing as-is")

    ssh_opts = ["-o", "StrictHostKeyChecking=no", "-q", "-i", EC2_METEOR_KEY]
    scp_opts = ["-o", "StrictHostKeyChecking=no", "-i", EC2_METEOR_KEY]

    # e.g. "2026-06-08T16:30:00Z" → "20260608T1630"
    ts = captured_at_iso.replace("-", "").replace(":", "").replace("Z", "")[:13]
    remote_img = f"{ts}.png"
    web_img = f"{ts}_web.webp"
    web_path = os.path.join(capdir, "MSU-MR", "msa_web.webp")
    has_web = make_meteor_web_image(image_path, web_path)

    try:
        subprocess.run(
            ["ssh"] + ssh_opts + [f"{EC2_METEOR_USER}@{EC2_METEOR_HOST}",
             f"mkdir -p {EC2_METEOR_REMOTE_DIR}"],
            check=True, timeout=30,
        )
        subprocess.run(
            ["scp"] + scp_opts + [image_path,
             f"{EC2_METEOR_USER}@{EC2_METEOR_HOST}:{EC2_METEOR_REMOTE_DIR}/{remote_img}"],
            check=True, timeout=120,
        )
        if has_web:
            subprocess.run(
                ["scp"] + scp_opts + [web_path,
                 f"{EC2_METEOR_USER}@{EC2_METEOR_HOST}:{EC2_METEOR_REMOTE_DIR}/{web_img}"],
                check=True, timeout=60,
            )

        # Update local manifest
        manifest = []
        if os.path.exists(METEOR_MANIFEST_PATH):
            try:
                with open(METEOR_MANIFEST_PATH) as f:
                    manifest = json.load(f)
                if not isinstance(manifest, list):
                    manifest = []
            except Exception:
                manifest = []
        _pass_id = os.path.basename(capdir)
        manifest = [e for e in manifest
                    if e.get("filename") != remote_img and e.get("pass_id") != _pass_id]
        entry = {
            "filename": remote_img,
            "name": name,
            "captured_at": captured_at_iso,
            "max_el": round(float(max_el or 0), 1),
            "pass_id": _pass_id,
        }
        if has_web:
            entry["web"] = web_img
        manifest.append(entry)
        manifest.sort(key=lambda e: e.get("captured_at", ""), reverse=True)
        atomic_write_json(METEOR_MANIFEST_PATH, manifest)

        # Push updated index to EC2 via temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            json.dump(manifest, tf, indent=2)
            tf_path = tf.name
        try:
            subprocess.run(
                ["scp"] + scp_opts + [tf_path,
                 f"{EC2_METEOR_USER}@{EC2_METEOR_HOST}:{EC2_METEOR_REMOTE_DIR}/index.json"],
                check=True, timeout=30,
            )
            subprocess.run(
                ["ssh"] + ssh_opts + [f"{EC2_METEOR_USER}@{EC2_METEOR_HOST}",
                 f"chmod 644 {EC2_METEOR_REMOTE_DIR}/index.json"],
                check=True, timeout=10,
            )
        finally:
            os.unlink(tf_path)

        log(f"PUSH OK — {remote_img} → sadbabyrabbit.com/meteor/ ({len(manifest)} total)")
        scheduler_event(
            "meteor.image_pushed",
            {"filename": remote_img, "name": name, "captured_at": captured_at_iso,
             "total": len(manifest)},
            {"title": "Meteor image live on site", "body": f"{name} — {max_el:.1f}°"},
        )
    except Exception as e:
        log(f"PUSH FAIL — {e}")


def backfill_meteor_images():
    """Push any existing MSA images not in the manifest yet. Runs once at startup."""
    import glob as _glob
    pattern = os.path.join(NOAADIR, "*/MSU-MR/msu_mr_rgb_MSA_corrected_map.png")
    candidates = sorted(_glob.glob(pattern), key=os.path.getmtime)
    if not candidates:
        return

    history_by_capdir = {}
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH) as f:
                for r in json.load(f):
                    if r.get("output"):
                        history_by_capdir[r["output"]] = r
        except Exception:
            pass

    existing_pass_ids = set()
    if os.path.exists(METEOR_MANIFEST_PATH):
        try:
            with open(METEOR_MANIFEST_PATH) as f:
                for e in json.load(f):
                    existing_pass_ids.add(e.get("pass_id", ""))
        except Exception:
            pass

    for img_path in candidates:
        capdir = os.path.dirname(os.path.dirname(img_path))
        if os.path.basename(capdir) in existing_pass_ids:
            continue
        _lookup = capdir.removesuffix("_decode")
        rec = history_by_capdir.get(capdir) or history_by_capdir.get(_lookup, {})
        name = rec.get("name") or "METEOR-M2 3"
        max_el = rec.get("max_el") or 0.0
        captured_at = rec.get("started_at")
        if not captured_at:
            mtime = os.path.getmtime(img_path)
            captured_at = datetime.datetime.fromtimestamp(
                mtime, datetime.timezone.utc
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        ts = captured_at.replace("-", "").replace(":", "").replace("Z", "")[:13]
        log(f"BACKFILL {os.path.basename(capdir)} → {ts}.png")
        push_meteor_image(capdir, name, max_el, captured_at)


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def send_pass_email(subject, body, attach=None):
    try:
        cmd = ["mail", "-s", subject]
        attaches = attach if isinstance(attach, (list, tuple)) else [attach]
        for a in attaches:
            if a and os.path.exists(a):
                cmd += ["-A", a]
        cmd.append(EMAIL_TO)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        proc.communicate(input=body.encode(), timeout=30)
        log(f"EMAIL SENT — {subject}")
    except Exception as e:
        log(f"EMAIL FAIL — {e}")


def chain_health(iqfile, freq_hz, samplerate):
    """Classify front-end state from raw IQ: healthy, no antenna, or dead LNA.

    Calibrated 2026-06-12 against the SAWbird+ chain at gain 40 / 2 Msps:
      antenna up + LNA powered : ~31 dB mean power, 137.680 MHz local birdie ~10 dB
      antenna off, LNA powered : ~14 dB, birdie gone
      LNA unpowered (blocked)  : ~1 dB
    Recalibrate thresholds if the LNA or gain changes (e.g. LaNA swap).
    """
    try:
        import numpy as np
        raw = np.memmap(iqfile, dtype=np.uint8, mode="r")
        n = min(len(raw) // 2, 40_000_000)
        if n < 1_000_000:
            return None
        ch = raw[: n * 2].astype(np.float32) - 127.5
        iq = ch[0::2] + 1j * ch[1::2]
        iq -= iq.mean()
        power = float(10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-9))
        birdie = None
        off = 137_679_700 - int(freq_hz)   # local always-on carrier, arrives via antenna
        if abs(off) < 0.45 * samplerate:
            nfft = 65536
            sp = np.zeros(nfft)
            win = np.hanning(nfft)
            for k in range(20):
                seg = iq[k * nfft:(k + 1) * nfft]
                if len(seg) < nfft:
                    break
                sp += np.abs(np.fft.fftshift(np.fft.fft(seg * win)))
            fr = np.fft.fftshift(np.fft.fftfreq(nfft, 1.0 / samplerate))
            m = np.abs(fr - off) < 5000
            if m.any():
                birdie = float(20 * np.log10(sp[m].max() / np.median(sp)))
        # Power is the reliable indicator. The 137.68 birdie is an unintentional
        # LOCAL emitter that fades in/out on its own (9.9 dB one pass, 2.2 dB the
        # next) — so a weak birdie is NOT evidence of an antenna fault and must
        # not flip the verdict. It's reported as a note only. (2026-06-14: dropped
        # the birdie<6 trigger after it false-alarmed a healthy 31 dB pass.)
        if power < 7:
            verdict = "LNA DEAD/UNPOWERED"
        elif power < 22:
            verdict = "NO ANTENNA?"
        else:
            verdict = "HEALTHY"
        if birdie is not None:
            b_str = f", birdie {birdie:.1f} dB" + (" (local emitter quiet)" if birdie < 6 else "")
        else:
            b_str = ""
        return f"{verdict} (power {power:.1f} dB{b_str})"
    except Exception as e:
        return f"check failed: {e}"


def make_email_thumb(src_png, max_px=800):
    """Downscale a waterfall PNG to a reasonably-sized JPEG for email attachment."""
    try:
        from PIL import Image
        out = os.path.splitext(src_png)[0] + "_email.jpg"
        im = Image.open(src_png).convert("RGB")
        im.thumbnail((max_px, max_px))
        im.save(out, "JPEG", quality=82, optimize=True)
        return out
    except Exception as e:
        log(f"THUMB FAIL {src_png} — {e}")
        return None


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

RTL_SDR_LOCK = os.path.join(HOME, ".rtlsdr.lock")

def _rtlsdr_usb_reset():
    """Find RTL-SDR in /sys and trigger a USB port reset. Returns True if reset attempted."""
    try:
        import glob
        # RTL2832U vendor/product IDs
        for vid_pid in ("0bda:2838", "0bda:2832", "0bda:2837"):
            vid, pid = vid_pid.split(":")
            matches = glob.glob(f"/sys/bus/usb/devices/*/idVendor")
            for vpath in matches:
                base = os.path.dirname(vpath)
                try:
                    v = open(vpath).read().strip()
                    p = open(os.path.join(base, "idProduct")).read().strip()
                    if v == vid and p == pid:
                        auth = os.path.join(base, "authorized")
                        open(auth, "w").write("0")
                        time.sleep(0.5)
                        open(auth, "w").write("1")
                        time.sleep(2)
                        log(f"RTL-SDR USB reset triggered at {base}")
                        return True
                except Exception:
                    continue
        log("RTL-SDR USB reset: device not found in /sys")
        return False
    except Exception as e:
        log(f"RTL-SDR USB reset failed: {e}")
        return False


def rtl_sdr_capture(freq_hz, outfile, duration_s, gain=40, label="", bias_tee=False):
    logfile = outfile + ".log"
    log(f"START {label} — rtl_sdr {freq_hz/1e6:.3f} MHz gain={gain} → {outfile} (tail -f {logfile})")
    cmd = ["rtl_sdr", "-f", str(freq_hz), "-s", "2000000", "-g", str(gain), outfile]

    # Kill any orphaned rtl_sdr processes that may still hold the USB interface
    r = subprocess.run(["pgrep", "-x", "rtl_sdr"], capture_output=True, text=True)
    for pid_s in r.stdout.split():
        try:
            os.kill(int(pid_s), 9)
            log(f"Killed orphaned rtl_sdr PID {pid_s}")
            time.sleep(0.5)
        except ProcessLookupError:
            pass

    # Acquire per-process lock so concurrent scheduler instances can't both open the device
    try:
        lock_fd = open(RTL_SDR_LOCK, "w")
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        log(f"SKIP  {label} — RTL-SDR lock held by another process")
        return None

    if bias_tee:
        subprocess.run(["rtl_biast", "-d", "0", "-b", "1"],
                       capture_output=True)

    try:
        for attempt in range(2):
            with open(logfile, "w" if attempt == 0 else "a") as lf:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=lf)
            time.sleep(1.5)
            if proc.poll() is not None:
                # Process already exited — check for USB claim error
                err = open(logfile).read() if os.path.exists(logfile) else ""
                if "usb_claim_interface" in err or "No supported devices" in err or "Failed to open" in err:
                    if attempt == 0:
                        log(f"RTL-SDR claim failed — attempting USB reset (attempt {attempt+1})")
                        _rtlsdr_usb_reset()
                        continue
                log(f"FAIL  {label} — rtl_sdr exited early (see {logfile})")
                return None
            try:
                proc.wait(timeout=duration_s)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=5)
            break
        size = os.path.getsize(outfile) if os.path.exists(outfile) else 0
        log(f"DONE  {label} — {size/1e6:.0f} MB captured")
        return outfile if size > 0 else None
    except Exception as e:
        log(f"FAIL  {label} — {e}")
        return None
    finally:
        if bias_tee:
            subprocess.run(["rtl_biast", "-d", "0", "-b", "0"],
                           capture_output=True)
        try:
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass


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
                    dc_block=True, source="hackrf", bias_tee=False):
    """Live satdump decode straight off the SDR (HackRF, or RTL-SDR for live-only
    pipelines like ORBCOMM auto). No IQ is saved — satdump decodes in real time."""
    logfile = capdir + ".log"
    pidfile = capdir + ".pid"
    # Convert samplerate to integer — satdump rejects scientific notation strings
    sr_int = int(float(samplerate)) if samplerate else 1_000_000
    flags = ("--iq_swap " if iq_swap else "") + f"sr={sr_int}" + (" dc_block" if dc_block else "")
    log(f"START {label} — satdump/{source} live {pipeline} {freq/1e6:.1f} MHz [{flags}] → {capdir} (tail -f {logfile})")
    cmd = ["satdump", "live", pipeline, capdir,
           "--source", source, "--samplerate", str(sr_int),
           "--frequency", str(int(float(freq))),
           "--timeout", str(duration_s)]
    if source == "rtlsdr":
        cmd += ["--gain", str(lna)]   # lna_gain repurposed as single RTL-SDR gain
        if bias_tee:
            cmd.append("--bias")      # power the SAWbird inline (137 MHz LRPT/ORBCOMM)
    else:
        cmd += ["--lna_gain", str(lna), "--vga_gain", str(vga), "--amp", str(amp)]
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
        # Meteor makes .cadu; ORBCOMM makes .frm. Count whichever the pipeline produced.
        prod = [os.path.join(dp, fn) for dp, _, fns in os.walk(capdir)
                for fn in fns if fn.endswith((".cadu", ".frm"))]
        size = max((os.path.getsize(p) for p in prod), default=0)
        if size > 0:
            log(f"DONE  {label} — {size} bytes decoded ({len(prod)} product file(s))")
        else:
            log(f"DONE  {label} — 0 bytes — no lock — check {logfile}")
        return size
    except Exception as e:
        log(f"FAIL  {label} — {e}")
        return 0
    finally:
        try:
            os.unlink(pidfile)
        except FileNotFoundError:
            pass
        if source == "rtlsdr" and bias_tee:
            # ensure the bias-tee is off after the live decode (satdump --bias may leave it on)
            subprocess.run(["rtl_biast", "-d", "0", "-b", "0"], capture_output=True)

_SATDUMP_SETTINGS = os.path.expanduser("~/.config/satdump/settings.json")
_SATDUMP_TLES     = os.path.expanduser("~/.config/satdump/satdump_tles.txt")
_SCHEDULER_TLE_CACHE = os.path.join(HOME, "src", "satellites-overhead", ".tlecache", "active.tle")

# satnogs 3le is the working source (2026-06-14): CelesTrak is unreachable from
# this box, ivanstanojevic now caps page-size at 100 + IP-blocks bursts, and the
# old satnogs ?format=tle&page_size=N endpoint 404s. ?format=3le returns the full
# catalog with names. This MERGES into both the satdump cache AND .tlecache/active.tle
# (the predictor's source — normally maintained by serve.py via CelesTrak, which
# is dead), so pass timing stays fresh. Without this the TLEs silently went 7+
# days stale and pass predictions drifted.
_TLE_SOURCE = "https://db.satnogs.org/api/tle/?format=3le"

def _parse_3le(text):
    """Parse 3LE/TLE text into {norad: (name, line1, line2)}."""
    out = {}
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("1 ") and l[2:7].strip().isdigit() and i + 1 < len(lines):
            l2 = lines[i + 1]
            if not l2.startswith("2 "):
                continue
            name = lines[i - 1] if i > 0 else l[2:7]
            if name.startswith("0 "):
                name = name[2:]
            out[int(l[2:7])] = (name.strip(), l, l2)
    return out

def _merge_tles(path, fresh):
    """Replace TLE lines for NORADs in `fresh`, keep everything else."""
    lines = open(path, errors="ignore").read().splitlines() if os.path.exists(path) else []
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("1 ") and l[2:7].strip().isdigit() and int(l[2:7]) in fresh and i + 1 < len(lines):
            n = int(l[2:7]); out += [fresh[n][1], fresh[n][2]]; i += 2
        else:
            out.append(l); i += 1
    seen = {int(l[2:7]) for l in out if l.startswith("1 ") and l[2:7].strip().isdigit()}
    for n, (nm, l1, l2) in fresh.items():
        if n not in seen:
            out += [nm, l1, l2]
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")

# satnogs 3le omits ORBCOMM, and CelesTrak (full catalog) is unreachable from this
# box, so ORBCOMM TLEs silently go 10+ days stale -> pass-time predictions drift by
# tens of minutes -> phantom passes / duplicate captures / 0-packet failure emails.
# tle.ivanstanojevic.me IS reachable and per-NORAD queries dodge its page-size cap,
# but it IP-blocks bursts. So we top up ONLY the enabled sats satnogs can't supply,
# at most once / 12h per NORAD (purely time-gated — NOT epoch-gated, since a source
# whose TLE never advances would otherwise be re-fetched forever). The throttle
# stores a per-NORAD "next allowed" time and is bumped BEFORE the request, so a
# crash/failure can't storm the API. With ~2 ORBCOMM birds that's <=4 requests/day.
_IVAN_THROTTLE  = os.path.join(HOME, "src", "satellites-overhead", ".tlecache", "ivan_last.json")
_IVAN_REFRESH_S = 12 * 3600   # on success, don't re-fetch this NORAD for 12h
_IVAN_RETRY_S   = 1 * 3600    # on failure, allow a retry after 1h (not the full 12h)
_IVAN_MAX_PER_CYCLE = 4       # cap fetches per refresh — spreads the ~17 ORBCOMM sats
                              # over several cycles so we never burst the API (it
                              # IP-blocks bursts; per-NORAD 12h throttle does the rest)

def _tle_epoch_from_l1(l1):
    """Epoch (UTC datetime) parsed from a TLE line-1, or None."""
    try:
        y = 2000 + int(l1[18:20]); doy = float(l1[20:32])
        return datetime.datetime(y, 1, 1, tzinfo=datetime.timezone.utc) + \
               datetime.timedelta(days=doy - 1)
    except Exception:
        return None

def _cached_tle_epoch(path, norad):
    """Epoch (UTC datetime) of the cached TLE for `norad`, or None if absent."""
    if not os.path.exists(path):
        return None
    for l in open(path, errors="ignore").read().splitlines():
        if l.startswith("1 ") and l[2:7].strip().isdigit() and int(l[2:7]) == norad:
            return _tle_epoch_from_l1(l)
    return None

def _enabled_rule_norads():
    try:
        data = json.load(open(RULES_PATH))
        rules = data if isinstance(data, list) else data.get("rules", [])
        return [int(r["norad"]) for r in rules if r.get("enabled") and r.get("norad")]
    except Exception:
        return []

def _orbcomm_cache_norads():
    """Every ORBCOMM NORAD in the satdump cache. The orbcomm auto-plotter picks
    which channels to demod from which sats it computes overhead (TLE-driven), so
    ALL of them must stay fresh — not just the enabled rule's bird. Stale ones make
    it target dead channels and decode nothing even on a strong signal."""
    out = []
    try:
        lines = open(_SATDUMP_TLES, errors="ignore").read().splitlines()
        for i, l in enumerate(lines):
            if l.strip().upper().startswith("ORBCOMM") and i + 1 < len(lines) \
               and lines[i + 1].startswith("1 ") and lines[i + 1][2:7].strip().isdigit():
                out.append(int(lines[i + 1][2:7]))
    except Exception:
        pass
    return out

def _supplement_tles_from_ivan(satnogs_norads):
    """Top up enabled sats satnogs can't supply (ORBCOMM) from ivanstanojevic, per
    NORAD. Rate-limit safe: each NORAD is fetched at most once / 12h (faster only to
    retry a failure), and the merge is newer-only so a stale source copy can never
    downgrade a fresher cached TLE."""
    import urllib.request
    need = set(_enabled_rule_norads()) | set(_orbcomm_cache_norads())
    need = [n for n in need if n not in satnogs_norads]
    if not need:
        return
    try:
        nxt = json.load(open(_IVAN_THROTTLE)) if os.path.exists(_IVAN_THROTTLE) else {}
    except Exception:
        nxt = {}
    now = time.time()
    # only those past their per-NORAD cooldown, stalest cached TLE first, capped per cycle
    def _stale_key(n):
        ep = _cached_tle_epoch(_SCHEDULER_TLE_CACHE, n)
        return ep.timestamp() if ep else 0.0   # missing/oldest = highest priority
    eligible = sorted((n for n in need if now >= float(nxt.get(str(n), 0))), key=_stale_key)
    for norad in eligible[:_IVAN_MAX_PER_CYCLE]:
        nxt[str(norad)] = now + _IVAN_RETRY_S   # anti-storm: block fast retry even if this fails
        try:
            req = urllib.request.Request(f"https://tle.ivanstanojevic.me/api/tle/{norad}",
                                         headers={"User-Agent": "sdr-scheduler-tle/1"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.load(r)
            l1, l2, nm = d.get("line1", ""), d.get("line2", ""), d.get("name", str(norad)).strip()
            if not (l1.startswith("1 ") and l2.startswith("2 ") and int(l1[2:7]) == norad):
                log(f"TLE ivan top-up — bad payload for {norad}")
                continue
            new_ep = _tle_epoch_from_l1(l1)
            cached_ep = _cached_tle_epoch(_SCHEDULER_TLE_CACHE, norad)
            if cached_ep and new_ep and new_ep <= cached_ep:
                log(f"TLE ivan {nm} ({norad}) — source not newer than cache, kept")
            else:
                for p in (_SATDUMP_TLES, _SCHEDULER_TLE_CACHE):
                    try:
                        _merge_tles(p, {norad: (nm, l1, l2)})
                    except Exception as e:
                        log(f"TLE ivan merge fail {p} norad {norad} — {e}")
                log(f"TLE ivan top-up — {nm} ({norad}) refreshed (satnogs lacks it)")
            nxt[str(norad)] = now + _IVAN_REFRESH_S   # success: don't re-fetch for 12h
        except Exception as e:
            log(f"TLE ivan fetch failed norad {norad} ({e}) — keeping cached")
        time.sleep(2)   # be gentle between per-NORAD requests
    try:
        with open(_IVAN_THROTTLE, "w") as f:
            json.dump(nxt, f)
    except Exception:
        pass

def refresh_satdump_tles():
    """Refresh TLEs from satnogs 3le into the satdump cache AND the predictor cache.
    Falls back to the existing caches (no-op) on failure so a fetch outage never
    blanks the TLEs. ORBCOMM (absent from satnogs) is topped up per-NORAD from
    ivanstanojevic afterward."""
    import urllib.request
    satnogs_norads = set()
    try:
        req = urllib.request.Request(_TLE_SOURCE, headers={"User-Agent": "sdr-scheduler-tle/1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read().decode("utf-8", errors="ignore")
        fresh = _parse_3le(data)
        if len(fresh) >= 100:
            satnogs_norads = set(fresh)
            for p in (_SATDUMP_TLES, _SCHEDULER_TLE_CACHE):
                try:
                    _merge_tles(p, fresh)
                except Exception as e:
                    log(f"TLE merge fail {p} — {e}")
        else:
            log(f"TLE refresh — only {len(fresh)} parsed, keeping existing cache")
    except Exception as e:
        log(f"TLE refresh fetch failed ({e}) — keeping existing cache")
    # ORBCOMM & anything else satnogs can't supply: per-NORAD top-up (rate-limited)
    try:
        _supplement_tles_from_ivan(satnogs_norads)
    except Exception as e:
        log(f"TLE ivan supplement error ({e})")
    try:
        with open(_SATDUMP_SETTINGS) as f:
            cfg = json.load(f)
        cfg.setdefault("user", {})["tles_last_updated"] = int(time.time())
        with open(_SATDUMP_SETTINGS, "w") as f:
            json.dump(cfg, f, indent=4)
    except Exception:
        pass


def rtlsdr_satdump_decode(capdir, duration_s, freq=137.9e6, gain=37, label="",
                          samplerate=2_000_000, iq_swap=True, dc_block=True,
                          pipeline="meteor_m2-x_lrpt", name="", norad=0,
                          max_el=0.0, profile="", bias_tee=False):
    """Capture CU8 IQ with rtl_sdr, then decode offline with satdump baseband mode."""
    iqfile  = capdir + ".iq"
    logfile = capdir + ".log"
    os.makedirs(capdir, exist_ok=True)

    # Step 1: capture IQ
    iq_result = rtl_sdr_capture(freq, iqfile, duration_s, gain=gain, label=label,
                                bias_tee=bias_tee)
    if not iq_result:
        log(f"DECODE SKIP {label} — IQ capture failed")
        return 0

    iq_mb = os.path.getsize(iqfile) / 1e6
    log(f"DECODE {label} — {iq_mb:.0f} MB IQ → satdump offline {pipeline}")

    # Refresh TLEs before satdump starts so it won't try to fetch them itself
    refresh_satdump_tles()

    # Step 2: decode offline
    cmd = ["satdump", pipeline, "baseband", iqfile, capdir,
           "--samplerate", str(samplerate),
           "--baseband_format", "cu8"]
    if iq_swap:
        cmd.append("--iq_swap")
    if dc_block:
        cmd.append("--dc_block")

    def _run_decode():
        try:
            with open(logfile, "w") as lf:
                proc = subprocess.Popen(cmd, stdout=lf, stderr=lf)
            proc.wait(timeout=duration_s * 4)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception as e:
            log(f"DECODE FAIL {label} — {e}")
            return
        cadu = os.path.join(capdir, f"{pipeline}.cadu")
        size = os.path.getsize(cadu) if os.path.exists(cadu) else 0

        # Generate pass summary now that satdump has finished writing its output
        summary_script = os.path.join(REPO_DIR, "satdump_pass_summary.py")
        if os.path.exists(summary_script):
            try:
                subprocess.run(
                    ["python3", summary_script, capdir,
                     "--name", name or label, "--norad", str(norad or 0),
                     "--max-el", str(max_el), "--pipeline", pipeline,
                     "--freq", str(int(freq))],
                    timeout=120,
                )
            except Exception as e:
                log(f"SUMMARY FAIL {label} — {e}")

        # Render a waterfall PNG from the raw IQ for at-a-glance "was anything on the air?"
        wf_script = os.path.expanduser("~/iq_waterfall.py")
        if os.path.exists(wf_script) and os.path.exists(iqfile):
            try:
                subprocess.run(
                    ["python3", wf_script, iqfile,
                     "--fs", str(samplerate), "--fc", str(int(freq)),
                     "--out", os.path.join(capdir, "waterfall.png")],
                    timeout=180,
                )
            except Exception as e:
                log(f"WATERFALL FAIL {label} — {e}")

        # Front-end health: was the antenna/LNA actually alive for this capture?
        chain_str = chain_health(iqfile, int(freq), samplerate) if os.path.exists(iqfile) else None
        if chain_str:
            log(f"CHAIN {label} — {chain_str}")

        summary_md = ""
        summary_path = os.path.join(capdir, "pass_summary.md")
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                summary_md = f.read()

        imgs = []
        for root, _, files in os.walk(capdir):
            if os.path.abspath(root) == os.path.abspath(capdir):
                continue  # skip capdir root — satdump products live in subdirs (MSU-MR/);
                          # ignores our own waterfall.png and other non-product artifacts
            for fn in sorted(files):
                if fn.lower().endswith((".png", ".jpg", ".webp")):
                    imgs.append(os.path.relpath(os.path.join(root, fn), capdir))

        if "meteor_lrpt" in profile and imgs:
            msa = os.path.join(capdir, "MSU-MR", "msu_mr_rgb_MSA_corrected_map.png")
            if os.path.exists(msa):
                _mtime = os.path.getmtime(msa)
                _captured_at = datetime.datetime.fromtimestamp(
                    _mtime, datetime.timezone.utc
                ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                try:
                    push_meteor_image(capdir, name or label, max_el, _captured_at)
                except Exception as e:
                    log(f"PUSH FAIL {label} — {e}")

        # Attach a downscaled waterfall so the email shows whether anything was on the air
        wf_png = os.path.join(capdir, "waterfall.png")
        wf_thumb = make_email_thumb(wf_png) if os.path.exists(wf_png) else None

        img_list = "\n".join(f"  {i}" for i in imgs) if imgs else "  (none)"
        if size > 0 or imgs:
            result = "DECODED" if size > 0 else "IMAGES (no CADU)"
            log(f"DECODE DONE {label} — {size} bytes CADU — {len(imgs)} images")
            body = summary_md if summary_md else f"Pass: {label}\nCADU: {size:,} bytes\n"
            body += f"\nImages ({len(imgs)}):\n{img_list}\n"
            if chain_str:
                body += f"\nChain: {chain_str}\n"
            # On a good pass, attach a web-sized composite so the image shows inline in
            # the email (not just the waterfall); full-res still goes to the gallery.
            comp_thumb = None
            if "meteor_lrpt" in profile:
                _comp = os.path.join(capdir, "MSU-MR", "msu_mr_rgb_MSA_corrected_map.png")
                if not (os.path.exists(_comp) and os.path.getsize(_comp) > 60_000):
                    _comp = os.path.join(capdir, "MSU-MR",
                                         "msu_mr_rgb_AVHRR_3a21_False_Color_corrected.png")
                if os.path.exists(_comp):
                    comp_thumb = make_email_thumb(_comp, max_px=1400)
            send_pass_email(f"SAT PASS: {label} — {result}", body,
                            attach=[a for a in (comp_thumb, wf_thumb) if a])
        else:
            log(f"DECODE DONE {label} — 0 bytes CADU — no lock — check {logfile}")
            body = summary_md or f"Pass: {label}\nCADU: 0 bytes\nResult: NO LOCK\nLog: {logfile}\n"
            if chain_str:
                body += f"\nChain: {chain_str}\n"
            send_pass_email(f"SAT PASS: {label} — NO LOCK", body, attach=wf_thumb)

        # finalize: correct the provisional history record the loop wrote right after
        # capture (before this decode ran), and clear the "decoding" status
        try:
            update_capture_record(capdir, size_bytes=size, cadu_bytes=size,
                                  success=bool(size > 0 or imgs))
        except Exception as _e:
            log(f"HISTORY UPDATE FAIL {label} — {_e}")
        _active_decodes.pop(capdir, None)

    _active_decodes[capdir] = {
        "type": "satdump", "label": label, "name": name or label, "output": capdir,
        "frequency_hz": float(freq), "phase": "decoding", "started": time.time(),
    }
    threading.Thread(target=_run_decode, daemon=False).start()
    return 0


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


# Meteor decodes run in a background thread AFTER run_job returns (to free the radio for
# the next pass), so the loop would otherwise write the history record before the decode
# finishes (showing 0/no-lock for a pass that actually decoded) and report "idle" while
# the decode is still working. These keep status + history honest during that window.
_active_decodes = {}   # capdir -> status payload (incl "started"); non-empty => decoding

def update_capture_record(output, **fields):
    """Update the most recent history record for `output` with real decode results.
    The loop writes a provisional record right after capture; this corrects it once the
    threaded decode knows the real CADU size / image count."""
    if not output or not os.path.exists(HISTORY_PATH):
        return
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)
        if not isinstance(history, list):
            return
    except Exception:
        return
    for rec in reversed(history):
        if rec.get("output") == output:
            rec.update(fields)
            try:
                atomic_write_json(HISTORY_PATH, history)
            except Exception as e:
                log(f"HISTORY UPDATE FAIL {output} — {e}")
            return

def _status_idle_or_decoding(next_job=None, idle_msg="idle"):
    """Write 'idle' (with next-pass info) unless a background decode is still running —
    then report 'decoding' so the CLI doesn't show idle mid-decode. Entries older than
    10 min are ignored as a safety net in case a decode thread died without clearing."""
    now = time.time()
    fresh = [d for d in _active_decodes.values() if now - d.get("started", 0) < 600]
    if fresh:
        d = fresh[-1]
        write_scheduler_status("running", d, f"decoding {d.get('label', '')}")
    else:
        write_scheduler_status("idle", next_job, idle_msg)


def _invoke_pass_manager(capdir, kwargs):
    """Spawn a claude --print agent at AOS to live-manage a pass."""
    label = kwargs.get("label", "unknown")
    norad = kwargs.get("_norad", "?")
    freq = kwargs.get("freq", kwargs.get("freq_hz", "?"))
    pipeline = kwargs.get("pipeline", "iq")
    duration_s = kwargs.get("duration_s", 300)
    max_el = kwargs.get("_max_el", "?")
    retry_idx = kwargs.get("_retry_idx", -1)
    lna = kwargs.get("lna", 16)
    vga = kwargs.get("vga", 36)
    amp = kwargs.get("amp", 1)
    iq_swap = kwargs.get("iq_swap", True)
    dc_block = kwargs.get("dc_block", True)
    samplerate = kwargs.get("samplerate", "2e6")
    logfile = capdir + ".log"
    pidfile = capdir + ".pid"
    claude_log = capdir + ".claude_pass.log"
    freq_hz = int(freq) if isinstance(freq, (int, float)) else freq
    freq_mhz = freq_hz / 1e6 if isinstance(freq_hz, int) else "?"

    # Serialize retry variants so Claude knows exactly what to try next
    variants_json = json.dumps(LRPT_RETRY_VARIANTS, indent=2)
    next_idx = retry_idx + 1
    next_variant = LRPT_RETRY_VARIANTS[next_idx] if 0 <= next_idx < len(LRPT_RETRY_VARIANTS) else None
    next_variant_json = json.dumps(next_variant) if next_variant else "none — all variants exhausted"

    # Build a ready-to-use retry curl template
    retry_template = json.dumps({
        "norad": norad,
        "name": label.split(" scan")[0].split(" LRPT")[0].strip(),
        "frequency_hz": freq_hz,
        "profile": kwargs.get("_profile", "meteor_lrpt_hackrf"),
        "pipeline": next_variant["pipeline"] if next_variant else pipeline,
        "samplerate": next_variant["samplerate"] if next_variant else samplerate,
        "iq_swap": next_variant["iq_swap"] if next_variant else iq_swap,
        "dc_block": next_variant["dc_block"] if next_variant else dc_block,
        "lna_gain": lna,
        "vga_gain": vga,
        "amp": amp,
        "duration_s": max(60, duration_s - 120),
        "_retry_idx": next_idx,
    }, indent=2)

    prompt = (
        f"You are the live pass manager for an SDR satellite capture. Read "
        f"{REPO_DIR}/CLAUDE.md first for hardware/pipeline context.\n\n"
        f"PASS: {label} | NORAD {norad} | {freq_mhz} MHz | pipeline={pipeline} | "
        f"max_el={max_el}° | duration={duration_s}s | retry_idx={retry_idx}\n"
        f"  Log:     {logfile}\n"
        f"  PID:     {pidfile}\n"
        f"  Capdir:  {capdir}\n"
        f"  Gains:   LNA={lna} VGA={vga} amp={amp} iq_swap={iq_swap} dc_block={dc_block}\n\n"
        f"LOOP until pidfile gone or {duration_s}s elapsed — check every 25s:\n"
        f"  tail -4 {logfile} | grep -E 'SNR|Viterbi|Deframer|Progress'\n"
        f"  wc -c {capdir}/*.cadu {capdir}/*.frm 2>/dev/null\n"
        f"  [ -f {pidfile} ] || break   # exit loop when capture ends\n\n"
        f"ACT IMMEDIATELY (don't wait for T+90s monitor) if you see:\n"
        f"  SNR>5 + BER=0.000 + Deframer NOSYNC  → LO false-lock, kill and retry with dc_block=true\n"
        f"  SNR>5 + BER 0.05-0.15 + Deframer SYNCED → Real lock, let it run, watch CADU grow\n"
        f"  SNR>28 or BER climbing to 0.5          → Saturated, kill and retry VGA-12\n"
        f"  SNR=0 through max elevation             → No signal, note and let expire\n"
        f"  Viterbi SYNCED + Deframer NOSYNC (any BER) → Wrong pipeline, retry next variant\n\n"
        f"NEXT RETRY VARIANT (idx={next_idx}): {next_variant_json}\n\n"
        f"ALL RETRY VARIANTS:\n{variants_json}\n\n"
        f"TO KILL AND RETRY (use exact payload below, adjust pipeline/flags per variant):\n"
        f"  kill $(cat {pidfile}) 2>/dev/null\n"
        f"  curl -s -X POST http://localhost:8723/scheduler/scan-now \\\n"
        f"    -H 'Content-Type: application/json' \\\n"
        f"    -d '{retry_template}'\n\n"
        f"NOTE: A T+90s monitor also runs independently. If you act before T+90s, "
        f"write a one-line note to {capdir}/pass_manager.lock so the monitor skips "
        f"its retry (check for that file in your loop too).\n\n"
        f"WHEN DONE: write {capdir}/pass_report.md — SNR peak, lock Y/N, CADU bytes, "
        f"actions taken, recommendation. Then exit."
    )
    try:
        with open(claude_log, "w") as lf:
            subprocess.Popen(
                ["claude", "--print", "-p", prompt],
                cwd=REPO_DIR,
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
        log(f"PASS MANAGER Claude started for {os.path.basename(capdir)} — {claude_log}")
        scheduler_event(
            "claude.pass_manager.started",
            {"capture": os.path.basename(capdir), "label": label, "log": claude_log},
            {"title": f"Claude managing {label}", "body": f"{max_el}° pass"},
        )
    except Exception as e:
        log(f"PASS MANAGER Claude invoke FAIL — {e}")


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

def _merge_orbcomm_passes(passes, gap_s=120, max_window_s=1500, cap=16):
    """Merge overlapping/adjacent constellation passes into single capture windows,
    keep the highest-elevation `cap`, return sorted by time. The auto-plotter decodes
    every ORBCOMM bird in view during a window, so one window per overlapping cluster
    is all we need. Meteor (priority 1) still wins any device conflict downstream."""
    if not passes:
        return []
    def dt(s): return datetime.datetime.fromisoformat(s)
    ps = sorted(passes, key=lambda p: p["aos"])
    merged, cur = [], dict(ps[0])
    for p in ps[1:]:
        if dt(p["aos"]) <= dt(cur["los"]) + datetime.timedelta(seconds=gap_s):
            if dt(p["los"]) > dt(cur["los"]):
                cur["los"] = p["los"]
            if float(p.get("max_el", 0)) > float(cur.get("max_el", 0)):
                cur["max_el"] = p["max_el"]; cur["name"] = p.get("name", cur.get("name"))
        else:
            merged.append(cur); cur = dict(p)
    merged.append(cur)
    for m in merged:
        m["duration_s"] = min(int((dt(m["los"]) - dt(m["aos"])).total_seconds()), max_window_s)
    merged.sort(key=lambda m: float(m.get("max_el", 0)), reverse=True)
    merged = merged[:cap]
    merged.sort(key=lambda m: m["aos"])
    return merged

def predict_rule_passes(rule, hours=24, limit=4):
    # Constellation rule (ORBCOMM): the live auto-plotter decodes every bird in view,
    # so we capture whenever ANY constellation member is high — predict them all and
    # merge into windows. Requires all their TLEs fresh (see _supplement_tles_from_ivan).
    if rule.get("constellation") == "orbcomm":
        norads = _orbcomm_cache_norads() or [int(rule["norad"])]
        cmd = ["python3", PREDICTOR, "--lat", str(LAT), "--lon", str(LON), "--alt-m", str(ALT_M),
               "--hours", str(hours), "--min-el", str(rule.get("min_peak_el", 40)),
               "--track-step-s", "120", "--limit", "300"]
        for n in norads:
            cmd += ["--norad", str(n)]
        raw = subprocess.check_output(cmd, text=True)
        return _merge_orbcomm_passes(json.loads(raw),
                                     cap=int(rule.get("max_windows", 16)),
                                     max_window_s=int(rule.get("max_capture_s", 1500)))
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
        # Keep the FULL dated datetime (manual jobs already do — see build_scan_now_job).
        # A bare "HH:MM" lost the date, so job_fire_dt() resolved it against today, and
        # predict_rule_passes returns ~4 passes spanning 24-30h: a NEXT-DAY pass at the
        # same clock time (Meteor drifts ~22 min/day) aliased onto TODAY and fired ~22 min
        # early as a phantom carrying the wrong day's elevation. That was every "duplicate".
        fire_time = fire_dt
        lna = int(rule.get("lna_gain", 32))
        vga = int(rule.get("vga_gain", 48))
        amp = int(rule.get("amp", 1))
        if float(p.get("max_el", 0)) >= 60:
            vga = max(0, vga - 12)
        aos_local = fire_dt.strftime("%H%M")
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
            _priority=float(rule.get("priority", 0) or 0),
        )
        profile = rule.get("profile", "raw_iq_hackrf")
        rtlsdr = profile.endswith("_rtlsdr")
        if profile in ("meteor_lrpt_hackrf", "satdump_hackrf",
                       "meteor_lrpt_rtlsdr", "satdump_rtlsdr"):
            is_lrpt = "meteor_lrpt" in profile
            default_pipeline = "meteor_m2-x_lrpt" if is_lrpt else "orbcomm_stx_auto_plotter"
            suffix = "LRPT" if is_lrpt else "SDR"
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
                    source="rtlsdr" if rtlsdr else "hackrf",
                    label=f"{label} {suffix}",
                    samplerate=str(rule.get("samplerate", LRPT_RETRY_VARIANTS[0]["samplerate"])),
                    iq_swap=bool(rule.get("iq_swap", LRPT_RETRY_VARIANTS[0]["iq_swap"])),
                    dc_block=bool(rule.get("dc_block", LRPT_RETRY_VARIANTS[0].get("dc_block", True))),
                    pipeline=str(rule.get("pipeline", default_pipeline)),
                    bias_tee=bool(rule.get("bias_tee", False)),
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
    rtlsdr = profile.endswith("_rtlsdr")
    is_lrpt = "meteor_lrpt" in profile
    default_pipeline = "meteor_m2-x_lrpt" if is_lrpt else "orbcomm_stx_auto_plotter"
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
    if profile in ("meteor_lrpt_hackrf", "satdump_hackrf",
                   "meteor_lrpt_rtlsdr", "satdump_rtlsdr"):
        return (
            datetime.datetime.now().astimezone(),
            "satdump",
            {
                **common,
                "capdir": f"{NOAADIR}/{slug}_{stamp}",
                "freq": frequency_hz,
                "source": "rtlsdr" if rtlsdr else "hackrf",
                "samplerate": samplerate,
                "iq_swap": iq_swap,
                "pipeline": pipeline,
                "dc_block": dc_block,
                "bias_tee": bool(command.get("bias_tee", profile == "meteor_lrpt_rtlsdr")),
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
    selected, skipped = resolve_rule_job_overlaps(jobs)
    if log_loaded and skipped:
        log(f"Skipped {len(skipped)} overlapping rule job segment(s) shorter than {MIN_PARTIAL_CAPTURE_S}s")
    return selected

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

def job_end_dt(job):
    return job_fire_dt(job[0]) + datetime.timedelta(seconds=max(1, int(job[2].get("duration_s", 1))))

def job_priority_score(job):
    kwargs = job[2]
    return priority_score(
        kwargs.get("_priority", 0),
        kwargs.get("_max_el", 0),
        kwargs.get("duration_s", 0),
    )

def _suffix_path(path, suffix):
    root, ext = os.path.splitext(path)
    return f"{root}{suffix}{ext}" if ext else f"{path}{suffix}"

def trim_job_to_window(job, start, end, part_index, part_count):
    original_start = job_fire_dt(job[0])
    original_end = job_end_dt(job)
    if start == original_start and end == original_end:
        return job

    _, ptype, kwargs = job
    next_kwargs = dict(kwargs)
    suffix = f"_part{part_index}" if part_count > 1 else "_partial"
    duration_s = max(1, int((end - start).total_seconds()))
    next_kwargs["duration_s"] = duration_s
    next_kwargs["_partial"] = True
    next_kwargs["_original_fire_time"] = original_start.isoformat()
    next_kwargs["_original_duration_s"] = kwargs.get("duration_s")
    label = kwargs.get("label", "")
    next_kwargs["label"] = f"{label} partial" if part_count == 1 else f"{label} partial {part_index}/{part_count}"
    if next_kwargs.get("capdir"):
        next_kwargs["capdir"] = _suffix_path(next_kwargs["capdir"], suffix)
    if next_kwargs.get("outfile"):
        next_kwargs["outfile"] = _suffix_path(next_kwargs["outfile"], suffix)
    return (start, ptype, next_kwargs)

def resolve_rule_job_overlaps(jobs):
    return trim_overlapping_windows(
        jobs,
        start_fn=lambda job: job_fire_dt(job[0]),
        end_fn=job_end_dt,
        score_fn=job_priority_score,
        trim_fn=trim_job_to_window,
        min_duration_s=MIN_PARTIAL_CAPTURE_S,
    )

def collect_jobs(log_loaded=False):
    jobs = command_jobs() + MANUAL_JOBS + optional_rule_jobs(log_loaded=log_loaded)
    jobs.sort(key=lambda job: job_fire_dt(job[0]))
    return jobs

def jobs_signature(jobs):
    return tuple((job_fire_dt(j[0]).isoformat(timespec="minutes"), j[1], j[2].get("label", "")) for j in jobs)

def run_job(ptype, kwargs):
    run_kwargs = dict(kwargs)
    for key in (
        "_command_id", "_queued_at", "_norad", "_name", "_profile", "_source",
        "_max_el", "_retry_idx", "_priority", "_partial", "_original_fire_time",
        "_original_duration_s",
    ):
        run_kwargs.pop(key, None)
    if ptype == "satdump":
        capdir = run_kwargs.get("capdir")
        if capdir and os.path.exists(MONITOR_SCRIPT):
            t = threading.Thread(target=_monitor_satdump, args=(capdir, kwargs), daemon=True)
            t.start()
        if capdir:
            threading.Thread(target=_invoke_pass_manager, args=(capdir, kwargs), daemon=True).start()
    if ptype == "iq":
        profile  = kwargs.get("_profile", "")
        norad    = kwargs.get("_norad")
        name     = kwargs.get("_name", "unknown")
        max_el   = kwargs.get("_max_el", 0.0)
        freq_hz  = run_kwargs.get("freq_hz", 0)
        if profile.endswith("_rtlsdr"):
            rtl_kwargs = {k: v for k, v in run_kwargs.items()
                          if k in ("freq_hz", "outfile", "duration_s", "label")}
            rtl_kwargs["gain"] = run_kwargs.get("lna", 40)
            rtl_kwargs["bias_tee"] = run_kwargs.get("bias_tee", False)
            outfile = rtl_sdr_capture(**rtl_kwargs)
        else:
            outfile = hackrf_capture(**run_kwargs)
            analyze_150mhz(outfile, run_kwargs["label"], freq_hz)
        if outfile:
            summary_script = os.path.join(REPO_DIR, "sat_iq_summary.py")
            if os.path.exists(summary_script):
                log(f"Post-pass summary: {os.path.basename(outfile)}")
                cmd = [
                    "python3", summary_script, outfile,
                    "--norad",  str(norad or 0),
                    "--name",   name,
                    "--max-el", str(max_el),
                    "--freq",   str(freq_hz),
                    "--force-summary",
                ]
                threading.Thread(
                    target=lambda c=cmd: subprocess.run(c, capture_output=False),
                    daemon=False,
                ).start()
            # gr_satellites decode for supported digital satellites
            # Signal frequencies (actual) vs tuned center (offset -50 kHz to avoid DC spike)
            GR_SAT_NAMES = {
                39444: ("AO-73",   145935000),
                44881: ("CAS-6",   145925000),
                43803: ("JY1-Sat", 145865000),
            }
            gr_sat_info = GR_SAT_NAMES.get(norad)
            if gr_sat_info:
                gr_sat, sig_freq = gr_sat_info
                freq_offset = sig_freq - freq_hz  # how far signal is from IQ center
                outdir = outfile.replace(".iq", "_gr_decode")
                os.makedirs(outdir, exist_ok=True)
                log(f"gr_satellites decode: {gr_sat} offset={freq_offset:+d}Hz → {outdir}")
                def _gr_decode(iqfile=outfile, sat=gr_sat, dumpdir=outdir, offset=freq_offset):
                    try:
                        import numpy as np
                        data = np.fromfile(iqfile, dtype=np.uint8)
                        cf32 = (data.astype(np.float32) - 128.0) / 128.0
                        tmppath = iqfile.replace(".iq", "_tmp.cf32")
                        cf32.tofile(tmppath)
                        del cf32, data
                        os.makedirs(dumpdir, exist_ok=True)
                        cmd = ["gr_satellites", sat, "--rawfile", tmppath,
                               "--samp_rate", "2000000", "--iq", "--dump_path", dumpdir]
                        if offset != 0:
                            cmd += ["--freq_offset", str(offset)]
                        subprocess.run(cmd, capture_output=False)
                        os.unlink(tmppath)
                    except Exception as e:
                        log(f"gr_satellites decode failed: {e}")
                threading.Thread(target=_gr_decode, daemon=False).start()
        return {"ok": bool(outfile), "output": outfile}
    elif ptype == "satdump":
        source   = run_kwargs.get("source", "hackrf")
        capdir   = run_kwargs.get("capdir", "")
        name     = kwargs.get("_name", "unknown")
        norad    = kwargs.get("_norad", 0)
        max_el   = kwargs.get("_max_el", 0.0)
        pipeline = run_kwargs.get("pipeline", "meteor_m2-x_lrpt")
        freq_hz  = int(run_kwargs.get("freq", 0))

        if source == "rtlsdr" and (pipeline in LIVE_ONLY_PIPELINES or pipeline == "orbcomm_bandscan"):
            if pipeline == "orbcomm_bandscan":
                # ORBCOMM band-scan: capture raw IQ, scan the band for ACTIVE channels
                # (PSD peaks) and decode each — no TLE channel-selection blind spot, so
                # it catches whatever's actually transmitting. Frames land in capdir for
                # orbcomm_ephem; the 4.5 GB raw IQ is deleted right after decoding.
                os.makedirs(capdir, exist_ok=True)
                iqfile = capdir + ".iq"
                rtl_sdr_capture(freq_hz, iqfile, run_kwargs.get("duration_s", 600),
                                gain=run_kwargs.get("lna", 40),
                                label=run_kwargs.get("label", name),
                                # ORBCOMM needs the SAWbird powered — bias on unless
                                # the rule explicitly set it False (FM114's rule is null)
                                bias_tee=run_kwargs.get("bias_tee") is not False)
                if os.path.exists(iqfile):
                    try:
                        subprocess.run(
                            ["python3", os.path.join(HOME, "orbcomm_scan_decode.py"),
                             iqfile, str(int(freq_hz)), "2000000", capdir],
                            timeout=int(run_kwargs.get("duration_s", 600)) * 3)
                    except Exception as e:
                        log(f"ORBCOMM BANDSCAN FAIL {name} — {e}")
                    try:
                        os.unlink(iqfile)   # drop the 4.5 GB raw IQ once decoded
                    except Exception:
                        pass
                cadu_bytes = sum(os.path.getsize(f)
                                 for f in glob.glob(os.path.join(capdir, "*.frm")))
            else:
                # ORBCOMM (live-only pipeline): decode live straight off the RTL-SDR.
                cadu_bytes = satdump_capture(
                    capdir     = capdir,
                    duration_s = run_kwargs.get("duration_s", 600),
                    freq       = freq_hz,
                    lna        = run_kwargs.get("lna", 40),
                    label      = run_kwargs.get("label", name),
                    samplerate = run_kwargs.get("samplerate", "2e6"),
                    iq_swap    = run_kwargs.get("iq_swap", False),
                    dc_block   = run_kwargs.get("dc_block", False),
                    pipeline   = pipeline,
                    source     = "rtlsdr",
                    bias_tee   = run_kwargs.get("bias_tee", False),
                )
            # ORBCOMM post-decode: parse frames for ephemeris (sat positions) + summary, log + email
            ephem_script = os.path.join(REPO_DIR, "orbcomm_ephem.py")
            if capdir and os.path.exists(ephem_script):
                try:
                    res = subprocess.run(["python3", ephem_script, capdir],
                                         capture_output=True, text=True, timeout=60)
                    summary = (res.stdout or "").strip()
                    if summary:
                        for ln in summary.splitlines():
                            log(f"ORBCOMM {ln.strip()}")
                        lbl = run_kwargs.get("label", name)
                        # Subject must reflect the outcome — it was always "ORBCOMM decode",
                        # so a 3049-packet/14-fix success and a 0-packet dud looked identical
                        # in the inbox (you could never tell a success from a failure).
                        pkts = fixes = 0
                        for ln in summary.splitlines():
                            s = ln.strip()
                            if s.startswith("ORBCOMM decode:"):
                                try:
                                    pkts = int(s.split("ORBCOMM decode:")[1].split("Fletcher")[0])
                                except Exception:
                                    pass
                            elif "ephemeris fix(es)" in s:
                                try:
                                    fixes = int(s.split("ephemeris fix(es)")[0])
                                except Exception:
                                    pass
                        if fixes > 0:
                            tag = f"DECODED — {fixes} fix{'es' if fixes != 1 else ''}, {pkts} pkts"
                        elif pkts > 0:
                            tag = f"partial — {pkts} pkts, no fixes"
                        else:
                            tag = "NO DATA"
                        send_pass_email(f"SAT PASS: {lbl} — ORBCOMM {tag}", summary + "\n")
                except Exception as e:
                    log(f"ORBCOMM EPHEM FAIL {name} — {e}")
        elif source == "rtlsdr":
            # RTL-SDR LRPT: capture CU8 IQ then decode offline (live mode broken for LRPT)
            cadu_bytes = rtlsdr_satdump_decode(
                capdir       = capdir,
                duration_s   = run_kwargs.get("duration_s", 600),
                freq         = freq_hz,
                gain         = run_kwargs.get("lna", 37),
                label        = run_kwargs.get("label", name),
                samplerate   = int(float(run_kwargs.get("samplerate", "2e6"))),
                iq_swap      = run_kwargs.get("iq_swap", True),
                dc_block     = run_kwargs.get("dc_block", True),
                pipeline     = pipeline,
                name         = name,
                norad        = norad,
                max_el       = max_el,
                profile      = kwargs.get("_profile", ""),
                bias_tee     = run_kwargs.get("bias_tee", False),
            )
        else:
            cadu_bytes = satdump_capture(**run_kwargs)

        freq_hz    = int(run_kwargs.get("freq", 0))
        if source != "rtlsdr":
            # RTL-SDR: summary and image push are handled in _run_decode after the async decode
            summary_script = os.path.join(REPO_DIR, "satdump_pass_summary.py")
            if capdir and os.path.exists(summary_script):
                cmd = [
                    "python3", summary_script, capdir,
                    "--name",     name,
                    "--norad",    str(norad or 0),
                    "--max-el",   str(max_el),
                    "--pipeline", pipeline,
                    "--freq",     str(freq_hz),
                ]
                threading.Thread(
                    target=lambda c=cmd: subprocess.run(c, capture_output=False),
                    daemon=True,
                ).start()
            profile_str = kwargs.get("_profile", "")
            if "meteor_lrpt" in profile_str and capdir:
                img = os.path.join(capdir, "MSU-MR", "msu_mr_rgb_MSA_corrected_map.png")
                if os.path.exists(img):
                    _mtime = os.path.getmtime(img)
                    _captured_at = datetime.datetime.fromtimestamp(
                        _mtime, datetime.timezone.utc
                    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    threading.Thread(
                        target=push_meteor_image,
                        args=(capdir, name, max_el, _captured_at),
                        daemon=True,
                    ).start()
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
        "partial": bool(kwargs.get("_partial")),
        "original_fire_time": kwargs.get("_original_fire_time"),
        "original_duration_s": kwargs.get("_original_duration_s"),
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
    threading.Thread(target=backfill_meteor_images, daemon=True).start()

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

        # NOTE: the "two predictions for one pass" we used to see was NOT a TLE-refresh
        # artifact — it was the date-less HH:MM bug above: next-day passes aliased onto
        # today and fired ~22 min early as phantoms. That also explains why adding
        # same-sat dedup once "cost us" the 2026-06-14 M2-4 pass — the phantom fires
        # FIRST, so dedup marked the sat done and skipped the REAL pass. With dated
        # fire_times the phantom is gone and job_key is date-qualified, so no extra
        # dedup is needed: a real pass and any genuine back-to-back pass keep distinct
        # keys, and a single job still can't double-fire.
        due = [job for job in jobs
               if job_key(job) not in completed
               and job_fire_dt(job[0]) <= now]
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
                _status_idle_or_decoding(
                    idle_msg="last capture failed" if failed else "last capture finished",
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
                    "partial": bool(kwargs.get("_partial")),
                    "original_fire_time": kwargs.get("_original_fire_time"),
                    "original_duration_s": kwargs.get("_original_duration_s"),
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
                if ptype == "iq":
                    _el = record.get("max_el") or 0.0
                    _status = "CAPTURED" if record["success"] else "FAILED"
                    send_pass_email(
                        f"SAT PASS: {record['name']} {_el:.1f}deg — {_status}",
                        f"Satellite: {record['name']}\nMax elevation: {_el:.1f}°\n"
                        f"Size: {record['size_bytes']:,} bytes\nResult: {_status}\n"
                        f"Output: {record.get('output', 'n/a')}\n",
                    )
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

        future = [job for job in jobs
                  if job_key(job) not in completed
                  and job_fire_dt(job[0]) > now]
        if future:
            job = sorted(future, key=lambda item: job_fire_dt(item[0]))[0]
            fire_dt = job_fire_dt(job[0])
            wait = max(0, (fire_dt - now).total_seconds())
            next_id = job_key(job)
            if next_id != last_next:
                log(f"Next: {job[2]['label']} at {fire_dt.strftime('%H:%M')} (in {wait:.0f}s)")
                _status_idle_or_decoding(status_job_payload(job[0], job[1], job[2]), "next capture pending")
                last_status_update = now_ts
                last_next = next_id
            elif now_ts - last_status_update >= 30:
                _status_idle_or_decoding(status_job_payload(job[0], job[1], job[2]), "next capture pending")
                last_status_update = now_ts
            sleep_s = min(POLL_INTERVAL_S, wait, max(1, next_reload - now_ts))
        else:
            if last_next is not None:
                log("No scheduled jobs pending.")
                _status_idle_or_decoding(idle_msg="no scheduled jobs pending")
                last_status_update = now_ts
                last_next = None
            elif now_ts - last_status_update >= 30:
                _status_idle_or_decoding(idle_msg="no scheduled jobs pending")
                last_status_update = now_ts
            sleep_s = min(POLL_INTERVAL_S, max(1, next_reload - now_ts))
        time.sleep(max(1, sleep_s))

# ── SCHEDULE ─────────────────────────────────────────────────────────────────
if __name__ != '__main__':
    raise ImportError("sdr_scheduler is not importable — run it directly")

# ── Single-instance guard ─────────────────────────────────────────────────────
_SCHED_PIDFILE = os.path.join(HOME, ".sdr_scheduler.pid")
_my_pid = os.getpid()
try:
    import fcntl as _fcntl
    # Open with "a" so we don't truncate before acquiring the lock
    _pid_fd = open(_SCHED_PIDFILE, "a")
    _fcntl.flock(_pid_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    # We have the lock — overwrite with our PID
    _pid_fd.seek(0); _pid_fd.truncate(); _pid_fd.write(str(_my_pid)); _pid_fd.flush()
except (IOError, OSError):
    existing = open(_SCHED_PIDFILE).read().strip() if os.path.exists(_SCHED_PIDFILE) else "?"
    print(f"[sdr_scheduler] Already running (PID {existing}) — exiting duplicate.", flush=True)
    raise SystemExit(0)

MANUAL_JOBS = [
    # Agent/user-created radio jobs belong here. They do not need to be
    # satellites and do not depend on TLEs, CelesTrak, the map, or serve.py.
]

scheduler_loop()
