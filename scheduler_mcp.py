#!/usr/bin/env python3
"""MCP stdio facade for the SDR scheduler.

This is an adapter only. It reads/writes the same scheduler rule file as the
web UI and scheduler, uses the same Python predictor, and does not require
serve.py or a browser to be running.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from predict import load_tles, look_at, make_observer, parse_start, predict_passes, select_tles

try:
    import ephem
except ImportError as exc:
    raise SystemExit("scheduler_mcp.py requires pyephem: python3 -m pip install ephem") from exc


ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
RULES_PATH = os.path.join(HOME, "sdr_scheduler_rules.json")
SCHEDULER_PATH = os.path.join(HOME, "sdr_scheduler.py")
SCHEDULER_BACKUP = os.path.join(ROOT, "scheduler", "sdr_scheduler.py")
LOG_PATH = os.path.join(HOME, "sdr_scheduler.log")
MCP_DEBUG_LOG = os.path.join(HOME, "sdr_scheduler_mcp.log")
TX_CACHE_DIR = os.path.join(ROOT, ".txcache")
SAT_CACHE_DIR = os.path.join(ROOT, ".satcache")
TLE_CACHE_DIR = os.path.join(ROOT, ".tlecache")
TX_TTL = 7 * 24 * 3600
DEFAULT_LAT = 40.42
DEFAULT_LON = -86.88
DEFAULT_ALT_M = 180.0
CAPTURE_PROFILES = {"meteor_lrpt_hackrf", "raw_iq_hackrf"}
RADIO_NAME_TERMS = (
    "ISS", "METEOR", "NOAA", "FENGYUN", "METOP", "AQUA", "TERRA", "SUOMI",
    "LANDSAT", "OKEAN", "SICH", "RESURS", "ELEKTRO", "GOES", "HAMSAT",
    "AO-", "SO-", "FO-", "IO-", "RS-", "CAS-", "XW-", "TEVEL", "LILACSAT",
    "SKYTERRA", "INMARSAT", "IRIDIUM", "GLOBALSTAR", "ORBCOMM",
)
BAND_RANGES = {
    "vdipole": {"label": "V-dipole VHF", "ranges": [(136e6, 138e6)], "profile": "meteor_lrpt_hackrf", "frequency_hz": 137_100_000},
    "amateur": {"label": "Amateur VHF/UHF", "ranges": [(144e6, 148e6), (430e6, 450e6)], "profile": "raw_iq_hackrf", "frequency_hz": 145_825_000},
    "lband": {"label": "L-band / patch", "ranges": [(1525e6, 1710e6)], "profile": "raw_iq_hackrf", "frequency_hz": 1_545_000_000},
    "adsb": {"label": "1090 / ADS-B antenna", "ranges": [(1087e6, 1093e6)], "profile": "raw_iq_hackrf", "frequency_hz": 1_090_000_000},
}


def debug(message: str) -> None:
    if os.environ.get("SDR_SCHEDULER_MCP_DEBUG", "1") in {"0", "false", "False"}:
        return
    try:
        with open(MCP_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except Exception:
        pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_rules() -> list[dict[str, Any]]:
    if not os.path.exists(RULES_PATH):
        return []
    with open(RULES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def write_rules(rules: list[dict[str, Any]]) -> None:
    tmp = RULES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
        f.write("\n")
    os.replace(tmp, RULES_PATH)


def validate_rule(rule: dict[str, Any]) -> dict[str, Any]:
    rule_id = str(rule.get("id") or "").strip()
    if not rule_id:
        raise ValueError("rule.id is required")
    if rule.get("type") != "satellite_recurring":
        raise ValueError("only satellite_recurring rules are supported")
    norad = int(rule.get("norad"))
    if norad <= 0:
        raise ValueError("rule.norad must be positive")
    frequency_hz = float(rule.get("frequency_hz"))
    if frequency_hz <= 0:
        raise ValueError("rule.frequency_hz must be positive")
    min_peak_el = float(rule.get("min_peak_el", 10))
    if min_peak_el < 0 or min_peak_el > 90:
        raise ValueError("rule.min_peak_el must be between 0 and 90")
    profile = str(rule.get("profile") or "raw_iq_hackrf")
    if profile not in CAPTURE_PROFILES:
        raise ValueError(f"unsupported rule.profile: {profile}")
    return {
        "id": rule_id,
        "enabled": bool(rule.get("enabled", True)),
        "type": "satellite_recurring",
        "name": str(rule.get("name") or f"NORAD {norad}"),
        "norad": norad,
        "group": str(rule.get("group") or "radio"),
        "frequency_hz": frequency_hz,
        "profile": profile,
        "min_peak_el": min_peak_el,
        "start_offset_s": int(rule.get("start_offset_s", -30)),
        "end_offset_s": int(rule.get("end_offset_s", 60)),
        "created_at": str(rule.get("created_at") or ""),
        "updated_at": str(rule.get("updated_at") or ""),
    }


def upsert_rule(rule: dict[str, Any]) -> dict[str, Any]:
    incoming = validate_rule(rule)
    timestamp = now_iso()
    incoming["updated_at"] = timestamp
    if not incoming["created_at"]:
        incoming["created_at"] = timestamp
    rules = read_rules()
    for i, existing in enumerate(rules):
        if str(existing.get("id")) == incoming["id"]:
            incoming["created_at"] = existing.get("created_at") or incoming["created_at"]
            rules[i] = incoming
            write_rules(rules)
            return incoming
    rules.append(incoming)
    write_rules(rules)
    return incoming


def find_rule(rule_id: str) -> dict[str, Any]:
    for rule in read_rules():
        if str(rule.get("id")) == str(rule_id):
            return rule
    raise ValueError(f"rule not found: {rule_id}")


def update_rule_fields(rule_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    rule = find_rule(rule_id)
    rule.update(updates)
    return upsert_rule(rule)


def delete_rule(rule_id: str) -> dict[str, Any]:
    rules = read_rules()
    next_rules = [rule for rule in rules if str(rule.get("id")) != str(rule_id)]
    write_rules(next_rules)
    return {"deleted": rule_id, "removed": len(rules) - len(next_rules), "count": len(next_rules)}


def load_group_tles(group: str):
    if group == "radio":
        tles = load_tles("active")
        return [tle for tle in tles if any(term in tle.name.upper() for term in RADIO_NAME_TERMS)]
    return load_tles(group)


def tx_frequency(tx: dict[str, Any]) -> float:
    return float(tx.get("downlink_low") or tx.get("downlink_high") or 0)


def tx_is_usable(tx: dict[str, Any]) -> bool:
    return bool(tx) and tx.get("alive") is not False and tx.get("status") != "inactive" and tx_frequency(tx) > 0


def fetch_cached_json(cache_dir: str, cache_name: str, url: str, expect_list: bool | None = None):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, cache_name)
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TX_TTL
    if fresh:
        with open(path, encoding="utf-8") as f:
            return json.load(f), "cache"
    req = urllib.request.Request(url, headers={"User-Agent": "satellites-overhead-mcp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if expect_list is True and not isinstance(data, list):
            raise ValueError("unexpected non-list response")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return data, "satnogs"
    except Exception:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f), "stale cache"
        raise


def fetch_transmitters(norad: int):
    url = f"https://db.satnogs.org/api/transmitters/?satellite__norad_cat_id={int(norad)}"
    return fetch_cached_json(TX_CACHE_DIR, f"{int(norad)}.json", url, expect_list=True)


def fetch_satellite(norad: int):
    url = f"https://db.satnogs.org/api/satellites/?norad_cat_id={int(norad)}"
    data, source = fetch_cached_json(SAT_CACHE_DIR, f"{int(norad)}.json", url, expect_list=True)
    return (data[0] if data else {}), source


def transmitter_bands(txs: list[dict[str, Any]]) -> list[str]:
    bands = set()
    for tx in filter(tx_is_usable, txs):
        freq = tx_frequency(tx)
        for band, cfg in BAND_RANGES.items():
            if any(lo <= freq <= hi for lo, hi in cfg["ranges"]):
                bands.add(band)
    return sorted(bands)


def predict_for_args(args: dict[str, Any]) -> list[dict[str, Any]]:
    group = str(args.get("group") or "radio")
    names = set(args.get("name") or args.get("names") or [])
    norads = {int(n) for n in args.get("norad") or args.get("norads") or []}
    tles = select_tles(load_group_tles(group), names, norads)
    return predict_passes(
        tles,
        lat=float(args.get("lat", DEFAULT_LAT)),
        lon=float(args.get("lon", DEFAULT_LON)),
        alt_m=float(args.get("alt_m", DEFAULT_ALT_M)),
        start=parse_start(args.get("start")),
        hours=float(args.get("hours", 24)),
        min_el=float(args.get("min_el", 10)),
        min_duration_s=int(args.get("min_duration_s", 0)),
        track_step_s=int(args.get("track_step_s", 60)),
        limit=int(args["limit"]) if args.get("limit") is not None else 50,
    )


def build_rule_id(norad: int, profile: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "-" for ch in f"sat-{int(norad)}-{profile}")


def make_rule_from_args(args: dict[str, Any]) -> dict[str, Any]:
    norad = int(args["norad"])
    profile = str(args.get("profile") or "raw_iq_hackrf")
    return {
        "id": str(args.get("id") or build_rule_id(norad, profile)),
        "enabled": bool(args.get("enabled", True)),
        "type": "satellite_recurring",
        "name": str(args.get("name") or f"NORAD {norad}"),
        "norad": norad,
        "group": str(args.get("group") or "radio"),
        "frequency_hz": float(args["frequency_hz"]),
        "profile": profile,
        "min_peak_el": float(args.get("min_peak_el", 10)),
        "start_offset_s": int(args.get("start_offset_s", -30)),
        "end_offset_s": int(args.get("end_offset_s", 60)),
    }


def rule_jobs(rule: dict[str, Any], hours: float = 24, limit: int = 4) -> list[dict[str, Any]]:
    passes = predict_for_args({
        "group": rule.get("group", "radio"),
        "norads": [rule["norad"]],
        "hours": hours,
        "min_el": rule.get("min_peak_el", 10),
        "track_step_s": 60,
        "limit": limit,
    })
    jobs = []
    for p in passes:
        aos = datetime.fromisoformat(p["aos"].replace("Z", "+00:00"))
        fire_dt = aos + timedelta(seconds=int(rule.get("start_offset_s", -30)))
        duration_s = max(1, int(p["duration_s"]) - int(rule.get("start_offset_s", -30)) + int(rule.get("end_offset_s", 60)))
        jobs.append({
            "rule_id": rule.get("id"),
            "name": rule.get("name") or p["name"],
            "norad": rule["norad"],
            "profile": rule.get("profile"),
            "frequency_hz": rule.get("frequency_hz"),
            "fire_time": iso(fire_dt),
            "aos": p["aos"],
            "los": p["los"],
            "duration_s": duration_s,
            "max_el": p["max_el"],
            "pass": p,
        })
    return jobs


def all_upcoming_jobs(hours: float = 24, limit_per_rule: int = 4) -> list[dict[str, Any]]:
    jobs = []
    for rule in read_rules():
        if rule.get("enabled", True) and rule.get("type") == "satellite_recurring":
            jobs.extend(rule_jobs(rule, hours, limit_per_rule))
    return sorted(jobs, key=lambda job: job["fire_time"])


def get_status() -> dict[str, Any]:
    log_tail = []
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            log_tail = f.readlines()[-20:]
    return {
        "rules_path": RULES_PATH,
        "rule_count": len(read_rules()),
        "enabled_rule_count": sum(1 for r in read_rules() if r.get("enabled", True)),
        "scheduler_path": SCHEDULER_PATH,
        "scheduler_exists": os.path.exists(SCHEDULER_PATH),
        "scheduler_backup": SCHEDULER_BACKUP,
        "scheduler_backup_exists": os.path.exists(SCHEDULER_BACKUP),
        "log_path": LOG_PATH,
        "log_exists": os.path.exists(LOG_PATH),
        "log_tail": [line.rstrip("\n") for line in log_tail],
        "tle_cache_dir": TLE_CACHE_DIR,
    }


def run_now(args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("confirm"):
        raise ValueError("run_scheduler_rule_now requires confirm=true")
    rule = find_rule(str(args["rule_id"]))
    jobs = rule_jobs(rule, hours=float(args.get("hours", 24)), limit=1)
    if not jobs:
        raise ValueError("no upcoming pass found for rule")
    job = jobs[0]
    duration_s = int(args.get("duration_s") or min(job["duration_s"], 600))
    freq = int(float(rule["frequency_hz"]))
    label = str(rule.get("name") or rule["id"]).replace("/", "_")
    outdir = os.path.join(HOME, "cosmos_captures")
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if rule.get("profile") == "meteor_lrpt_hackrf":
        capdir = os.path.join(HOME, "noaa_captures", f"{label}_{stamp}")
        cmd = [
            "satdump", "live", "meteor_m2-x_lrpt", capdir,
            "--source", "hackrf", "--samplerate", "2e6",
            "--frequency", str(freq), "--lna_gain", "32", "--vga_gain", "48",
            "--timeout", str(duration_s),
        ]
    else:
        outfile = os.path.join(outdir, f"{label}_{stamp}.iq")
        cmd = ["hackrf_transfer", "-r", outfile, "-f", str(freq), "-s", "2000000", "-l", "32", "-g", "40", "-a", "1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"pid": proc.pid, "command": cmd, "duration_s": duration_s, "source_job": job}


def list_radio_targets(args: dict[str, Any]) -> list[dict[str, Any]]:
    query = str(args.get("query") or "").lower()
    limit = int(args.get("limit", 200))
    out = []
    for tle in load_group_tles(str(args.get("group") or "radio")):
        if query and query not in tle.name.lower() and query not in str(tle.norad):
            continue
        out.append({"name": tle.name, "norad": tle.norad})
        if len(out) >= limit:
            break
    return out


def list_overhead_now(args: dict[str, Any]) -> list[dict[str, Any]]:
    group = str(args.get("group") or "radio")
    min_el = float(args.get("min_el", 0))
    at = parse_start(args.get("at"))
    obs = make_observer(float(args.get("lat", DEFAULT_LAT)), float(args.get("lon", DEFAULT_LON)), float(args.get("alt_m", DEFAULT_ALT_M)), at)
    out = []
    for tle in load_group_tles(group):
        sat = ephem.readtle(tle.name, tle.line1, tle.line2)
        sample = look_at(sat, obs, at)
        if sample["el"] >= min_el:
            out.append({"name": tle.name, "norad": tle.norad, **sample})
    out.sort(key=lambda row: row["el"], reverse=True)
    return out[: int(args.get("limit", 100))]


def suggest_capture_settings(args: dict[str, Any]) -> dict[str, Any]:
    norad = int(args["norad"])
    txs, source = fetch_transmitters(norad)
    bands = transmitter_bands(txs)
    band = str(args.get("band") or (bands[0] if bands else "vdipole"))
    cfg = BAND_RANGES.get(band, BAND_RANGES["vdipole"])
    usable = sorted([tx for tx in txs if tx_is_usable(tx)], key=tx_frequency)
    selected = None
    for tx in usable:
        freq = tx_frequency(tx)
        if any(lo <= freq <= hi for lo, hi in cfg["ranges"]):
            selected = tx
            break
    return {
        "norad": norad,
        "source": source,
        "bands": bands or ["unknown"],
        "selected_band": band,
        "profile": cfg["profile"],
        "frequency_hz": tx_frequency(selected) if selected else cfg["frequency_hz"],
        "transmitter": selected,
    }


def tool_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


def schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


TOOLS = [
    {"name": "list_scheduler_rules", "description": "List all SDR scheduler rules.", "inputSchema": schema({})},
    {"name": "get_scheduler_rule", "description": "Get one scheduler rule by id.", "inputSchema": schema({"rule_id": {"type": "string"}}, ["rule_id"])},
    {"name": "add_satellite_rule", "description": "Create or replace a recurring satellite scheduler rule.", "inputSchema": schema({
        "norad": {"type": "integer"}, "name": {"type": "string"}, "frequency_hz": {"type": "number"},
        "profile": {"type": "string", "enum": sorted(CAPTURE_PROFILES)}, "group": {"type": "string"},
        "min_peak_el": {"type": "number"}, "start_offset_s": {"type": "integer"}, "end_offset_s": {"type": "integer"},
        "enabled": {"type": "boolean"}, "id": {"type": "string"},
    }, ["norad", "frequency_hz"])},
    {"name": "update_scheduler_rule", "description": "Patch a scheduler rule by id.", "inputSchema": schema({"rule_id": {"type": "string"}, "updates": {"type": "object"}}, ["rule_id", "updates"])},
    {"name": "delete_scheduler_rule", "description": "Delete a scheduler rule by id.", "inputSchema": schema({"rule_id": {"type": "string"}}, ["rule_id"])},
    {"name": "enable_scheduler_rule", "description": "Enable a scheduler rule by id.", "inputSchema": schema({"rule_id": {"type": "string"}}, ["rule_id"])},
    {"name": "disable_scheduler_rule", "description": "Disable a scheduler rule by id.", "inputSchema": schema({"rule_id": {"type": "string"}}, ["rule_id"])},
    {"name": "predict_satellite_passes", "description": "Predict satellite passes using cached TLEs.", "inputSchema": schema({
        "group": {"type": "string"}, "norads": {"type": "array", "items": {"type": "integer"}}, "names": {"type": "array", "items": {"type": "string"}},
        "lat": {"type": "number"}, "lon": {"type": "number"}, "alt_m": {"type": "number"}, "start": {"type": "string"},
        "hours": {"type": "number"}, "min_el": {"type": "number"}, "track_step_s": {"type": "integer"}, "limit": {"type": "integer"},
    })},
    {"name": "list_overhead_now", "description": "List satellites currently above the selected elevation.", "inputSchema": schema({
        "group": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"}, "alt_m": {"type": "number"},
        "min_el": {"type": "number"}, "limit": {"type": "integer"}, "at": {"type": "string"},
    })},
    {"name": "list_radio_targets", "description": "List cached radio target satellites.", "inputSchema": schema({"query": {"type": "string"}, "group": {"type": "string"}, "limit": {"type": "integer"}})},
    {"name": "get_satellite_details", "description": "Get SatNOGS satellite metadata by NORAD id.", "inputSchema": schema({"norad": {"type": "integer"}}, ["norad"])},
    {"name": "list_satellite_transmitters", "description": "Get SatNOGS transmitter records by NORAD id.", "inputSchema": schema({"norad": {"type": "integer"}}, ["norad"])},
    {"name": "suggest_capture_settings", "description": "Suggest frequency/profile from transmitter records and antenna band.", "inputSchema": schema({"norad": {"type": "integer"}, "band": {"type": "string"}}, ["norad"])},
    {"name": "list_upcoming_scheduler_runs", "description": "List upcoming jobs generated from enabled rules.", "inputSchema": schema({"hours": {"type": "number"}, "limit_per_rule": {"type": "integer"}})},
    {"name": "dry_run_scheduler_rule", "description": "Show jobs a scheduler rule would create.", "inputSchema": schema({"rule_id": {"type": "string"}, "hours": {"type": "number"}, "limit": {"type": "integer"}}, ["rule_id"])},
    {"name": "run_scheduler_rule_now", "description": "Start an immediate capture for a rule. Requires confirm=true.", "inputSchema": schema({"rule_id": {"type": "string"}, "confirm": {"type": "boolean"}, "hours": {"type": "number"}, "duration_s": {"type": "integer"}}, ["rule_id", "confirm"])},
    {"name": "get_scheduler_status", "description": "Return scheduler paths, rule counts, cache paths, and log tail.", "inputSchema": schema({})},
]


def call_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "list_scheduler_rules":
        return read_rules()
    if name == "get_scheduler_rule":
        return find_rule(str(args["rule_id"]))
    if name == "add_satellite_rule":
        return upsert_rule(make_rule_from_args(args))
    if name == "update_scheduler_rule":
        return update_rule_fields(str(args["rule_id"]), dict(args["updates"]))
    if name == "delete_scheduler_rule":
        return delete_rule(str(args["rule_id"]))
    if name == "enable_scheduler_rule":
        return update_rule_fields(str(args["rule_id"]), {"enabled": True})
    if name == "disable_scheduler_rule":
        return update_rule_fields(str(args["rule_id"]), {"enabled": False})
    if name == "predict_satellite_passes":
        return predict_for_args(args)
    if name == "list_overhead_now":
        return list_overhead_now(args)
    if name == "list_radio_targets":
        return list_radio_targets(args)
    if name == "get_satellite_details":
        data, source = fetch_satellite(int(args["norad"]))
        return {"source": source, "satellite": data}
    if name == "list_satellite_transmitters":
        data, source = fetch_transmitters(int(args["norad"]))
        return {"source": source, "transmitters": data}
    if name == "suggest_capture_settings":
        return suggest_capture_settings(args)
    if name == "list_upcoming_scheduler_runs":
        return all_upcoming_jobs(float(args.get("hours", 24)), int(args.get("limit_per_rule", 4)))
    if name == "dry_run_scheduler_rule":
        return rule_jobs(find_rule(str(args["rule_id"])), float(args.get("hours", 24)), int(args.get("limit", 4)))
    if name == "run_scheduler_rule_now":
        return run_now(args)
    if name == "get_scheduler_status":
        return get_status()
    raise ValueError(f"unknown tool: {name}")


def read_message() -> dict[str, Any] | None:
    header = b""
    while b"\r\n\r\n" not in header and b"\n\n" not in header:
        ch = sys.stdin.buffer.read(1)
        if not ch:
            debug("stdin closed")
            return None
        header += ch
    if b"\r\n\r\n" in header:
        header_bytes, rest = header.split(b"\r\n\r\n", 1)
    else:
        header_bytes, rest = header.split(b"\n\n", 1)
    length = None
    for line in header_bytes.decode("ascii", errors="replace").splitlines():
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
            break
    if length is None:
        debug(f"missing Content-Length in header: {header_bytes!r}")
        raise RuntimeError("missing Content-Length")
    body = rest + sys.stdin.buffer.read(length - len(rest))
    message = json.loads(body[:length].decode("utf-8"))
    debug(f"recv method={message.get('method')} id={message.get('id')}")
    return message


def write_message(message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()
    debug(f"sent id={message.get('id')} keys={list(message.keys())}")


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    if "id" not in message:
        return None
    msg_id = message["id"]
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "sdr-scheduler", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = tool_result(call_tool(params["name"], params.get("arguments") or {}))
        else:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(exc)}}


def main() -> int:
    debug(f"start argv={sys.argv!r} cwd={os.getcwd()!r}")
    while True:
        message = read_message()
        if message is None:
            return 0
        response = handle(message)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
