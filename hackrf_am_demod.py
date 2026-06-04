#!/usr/bin/env python3
"""
AM envelope demodulator for HackRF IQ stream.

Usage:
    hackrf_transfer -r /dev/stdout -f <freq_hz> -s 2000000 -l <lna> -g <vga> -a <amp> \
        | python3 hackrf_am_demod.py [output.wav]

Outputs a 16-bit mono WAV at AUDIO_RATE Hz. If no output file is given, writes raw
int16 PCM to stdout (pipe to: sox -t raw -r 16000 -e signed -b 16 -c 1 - output.wav)

Aviation AM gains: LNA=16, VGA=36, amp=1
"""

import sys
import numpy as np
import wave

SAMPLE_RATE = 2_000_000
AUDIO_RATE  = 16_000
DECIMATE    = SAMPLE_RATE // AUDIO_RATE  # 125 — clean integer

# Anti-aliasing FIR: cutoff at AUDIO_RATE/2, applied before decimation
try:
    from scipy.signal import firwin, lfilter
    _LP_TAPS = firwin(65, AUDIO_RATE / 2, fs=SAMPLE_RATE)
    _USE_SCIPY = True
except ImportError:
    _USE_SCIPY = False

_DC_ALPHA = 0.995  # IIR DC blocker pole: H(z) = (1-z^-1)/(1-α*z^-1)
_DC_B = np.array([1.0, -1.0])
_DC_A = np.array([1.0, -_DC_ALPHA])
_dc_zi = np.zeros(1)

def _demod_chunk(raw: bytes) -> np.ndarray:
    global _dc_zi
    samples = np.frombuffer(raw, dtype=np.int8).astype(np.float32)
    I = samples[0::2]
    Q = samples[1::2]

    # AM envelope detection
    env = np.sqrt(I * I + Q * Q)

    # Anti-alias then decimate
    if _USE_SCIPY:
        env = lfilter(_LP_TAPS, 1.0, env)
    audio = env[::DECIMATE]

    # IIR DC blocker via scipy (preserves state across chunks)
    if _USE_SCIPY:
        audio, _dc_zi = lfilter(_DC_B, _DC_A, audio, zi=_dc_zi)
    else:
        audio -= np.mean(audio)

    return audio


def main():
    outfile = sys.argv[1] if len(sys.argv) > 1 else None
    wav = None

    if outfile:
        wav = wave.open(outfile, 'w')
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(AUDIO_RATE)

    # Process in chunks of 0.5s of audio samples
    chunk_iq_bytes = DECIMATE * 8000 * 2  # 0.5s at SAMPLE_RATE, 2 bytes/sample

    # Running peak for soft AGC
    agc_peak = 1.0
    AGC_ATTACK  = 0.99
    AGC_RELEASE = 0.9999

    try:
        while True:
            raw = sys.stdin.buffer.read(chunk_iq_bytes)
            if not raw:
                break
            # Pad last chunk if needed
            if len(raw) % 2:
                raw = raw[:-1]
            if len(raw) < 2:
                break

            audio = _demod_chunk(raw)

            # Soft AGC
            chunk_peak = float(np.max(np.abs(audio))) or 1e-6
            if chunk_peak > agc_peak:
                agc_peak = agc_peak * AGC_ATTACK + chunk_peak * (1 - AGC_ATTACK)
            else:
                agc_peak = agc_peak * AGC_RELEASE + chunk_peak * (1 - AGC_RELEASE)

            audio_norm = np.clip(audio / agc_peak, -1.0, 1.0)
            pcm = (audio_norm * 32767 * 0.9).astype(np.int16)

            if wav:
                wav.writeframes(pcm.tobytes())
            else:
                sys.stdout.buffer.write(pcm.tobytes())
                sys.stdout.buffer.flush()

    except KeyboardInterrupt:
        pass
    finally:
        if wav:
            wav.close()
            sys.stderr.write(f"Wrote {outfile}\n")


if __name__ == "__main__":
    main()
