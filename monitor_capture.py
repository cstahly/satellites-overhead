#!/usr/bin/env python3
"""
Satellite capture monitor and diagnostic reporter.

Usage:
    python3 monitor_capture.py <capdir> [--check-only]

Reads the satdump log at <capdir>.log, parses signal diagnostics, writes
<capdir>/diagnostic_report.md, and prints a JSON decision record to stdout.

Exit codes:
    0  — capture healthy or complete, no intervention needed
    1  — intervention taken or recommended (see JSON output)
    2  — capture not yet started or log not found
"""
import json
import os
import re
import signal
import sys
import datetime

HOME = os.path.expanduser("~")
STATUS_PATH = os.path.join(HOME, "sdr_scheduler_status.json")


def parse_log(logfile):
    """Return list of sample dicts parsed from satdump live log."""
    samples = []
    snr_re = re.compile(r"SNR\s*:\s*([\d.]+)dB.*Peak SNR\s*:\s*([\d.]+)dB")
    ber_re = re.compile(r"Viterbi\s*:\s*(\w+)\s+BER\s*:\s*([\d.]+),\s*Deframer\s*:\s*(\w+)")
    with open(logfile, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        snr_m = snr_re.search(lines[i])
        if snr_m and i + 1 < len(lines):
            ber_m = ber_re.search(lines[i + 1])
            if ber_m:
                ts_m = re.search(r"\[(\d{2}:\d{2}:\d{2})", lines[i])
                samples.append({
                    "time": ts_m.group(1) if ts_m else None,
                    "snr": float(snr_m.group(1)),
                    "peak_snr": float(snr_m.group(2)),
                    "viterbi": ber_m.group(1),
                    "ber": float(ber_m.group(2)),
                    "deframer": ber_m.group(3),
                })
                i += 2
                continue
        i += 1
    return samples


def classify(samples):
    """Return (status, notes) based on sample history."""
    if not samples:
        return "no_signal", "No demodulator samples found — satdump may not have started yet."

    recent = samples[-3:] if len(samples) >= 3 else samples
    avg_snr = sum(s["snr"] for s in recent) / len(recent)
    avg_ber = sum(s["ber"] for s in recent) / len(recent)
    synced = sum(1 for s in recent if s["deframer"] == "SYNCED")
    viterbi_ok = sum(1 for s in recent if s["viterbi"] == "SYNCED")

    if avg_snr > 28 and avg_ber > 0.1:
        return "saturated", f"ADC saturation likely — SNR {avg_snr:.1f} dB but BER {avg_ber:.3f}. Reduce amp or VGA."

    if avg_snr < 5:
        return "weak", f"Signal too weak — SNR {avg_snr:.1f} dB. Wrong frequency, antenna, or gains."

    if viterbi_ok and avg_ber < 0.05 and synced == 0:
        # Good Viterbi but no deframer sync — the persistent issue
        if avg_snr > 15:
            return "nosync_good_signal", (
                f"Viterbi locked (BER {avg_ber:.3f}), SNR {avg_snr:.1f} dB — but Deframer NOSYNC throughout. "
                "Likely phase/IQ mismatch. Try: --iq_swap, different pipeline (meteor_m2_lrpt), or --samplerate 1e6."
            )
        else:
            return "nosync_marginal", (
                f"Viterbi locked but weak signal — SNR {avg_snr:.1f} dB, BER {avg_ber:.3f}. "
                "May sync with better pass geometry."
            )

    if synced > 0:
        return "synced", f"Deframer SYNCED — SNR {avg_snr:.1f} dB, BER {avg_ber:.4f}. Capture is working."

    return "unknown", f"Mixed state — SNR {avg_snr:.1f} dB, BER {avg_ber:.3f}, {synced}/{len(recent)} samples synced."


def get_satdump_pid(capdir):
    pidfile = capdir + ".pid"
    if os.path.exists(pidfile):
        try:
            return int(open(pidfile).read().strip())
        except Exception:
            pass
    # fallback: find satdump processes writing to this capdir
    try:
        import subprocess
        out = subprocess.check_output(["pgrep", "-f", f"satdump.*{os.path.basename(capdir)}"], text=True)
        pids = [int(p) for p in out.strip().split()]
        return pids[0] if pids else None
    except Exception:
        return None


def kill_satdump(capdir):
    pid = get_satdump_pid(capdir)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            return pid
        except ProcessLookupError:
            return None
    return None


def cadu_size(capdir):
    cadu = os.path.join(capdir, "meteor_m2-x_lrpt.cadu")
    return os.path.getsize(cadu) if os.path.exists(cadu) else 0


def dir_size(capdir):
    total = 0
    for dp, _, files in os.walk(capdir):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def write_report(capdir, samples, status, notes, action, logfile):
    report_path = os.path.join(capdir, "diagnostic_report.md")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# Capture Diagnostic Report",
        f"",
        f"**Generated:** {now}  ",
        f"**Status:** `{status}`  ",
        f"**Log:** `{logfile}`  ",
        f"",
        f"## Assessment",
        f"",
        notes,
        f"",
    ]

    if action:
        lines += [f"**Action taken:** {action}", ""]

    if samples:
        lines += [
            "## Signal Samples",
            "",
            "| Time | SNR | Peak SNR | Viterbi | BER | Deframer |",
            "|------|-----|----------|---------|-----|----------|",
        ]
        for s in samples:
            lines.append(
                f"| {s['time'] or '?'} | {s['snr']:.1f} dB | {s['peak_snr']:.1f} dB "
                f"| {s['viterbi']} | {s['ber']:.4f} | {s['deframer']} |"
            )
        lines.append("")

    cadu = cadu_size(capdir)
    dsize = dir_size(capdir)
    lines += [
        "## Output",
        "",
        f"- CADU size: {cadu:,} bytes {'✓ IMAGES LIKELY' if cadu > 0 else '✗ no lock'}",
        f"- Total directory size: {dsize / 1e6:.1f} MB",
        "",
    ]

    if status == "nosync_good_signal":
        lines += [
            "## Troubleshooting Notes",
            "",
            "Persistent `Viterbi SYNCED + BER 0.000 + Deframer NOSYNC` with good SNR indicates",
            "a pipeline configuration mismatch, not a signal quality problem. Known causes:",
            "",
            "- **IQ swap** — HackRF may output I/Q in opposite order from what OQPSK demodulator expects.",
            "  Fix: `--iq_swap`",
            "- **Wrong samplerate** — `meteor_m2-x_lrpt` pipeline expects 1 MSPS; running at 2 MSPS",
            "  may misconfigure the demodulator filter. Fix: `--samplerate 1e6`",
            "- **Phase ambiguity** — OQPSK has 4-fold phase ambiguity. If the demodulator locks in",
            "  a non-canonical rotation, Viterbi succeeds but CCSDS ASM (0x1ACFFC1D) is never found.",
            "- **Wrong pipeline** — Try `meteor_m2_lrpt` (older QPSK decoder) as an alternative.",
            "",
            "SatDump v1.2.3 (installed). The pre-1.0 Viterbi padding bug is not present.",
            "",
        ]

    os.makedirs(capdir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return report_path


def main():
    if len(sys.argv) < 2:
        print("Usage: monitor_capture.py <capdir> [--check-only]", file=sys.stderr)
        sys.exit(2)

    capdir = os.path.realpath(sys.argv[1])
    check_only = "--check-only" in sys.argv
    logfile = capdir + ".log"

    if not os.path.exists(logfile):
        result = {"status": "no_log", "action": None, "notes": f"Log not found: {logfile}"}
        print(json.dumps(result))
        sys.exit(2)

    samples = parse_log(logfile)
    status, notes = classify(samples)

    action = None
    killed_pid = None

    # Pass manager lock: if Claude already acted mid-pass, skip monitor intervention
    pass_manager_lock = os.path.join(capdir, "pass_manager.lock")
    if os.path.exists(pass_manager_lock):
        action = "pass_manager.lock present — skipping monitor intervention"
        result = {
            "status": status, "notes": notes, "action": action, "killed_pid": None,
            "samples": len(samples),
            "avg_snr": round(sum(s["snr"] for s in samples) / len(samples), 2) if samples else None,
            "deframer_synced": any(s["deframer"] == "SYNCED" for s in samples),
            "cadu_bytes": cadu_size(capdir),
            "report_path": write_report(capdir, samples, status, notes, action, logfile),
            "capdir": capdir, "logfile": logfile,
        }
        print(json.dumps(result))
        sys.exit(0)

    if not check_only and status in ("saturated", "nosync_good_signal") and len(samples) >= 3:
        killed_pid = kill_satdump(capdir)
        if killed_pid:
            action = f"Killed satdump PID {killed_pid} — {status}"

    report_path = write_report(capdir, samples, status, notes, action, logfile)

    result = {
        "status": status,
        "notes": notes,
        "action": action,
        "killed_pid": killed_pid,
        "samples": len(samples),
        "avg_snr": round(sum(s["snr"] for s in samples) / len(samples), 2) if samples else None,
        "deframer_synced": any(s["deframer"] == "SYNCED" for s in samples),
        "cadu_bytes": cadu_size(capdir),
        "report_path": report_path,
        "capdir": capdir,
        "logfile": logfile,
    }
    print(json.dumps(result, indent=2))
    sys.exit(1 if (action or status in ("saturated", "nosync_good_signal", "weak")) else 0)


if __name__ == "__main__":
    main()
