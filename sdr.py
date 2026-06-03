#!/usr/bin/env python3
"""
sdr — CLI for the satellites-overhead scheduler service.

Usage:
    sdr.py status
    sdr.py overhead [--min-el N]
    sdr.py passes [--norad N] [--hours N] [--min-el N]
    sdr.py rules
    sdr.py rule enable <id>
    sdr.py rule disable <id>
    sdr.py captures [--norad N] [--limit N]
    sdr.py scan <norad> [--duration N]
    sdr.py report <capture-id>

Options:
    --url URL       Service base URL [default: http://localhost:8723]
    --json          Raw JSON output
    --help, -h      Show help

Examples:
    sdr.py status
    sdr.py passes --norad 59051 --hours 12
    sdr.py scan 59051 --duration 600
    sdr.py captures --norad 59051
    sdr.py rule enable sat-59051-meteor_lrpt_hackrf
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_URL = "http://localhost:8723"

# ── colour helpers ────────────────────────────────────────────────────────────

_NO_COLOUR = not sys.stdout.isatty() or os.name == "nt"


def _c(code, text):
    return text if _NO_COLOUR else f"\033[{code}m{text}\033[0m"


def green(t):  return _c("32", t)
def yellow(t): return _c("33", t)
def red(t):    return _c("31", t)
def bold(t):   return _c("1",  t)
def dim(t):    return _c("2",  t)
def cyan(t):   return _c("36", t)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def post(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def delete(url):
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get_text(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode()


# ── formatting ────────────────────────────────────────────────────────────────

def fmt_dt(iso):
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return iso


def fmt_dt_short(iso):
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return iso


def fmt_dur(seconds):
    if seconds is None:
        return "—"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def fmt_bytes(n):
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_el(el):
    if el is None:
        return "—"
    el = float(el)
    colour = green if el >= 45 else yellow if el >= 20 else dim
    return colour(f"{el:.1f}°")


def col_widths(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    return widths


def print_table(headers, rows):
    if not rows:
        print(dim("  (no results)"))
        return
    widths = col_widths(rows, headers)
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    print(bold(fmt.format(*headers)))
    print(dim("  " + "  ".join("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def time_until(iso):
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        if delta < 0:
            return dim("now")
        return cyan(f"in {fmt_dur(delta)}")
    except Exception:
        return ""


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_status(args):
    data = get(f"{args.url}/scheduler/status")
    if args.json:
        print(json.dumps(data, indent=2))
        return

    state = data.get("state", "unknown")
    live = data.get("live", False)
    state_str = green("running") if live else (yellow("idle") if state == "idle" else red(state))
    age = data.get("status_age_s")
    age_str = f"  {dim(f'updated {int(age)}s ago')}" if age is not None else ""

    print(f"\n  Scheduler  {state_str}{age_str}")
    print(f"  Queue      {data.get('queue_count', 0)} command(s) pending")

    job = data.get("current_job")
    if job:
        label = job.get("label") or "—"
        msg = data.get("message", "")
        if live:
            freq = job.get("frequency_hz")
            freq_str = f"  {freq/1e6:.3f} MHz" if freq else ""
            out = job.get("output", "")
            print(f"  Job        {bold(label)}{freq_str}")
            if out:
                print(f"  Output     {dim(out)}")
        else:
            fire = fmt_dt_short(job.get("fire_time"))
            until = time_until(job.get("fire_time"))
            print(f"  Next       {bold(label)}  {fire}  {until}")
        if msg:
            print(f"  Status     {dim(msg)}")
    print()


def cmd_overhead(args):
    # No dedicated HTTP endpoint — find passes with AOS in the past and LOS in
    # the future by predicting a short window starting 2h ago.
    from datetime import timedelta
    start = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = (f"lat=40.42&lon=-86.88&alt_m=180&hours=2.5&min_el={args.min_el}"
              f"&group=radio&track_step_s=60&start={start}")
    data = get(f"{args.url}/passes?{params}")
    if args.json:
        print(json.dumps(data, indent=2))
        return
    now_ts = datetime.now(timezone.utc).timestamp()
    overhead = [
        p for p in data
        if (datetime.fromisoformat(p["aos"].replace("Z", "+00:00")).timestamp() <= now_ts <=
            datetime.fromisoformat(p["los"].replace("Z", "+00:00")).timestamp())
    ]
    if not overhead:
        print(dim("  Nothing above the horizon right now."))
        return
    print()
    rows = []
    for p in overhead:
        los_dt = datetime.fromisoformat(p["los"].replace("Z", "+00:00"))
        remaining = int((los_dt.timestamp() - now_ts))
        rows.append((
            p.get("name", "—"),
            p.get("norad", "—"),
            fmt_el(p.get("max_el")),
            cyan(f"LOS in {fmt_dur(remaining)}"),
        ))
    print_table(["Satellite", "NORAD", "Max El", ""], rows)
    print()


def cmd_passes(args):
    params = f"lat=40.42&lon=-86.88&alt_m=180&hours={args.hours}&min_el={args.min_el}&group=radio&track_step_s=60"
    if args.norad:
        params += f"&norad={args.norad}"
    data = get(f"{args.url}/passes?{params}")
    if args.json:
        print(json.dumps(data, indent=2))
        return
    if not data:
        print(dim("  No passes found."))
        return
    print()
    rows = []
    for p in data:
        rows.append((
            p.get("name", "—"),
            p.get("norad", "—"),
            fmt_dt_short(p.get("aos")),
            time_until(p.get("aos")),
            fmt_el(p.get("max_el")),
            fmt_dur(p.get("duration_s")),
        ))
    print_table(["Satellite", "NORAD", "AOS (local)", "Until", "Max El", "Duration"], rows)
    print()


def cmd_rules(args):
    data = get(f"{args.url}/scheduler/rules")
    if args.json:
        print(json.dumps(data, indent=2))
        return
    if not data:
        print(dim("  No rules configured."))
        return
    print()
    rows = []
    for r in data:
        enabled = green("yes") if r.get("enabled") else red("no")
        freq = r.get("frequency_hz")
        freq_str = f"{freq/1e6:.3f}" if freq else "—"
        rows.append((
            r.get("id", "—"),
            r.get("name", "—"),
            enabled,
            freq_str,
            r.get("profile", "—"),
            f'{r.get("lna_gain","?")} / {r.get("vga_gain","?")} / {r.get("amp","?")}',
            f'{r.get("min_peak_el","?")}°',
        ))
    print_table(["ID", "Satellite", "On", "MHz", "Profile", "LNA/VGA/Amp", "Min El"], rows)
    print()


def cmd_rule_toggle(args, enable):
    rules = get(f"{args.url}/scheduler/rules")
    rule = next((r for r in rules if r.get("id") == args.id), None)
    if not rule:
        print(red(f"  Rule '{args.id}' not found."))
        sys.exit(1)
    rule["enabled"] = enable
    result = post(f"{args.url}/scheduler/rules", rule)
    state = green("enabled") if enable else red("disabled")
    print(f"  Rule {bold(args.id)} {state}.")


def cmd_captures(args):
    url = f"{args.url}/captures"
    if args.norad:
        url += f"?norad={args.norad}"
    data = get(url)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    if not data:
        print(dim("  No captures recorded yet."))
        return
    limit = getattr(args, "limit", 20)
    data = data[:limit]
    print()
    rows = []
    for c in data:
        cadu = c.get("cadu_bytes")
        cadu_str = green(fmt_bytes(cadu)) if cadu else dim("no lock")
        has_report = "yes" if c.get("report_path") else dim("—")
        rows.append((
            fmt_dt_short(c.get("started_at")),
            c.get("name", "—"),
            c.get("profile", "—"),
            fmt_dur((
                (datetime.fromisoformat(c["ended_at"].replace("Z", "+00:00")) -
                 datetime.fromisoformat(c["started_at"].replace("Z", "+00:00"))).total_seconds()
            ) if c.get("started_at") and c.get("ended_at") else None),
            fmt_bytes(c.get("size_bytes")),
            cadu_str,
            has_report,
            dim(c.get("id", "")[:8]),
        ))
    print_table(["Time", "Satellite", "Profile", "Duration", "Size", "CADU", "Report", "ID"], rows)
    print()


def cmd_scan(args):
    # Get capture settings first
    settings = get(f"{args.url}/capture-settings?norad={args.norad}")
    payload = {
        "norad": args.norad,
        "name": settings.get("transmitter", {}) and f"NORAD {args.norad}",
        "duration_s": args.duration,
    }
    # Try to get satellite name
    try:
        sat = get(f"{args.url}/satellite?norad={args.norad}")
        payload["name"] = sat.get("name") or f"NORAD {args.norad}"
    except Exception:
        payload["name"] = f"NORAD {args.norad}"

    freq = settings.get("frequency_hz", 0)
    print(f"\n  Queuing scan for {bold(payload['name'])} (NORAD {args.norad})")
    print(f"  Frequency  {freq/1e6:.3f} MHz")
    print(f"  Profile    {settings.get('profile', '—')}")
    print(f"  Gains      LNA={settings.get('lna_gain')} VGA={settings.get('vga_gain')} amp={settings.get('amp')}")
    print(f"  Duration   {fmt_dur(args.duration)}")

    result = post(f"{args.url}/scheduler/scan-now", payload)
    cmd_id = result.get("command", {}).get("id", "—")
    print(f"\n  {green('Queued')}  command id: {dim(cmd_id)}")
    print()


def cmd_report(args):
    text = get_text(f"{args.url}/captures/{args.capture_id}/report")
    print(text)


# ── main ──────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="sdr",
        description="CLI for the satellites-overhead scheduler service.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", default=DEFAULT_URL, metavar="URL",
                   help=f"Service base URL (default: {DEFAULT_URL})")
    p.add_argument("--json", action="store_true", help="Raw JSON output")

    sub = p.add_subparsers(dest="command", metavar="command")
    sub.required = True

    sub.add_parser("status", help="Scheduler status and next job")

    ov = sub.add_parser("overhead", help="Satellites overhead right now")
    ov.add_argument("--min-el", type=float, default=10, metavar="DEG")

    ps = sub.add_parser("passes", help="Upcoming passes")
    ps.add_argument("--norad", type=int, metavar="N")
    ps.add_argument("--hours", type=float, default=24, metavar="N")
    ps.add_argument("--min-el", type=float, default=10, metavar="DEG")

    sub.add_parser("rules", help="List scheduler rules")

    rl = sub.add_parser("rule", help="Enable or disable a rule")
    rl.add_argument("action", choices=["enable", "disable"])
    rl.add_argument("id", metavar="RULE_ID")

    cap = sub.add_parser("captures", help="Capture history")
    cap.add_argument("--norad", type=int, metavar="N")
    cap.add_argument("--limit", type=int, default=20, metavar="N")

    sc = sub.add_parser("scan", help="Queue an immediate capture")
    sc.add_argument("norad", type=int, metavar="NORAD")
    sc.add_argument("--duration", type=int, default=300, metavar="SECONDS")

    rp = sub.add_parser("report", help="Show diagnostic report for a capture")
    rp.add_argument("capture_id", metavar="CAPTURE_ID")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "status":
            cmd_status(args)
        elif args.command == "overhead":
            cmd_overhead(args)
        elif args.command == "passes":
            cmd_passes(args)
        elif args.command == "rules":
            cmd_rules(args)
        elif args.command == "rule":
            cmd_rule_toggle(args, enable=(args.action == "enable"))
        elif args.command == "captures":
            cmd_captures(args)
        elif args.command == "scan":
            cmd_scan(args)
        elif args.command == "report":
            cmd_report(args)
    except urllib.error.URLError as e:
        print(red(f"\n  Cannot reach {args.url}: {e.reason}"))
        print(dim("  Is the service running? systemctl --user status satellites-overhead.service\n"))
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
