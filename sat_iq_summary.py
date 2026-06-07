#!/usr/bin/env python3
"""
Post-process a raw IQ satellite pass captured with rtl_sdr (CU8 format).
FM demodulates, detects activity, transcribes voice with Whisper,
then calls Claude for a pass narrative.

Usage:
    python3 sat_iq_summary.py <file.iq> \
        --norad 27607 --name "SO-50" --max-el 42.3 --freq 145850000
"""
import argparse, os, re, sys, wave, subprocess, datetime
import numpy as np
from scipy.signal import firwin, lfilter


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

SAMPLE_RATE  = 2_000_000
DECIMATE     = 40            # → 50 kHz audio
AUDIO_RATE   = SAMPLE_RATE // DECIMATE
ACTIVITY_THR = 1.8           # RMS multiples above noise floor (was 3.0 — too high for APRS/weak signals)
MIN_BURST_S  = 0.3

SAT_CONTEXT = {
    27607: (
        "SO-50 is an FM voice repeater satellite. Downlink 145.850 MHz, uplink 436.795 MHz "
        "(67 Hz CTCSS tone required). It carries live amateur radio voice conversations."
    ),
    25544: (
        "The ISS APRS digipeater operates on 145.825 MHz. It rebroadcasts APRS packets from "
        "ground stations worldwide. Audio will contain 1200 baud Bell 202 AFSK tones — "
        "not human voice. Whisper transcripts of APRS will be noise/gibberish."
    ),
    39444: (
        "AO-73 (FUNcube-1) is a linear transponder satellite. Beacon at 145.935 MHz, "
        "transponder downlink passband ~145.950–145.970 MHz. SSB/CW signals."
    ),
    24278: (
        "FO-29 (JAS-2) is a Japanese amateur linear transponder satellite. "
        "Downlink passband 435.800–435.900 MHz (USB). Carries SSB voice and CW contacts."
    ),
    44909: (
        "RS-44 is a Russian amateur linear transponder satellite. "
        "Downlink passband 435.610–435.670 MHz (USB). Carries SSB voice and CW contacts."
    ),
    7530: (
        "AO-7 (OSCAR 7) launched 1974, oldest operational amateur satellite. "
        "Mode B downlink passband 435.025–435.175 MHz (USB). Carries SSB voice and CW."
    ),
}

# NОРАDs that use linear transponders — SSB/CW, not FM voice
SSB_NORADS = {24278, 44909, 7530, 39444}


# ── SSB demod + energy scan (CU8 input) ──────────────────────────────────────

def ssb_scan_file(iqpath: str, wavpath: str, center_hz: int):
    """
    Upper-sideband demod of a CU8 IQ file.
    Scans the full 2 MHz capture for any signal energy above noise,
    then demodulates USB audio centered on the strongest activity band.
    """
    from scipy.signal import firwin, lfilter, hilbert

    chunk_s   = SAMPLE_RATE           # 1-second chunks
    audio_buf = []
    energy_by_bin = None
    n_chunks  = 0

    with open(iqpath, 'rb') as fh:
        while True:
            raw = fh.read(chunk_s * 2)
            if not raw:
                break
            s = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 127.5
            I, Q = s[0::2], s[1::2]
            c = I + 1j * Q

            # Accumulate FFT magnitude for energy map
            fft = np.abs(np.fft.fft(c, n=4096))
            energy_by_bin = fft if energy_by_bin is None else energy_by_bin + fft
            n_chunks += 1

            # USB demod: analytic signal → take real part after shifting
            # Apply LPF to 3 kHz (voice bandwidth)
            lp = firwin(65, 3000, fs=SAMPLE_RATE)
            filtered = lfilter(lp, 1.0, c.real)
            audio_buf.append(filtered[::DECIMATE])

    if energy_by_bin is None:
        return None, 0.0, {}

    # Build frequency axis and find peak energy band
    freqs = np.fft.fftfreq(4096, d=1.0/SAMPLE_RATE)
    energy_by_bin /= n_chunks
    noise_floor = np.median(energy_by_bin)
    peak_idx = np.argmax(energy_by_bin)
    peak_freq_offset = freqs[peak_idx]
    peak_snr = energy_by_bin[peak_idx] / noise_floor if noise_floor > 0 else 0

    # Bin the spectrum into 50 kHz slots for reporting
    bin_w = 50_000
    n_bins = SAMPLE_RATE // bin_w
    slot_energy = {}
    for i in range(n_bins):
        lo = i * bin_w - SAMPLE_RATE // 2
        hi = lo + bin_w
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            slot_energy[f"{center_hz/1e6:.3f}+{lo/1000:+.0f}kHz"] = float(
                energy_by_bin[mask].mean() / noise_floor
            )

    # Write USB audio wav
    audio = np.concatenate(audio_buf)
    pk = float(np.max(np.abs(audio))) or 1.0
    pcm = np.clip(audio / pk, -1.0, 1.0)
    with wave.open(wavpath, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(AUDIO_RATE)
        wf.writeframes((pcm * 32767 * 0.9).astype(np.int16).tobytes())

    return wavpath, peak_snr, {"peak_offset_hz": peak_freq_offset,
                               "peak_snr": peak_snr,
                               "noise_floor": noise_floor,
                               "slot_energy": slot_energy}

# ── FM demod (CU8 input — RTL-SDR unsigned 8-bit IQ) ─────────────────────────

_LP  = firwin(65, 15_000, fs=SAMPLE_RATE)
_DCB = np.array([1.0, -1.0])
_DCA = np.array([1.0, -0.995])

def fm_demod_file(iqpath: str, wavpath: str):
    dc_zi = np.zeros(1)
    prev  = None
    chunk = SAMPLE_RATE  # 1-second chunks

    with open(iqpath, 'rb') as iq, wave.open(wavpath, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(AUDIO_RATE)
        agc_peak = 1.0

        while True:
            raw = iq.read(chunk * 2)
            if not raw:
                break
            # CU8: unsigned byte, subtract 127.5 to centre on zero
            s = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 127.5
            I, Q = s[0::2], s[1::2]
            c = I + 1j * Q

            if prev is None:
                prev = c[-1]
            c_prev = np.concatenate([[prev], c[:-1]])
            prev = c[-1]

            fm = np.angle(c * np.conj(c_prev))
            fm = lfilter(_LP, 1.0, fm)
            audio = fm[::DECIMATE]
            audio, dc_zi = lfilter(_DCB, _DCA, audio, zi=dc_zi)

            pk = float(np.max(np.abs(audio))) or 1e-6
            if pk < agc_peak:
                agc_peak = agc_peak * 0.9999 + pk * 0.0001
            else:
                agc_peak = agc_peak * 0.99 + pk * 0.01

            pcm = np.clip(audio / agc_peak, -1.0, 1.0)
            wf.writeframes((pcm * 32767 * 0.9).astype(np.int16).tobytes())


# ── Activity detection ────────────────────────────────────────────────────────

def find_bursts(wavpath: str):
    with wave.open(wavpath) as wf:
        rate = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)

    win        = rate // 10
    # Use 10th-percentile of per-window RMS as noise floor so a satellite that's
    # already overhead at AOS (high-elevation pass) doesn't pollute the baseline.
    all_rms = np.array([
        np.sqrt(np.mean(data[i:i + win] ** 2))
        for i in range(0, len(data) - win, win)
    ])
    noise_rms  = float(np.percentile(all_rms, 10)) or 1.0
    threshold  = noise_rms * ACTIVITY_THR

    active = all_rms > threshold

    bursts, in_burst, start = [], False, 0.0
    for i, a in enumerate(active):
        t = i * 0.1
        if a and not in_burst:
            start, in_burst = t, True
        elif not a and in_burst:
            if t - start >= MIN_BURST_S:
                bursts.append((start, t))
            in_burst = False
    if in_burst:
        bursts.append((start, len(active) * 0.1))

    return bursts, noise_rms


# ── Whisper transcription ─────────────────────────────────────────────────────

def transcribe_bursts(wavpath: str, bursts: list) -> list[dict]:
    from faster_whisper import WhisperModel
    model = WhisperModel("turbo", device="cpu", compute_type="int8")
    results = []
    for start, end in bursts:
        tmp = f"/tmp/sat_burst_{int(start)}_{int(end)}.wav"
        dur = end - start + 0.5
        subprocess.run(
            ["sox", wavpath, tmp, "trim", str(max(0.0, start - 0.2)), str(dur)],
            capture_output=True,
        )
        if not os.path.exists(tmp):
            continue
        segs, _ = model.transcribe(tmp, beam_size=1, language="en", vad_filter=True)
        text = " ".join(s.text.strip() for s in segs).strip()
        os.unlink(tmp)
        results.append({"start": start, "end": end, "text": text or "[unintelligible]"})
    return results


# ── Claude summary ────────────────────────────────────────────────────────────

def claude_summary(name, norad, freq_hz, max_el, bursts, noise_rms,
                   transcripts, iq_mb, energy_info=None) -> str:
    _load_api_key()
    import anthropic

    context = SAT_CONTEXT.get(norad,
        f"Amateur satellite, downlink {freq_hz/1e6:.3f} MHz.")

    if transcripts:
        tx_block = "Transcriptions:\n" + "\n".join(
            f"  t={t['start']:.1f}–{t['end']:.1f}s: {t['text']}"
            for t in transcripts
        )
    elif bursts:
        total_s = sum(e - s for s, e in bursts)
        tx_block = (f"{len(bursts)} signal burst(s) detected "
                    f"(total {total_s:.1f}s), no intelligible voice transcribed.")
    else:
        tx_block = "No signal activity detected above the noise floor."

    energy_block = ""
    if energy_info:
        snr = energy_info.get("peak_snr", 0)
        offset = energy_info.get("peak_offset_hz", 0)
        energy_block = (
            f"\nSpectrum scan: peak SNR={snr:.1f}x noise floor at "
            f"{offset/1000:+.1f} kHz offset from tune frequency. "
        )
        if snr > 3:
            energy_block += "Signal energy detected above noise — satellite likely present."
        else:
            energy_block += "No significant signal energy detected — satellite not heard or very weak."

    prompt = (
        f"You are writing a post-pass report for an amateur radio satellite observation.\n\n"
        f"Satellite: {name} (NORAD {norad})\n"
        f"Context: {context}\n"
        f"Pass peak elevation: {max_el}°\n"
        f"Capture: {iq_mb:.0f} MB IQ, noise RMS={noise_rms:.0f}, "
        f"{len(bursts)} activity burst(s) detected\n"
        f"{energy_block}\n"
        f"{tx_block}\n\n"
        f"Write a concise 3–5 sentence pass report. Describe whether the satellite "
        f"was heard, what activity was present, any notable content from transcripts, "
        f"and a one-line quality assessment. Be factual and direct."
    )

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("iqfile")
    ap.add_argument("--norad",  type=int,   default=0)
    ap.add_argument("--name",               default="Unknown Satellite")
    ap.add_argument("--max-el", type=float, default=0.0, dest="max_el")
    ap.add_argument("--freq",   type=int,   default=145_850_000)
    ap.add_argument("--force-summary", action="store_true",
                    help="Call Claude even if no bursts detected")
    ap.add_argument("--mode", choices=["fm", "ssb", "auto"], default="auto",
                    help="Demod mode: fm=voice repeaters, ssb=linear transponders, auto=detect from NORAD")
    args = ap.parse_args()

    if not os.path.exists(args.iqfile):
        print(f"[sat_summary] ERROR: {args.iqfile} not found", file=sys.stderr)
        sys.exit(1)

    base       = args.iqfile.replace(".iq", "")
    wavpath    = base + ".wav"
    reportpath = base + "_summary.md"
    iq_mb      = os.path.getsize(args.iqfile) / 1e6

    # Resolve mode: auto picks ssb for known linear transponder NОРАDs
    mode = args.mode
    if mode == "auto":
        mode = "ssb" if args.norad in SSB_NORADS else "fm"

    print(f"[sat_summary] {args.name} | NORAD {args.norad} | "
          f"{args.freq/1e6:.3f} MHz | el={args.max_el}° | {iq_mb:.0f} MB | mode={mode}", flush=True)

    energy_info = None
    bursts = []
    noise_rms = 0.0
    transcripts = []

    if mode == "ssb":
        print(f"[sat_summary] SSB scan + energy detection…", flush=True)
        _, peak_snr, energy_info = ssb_scan_file(args.iqfile, wavpath, args.freq)
        noise_rms = energy_info.get("noise_floor", 0)
        print(f"[sat_summary] Peak SNR={peak_snr:.1f}x  offset={energy_info.get('peak_offset_hz',0)/1000:+.1f}kHz", flush=True)
        if peak_snr > 3:
            print(f"[sat_summary] Signal detected — attempting SSB voice transcription…", flush=True)
            bursts_wav, _ = find_bursts(wavpath)
            bursts = bursts_wav
            if bursts:
                transcripts = transcribe_bursts(wavpath, bursts)
                for t in transcripts:
                    print(f"  [{t['start']:.1f}–{t['end']:.1f}s] {t['text']}", flush=True)
        else:
            print(f"[sat_summary] No signal above noise — satellite not detected", flush=True)
        if not args.force_summary and peak_snr <= 3:
            sys.exit(0)
    else:
        print(f"[sat_summary] FM demodulating…", flush=True)
        fm_demod_file(args.iqfile, wavpath)
        bursts, noise_rms = find_bursts(wavpath)
        print(f"[sat_summary] Noise RMS={noise_rms:.0f}  Bursts={len(bursts)}", flush=True)
        for s, e in bursts:
            print(f"  {s:.1f}s – {e:.1f}s  ({e-s:.1f}s)", flush=True)
        if bursts:
            print(f"[sat_summary] Transcribing {len(bursts)} burst(s)…", flush=True)
            transcripts = transcribe_bursts(wavpath, bursts)
            for t in transcripts:
                print(f"  [{t['start']:.1f}–{t['end']:.1f}s] {t['text']}", flush=True)
        if not bursts and not args.force_summary:
            print(f"[sat_summary] No activity detected — skipping Claude call (use --force-summary to override)", flush=True)
            sys.exit(0)

    print(f"[sat_summary] Calling Claude for narrative…", flush=True)
    summary = claude_summary(
        args.name, args.norad, args.freq, args.max_el,
        bursts, noise_rms, transcripts, iq_mb, energy_info,
    )

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# {args.name} Pass Summary",
        f"",
        f"| | |",
        f"|---|---|",
        f"| **Satellite** | {args.name} (NORAD {args.norad}) |",
        f"| **Frequency** | {args.freq/1e6:.3f} MHz |",
        f"| **Peak Elevation** | {args.max_el}° |",
        f"| **Capture** | {iq_mb:.0f} MB |",
        f"| **Activity** | {len(bursts)} burst(s), noise RMS={noise_rms:.0f} |",
        f"| **Processed** | {ts} |",
        f"",
        f"## Summary",
        f"",
        summary,
    ]

    if transcripts:
        lines += ["", "## Transcriptions", ""]
        for t in transcripts:
            lines.append(f"**t={t['start']:.1f}–{t['end']:.1f}s:** {t['text']}")

    with open(reportpath, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[sat_summary] Report: {reportpath}", flush=True)
    print(f"\n--- SUMMARY ---\n{summary}\n---------------", flush=True)


if __name__ == "__main__":
    main()
