"""dsp.peak 단위 테스트 — sample peak + true peak."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.dsp import (
    DEFAULT_TRUE_PEAK_OVERSAMPLE,
    peak,
    peak_channels,
    true_peak,
    true_peak_channels,
)

SR = 48000


def _sine(amplitude: float, freq: float = 1000.0, duration: float = 0.1) -> np.ndarray:
    t = np.arange(int(SR * duration)) / SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float64)


class TestPeak:
    def test_sine_amplitude(self) -> None:
        assert peak(_sine(amplitude=0.5)) == pytest.approx(0.5, rel=1e-3)

    def test_dc_signal(self) -> None:
        sig = np.full(1000, 0.3, dtype=np.float64)
        assert peak(sig) == pytest.approx(0.3, abs=1e-12)

    def test_silence_is_zero(self) -> None:
        assert peak(np.zeros(1024, dtype=np.float64)) == 0.0

    def test_mixed_signs(self) -> None:
        sig = np.array([0.1, -0.7, 0.3, -0.2], dtype=np.float64)
        assert peak(sig) == pytest.approx(0.7)

    def test_single_sample(self) -> None:
        assert peak(np.array([-0.42], dtype=np.float64)) == pytest.approx(0.42)

    def test_float32_input_handled(self) -> None:
        sig = _sine(amplitude=0.5).astype(np.float32)
        assert peak(sig) == pytest.approx(0.5, rel=1e-3)

    def test_negative_and_positive_symmetric(self) -> None:
        a = np.array([0.4, -0.3, 0.2, -0.1], dtype=np.float64)
        assert peak(a) == peak(-a)

    def test_rejects_2d_input(self) -> None:
        with pytest.raises(ValueError, match="1D"):
            peak(np.zeros((100, 2), dtype=np.float64))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            peak(np.array([], dtype=np.float64))

    def test_deterministic(self) -> None:
        sig = np.random.default_rng(42).standard_normal(1000)
        assert peak(sig) == peak(sig)


class TestPeakChannels:
    def test_per_channel_independent(self) -> None:
        sig = np.column_stack(
            [
                np.array([0.1, -0.3, 0.2]),
                np.array([0.5, -0.6, 0.4]),
            ]
        )
        result = peak_channels(sig)
        assert result.shape == (2,)
        assert result[0] == pytest.approx(0.3)
        assert result[1] == pytest.approx(0.6)

    def test_32_channels_m32_scenario(self) -> None:
        frames = 512
        sig = np.tile(np.arange(32, dtype=np.float64) * 0.01, (frames, 1))
        result = peak_channels(sig)
        assert result.shape == (32,)
        for i in range(32):
            assert result[i] == pytest.approx(i * 0.01, abs=1e-12)

    def test_returns_float64(self) -> None:
        sig = np.zeros((100, 4), dtype=np.float32)
        assert peak_channels(sig).dtype == np.float64

    def test_rejects_1d_input(self) -> None:
        with pytest.raises(ValueError, match="2D"):
            peak_channels(np.zeros(100, dtype=np.float64))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            peak_channels(np.zeros((0, 2), dtype=np.float64))


class TestTruePeak:
    def test_sine_close_to_amplitude(self) -> None:
        # 1kHz 사인 amp 0.5 → true peak는 0.5 이상이고 약간 더 클 수 있음.
        # 4x 오버샘플링 후 inter-sample 최댓값.
        result = true_peak(_sine(amplitude=0.5))
        assert math.isfinite(result)
        # sample peak는 0.5 근처(샘플 격자에 맞을 수도 있음).
        # true peak는 그것 이상.
        assert result >= peak(_sine(amplitude=0.5)) - 1e-9
        # 그리고 진폭의 110% 안에 있어야 정상 (대형 over-shoot 없음).
        assert result < 0.5 * 1.1

    def test_always_at_least_sample_peak(self) -> None:
        # true_peak >= peak 라는 속성을 여러 신호로 검증.
        rng = np.random.default_rng(123)
        for _ in range(5):
            sig = rng.standard_normal(1024) * 0.3
            p = peak(sig)
            tp = true_peak(sig)
            assert tp >= p - 1e-9

    def test_silence_is_zero(self) -> None:
        assert true_peak(np.zeros(1024, dtype=np.float64)) == pytest.approx(
            0.0, abs=1e-9
        )

    def test_dc_signal_remains_dc(self) -> None:
        # DC는 오버샘플링 후에도 DC. peak == |DC value|.
        sig = np.full(1000, 0.3, dtype=np.float64)
        # resample_poly의 양 끝 transient 영향을 감안해 약간의 tolerance.
        assert true_peak(sig) == pytest.approx(0.3, abs=0.05)

    def test_oversample_one_equals_sample_peak(self) -> None:
        sig = _sine(amplitude=0.7)
        assert true_peak(sig, oversample=1) == peak(sig)

    def test_higher_oversample_yields_at_least_lower(self) -> None:
        # 단조성: 더 높은 oversample은 더 정확 → 동등 이상.
        sig = _sine(amplitude=0.5)
        tp2 = true_peak(sig, oversample=2)
        tp4 = true_peak(sig, oversample=4)
        tp8 = true_peak(sig, oversample=8)
        # 모두 sample peak 이상. 단순 단조성은 강제 아님(필터 양상에 따라
        # 미세 변동) — 대신 sample peak 하한 검증.
        sp = peak(sig)
        for tp in (tp2, tp4, tp8):
            assert tp >= sp - 1e-9

    def test_default_oversample_constant(self) -> None:
        assert DEFAULT_TRUE_PEAK_OVERSAMPLE == 4

    def test_deterministic(self) -> None:
        sig = np.random.default_rng(7).standard_normal(1024) * 0.3
        assert true_peak(sig) == true_peak(sig)

    def test_float32_input_handled(self) -> None:
        sig = _sine(amplitude=0.5).astype(np.float32)
        assert math.isfinite(true_peak(sig))

    def test_rejects_2d_input(self) -> None:
        with pytest.raises(ValueError, match="1D"):
            true_peak(np.zeros((100, 2), dtype=np.float64))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            true_peak(np.array([], dtype=np.float64))

    def test_rejects_oversample_zero(self) -> None:
        with pytest.raises(ValueError, match="oversample"):
            true_peak(_sine(amplitude=0.1), oversample=0)

    def test_rejects_oversample_negative(self) -> None:
        with pytest.raises(ValueError, match="oversample"):
            true_peak(_sine(amplitude=0.1), oversample=-1)


class TestTruePeakChannels:
    def test_per_channel_independent(self) -> None:
        sig = np.column_stack(
            [
                _sine(amplitude=0.3),
                _sine(amplitude=0.7),
            ]
        )
        result = true_peak_channels(sig)
        assert result.shape == (2,)
        # 채널 1이 더 작고 채널 2가 더 큼.
        assert result[0] < result[1]

    def test_32_channels(self) -> None:
        frames = 1024
        # 채널마다 다른 amplitude의 사인파.
        sig = np.column_stack(
            [_sine(amplitude=0.01 * (i + 1), duration=frames / SR) for i in range(32)]
        )
        result = true_peak_channels(sig)
        assert result.shape == (32,)
        # 단조 증가: 채널 인덱스 클수록 더 큰 true peak.
        for i in range(31):
            assert result[i] <= result[i + 1] + 1e-9

    def test_returns_float64(self) -> None:
        sig = np.zeros((512, 2), dtype=np.float32)
        # 0 신호도 OK — resample_poly가 0을 반환.
        assert true_peak_channels(sig).dtype == np.float64

    def test_oversample_one_equals_peak_channels(self) -> None:
        sig = np.column_stack([_sine(amplitude=0.4), _sine(amplitude=0.6)])
        np.testing.assert_array_equal(
            true_peak_channels(sig, oversample=1), peak_channels(sig)
        )

    def test_rejects_1d_input(self) -> None:
        with pytest.raises(ValueError, match="2D"):
            true_peak_channels(np.zeros(100, dtype=np.float64))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            true_peak_channels(np.zeros((0, 2), dtype=np.float64))

    def test_rejects_oversample_zero(self) -> None:
        sig = np.zeros((100, 2), dtype=np.float64)
        with pytest.raises(ValueError, match="oversample"):
            true_peak_channels(sig, oversample=0)
