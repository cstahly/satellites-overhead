#!/usr/bin/env python3
"""Bounded-memory spectrum summary for a raw HackRF int8 IQ capture."""

import math
import os
import sys

import numpy as np


SAMPLE_RATE = 2_000_000
FFT_SIZE = 8192
MAX_WINDOWS = 4096


def average_spectrum(path, fft_size=FFT_SIZE, max_windows=MAX_WINDOWS):
    total_complex_samples = os.path.getsize(path) // 2
    total_windows = total_complex_samples // fft_size
    if total_windows < 1:
        raise ValueError("capture is too short for spectrum analysis")

    stride = max(1, math.ceil(total_windows / max_windows))
    power_sum = np.zeros(fft_size, dtype=np.float64)
    windows_analyzed = 0

    with open(path, "rb") as capture:
        for window_index in range(0, total_windows, stride):
            capture.seek(window_index * fft_size * 2)
            raw = capture.read(fft_size * 2)
            if len(raw) < fft_size * 2:
                break
            samples = np.frombuffer(raw, dtype=np.int8)
            iq = samples[0::2].astype(np.float32)
            iq = iq.astype(np.complex64)
            iq.imag = samples[1::2]
            spectrum = np.fft.fftshift(np.fft.fft(iq))
            power_sum += np.abs(spectrum) ** 2
            windows_analyzed += 1

    if windows_analyzed < 1:
        raise ValueError("capture contains no complete analysis windows")
    return power_sum / windows_analyzed, total_complex_samples, windows_analyzed


def analyze(path, label="unknown", center_hz=150_000_000):
    average_power, total_samples, windows_analyzed = average_spectrum(path)
    average_db = 10 * np.log10(average_power + 1e-10)
    frequencies = center_hz + np.fft.fftshift(np.fft.fftfreq(FFT_SIZE, d=1 / SAMPLE_RATE))
    noise = float(np.median(average_db))

    peaks = [
        (frequencies[i], average_db[i] - noise)
        for i in range(len(average_db))
        if average_db[i] - noise > 8 and abs(frequencies[i] - center_hz) >= 50_000
    ]
    peaks.sort(key=lambda item: -item[1])

    lines = [
        f"\n=== {label} ===",
        f"Duration: {total_samples / SAMPLE_RATE:.0f}s | Noise: {noise:.1f} dB | "
        f"FFT windows: {windows_analyzed}",
    ]
    if peaks:
        lines.append("Off-center signals (excluding LO):")
        for frequency_hz, strength_db in peaks[:10]:
            lines.append(f"  {frequency_hz / 1e6:.4f} MHz  +{strength_db:.1f} dB")
        sidebands_khz = [abs(frequency_hz - center_hz) / 1000 for frequency_hz, _ in peaks[:10]]
        if any(2.5 < sideband < 3.5 or 4.5 < sideband < 5.5 or 6.5 < sideband < 7.5
               for sideband in sidebands_khz):
            lines.append("*** TSIKADA SIDEBAND PATTERN DETECTED ***")
    else:
        lines.append("No significant off-center signals detected")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <file.iq> [label] [center_hz]")
    label = sys.argv[2] if len(sys.argv) > 2 else "unknown"
    center_hz = float(sys.argv[3]) if len(sys.argv) > 3 else 150_000_000
    print(analyze(sys.argv[1], label, center_hz))


if __name__ == "__main__":
    main()
