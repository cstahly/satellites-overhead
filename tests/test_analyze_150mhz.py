import os
import tempfile
import unittest

import numpy as np

from analyze_150mhz import average_spectrum


class AverageSpectrumTests(unittest.TestCase):
    def test_analysis_is_bounded_by_max_windows(self):
        fft_size = 256
        total_windows = 10
        samples = np.tile(np.array([20, -20], dtype=np.int8), fft_size * total_windows)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "capture.iq")
            samples.tofile(path)
            spectrum, total_samples, windows = average_spectrum(
                path,
                fft_size=fft_size,
                max_windows=3,
            )

        self.assertEqual(total_samples, fft_size * total_windows)
        self.assertEqual(windows, 3)
        self.assertEqual(spectrum.shape, (fft_size,))
        self.assertTrue(np.isfinite(spectrum).all())


if __name__ == "__main__":
    unittest.main()
