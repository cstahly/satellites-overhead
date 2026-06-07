#!/usr/bin/env python3
"""
Post-pass AI summary for a satdump capture directory.
Reads the .log file, extracts decode metrics, calls Claude for a narrative.

Usage:
    python3 satdump_pass_summary.py <capdir> \
        --name "ORBCOMM FM112" --norad 41184 --max-el 38.0
"""
import argparse, os, re, sys, datetime


def _load_api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    env_file = os.path.expanduser("~/.config/sdr/env")
    if os.path.exists(env_file):
        for line in open(env_file):
            m = re.match(r'^ANTHROPIC_API_KEY=(.+)', line.strip())
            if m:
                os.environ["ANTHROPIC_API_KEY"] = m.group(1).strip('"\'')
                return

_load_api_key()
import anthropic

SAT_CONTEXT = {
    "orbcomm": (
        "ORBCOMM is a commercial LEO messaging satellite constellation operating near 137 MHz. "
        "The satdump orbcomm_stx_auto_plotter pipeline decodes store-and-forward data messages."
    ),
    "meteor":  (
        "Meteor-M is a Russian weather satellite transmitting LRPT (Low Rate Picture Transmission) "
        "imagery at 137.9 MHz. A successful pass produces visible/IR weather imagery. "
        "CADU bytes > 0 means frames were decoded; higher is better. 72 bytes per frame."
    ),
}


def read_log(capdir: str) -> str:
    logfile = capdir + ".log"
    if not os.path.exists(logfile):
        return ""
    with open(logfile, errors="replace") as f:
        return f.read()


def extract_metrics(log_text: str, capdir: str = "") -> dict:
    metrics = {}
    # SNR: look for highest value seen
    snr_vals = [float(m) for m in re.findall(r'SNR[:\s=]+([0-9]+(?:\.[0-9]+)?)', log_text)]
    if snr_vals:
        metrics["peak_snr"] = max(snr_vals)

    # Viterbi sync
    if "Viterbi" in log_text:
        metrics["viterbi_synced"] = "SYNCED" in log_text

    # Deframer
    if "Deframer" in log_text:
        metrics["deframer_synced"] = "SYNCED" in log_text and "NOSYNC" not in log_text.split("SYNCED")[-1][:200]

    # CADU bytes from any file ending in .cadu
    cadu_files = [f for f in os.listdir(capdir) if f.endswith(".cadu")] if os.path.isdir(capdir) else []
    if cadu_files:
        total = sum(os.path.getsize(os.path.join(capdir, f)) for f in cadu_files)
        metrics["cadu_bytes"] = total
        metrics["cadu_frames"] = total // 892  # standard CADU frame size

    # Images decoded
    img_files = [f for f in os.listdir(capdir) if f.lower().endswith((".png", ".jpg"))] if os.path.isdir(capdir) else []
    metrics["images"] = len(img_files)

    return metrics


def write_summary(capdir: str, name: str, norad: int, max_el: float,
                  pipeline: str, freq_hz: int) -> str:
    log_text = read_log(capdir)
    metrics  = extract_metrics(log_text, capdir)

    # Pick last 3000 chars of log (most relevant — end of pass)
    log_tail = log_text[-3000:] if len(log_text) > 3000 else log_text

    sat_key  = "meteor" if "meteor" in name.lower() else "orbcomm" if "orbcomm" in name.lower() else ""
    context  = SAT_CONTEXT.get(sat_key, f"Amateur/commercial satellite on {freq_hz/1e6:.3f} MHz.")

    metrics_block = "\n".join(f"  {k}: {v}" for k, v in metrics.items()) or "  (no metrics extracted)"

    prompt = (
        f"You are writing a post-pass report for an SDR satellite decode.\n\n"
        f"Satellite: {name} (NORAD {norad})\n"
        f"Context: {context}\n"
        f"Pipeline: {pipeline} | Frequency: {freq_hz/1e6:.3f} MHz | Peak elevation: {max_el}°\n\n"
        f"Extracted metrics:\n{metrics_block}\n\n"
        f"End of capture log (last 3000 chars):\n{log_tail}\n\n"
        f"Write a concise 3–5 sentence pass report. Cover: whether a signal was acquired, "
        f"decode quality (SNR, lock status, CADU bytes if relevant), any imagery or data "
        f"successfully decoded, and a one-line quality verdict. Be direct and factual."
    )

    client = anthropic.Anthropic()
    resp   = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capdir")
    ap.add_argument("--name",     default="Unknown Satellite")
    ap.add_argument("--norad",    type=int,   default=0)
    ap.add_argument("--max-el",   type=float, default=0.0, dest="max_el")
    ap.add_argument("--pipeline", default="unknown")
    ap.add_argument("--freq",     type=int,   default=137_000_000)
    args = ap.parse_args()

    print(f"[satdump_summary] {args.name} | NORAD {args.norad} | el={args.max_el}°", flush=True)

    summary = write_summary(
        args.capdir, args.name, args.norad,
        args.max_el, args.pipeline, args.freq,
    )

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reportpath = os.path.join(args.capdir, "pass_summary.md")
    metrics = extract_metrics(read_log(args.capdir), args.capdir)

    lines = [
        f"# {args.name} Pass Summary",
        f"",
        f"| | |",
        f"|---|---|",
        f"| **Satellite** | {args.name} (NORAD {args.norad}) |",
        f"| **Frequency** | {args.freq/1e6:.3f} MHz |",
        f"| **Pipeline** | {args.pipeline} |",
        f"| **Peak Elevation** | {args.max_el}° |",
        f"| **Processed** | {ts} |",
    ]
    for k, v in metrics.items():
        lines.append(f"| **{k.replace('_',' ').title()}** | {v} |")
    lines += [
        f"",
        f"## Summary",
        f"",
        summary,
    ]

    with open(reportpath, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[satdump_summary] Report: {reportpath}", flush=True)
    print(f"\n--- SUMMARY ---\n{summary}\n---------------", flush=True)


if __name__ == "__main__":
    main()
