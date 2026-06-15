#!/usr/bin/env python3
"""Standalone OFFLINE ORBCOMM channelizer — does NOT touch the scheduler.
Reads a wideband cu8 IQ recording, mixes one ORBCOMM downlink channel to DC,
low-pass decimates, and writes a narrow cu8 file suitable for satdump's
OFFLINE-capable `orbcomm_stx` pipeline (the non-auto demod that has a baseband
`work` graph). Usage:

  orbcomm_offline.py <in.iq> <capture_center_hz> <fs_hz> <target_hz> <out.cu8> \
                     [decim] [start_s] [dur_s]
"""
import sys, os, numpy as np
from scipy.signal import decimate

inf, cc, fs, tgt, outf = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
decim   = int(sys.argv[6]) if len(sys.argv) > 6 else 8
start_s = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0
dur_s   = float(sys.argv[8]) if len(sys.argv) > 8 else 1e9

foff = tgt - cc                       # how far the channel is from capture DC
sps_in = int(fs)
start_samp = int(start_s * sps_in)
n_samp = int(min(dur_s * sps_in, (os.path.getsize(inf)//2) - start_samp))
print(f"shift {foff/1e3:+.1f} kHz to DC, decim {decim} -> {fs/decim/1e3:.1f} kHz, "
      f"{n_samp/sps_in:.1f}s from t={start_s:.0f}s")

chunk = 4_000_000                      # complex samples per chunk
n0 = 0
out = open(outf, "wb")
phase = 0.0
w = 2*np.pi*foff/fs
while n0 < n_samp:
    cnt = min(chunk, n_samp - n0)
    raw = np.fromfile(inf, dtype=np.uint8, count=2*cnt, offset=2*(start_samp+n0))
    if raw.size < 2: break
    cnt = raw.size//2
    iq = (raw[0::2].astype(np.float32)-127.5) + 1j*(raw[1::2].astype(np.float32)-127.5)
    t = np.arange(cnt)
    mix = iq * np.exp(-1j*(phase + w*t))
    phase = (phase + w*cnt) % (2*np.pi)
    dec = decimate(mix, decim, ftype='fir', zero_phase=False)
    # back to cu8
    o = np.empty(dec.size*2, dtype=np.uint8)
    o[0::2] = np.clip(np.real(dec)+127.5, 0, 255).astype(np.uint8)
    o[1::2] = np.clip(np.imag(dec)+127.5, 0, 255).astype(np.uint8)
    o.tofile(out)
    n0 += cnt
out.close()
print(f"wrote {outf} ({os.path.getsize(outf)} bytes, fs={fs/decim:.0f})")
