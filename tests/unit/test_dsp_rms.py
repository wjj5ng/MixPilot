"""dsp.rms 단위 테스트 — 알려진 신호 검증·수치 안정성·결정성."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.dsp import SILENCE_FLOOR_DBFS, rms, rms_channels, to_dbfs


class TestRms:
    def test_sine_wave_rms_equals_amplitude_over_sqrt2(self) -> None:
        amplitude = 0.5
        sample_rate = 48000
        freq = 440
        t = np.arange(sample_rate) / sample_rate
        sig = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float64)
        expected = amplitude / math.sqrt(2)
        assert rms(sig) == pytest.approx(expected, rel=1e-4)

    def test_dc_signal_rms_equals_absolute_value(self) -> None:
        sig = np.full(1000, 0.3, dtype=np.float64)
        assert rms(sig) == pytest.approx(0.3, abs=1e-12)

    def test_zero_signal_is_exactly_zero(self) -> None:
        sig = np.zeros(1024, dtype=np.float64)
        assert rms(sig) == 0.0

    def test_single_sample(self) -> None:
        sig = np.array([0.7], dtype=np.float64)
        assert rms(sig) == pytest.approx(0.7)

    def test_impulse_rms(self) -> None:
        # 길이 N에 단일 임펄스(=1.0) → RMS = 1/sqrt(N).
        n = 100
        sig = np.zeros(n, dtype=np.float64)
        sig[0] = 1.0
        assert rms(sig) == pytest.approx(1.0 / math.sqrt(n))

    def test_float32_input_handled(self) -> None:
        sig = np.array([0.5, -0.5], dtype=np.float32)
        # sqrt((0.25 + 0.25) / 2) = 0.5
        assert rms(sig) == pytest.approx(0.5)

    def test_negative_and_positive_symmetric(self) -> None:
        a = np.array([0.4, -0.3, 0.2, -0.1], dtype=np.float64)
        b = -a
        assert rms(a) == pytest.approx(rms(b))

    def test_rejects_2d_input(self) -> None:
        sig = np.zeros((100, 2), dtype=np.float64)
        with pytest.raises(ValueError, match="1D"):
            rms(sig)

    def test_rejects_empty_input(self) -> None:
        sig = np.array([], dtype=np.float64)
        with pytest.raises(ValueError, match="empty"):
            rms(sig)

    def test_deterministic_same_input_same_output(self) -> None:
        # 결정성 원칙: 같은 입력이면 항상 같은 결과.
        sig = np.random.default_rng(42).standard_normal(1000)
        assert rms(sig) == rms(sig)


class TestRmsChannels:
    def test_per_channel_independent(self) -> None:
        sig = np.column_stack(
            [
                np.full(1000, 0.3),
                np.full(1000, 0.7),
            ]
        )
        result = rms_channels(sig)
        assert result.shape == (2,)
        assert result[0] == pytest.approx(0.3, abs=1e-12)
        assert result[1] == pytest.approx(0.7, abs=1e-12)

    def test_32_channels_m32_scenario(self) -> None:
        # M32 시나리오: 32채널 동시 분석.
        frames = 512
        sig = np.tile(np.arange(32, dtype=np.float64) * 0.01, (frames, 1))
        result = rms_channels(sig)
        assert result.shape == (32,)
        for i in range(32):
            assert result[i] == pytest.approx(i * 0.01, abs=1e-12)

    def test_returns_float64(self) -> None:
        sig = np.zeros((100, 4), dtype=np.float32)
        result = rms_channels(sig)
        assert result.dtype == np.float64

    def test_rejects_1d_input(self) -> None:
        sig = np.zeros(100, dtype=np.float64)
        with pytest.raises(ValueError, match="2D"):
            rms_channels(sig)

    def test_rejects_empty(self) -> None:
        sig = np.zeros((0, 2), dtype=np.float64)
        with pytest.raises(ValueError, match="empty"):
            rms_channels(sig)


class TestToDbfs:
    def test_full_scale_is_zero_db(self) -> None:
        assert to_dbfs(1.0) == pytest.approx(0.0)

    def test_half_amplitude_is_negative_6db(self) -> None:
        # 20 * log10(0.5) ≈ -6.02
        assert to_dbfs(0.5) == pytest.approx(-6.020599913, abs=1e-6)

    def test_silence_uses_floor(self) -> None:
        assert to_dbfs(0.0) == SILENCE_FLOOR_DBFS

    def test_negative_input_treated_as_silence(self) -> None:
        # 음수 amplitude는 비정상이지만 안전하게 floor 처리.
        assert to_dbfs(-0.5) == SILENCE_FLOOR_DBFS

    def test_custom_ref_scales_correctly(self) -> None:
        # ref=2.0, linear=1.0 → 20 * log10(0.5).
        assert to_dbfs(1.0, ref=2.0) == pytest.approx(-6.020599913, abs=1e-6)

    def test_rejects_non_positive_ref(self) -> None:
        with pytest.raises(ValueError, match="ref"):
            to_dbfs(0.5, ref=0.0)
        with pytest.raises(ValueError, match="ref"):
            to_dbfs(0.5, ref=-1.0)

    def test_deterministic(self) -> None:
        assert to_dbfs(0.123) == to_dbfs(0.123)
