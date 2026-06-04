#!/usr/bin/env python3
"""
FM demodulator for raw HackRF IQ files (int8, 2 MSPS).
Frequency-shifts to a target offset, FM-discriminates, decimates to audio.

Usage:
    python3 hackrf_fm_demod.py <iqfile> <offset_hz> [out_rate_hz]
    | multimon-ng -t raw -r <out_rate_hz> -a AFSK1200 -f alpha -

Defaults: offset=0, out_rate=50000

Examples:
    # ISS APRS (145.825 MHz) from capture centered at 145.800 MHz
    python3 hackrf_fm_demod.py iss_1805.iq 25000 | multimon-ng -t raw -r 50000 -a AFSK1200 -f alpha -

    # AO-73 telemetry (145.935 MHz) from capture centered at 145.815 MHz
    python3 hackrf_fm_demod.py funcube_1__ao_73_1648.iq 120000 50000
"""
import sys, numpy as np
from scipy.signal import firwin, lfilter

SAMPLE_RATE = 2_000_000
DECIMATE    = 40            # 2M / 40 = 50 kHz output — clean integer
OUT_RATE    = SAMPLE_RATE // DECIMATE  # 50000

iqfile     = sys.argv[1]
offset_hz  = int(sys.argv[2]) if len(sys.argv) > 2 else 0
out_rate   = int(sys.argv[3]) if len(sys.argv) > 3 else OUT_RATE

CHUNK = SAMPLE_RATE  # 1 second at a time

# Anti-alias LPF for FM channel before decimation (15 kHz audio BW)
_lp = firwin(65, 15_000, fs=SAMPLE_RATE)
# Phase state
_prev = None

with open(iqfile, 'rb') as f:
    chunk_i = 0
    while True:
        raw = f.read(CHUNK * 2)
        if not raw:
            break
        s = np.frombuffer(raw, dtype=np.int8).astype(np.float32)
        I = s[0::2]
        Q = s[1::2]
        N = len(I)

        # Frequency shift: mix down by offset_hz
        t = np.arange(chunk_i * N, (chunk_i + 1) * N)
        shift = np.exp(-1j * 2 * np.pi * offset_hz * t / SAMPLE_RATE)
        c = (I + 1j * Q) * shift

        # FM discriminator: d/dt(arg(c)) = Im(c* · dc/dt) / |c|²
        # Efficient: angle(c[n] * conj(c[n-1]))
        if _prev is None:
            _prev = c[-1]
        c_prev = np.concatenate([[_prev], c[:-1]])
        _prev = c[-1]
        fm = np.angle(c * np.conj(c_prev))

        # Lowpass + decimate
        fm = lfilter(_lp, 1.0, fm)
        audio = fm[::DECIMATE]

        # Normalize to int16 (FM deviation ≈ ±5 kHz → ≈ ±0.016 rad/sample at 2MSPS)
        pcm = np.clip(audio * (32767 / 0.016), -32767, 32767).astype(np.int16)
        sys.stdout.buffer.write(pcm.tobytes())
        sys.stdout.buffer.flush()
        chunk_i += 1
