"""옥타브 밴드 스펙트럼 DSP 단위 테스트."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.dsp.rms import SILENCE_FLOOR_DBFS
from mixpilot.dsp.spectrum import OCTAVE_CENTERS_HZ, octave_band_levels_dbfs

_SR = 48000


def _sine(freq_hz: float, *, amp: float = 1.0, n: int = 4096) -> np.ndarray:
    t = np.arange(n) / _SR
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float64)


class TestShape:
    def test_returns_one_value_per_octave(self) -> None:
        bands = octave_band_levels_dbfs(_sine(1000.0), _SR)
        assert len(bands) == len(OCTAVE_CENTERS_HZ)

    def test_all_values_are_floats(self) -> None:
        bands = octave_band_levels_dbfs(_sine(1000.0), _SR)
        assert all(isinstance(b, float) for b in bands)


class TestInputValidation:
    def test_rejects_2d(self) -> None:
        with pytest.raises(ValueError, match="must be 1D"):
            octave_band_levels_dbfs(np.zeros((100, 2), dtype=np.float64), _SR)

    def test_rejects_non_positive_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate must be positive"):
            octave_band_levels_dbfs(_sine(1000.0), 0)

    def test_tiny_signal_returns_all_silence(self) -> None:
        bands = octave_band_levels_dbfs(np.zeros(3, dtype=np.float64), _SR)
        assert bands == [SILENCE_FLOOR_DBFS] * len(OCTAVE_CENTERS_HZ)


class TestSineLocalization:
    def test_1khz_sine_peaks_in_1khz_band(self) -> None:
        # 1 kHz 사인 amplitude 1 → 1 kHz 밴드(707-1414 Hz)가 최대.
        bands = octave_band_levels_dbfs(_sine(1000.0, amp=1.0, n=8192), _SR)
        # 1 kHz 밴드의 인덱스 — OCTAVE_CENTERS_HZ에서 4번째 (인덱스 3).
        khz_idx = OCTAVE_CENTERS_HZ.index(1000.0)
        max_idx = max(range(len(bands)), key=lambda i: bands[i])
        assert max_idx == khz_idx

    def test_4khz_sine_peaks_in_4khz_band(self) -> None:
        bands = octave_band_levels_dbfs(_sine(4000.0, amp=1.0, n=8192), _SR)
        khz4_idx = OCTAVE_CENTERS_HZ.index(4000.0)
        max_idx = max(range(len(bands)), key=lambda i: bands[i])
        assert max_idx == khz4_idx

    def test_full_scale_sine_near_minus_3_dbfs_in_band(self) -> None:
        # Hann leakage 고려해 ±2 dB 허용.
        bands = octave_band_levels_dbfs(_sine(1000.0, amp=1.0, n=8192), _SR)
        khz_idx = OCTAVE_CENTERS_HZ.index(1000.0)
        # RMS = 1/√2 → -3.01 dBFS.
        assert bands[khz_idx] == pytest.approx(-3.01, abs=2.0)


class TestSilence:
    def test_silence_all_silence_floor(self) -> None:
        bands = octave_band_levels_dbfs(np.zeros(4096, dtype=np.float64), _SR)
        assert bands == [SILENCE_FLOOR_DBFS] * len(OCTAVE_CENTERS_HZ)


class TestPropertyOrderInvariance:
    def test_band_order_matches_octave_centers(self) -> None:
        # bands[i]가 OCTAVE_CENTERS_HZ[i] 밴드에 해당하는지 — 다중 사인으로 점검.
        # 250 Hz + 4 kHz 사인을 동시에 → 두 밴드만 두드러져야 함.
        n = 8192
        t = np.arange(n) / _SR
        sig = (
            0.3 * np.sin(2 * np.pi * 250.0 * t) + 0.3 * np.sin(2 * np.pi * 4000.0 * t)
        ).astype(np.float64)
        bands = octave_band_levels_dbfs(sig, _SR)
        idx_250 = OCTAVE_CENTERS_HZ.index(250.0)
        idx_4k = OCTAVE_CENTERS_HZ.index(4000.0)
        # 두 밴드 모두 강함 — 다른 밴드들보다 큼.
        other_max = max(b for i, b in enumerate(bands) if i not in {idx_250, idx_4k})
        assert bands[idx_250] > other_max
        assert bands[idx_4k] > other_max


class TestFiniteValues:
    def test_random_input_yields_finite_bands(self) -> None:
        rng = np.random.default_rng(42)
        signal = (rng.standard_normal(4096) * 0.1).astype(np.float64)
        bands = octave_band_levels_dbfs(signal, _SR)
        assert all(math.isfinite(b) or b == SILENCE_FLOOR_DBFS for b in bands)
