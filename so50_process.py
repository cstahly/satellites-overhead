#!/usr/bin/env python3
"""
Post-process a SO-50 raw IQ capture:
  1. FM demodulate → WAV
  2. Detect active segments (>3x noise RMS)
  3. If activity found, run faster-whisper and write transcript
  4. Write summary report alongside the IQ file

Usage: python3 so50_process.py <iqfile.iq>
"""
import sys, os, wave, subprocess, json, datetime
import numpy as np
from scipy.signal import firwin, lfilter

SAMPLE_RATE  = 2_000_000
DECIMATE     = 40          # → 50 kHz audio
AUDIO_RATE   = SAMPLE_RATE // DECIMATE
ACTIVITY_THR = 3.0         # RMS multiple above noise to count as transmission
MIN_BURST_S  = 0.3         # ignore bursts shorter than this

# ── FM demod ──────────────────────────────────────────────────────────────────

_LP  = firwin(65, 15_000, fs=SAMPLE_RATE)
_DCB = np.array([1.0, -1.0])
_DCA = np.array([1.0, -0.995])

def fm_demod_file(iqpath: str, wavpath: str):
    dc_zi = np.zeros(1)
    prev  = None
    chunk = SAMPLE_RATE  # 1 s

    with open(iqpath, 'rb') as iq, wave.open(wavpath, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(AUDIO_RATE)
        agc_peak = 1.0

        while True:
            raw = iq.read(chunk * 2)
            if not raw:
                break
            s = np.frombuffer(raw, dtype=np.int8).astype(np.float32)
            I, Q = s[0::2], s[1::2]
            c = I + 1j * Q

            # FM discriminator
            if prev is None:
                prev = c[-1]
            c_prev = np.concatenate([[prev], c[:-1]])
            prev = c[-1]
            fm = np.angle(c * np.conj(c_prev))

            fm = lfilter(_LP, 1.0, fm)
            audio = fm[::DECIMATE]
            audio, dc_zi = lfilter(_DCB, _DCA, audio, zi=dc_zi)

            pk = float(np.max(np.abs(audio))) or 1e-6
            agc_peak = agc_peak * 0.9999 + pk * 0.0001 if pk < agc_peak else agc_peak * 0.99 + pk * 0.01
            pcm = np.clip(audio / agc_peak, -1.0, 1.0)
            wf.writeframes((pcm * 32767 * 0.9).astype(np.int16).tobytes())


# ── Activity detection ────────────────────────────────────────────────────────

def find_bursts(wavpath: str):
    with wave.open(wavpath) as wf:
        rate = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)

    # Noise floor from first 10 s
    noise_rms = np.sqrt(np.mean(data[:rate * 10] ** 2)) or 1.0
    threshold  = noise_rms * ACTIVITY_THR

    # 0.1 s windows
    win = rate // 10
    active = np.array([
        np.sqrt(np.mean(data[i:i+win] ** 2)) > threshold
        for i in range(0, len(data) - win, win)
    ])

    bursts = []
    in_burst = False
    start = 0
    for i, a in enumerate(active):
        t = i * 0.1
        if a and not in_burst:
            start = t
            in_burst = True
        elif not a and in_burst:
            if t - start >= MIN_BURST_S:
                bursts.append((start, t))
            in_burst = False
    if in_burst:
        bursts.append((start, len(active) * 0.1))

    return bursts, noise_rms


# ── Whisper transcription ─────────────────────────────────────────────────────

def transcribe_bursts(wavpath: str, bursts: list):
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    results = []
    for start, end in bursts:
        # Extract burst to temp wav via sox
        tmp = f"/tmp/so50_burst_{int(start)}_{int(end)}.wav"
        duration = end - start + 0.5  # small padding
        subprocess.run(
            ["sox", wavpath, tmp, "trim", str(max(0, start - 0.2)), str(duration)],
            capture_output=True
        )
        if not os.path.exists(tmp):
            continue
        segments, info = model.transcribe(tmp, beam_size=5, language="en")
        text = " ".join(s.text.strip() for s in segments).strip()
        os.unlink(tmp)
        results.append({"start": start, "end": end, "duration": end - start, "text": text or "[unintelligible]"})
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    iqpath = sys.argv[1]
    base   = iqpath.replace(".iq", "")
    wavpath    = base + ".wav"
    reportpath = base + "_report.md"

    print(f"[so50] Demodulating {os.path.basename(iqpath)} …", flush=True)
    fm_demod_file(iqpath, wavpath)
    print(f"[so50] WAV written: {wavpath}", flush=True)

    bursts, noise_rms = find_bursts(wavpath)
    print(f"[so50] Noise RMS: {noise_rms:.0f}  Bursts found: {len(bursts)}", flush=True)
    for s, e in bursts:
        print(f"  {s:.1f}s – {e:.1f}s  ({e-s:.1f}s)", flush=True)

    lines = [
        f"# SO-50 Pass Report",
        f"",
        f"**File:** `{os.path.basename(iqpath)}`  ",
        f"**Processed:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Noise RMS:** {noise_rms:.0f}  ",
        f"**Transmissions detected:** {len(bursts)}",
        f"",
    ]

    if bursts:
        print(f"[so50] Transcribing {len(bursts)} burst(s) with Whisper …", flush=True)
        transcripts = transcribe_bursts(wavpath, bursts)
        lines.append("## Transmissions")
        lines.append("")
        for t in transcripts:
            lines.append(f"**t={t['start']:.1f}–{t['end']:.1f}s** ({t['duration']:.1f}s)")
            lines.append(f"> {t['text']}")
            lines.append("")
            print(f"  [{t['start']:.1f}–{t['end']:.1f}s] {t['text']}", flush=True)
    else:
        lines.append("*No transmissions detected — pass was quiet.*")

    with open(reportpath, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[so50] Report: {reportpath}", flush=True)


if __name__ == "__main__":
    main()
