#!/usr/bin/env python3
"""
Live narrowband FM demodulator for HackRF IQ stream.

Usage:
    hackrf_transfer -r /dev/stdout -f <freq_hz> -s 2000000 -l 32 -g 48 -a 1 \
        | python3 hackrf_fm_live.py \
        | sox -t raw -r 16000 -e signed -b 16 -c 1 - -d

Outputs 16-bit mono PCM at 16000 Hz. NFM deviation ~5 kHz (public safety, ham).
"""
import sys
import numpy as np

try:
    from scipy.signal import firwin, lfilter
    _LP_TAPS = firwin(65, 8_000, fs=2_000_000)
    _USE_SCIPY = True
except ImportError:
    _USE_SCIPY = False

SAMPLE_RATE = 2_000_000
AUDIO_RATE  = 16_000
DECIMATE    = SAMPLE_RATE // AUDIO_RATE  # 125

_prev = None

# Soft AGC state
agc_peak   = 1.0
AGC_ATTACK  = 0.99
AGC_RELEASE = 0.9999

CHUNK_SAMPLES = AUDIO_RATE * DECIMATE  # 0.5s of IQ at 2 MSPS = 2M samples... use 0.25s
CHUNK_BYTES   = AUDIO_RATE // 2 * DECIMATE * 2  # 0.5s audio → 0.5 * 16000 * 125 * 2 bytes

def demod_chunk(raw: bytes) -> np.ndarray:
    global _prev, agc_peak

    s = np.frombuffer(raw, dtype=np.int8).astype(np.float32)
    I = s[0::2]
    Q = s[1::2]
    c = I + 1j * Q

    # FM discriminator
    if _prev is None:
        _prev = c[-1]
    c_prev = np.concatenate([[_prev], c[:-1]])
    _prev = c[-1]
    fm = np.angle(c * np.conj(c_prev))

    # Anti-alias + decimate
    if _USE_SCIPY:
        fm = lfilter(_LP_TAPS, 1.0, fm)
    audio = fm[::DECIMATE]

    # Soft AGC
    chunk_peak = float(np.max(np.abs(audio))) or 1e-6
    if chunk_peak > agc_peak:
        agc_peak = agc_peak * AGC_ATTACK  + chunk_peak * (1 - AGC_ATTACK)
    else:
        agc_peak = agc_peak * AGC_RELEASE + chunk_peak * (1 - AGC_RELEASE)

    audio_norm = np.clip(audio / agc_peak, -1.0, 1.0)
    return (audio_norm * 32767 * 0.9).astype(np.int16)


def main():
    try:
        while True:
            raw = sys.stdin.buffer.read(CHUNK_BYTES)
            if not raw:
                break
            if len(raw) % 2:
                raw = raw[:-1]
            if len(raw) < 2:
                break
            pcm = demod_chunk(raw)
            sys.stdout.buffer.write(pcm.tobytes())
            sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
