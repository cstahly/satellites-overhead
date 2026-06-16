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

# --- 1. averaged PSD across the whole pass ---
nfft = 8192
acc = np.zeros(nfft); w = np.hanning(nfft); n = 0
for frac in np.linspace(0.04, 0.96, 80):
    off = int(sz * frac) // 2 * 2
    raw = np.fromfile(iq, dtype=np.uint8, count=2 * nfft * 4, offset=off)
    if raw.size < 2 * nfft:
        continue
    x = (raw[0::2].astype(np.float32) - 127.5) + 1j * (raw[1::2].astype(np.float32) - 127.5)
    for k in range(len(x) // nfft):
        acc += np.abs(np.fft.fftshift(np.fft.fft(x[k * nfft:(k + 1) * nfft] * w))) ** 2; n += 1
psd = 10 * np.log10(acc / max(n, 1) + 1e-9)
f = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs)) + center
nfloor = np.median(psd[(f > 137.0e6) & (f < 138.0e6)])

# --- 2. candidate channels: local PSD maxima >noise+5dB, away from DC birdie ---
cand = []
inband = np.where((f > 137.0e6) & (f < 138.0e6))[0]
for i in sorted(inband, key=lambda j: -psd[j]):
    if psd[i] < nfloor + 5:
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
print(f"  noise {nfloor:.1f} dB; {len(cand)} candidate channels: " +
      (", ".join(f"{c/1e6:.4f}" for c in cand) if cand else "(none above noise+5dB — weak/no signal)"))

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
