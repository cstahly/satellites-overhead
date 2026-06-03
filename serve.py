#!/usr/bin/env python3
"""Static server for the satellite app + a caching TLE proxy.

The browser fetches /tle?group=NAME instead of hitting CelesTrak directly.
This server fetches each group from CelesTrak at most once per TTL, caches it
on disk, and serves the cached copy otherwise -- so reloading the page or
switching catalogs never trips CelesTrak's rate limiter (HTTP 403). If a fresh
fetch fails, the last good copy on disk is served instead.

Usage:  python3 serve.py [port]        (default 8723)
"""
import http.server
import json
import os
import socketserver
import sys
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from predict import parse_start, parse_tles, predict_passes, select_tles

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8723
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, ".tlecache")
TX_CACHE_DIR = os.path.join(ROOT, ".txcache")
SAT_CACHE_DIR = os.path.join(ROOT, ".satcache")
RULES_PATH = os.path.join(os.path.expanduser("~"), "sdr_scheduler_rules.json")
COMMANDS_PATH = os.path.join(os.path.expanduser("~"), "sdr_scheduler_commands.json")
STATUS_PATH = os.path.join(os.path.expanduser("~"), "sdr_scheduler_status.json")
HISTORY_PATH = os.path.join(os.path.expanduser("~"), "sdr_capture_history.json")
TTL = 2 * 3600  # seconds; CelesTrak asks clients not to refetch a group within ~2h
TX_TTL = 7 * 24 * 3600

# Only allow the catalogs the app exposes (also prevents using us as an open proxy).
ALLOWED = {"active", "radio", "visual", "stations", "starlink", "gps-ops", "science"}
RADIO_NAME_TERMS = (
    "ISS", "METEOR", "NOAA", "FENGYUN", "METOP", "AQUA", "TERRA", "SUOMI",
    "LANDSAT", "OKEAN", "SICH", "RESURS", "ELEKTRO", "GOES", "HAMSAT",
    "AO-", "SO-", "FO-", "IO-", "RS-", "CAS-", "XW-", "TEVEL", "LILACSAT",
    "SKYTERRA", "INMARSAT", "IRIDIUM", "GLOBALSTAR", "ORBCOMM",
)
BAND_RANGES = {
    "vdipole": {
        "label": "V-dipole VHF",
        "ranges": ((136e6, 138e6),),
        "profile": "meteor_lrpt_hackrf",
        "frequency_hz": 137_100_000,
        "lna_gain": 16,
        "vga_gain": 36,
        "amp": 1,
    },
    "amateur": {
        "label": "Amateur VHF/UHF",
        "ranges": ((144e6, 148e6), (430e6, 450e6)),
        "profile": "raw_iq_hackrf",
        "frequency_hz": 145_825_000,
        "lna_gain": 32,
        "vga_gain": 48,
        "amp": 1,
    },
    "lband": {
        "label": "L-band / patch",
        "ranges": ((1525e6, 1710e6),),
        "profile": "raw_iq_hackrf",
        "frequency_hz": 1_545_000_000,
        "lna_gain": 32,
        "vga_gain": 48,
        "amp": 1,
    },
    "adsb": {
        "label": "1090 / ADS-B antenna",
        "ranges": ((1087e6, 1093e6),),
        "profile": "raw_iq_hackrf",
        "frequency_hz": 1_090_000_000,
        "lna_gain": 32,
        "vga_gain": 48,
        "amp": 1,
    },
}
BAND_PRIORITY = ("vdipole", "amateur", "lband", "adsb")

LAT = 40.42
LON = -86.88
ALT_M = 180

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(TX_CACHE_DIR, exist_ok=True)
os.makedirs(SAT_CACHE_DIR, exist_ok=True)


def first_value(qs, name, default=None):
    return qs.get(name, [default])[0]


def float_param(qs, name, default=None, required=False):
    value = first_value(qs, name, default)
    if value is None:
        if required:
            raise ValueError(f"missing required parameter: {name}")
        return None
    return float(value)


def int_param(qs, name, default=None):
    value = first_value(qs, name, default)
    return None if value is None else int(value)


def write_json(handler, status, payload):
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def read_rules():
    if not os.path.exists(RULES_PATH):
        return []
    with open(RULES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def write_rules(rules):
    write_json_file(RULES_PATH, rules)


def read_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data


def write_json_file(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_commands():
    data = read_json_file(COMMANDS_PATH, [])
    return data if isinstance(data, list) else []


def write_commands(commands):
    write_json_file(COMMANDS_PATH, commands)


def enqueue_scheduler_command(command):
    commands = read_commands()
    commands.append(command)
    write_commands(commands)
    return command


def scheduler_status():
    status = read_json_file(STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    updated_at = status.get("updated_at")
    age_s = None
    if updated_at:
        try:
            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_s = max(0, datetime.now(timezone.utc).timestamp() - updated.timestamp())
        except Exception:
            age_s = None
    queue = read_commands()
    is_fresh = age_s is not None and age_s < 120
    live = bool(status.get("live")) and is_fresh
    return {
        **status,
        "live": live,
        "fresh": is_fresh,
        "status_age_s": age_s,
        "queue_count": len(queue),
        "commands_path": COMMANDS_PATH,
        "status_path": STATUS_PATH,
    }


def read_captures(norad=None):
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    if norad is not None:
        data = [r for r in data if r.get("norad") == norad]
    # Freshen report_path: check if the report file exists on disk now even if
    # it didn't when the history record was written (monitor runs after).
    for r in data:
        output = r.get("output")
        if output and os.path.isdir(output):
            rp = os.path.join(output, "diagnostic_report.md")
            r["report_path"] = rp if os.path.exists(rp) else None
    return sorted(data, key=lambda r: r.get("started_at", ""), reverse=True)


def safe_output_path(output):
    """Return resolved path only if it's safely under HOME."""
    home = os.path.expanduser("~")
    resolved = os.path.realpath(output)
    if resolved.startswith(home + os.sep) or resolved == home:
        return resolved
    return None


def validate_rule(rule):
    if not isinstance(rule, dict):
        raise ValueError("rule must be an object")
    rule_id = str(rule.get("id") or "").strip()
    if not rule_id:
        raise ValueError("rule.id is required")
    if rule.get("type") != "satellite_recurring":
        raise ValueError("only satellite_recurring rules are supported")
    norad = int(rule.get("norad"))
    if norad <= 0:
        raise ValueError("rule.norad must be positive")
    freq_hz = float(rule.get("frequency_hz"))
    if freq_hz <= 0:
        raise ValueError("rule.frequency_hz must be positive")
    min_el = float(rule.get("min_peak_el", 10))
    if min_el < 0 or min_el > 90:
        raise ValueError("rule.min_peak_el must be between 0 and 90")
    profile = str(rule.get("profile", "raw_iq_hackrf"))
    if profile not in {"meteor_lrpt_hackrf", "raw_iq_hackrf", "satdump_hackrf"}:
        raise ValueError("unsupported rule.profile")
    lna_gain = int(rule.get("lna_gain", 32))
    vga_gain = int(rule.get("vga_gain", 48))
    amp = int(rule.get("amp", 1))
    if lna_gain < 0 or lna_gain > 40:
        raise ValueError("rule.lna_gain must be between 0 and 40")
    if vga_gain < 0 or vga_gain > 62:
        raise ValueError("rule.vga_gain must be between 0 and 62")
    if amp not in {0, 1}:
        raise ValueError("rule.amp must be 0 or 1")
    clean = {
        "id": rule_id,
        "enabled": bool(rule.get("enabled", True)),
        "type": "satellite_recurring",
        "name": str(rule.get("name") or f"NORAD {norad}"),
        "norad": norad,
        "group": str(rule.get("group") or "active"),
        "frequency_hz": freq_hz,
        "profile": profile,
        "lna_gain": lna_gain,
        "vga_gain": vga_gain,
        "amp": amp,
        "min_peak_el": min_el,
        "start_offset_s": int(rule.get("start_offset_s", -30)),
        "end_offset_s": int(rule.get("end_offset_s", 60)),
        "pipeline": str(rule.get("pipeline") or ""),
        "samplerate": str(rule.get("samplerate") or ""),
        "iq_swap": bool(rule.get("iq_swap", False)),
        "created_at": str(rule.get("created_at") or ""),
        "updated_at": str(rule.get("updated_at") or ""),
    }
    return clean


def filter_radio_tles(text):
    out = []
    tles = parse_tles(text)
    for tle in tles:
        name = tle.name.upper()
        if any(term in name for term in RADIO_NAME_TERMS):
            out.extend([tle.name, tle.line1, tle.line2])
    return "\n".join(out) + ("\n" if out else "")


def fetch_transmitters(norad):
    path = os.path.join(TX_CACHE_DIR, f"{int(norad)}.json")
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TX_TTL
    if fresh:
        with open(path, encoding="utf-8") as f:
            return json.load(f), "cache"

    url = f"https://db.satnogs.org/api/transmitters/?satellite__norad_cat_id={int(norad)}"
    req = urllib.request.Request(url, headers={"User-Agent": "satellites-overhead/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("unexpected SatNOGS response")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return data, "satnogs"
    except Exception:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f), "stale cache"
        raise


def tx_frequency(tx):
    return float(tx.get("downlink_low") or tx.get("downlink_high") or 0)


def tx_is_usable(tx):
    return bool(tx) and tx.get("alive") is not False and tx.get("status") != "inactive" and tx_frequency(tx) > 0


def transmitter_bands(txs):
    bands = set()
    for tx in filter(tx_is_usable, txs):
        freq = tx_frequency(tx)
        for band, cfg in BAND_RANGES.items():
            if any(lo <= freq <= hi for lo, hi in cfg["ranges"]):
                bands.add(band)
    return [band for band in BAND_PRIORITY if band in bands]


def select_capture_band(bands, band=None):
    if band in BAND_RANGES:
        return band
    for candidate in BAND_PRIORITY:
        if candidate in bands:
            return candidate
    return "vdipole"


def suggest_capture_settings(norad, band=None):
    txs, source = fetch_transmitters(norad)
    bands = transmitter_bands(txs)
    selected_band = select_capture_band(bands, band)
    cfg = BAND_RANGES[selected_band]
    usable = sorted([tx for tx in txs if tx_is_usable(tx)], key=tx_frequency)
    selected = None
    for tx in usable:
        freq = tx_frequency(tx)
        if any(lo <= freq <= hi for lo, hi in cfg["ranges"]):
            selected = tx
            break
    return {
        "norad": int(norad),
        "source": source,
        "bands": bands or ["unknown"],
        "selected_band": selected_band,
        "profile": cfg["profile"],
        "frequency_hz": tx_frequency(selected) if selected else cfg["frequency_hz"],
        "lna_gain": cfg["lna_gain"],
        "vga_gain": cfg["vga_gain"],
        "amp": cfg["amp"],
        "transmitter": selected,
    }


def validate_scan_now(payload):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    norad = int(payload.get("norad"))
    if norad <= 0:
        raise ValueError("norad must be positive")
    name = str(payload.get("name") or f"NORAD {norad}")
    band = payload.get("band") or ""
    suggested = suggest_capture_settings(norad, band)
    max_el = float(payload.get("max_el", payload.get("el", 0)) or 0)
    vga_gain = int(suggested["vga_gain"])
    if max_el >= 60:
        vga_gain = max(0, vga_gain - 12)
    duration_s = int(payload.get("duration_s", 300) or 300)
    if duration_s < 1 or duration_s > 3600:
        raise ValueError("duration_s must be between 1 and 3600")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "id": f"scan-{norad}-{int(time.time())}",
        "type": "scan_now",
        "queued_at": now,
        "name": name,
        "norad": norad,
        "group": str(payload.get("group") or "radio"),
        "profile": suggested["profile"],
        "frequency_hz": int(float(suggested["frequency_hz"])),
        "lna_gain": int(suggested["lna_gain"]),
        "vga_gain": vga_gain,
        "amp": int(suggested["amp"]),
        "duration_s": duration_s,
        "source": "web",
        "capture_settings": suggested,
        "observer_snapshot": {
            "el": payload.get("el"),
            "az": payload.get("az"),
            "range": payload.get("range"),
        },
    }


def fetch_satellite(norad):
    path = os.path.join(SAT_CACHE_DIR, f"{int(norad)}.json")
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TX_TTL
    if fresh:
        with open(path, encoding="utf-8") as f:
            return json.load(f), "cache"

    url = f"https://db.satnogs.org/api/satellites/?norad_cat_id={int(norad)}"
    req = urllib.request.Request(url, headers={"User-Agent": "satellites-overhead/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("unexpected SatNOGS response")
        payload = data[0] if data else {}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        return payload, "satnogs"
    except Exception:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f), "stale cache"
        raise


def fetch_tle(group):
    """Return (text, source) where source describes cache freshness."""
    if group == "radio":
        text, source = fetch_tle("active")
        return filter_radio_tles(text), source + "; radio subset"

    path = os.path.join(CACHE_DIR, group + ".tle")
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TTL
    if fresh:
        age = int((time.time() - os.path.getmtime(path)) / 60)
        with open(path, encoding="utf-8") as f:
            return f.read(), f"cache ({age}m old)"

    url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
    req = urllib.request.Request(url, headers={"User-Agent": "satellites-overhead/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
        if "\n1 " not in ("\n" + text):  # sanity: looks like TLE data
            raise ValueError("response did not look like TLE data")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return text, "celestrak (fresh)"
    except Exception as e:
        if os.path.exists(path):  # serve stale rather than fail
            age = int((time.time() - os.path.getmtime(path)) / 60)
            with open(path, encoding="utf-8") as f:
                return f.read(), f"stale cache ({age}m old; live fetch failed: {e})"
        raise


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/tle":
            group = (parse_qs(parsed.query).get("group", ["active"])[0]).lower()
            if group not in ALLOWED:
                self.send_error(400, "unknown group")
                return
            try:
                text, source = fetch_tle(group)
            except Exception as e:
                self.send_error(502, f"could not obtain TLE data: {e}")
                return
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-TLE-Source", source)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            sys.stderr.write(f"[tle] {group}: {source}, {len(body)} bytes\n")
            return
        if parsed.path == "/passes":
            qs = parse_qs(parsed.query)
            group = first_value(qs, "group", "active").lower()
            if group not in ALLOWED:
                self.send_error(400, "unknown group")
                return
            try:
                lat = float_param(qs, "lat", required=True)
                lon = float_param(qs, "lon", required=True)
                alt_m = float_param(qs, "alt_m", 0.0)
                hours = float_param(qs, "hours", 24.0)
                min_el = float_param(qs, "min_el", 10.0)
                min_duration_s = int_param(qs, "min_duration_s", 0)
                track_step_s = int_param(qs, "track_step_s", 1)
                limit = int_param(qs, "limit", 100)
                start = parse_start(first_value(qs, "start"))
                if track_step_s < 1:
                    raise ValueError("track_step_s must be >= 1")
                text, source = fetch_tle(group)
                names = set(qs.get("name", []))
                norads = {int(n) for n in qs.get("norad", [])}
                tles = select_tles(parse_tles(text), names, norads)
                passes = predict_passes(
                    tles,
                    lat=lat,
                    lon=lon,
                    alt_m=alt_m,
                    start=start,
                    hours=hours,
                    min_el=min_el,
                    track_step_s=track_step_s,
                    min_duration_s=min_duration_s,
                    limit=limit,
                )
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(502, f"could not predict passes: {e}")
                return
            write_json(self, 200, passes)
            sys.stderr.write(
                f"[passes] {group}: {source}, {len(tles)} sats, {len(passes)} passes\n"
            )
            return
        if parsed.path == "/scheduler/rules":
            try:
                write_json(self, 200, read_rules())
            except Exception as e:
                self.send_error(500, f"could not read scheduler rules: {e}")
            return
        if parsed.path == "/scheduler/status":
            try:
                write_json(self, 200, scheduler_status())
            except Exception as e:
                self.send_error(500, f"could not read scheduler status: {e}")
            return
        if parsed.path == "/transmitters":
            qs = parse_qs(parsed.query)
            try:
                norad = int(first_value(qs, "norad"))
                data, source = fetch_transmitters(norad)
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(502, f"could not fetch transmitters: {e}")
                return
            write_json(self, 200, data)
            sys.stderr.write(f"[transmitters] {norad}: {source}, {len(data)} records\n")
            return
        if parsed.path == "/capture-settings":
            qs = parse_qs(parsed.query)
            try:
                norad = int(first_value(qs, "norad"))
                band = first_value(qs, "band")
                data = suggest_capture_settings(norad, band)
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(502, f"could not suggest capture settings: {e}")
                return
            write_json(self, 200, data)
            sys.stderr.write(
                f"[capture-settings] {norad}: {data['source']}, {data['selected_band']}\n"
            )
            return
        if parsed.path == "/satellite":
            qs = parse_qs(parsed.query)
            try:
                norad = int(first_value(qs, "norad"))
                data, source = fetch_satellite(norad)
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(502, f"could not fetch satellite details: {e}")
                return
            write_json(self, 200, data)
            sys.stderr.write(f"[satellite] {norad}: {source}\n")
            return
        if parsed.path == "/scheduler/upcoming":
            qs = parse_qs(parsed.query)
            hours = float(first_value(qs, "hours", "24"))
            limit_per_rule = int(first_value(qs, "limit_per_rule", "4"))
            try:
                rules = read_rules()
                results = []
                for rule in rules:
                    if not rule.get("enabled", True):
                        continue
                    if rule.get("type") != "satellite_recurring":
                        continue
                    try:
                        tles_text, _ = fetch_tle(rule.get("group", "radio"))
                        tles = select_tles(parse_tles(tles_text), set(), {int(rule["norad"])})
                        passes = predict_passes(tles, lat=LAT, lon=LON, alt_m=ALT_M,
                                               start=parse_start(None), hours=hours,
                                               min_el=rule.get("min_peak_el", 10),
                                               track_step_s=60, limit=limit_per_rule)
                        start_offset_s = int(rule.get("start_offset_s", -30))
                        end_offset_s = int(rule.get("end_offset_s", 60))
                        from datetime import timedelta as _td
                        for p in passes:
                            aos = datetime.fromisoformat(p["aos"].replace("Z", "+00:00"))
                            los = datetime.fromisoformat(p["los"].replace("Z", "+00:00"))
                            fire = aos + _td(seconds=start_offset_s)
                            end = los + _td(seconds=end_offset_s)
                            vga = int(rule.get("vga_gain", 48))
                            if float(p.get("max_el", 0)) >= 60:
                                vga = max(0, vga - 12)
                            results.append({
                                "rule_id": rule["id"],
                                "name": rule.get("name", p["name"]),
                                "norad": rule["norad"],
                                "fire_time": fire.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "aos": p["aos"],
                                "los": p["los"],
                                "max_el": p["max_el"],
                                "duration_s": int(p["duration_s"]) - start_offset_s + end_offset_s,
                                "vga_gain": vga,
                            })
                    except Exception:
                        continue
                results.sort(key=lambda r: r["fire_time"])
            except Exception as e:
                self.send_error(500, f"could not compute upcoming runs: {e}")
                return
            write_json(self, 200, results)
            return
        if parsed.path == "/captures":
            qs = parse_qs(parsed.query)
            norad_str = first_value(qs, "norad")
            try:
                norad = int(norad_str) if norad_str else None
                data = read_captures(norad)
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(500, f"could not read capture history: {e}")
                return
            write_json(self, 200, data)
            return
        if parsed.path.startswith("/captures/") and parsed.path.endswith("/report"):
            capture_id = parsed.path[len("/captures/"):-len("/report")]
            try:
                record = next((r for r in read_captures() if r.get("id") == capture_id), None)
                if record is None:
                    self.send_error(404, "capture not found")
                    return
                rp = record.get("report_path")
                if not rp or not os.path.exists(rp):
                    self.send_error(404, "no diagnostic report for this capture")
                    return
                safe = safe_output_path(rp)
                if not safe:
                    self.send_error(403, "report path outside home directory")
                    return
                with open(safe, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(500, f"could not read report: {e}")
            return
        if parsed.path.startswith("/captures/") and parsed.path.endswith("/download"):
            capture_id = parsed.path[len("/captures/"):-len("/download")]
            try:
                all_captures = read_captures()
                record = next((r for r in all_captures if r.get("id") == capture_id), None)
                if record is None:
                    self.send_error(404, "capture not found")
                    return
                output = record.get("output")
                if not output:
                    self.send_error(404, "capture has no output path")
                    return
                safe = safe_output_path(output)
                if not safe or not os.path.exists(safe):
                    self.send_error(404, "capture output not found on disk")
                    return
                basename = os.path.basename(safe.rstrip("/"))
                if os.path.isdir(safe):
                    filename = f"{basename}.tar.gz"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/gzip")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.end_headers()
                    with tarfile.open(fileobj=self.wfile, mode="w|gz") as tar:
                        tar.add(safe, arcname=basename)
                else:
                    size = os.path.getsize(safe)
                    filename = basename
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Length", str(size))
                    self.end_headers()
                    with open(safe, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
            except BrokenPipeError:
                pass
            except Exception as e:
                sys.stderr.write(f"[captures/download] error: {e}\n")
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/scheduler/rules":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                incoming = validate_rule(json.loads(body))
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                incoming["updated_at"] = now
                if not incoming["created_at"]:
                    incoming["created_at"] = now
                rules = read_rules()
                replaced = False
                for i, rule in enumerate(rules):
                    if rule.get("id") == incoming["id"]:
                        incoming["created_at"] = rule.get("created_at") or incoming["created_at"]
                        rules[i] = incoming
                        replaced = True
                        break
                if not replaced:
                    rules.append(incoming)
                write_rules(rules)
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(500, f"could not save scheduler rule: {e}")
                return
            write_json(self, 200, incoming)
            sys.stderr.write(f"[scheduler] saved rule {incoming['id']}\n")
            return
        if parsed.path == "/scheduler/scan-now":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                command = validate_scan_now(json.loads(body))
                enqueue_scheduler_command(command)
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(500, f"could not queue scan: {e}")
                return
            write_json(self, 200, {"queued": True, "command": command, "status": scheduler_status()})
            sys.stderr.write(f"[scheduler] queued scan {command['id']}\n")
            return
        super().do_GET()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/scheduler/rules/"):
            rule_id = parsed.path.rsplit("/", 1)[-1]
            try:
                rules = read_rules()
                next_rules = [rule for rule in rules if str(rule.get("id")) != rule_id]
                write_rules(next_rules)
            except Exception as e:
                self.send_error(500, f"could not delete scheduler rule: {e}")
                return
            write_json(self, 200, {"deleted": rule_id, "count": len(next_rules)})
            sys.stderr.write(f"[scheduler] deleted rule {rule_id}\n")
            return
        super().do_GET()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving {ROOT} on http://localhost:{PORT}  (TLE proxy at /tle?group=active)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
