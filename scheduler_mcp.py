#!/usr/bin/env python3
"""MCP stdio facade for the SDR scheduler.

This is an adapter only. It reads/writes the same scheduler rule file as the
web UI and scheduler, uses the same Python predictor, and does not require
serve.py or a browser to be running.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from predict import load_tles, look_at, make_observer, parse_start, predict_passes, select_tles

try:
    import ephem
except ImportError as exc:
    raise SystemExit("scheduler_mcp.py requires pyephem: python3 -m pip install ephem") from exc


ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
RULES_PATH = os.path.join(HOME, "sdr_scheduler_rules.json")
COMMANDS_PATH = os.path.join(HOME, "sdr_scheduler_commands.json")
STATUS_PATH = os.path.join(HOME, "sdr_scheduler_status.json")
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
CAPTURE_PROFILES = {"meteor_lrpt_hackrf", "raw_iq_hackrf", "satdump_hackrf"}
RADIO_NAME_TERMS = (
    "ISS", "METEOR", "NOAA", "FENGYUN", "METOP", "AQUA", "TERRA", "SUOMI",
    "LANDSAT", "OKEAN", "SICH", "RESURS", "ELEKTRO", "GOES", "HAMSAT",
    "AO-", "SO-", "FO-", "IO-", "RS-", "CAS-", "XW-", "TEVEL", "LILACSAT",
    "SKYTERRA", "INMARSAT", "IRIDIUM", "GLOBALSTAR", "ORBCOMM",
)
BAND_RANGES = {
    "vdipole": {"label": "V-dipole VHF", "ranges": [(136e6, 138e6)], "profile": "meteor_lrpt_hackrf", "frequency_hz": 137_100_000, "lna_gain": 16, "vga_gain": 36, "amp": 1},
    "amateur": {"label": "Amateur VHF/UHF", "ranges": [(144e6, 148e6), (430e6, 450e6)], "profile": "raw_iq_hackrf", "frequency_hz": 145_825_000, "lna_gain": 32, "vga_gain": 48, "amp": 1},
    "lband": {"label": "L-band / patch", "ranges": [(1525e6, 1710e6)], "profile": "raw_iq_hackrf", "frequency_hz": 1_545_000_000, "lna_gain": 32, "vga_gain": 48, "amp": 1},
    "adsb": {"label": "1090 / ADS-B antenna", "ranges": [(1087e6, 1093e6)], "profile": "raw_iq_hackrf", "frequency_hz": 1_090_000_000, "lna_gain": 32, "vga_gain": 48, "amp": 1},
}
BAND_PRIORITY = ("vdipole", "amateur", "lband", "adsb")


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
    write_json_file(RULES_PATH, rules)


def read_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json_file(path: str, payload) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_commands() -> list[dict[str, Any]]:
    data = read_json_file(COMMANDS_PATH, [])
    return data if isinstance(data, list) else []


def write_commands(commands: list[dict[str, Any]]) -> None:
    write_json_file(COMMANDS_PATH, commands)


def enqueue_scheduler_command(command: dict[str, Any]) -> dict[str, Any]:
    commands = read_commands()
    commands.append(command)
    write_commands(commands)
    return command


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
    lna_gain = int(rule.get("lna_gain", 32))
    vga_gain = int(rule.get("vga_gain", 48))
    amp = int(rule.get("amp", 1))
    if lna_gain < 0 or lna_gain > 40:
        raise ValueError("rule.lna_gain must be between 0 and 40")
    if vga_gain < 0 or vga_gain > 62:
        raise ValueError("rule.vga_gain must be between 0 and 62")
    if amp not in {0, 1}:
        raise ValueError("rule.amp must be 0 or 1")
    return {
        "id": rule_id,
        "enabled": bool(rule.get("enabled", True)),
        "type": "satellite_recurring",
        "name": str(rule.get("name") or f"NORAD {norad}"),
        "norad": norad,
        "group": str(rule.get("group") or "radio"),
        "frequency_hz": frequency_hz,
        "profile": profile,
        "lna_gain": lna_gain,
        "vga_gain": vga_gain,
        "amp": amp,
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
    return [band for band in BAND_PRIORITY if band in bands]


def select_capture_band(bands: list[str], band: str = "") -> str:
    if band in BAND_RANGES:
        return band
    for candidate in BAND_PRIORITY:
        if candidate in bands:
            return candidate
    return "vdipole"


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
        "lna_gain": int(args.get("lna_gain", 32)),
        "vga_gain": int(args.get("vga_gain", 48)),
        "amp": int(args.get("amp", 1)),
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
            "lna_gain": rule.get("lna_gain", 32),
            "vga_gain": rule.get("vga_gain", 48),
            "amp": rule.get("amp", 1),
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
    scheduler_status = read_json_file(STATUS_PATH, {})
    if not isinstance(scheduler_status, dict):
        scheduler_status = {}
    return {
        "rules_path": RULES_PATH,
        "rule_count": len(read_rules()),
        "enabled_rule_count": sum(1 for r in read_rules() if r.get("enabled", True)),
        "commands_path": COMMANDS_PATH,
        "queued_command_count": len(read_commands()),
        "status_path": STATUS_PATH,
        "scheduler_status": scheduler_status,
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
    command = {
        "id": f"scan-{rule['norad']}-{int(time.time())}",
        "type": "scan_now",
        "queued_at": now_iso(),
        "name": rule.get("name") or f"NORAD {rule['norad']}",
        "norad": int(rule["norad"]),
        "group": rule.get("group", "radio"),
        "profile": rule.get("profile", "raw_iq_hackrf"),
        "pipeline": rule.get("pipeline", ""),
        "samplerate": rule.get("samplerate", ""),
        "iq_swap": bool(rule.get("iq_swap", False)),
        "frequency_hz": int(float(rule["frequency_hz"])),
        "lna_gain": int(rule.get("lna_gain", 32)),
        "vga_gain": int(rule.get("vga_gain", 48)),
        "amp": int(rule.get("amp", 1)),
        "dc_block": bool(rule["dc_block"]) if "dc_block" in rule else (rule.get("profile") == "meteor_lrpt_hackrf"),
        "duration_s": duration_s,
        "source": "mcp",
        "source_rule_id": rule["id"],
        "source_job": job,
    }
    enqueue_scheduler_command(command)
    return {"queued": True, "command": command, "source_job": job}


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
    band = select_capture_band(bands, str(args.get("band") or ""))
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
        "lna_gain": cfg["lna_gain"],
        "vga_gain": cfg["vga_gain"],
        "amp": cfg["amp"],
        "transmitter": selected,
    }


mcp = FastMCP("sdr-scheduler")


@mcp.tool()
def list_scheduler_rules() -> list[dict[str, Any]]:
    """List all SDR scheduler rules."""
    return read_rules()


@mcp.tool()
def get_scheduler_rule(rule_id: str) -> dict[str, Any]:
    """Get one scheduler rule by id."""
    return find_rule(rule_id)


@mcp.tool()
def add_satellite_rule(
    norad: int,
    frequency_hz: float,
    name: str = "",
    profile: str = "raw_iq_hackrf",
    group: str = "radio",
    min_peak_el: float = 10,
    lna_gain: int = 32,
    vga_gain: int = 48,
    amp: int = 1,
    start_offset_s: int = -30,
    end_offset_s: int = 60,
    enabled: bool = True,
    id: str = "",
) -> dict[str, Any]:
    """Create or replace a recurring satellite scheduler rule."""
    return upsert_rule(make_rule_from_args(locals()))


@mcp.tool()
def update_scheduler_rule(rule_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Patch a scheduler rule by id."""
    return update_rule_fields(rule_id, updates)


@mcp.tool()
def delete_scheduler_rule(rule_id: str) -> dict[str, Any]:
    """Delete a scheduler rule by id."""
    return delete_rule(rule_id)


@mcp.tool()
def enable_scheduler_rule(rule_id: str) -> dict[str, Any]:
    """Enable a scheduler rule by id."""
    return update_rule_fields(rule_id, {"enabled": True})


@mcp.tool()
def disable_scheduler_rule(rule_id: str) -> dict[str, Any]:
    """Disable a scheduler rule by id."""
    return update_rule_fields(rule_id, {"enabled": False})


@mcp.tool()
def predict_satellite_passes(
    group: str = "radio",
    norads: list[int] | None = None,
    names: list[str] | None = None,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    alt_m: float = DEFAULT_ALT_M,
    start: str | None = None,
    hours: float = 24,
    min_el: float = 10,
    min_duration_s: int = 0,
    track_step_s: int = 60,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Predict satellite passes using cached TLEs."""
    return predict_for_args(locals())


@mcp.tool(name="list_overhead_now")
def list_overhead_now_tool(
    group: str = "radio",
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    alt_m: float = DEFAULT_ALT_M,
    min_el: float = 0,
    limit: int = 100,
    at: str | None = None,
) -> list[dict[str, Any]]:
    """List satellites currently above the selected elevation."""
    return list_overhead_now(locals())


@mcp.tool(name="list_radio_targets")
def list_radio_targets_tool(query: str = "", group: str = "radio", limit: int = 200) -> list[dict[str, Any]]:
    """List cached radio target satellites."""
    return list_radio_targets(locals())


@mcp.tool()
def get_satellite_details(norad: int) -> dict[str, Any]:
    """Get SatNOGS satellite metadata by NORAD id."""
    data, source = fetch_satellite(norad)
    return {"source": source, "satellite": data}


@mcp.tool()
def list_satellite_transmitters(norad: int) -> dict[str, Any]:
    """Get SatNOGS transmitter records by NORAD id."""
    data, source = fetch_transmitters(norad)
    return {"source": source, "transmitters": data}


@mcp.tool(name="suggest_capture_settings")
def suggest_capture_settings_tool(norad: int, band: str = "") -> dict[str, Any]:
    """Suggest frequency/profile from transmitter records and antenna band."""
    return suggest_capture_settings(locals())


@mcp.tool()
def list_upcoming_scheduler_runs(hours: float = 24, limit_per_rule: int = 4) -> list[dict[str, Any]]:
    """List upcoming jobs generated from enabled rules."""
    return all_upcoming_jobs(hours, limit_per_rule)


@mcp.tool()
def dry_run_scheduler_rule(rule_id: str, hours: float = 24, limit: int = 4) -> list[dict[str, Any]]:
    """Show jobs a scheduler rule would create."""
    return rule_jobs(find_rule(rule_id), hours, limit)


@mcp.tool()
def run_scheduler_rule_now(rule_id: str, confirm: bool, hours: float = 24, duration_s: int | None = None) -> dict[str, Any]:
    """Start an immediate capture for a rule. Requires confirm=true."""
    return run_now(locals())


@mcp.tool()
def get_scheduler_status() -> dict[str, Any]:
    """Return scheduler paths, rule counts, cache paths, and log tail."""
    return get_status()


if __name__ == "__main__":
    debug(f"start FastMCP argv={sys.argv!r} cwd={os.getcwd()!r}")
    mcp.run(transport="stdio")
