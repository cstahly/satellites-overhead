#!/usr/bin/env python3
"""Scan a wideband ORBCOMM IQ capture for active downlink channels (PSD peaks
above noise in 137.0-138.0 MHz, excluding the DC birdie), then offline-decode
each with orbcomm_stx + the deframer. Replaces the old two-hardcoded-channels
approach so it finds whatever channel pair the bird is actually using.
Usage: orbcomm_scan_decode.py <iq> <center_hz> <fs_hz>"""
import sys, os, glob, subprocess, numpy as np
sys.path.insert(0, "/home/cstahly/src/satellites-overhead")
import orbcomm_ephem as oe

iq, center, fs = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
capdir = sys.argv[4] if len(sys.argv) > 4 else None   # if given, copy each channel's .frm
                                                      # here so orbcomm_ephem (globs
                                                      # capdir/*.frm) sees them all
import shutil
OFFLINE = "/home/cstahly/orbcomm_offline.py"
sz = os.path.getsize(iq)

# --- 1. PSD with TIME-SLICE PEAK-HOLD across the pass ---
# A bird is only overhead/transmitting for part of a 15-25 min capture, so averaging
# the whole capture dilutes it below threshold (that's why the live scheduled passes
# came up empty while a short hand-clipped capture decoded fine). Instead: average
# within ~16 time slices, then peak-hold (max per bin) across slices — a signal that's
# present in ANY slice survives at full strength.
nfft = 8192; w = np.hanning(nfft)
NSLICES = 16
peak = None
for s in range(NSLICES):
    base = (s + 0.5) / NSLICES
    acc = np.zeros(nfft); n = 0
    for frac in np.linspace(max(0.01, base - 0.025), min(0.99, base + 0.025), 6):
        off = int(sz * frac) // 2 * 2
        raw = np.fromfile(iq, dtype=np.uint8, count=2 * nfft * 4, offset=off)
        if raw.size < 2 * nfft:
            continue
        x = (raw[0::2].astype(np.float32) - 127.5) + 1j * (raw[1::2].astype(np.float32) - 127.5)
        for k in range(len(x) // nfft):
            acc += np.abs(np.fft.fftshift(np.fft.fft(x[k * nfft:(k + 1) * nfft] * w))) ** 2; n += 1
    if n:
        sl = acc / n
        peak = sl if peak is None else np.maximum(peak, sl)
psd = 10 * np.log10((peak if peak is not None else np.ones(nfft)) + 1e-9)
f = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs)) + center
inband = np.where((f > 137.0e6) & (f < 138.0e6))[0]
nfloor = np.median(psd[inband])

# --- 2. candidate channels: local peak-hold maxima > noise+THR dB, away from DC birdie ---
THR = 4.0   # lower than the old +5 — peak-hold keeps real signals well clear of this
cand = []
for i in sorted(inband, key=lambda j: -psd[j]):
    if psd[i] < nfloor + THR:
        break
    fr = f[i]
    if abs(fr - center) < 10e3:           # skip DC/LO birdie
        continue
    if i <= 1 or i >= nfft - 2 or psd[i] != max(psd[i - 2:i + 3]):
        continue
    if any(abs(fr - c) < 15e3 for c in cand):
        continue
    cand.append(fr)
    if len(cand) >= 8:
        break
cand.sort()
# top in-band peaks (for diagnosing detection even when nothing clears THR)
_top = sorted(((f[i], psd[i] - nfloor) for i in inband), key=lambda t: -t[1])[:8]
_summary = (f"  noise {nfloor:.1f} dB (peak-hold); {len(cand)} candidate channels (>+{THR:.0f}dB): " +
            (", ".join(f"{c/1e6:.4f}" for c in cand) if cand else "(none — weak/no signal)") +
            "\n  top in-band peaks (MHz +dB): " + ", ".join(f"{fr/1e6:.4f}+{db:.1f}" for fr, db in _top))
print(_summary)
if capdir:   # persist so a failed pass is diagnosable without keeping the 4.5 GB IQ
    try:
        with open(os.path.join(capdir, "bandscan_report.txt"), "w") as _rf:
            _rf.write(_summary + "\n")
    except Exception:
        pass

# --- 3. offline-decode each candidate ---
total = 0
for _i, ch in enumerate(cand):
    subprocess.run(["python3", OFFLINE, iq, str(center), str(fs), str(int(round(ch))),
                    "/tmp/orb_scan.cu8", "8", "0", "100000"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = "/tmp/orb_scan_out"; os.system(f"rm -rf {out}; mkdir -p {out}")
    subprocess.run(["satdump", "orbcomm_stx", "baseband", "/tmp/orb_scan.cu8", out,
                    "--samplerate", "250000", "--baseband_format", "cu8"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    v = oe.load_valid(out)
    frm = glob.glob(out + "/*.frm")
    nb = os.path.getsize(frm[0]) if frm else 0
    if capdir and frm and nb > 0:   # hand frames to orbcomm_ephem via the capture dir
        try:
            shutil.copy(frm[0], os.path.join(capdir, f"orbcomm_bandscan_ch{_i}.frm"))
        except Exception:
            pass
    print(f"    {ch/1e6:.4f} MHz: .frm {nb}B, {len(v)} Fletcher-valid packets")
    total += len(v)
print(f"  >>> TOTAL valid packets across scan: {total}")
sys.exit(0 if total else 2)
