"""Dynamic Range (crest factor in dB) 단위 테스트."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.dsp.dynamic_range import dynamic_range_channels, dynamic_range_db


class TestDynamicRangeDb:
    def test_silence_returns_zero(self) -> None:
        signal = np.zeros(1000, dtype=np.float64)
        assert dynamic_range_db(signal) == 0.0

    def test_dc_signal_zero_dr(self) -> None:
        # DC: peak=value, RMS=|value| → 비율 1 → 0 dB.
        signal = np.full(1000, 0.5, dtype=np.float64)
        assert dynamic_range_db(signal) == pytest.approx(0.0, abs=1e-9)

    def test_sine_wave_crest_factor(self) -> None:
        # 사인파의 이론 crest factor: 20·log10(√2) = 3.0103 dB.
        sr = 48000
        t = np.arange(sr) / sr
        signal = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
        dr = dynamic_range_db(signal)
        assert dr == pytest.approx(20.0 * math.log10(math.sqrt(2.0)), abs=1e-3)

    def test_sine_wave_independent_of_amplitude(self) -> None:
        # Crest factor는 amplitude에 무관 — 비율만 의존.
        sr = 48000
        t = np.arange(sr) / sr
        for amp in (0.01, 0.1, 0.5, 0.99):
            signal = (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
            assert dynamic_range_db(signal) == pytest.approx(
                20.0 * math.log10(math.sqrt(2.0)), abs=1e-3
            )

    def test_white_noise_dr_in_typical_range(self) -> None:
        # 가우시안 화이트 노이즈는 보통 10~14 dB.
        rng = np.random.default_rng(42)
        signal = rng.standard_normal(48000).astype(np.float64) * 0.1
        dr = dynamic_range_db(signal)
        assert 8.0 < dr < 16.0

    def test_property_dr_always_non_negative(self) -> None:
        # peak >= RMS는 수학적 항등 (max ≥ mean of squares√).
        rng = np.random.default_rng(7)
        for _ in range(20):
            signal = (rng.standard_normal(1024) * rng.uniform(0.01, 1.0)).astype(
                np.float64
            )
            assert dynamic_range_db(signal) >= 0.0

    def test_impulse_high_dr(self) -> None:
        # 단일 임펄스: peak=1, RMS = 1/√N. DR = 20·log10(√N).
        n = 1024
        signal = np.zeros(n, dtype=np.float64)
        signal[0] = 1.0
        expected = 20.0 * math.log10(math.sqrt(n))
        assert dynamic_range_db(signal) == pytest.approx(expected, rel=1e-6)

    def test_rejects_2d(self) -> None:
        with pytest.raises(ValueError, match="must be 1D"):
            dynamic_range_db(np.zeros((10, 2), dtype=np.float64))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            dynamic_range_db(np.zeros(0, dtype=np.float64))

    def test_accepts_float32(self) -> None:
        signal = (0.5 * np.sin(np.linspace(0, 2 * np.pi * 100, 4800))).astype(
            np.float32
        )
        dr = dynamic_range_db(signal)
        assert dr == pytest.approx(20.0 * math.log10(math.sqrt(2.0)), abs=1e-2)


class TestDynamicRangeChannels:
    def test_shape_and_dtype(self) -> None:
        rng = np.random.default_rng(0)
        signal = rng.standard_normal((1024, 4)).astype(np.float64) * 0.1
        out = dynamic_range_channels(signal)
        assert out.shape == (4,)
        assert out.dtype == np.float64

    def test_per_channel_independent(self) -> None:
        sr = 48000
        t = np.arange(sr) / sr
        ch_sine = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
        ch_dc = np.full(sr, 0.5, dtype=np.float64)
        ch_silence = np.zeros(sr, dtype=np.float64)
        signal = np.stack([ch_sine, ch_dc, ch_silence], axis=1)
        out = dynamic_range_channels(signal)
        assert out[0] == pytest.approx(
            20.0 * math.log10(math.sqrt(2.0)), abs=1e-3
        )
        assert out[1] == pytest.approx(0.0, abs=1e-9)
        assert out[2] == 0.0

    def test_rejects_1d(self) -> None:
        with pytest.raises(ValueError, match="must be 2D"):
            dynamic_range_channels(np.zeros(100, dtype=np.float64))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            dynamic_range_channels(np.zeros((0, 4), dtype=np.float64))
