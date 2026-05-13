"""dsp.lufs 단위 테스트 — 결정성·수치 안정성·경계.

LUFS는 K-weighting + 게이팅이라 닫힌-형식 기대값을 만들기 어렵다.
* 정확성*은 pyloudnorm에 위임하고, 우리는 **속성(property)** 기반으로 검증:
- 무음 → SILENCE_FLOOR_LUFS
- 더 큰 신호 → 더 높은 LUFS (단조성)
- 같은 입력 → 같은 출력 (결정성)
- 잘못된 입력 → ValueError
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.dsp import (
    MIN_DURATION_SECONDS,
    SILENCE_FLOOR_LUFS,
    lufs_channels,
    lufs_integrated,
)

SR = 48000


def _sine(amplitude: float, freq: float = 1000.0, duration: float = 1.0) -> np.ndarray:
    """주어진 진폭의 사인파 신호 생성."""
    t = np.arange(int(SR * duration)) / SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float64)


class TestLufsIntegrated:
    def test_silence_returns_floor(self) -> None:
        samples = np.zeros(SR, dtype=np.float64)
        assert lufs_integrated(samples, SR) == SILENCE_FLOOR_LUFS

    def test_very_quiet_signal_returns_floor(self) -> None:
        # -90 dBFS 사인파 — 게이트 차단되어 floor 반환 예상.
        samples = _sine(amplitude=10 ** (-90.0 / 20.0))
        assert lufs_integrated(samples, SR) == SILENCE_FLOOR_LUFS

    def test_sine_at_typical_level_in_expected_range(self) -> None:
        # 1kHz 사인 amplitude 0.1: RMS = 0.0707 (-23 dBFS).
        # K-weighting은 1kHz에서 거의 중성이므로 LUFS ≈ -23 부근.
        # (K-weight의 +4 dB boost는 2-3kHz 영역).
        result = lufs_integrated(_sine(amplitude=0.1), SR)
        assert -25.0 < result < -21.0

    def test_louder_signal_yields_higher_lufs(self) -> None:
        # 단조성: 진폭이 클수록 LUFS도 커진다.
        a = lufs_integrated(_sine(amplitude=0.05), SR)
        b = lufs_integrated(_sine(amplitude=0.1), SR)
        c = lufs_integrated(_sine(amplitude=0.5), SR)
        assert a < b < c

    def test_doubling_amplitude_adds_about_6_db(self) -> None:
        # 진폭 2배 → +6 dB → +6 LUFS (선형 + K-weighting 안정 영역에서).
        a = lufs_integrated(_sine(amplitude=0.1), SR)
        b = lufs_integrated(_sine(amplitude=0.2), SR)
        assert b - a == pytest.approx(6.0, abs=0.1)

    def test_deterministic_same_input_same_output(self) -> None:
        samples = _sine(amplitude=0.1)
        assert lufs_integrated(samples, SR) == lufs_integrated(samples, SR)

    def test_float32_input_accepted(self) -> None:
        samples = _sine(amplitude=0.1).astype(np.float32)
        result = lufs_integrated(samples, SR)
        assert math.isfinite(result)
        assert result > SILENCE_FLOOR_LUFS

    def test_rejects_2d_input(self) -> None:
        samples = np.zeros((SR, 2), dtype=np.float64)
        with pytest.raises(ValueError, match="1D"):
            lufs_integrated(samples, SR)

    def test_rejects_zero_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            lufs_integrated(_sine(amplitude=0.1), 0)

    def test_rejects_negative_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            lufs_integrated(_sine(amplitude=0.1), -1)

    def test_rejects_too_short_signal(self) -> None:
        # 100ms — 최소 400ms 미만.
        samples = _sine(amplitude=0.1, duration=0.1)
        with pytest.raises(ValueError, match="too short"):
            lufs_integrated(samples, SR)

    def test_accepts_minimum_duration(self) -> None:
        samples = _sine(amplitude=0.1, duration=MIN_DURATION_SECONDS)
        # 예외 없이 통과 + 유한값.
        result = lufs_integrated(samples, SR)
        assert math.isfinite(result)


class TestLufsChannels:
    def test_per_channel_independent(self) -> None:
        # 두 채널: amp 0.1, amp 0.2 → 약 6 LUFS 차이.
        ch0 = _sine(amplitude=0.1)
        ch1 = _sine(amplitude=0.2)
        samples = np.column_stack([ch0, ch1])
        result = lufs_channels(samples, SR)
        assert result.shape == (2,)
        assert result[1] - result[0] == pytest.approx(6.0, abs=0.1)

    def test_32_channels_m32_scenario(self) -> None:
        # M32 시나리오: 32채널 동시 분석. 모두 동일 신호 → 동일 LUFS.
        ch = _sine(amplitude=0.1)
        samples = np.tile(ch[:, np.newaxis], (1, 32))
        result = lufs_channels(samples, SR)
        assert result.shape == (32,)
        # 모든 채널이 동일 신호이므로 LUFS도 거의 동일.
        for value in result:
            assert value == pytest.approx(result[0], abs=0.01)

    def test_returns_float64(self) -> None:
        samples = np.tile(_sine(amplitude=0.1)[:, np.newaxis], (1, 2))
        result = lufs_channels(samples, SR)
        assert result.dtype == np.float64

    def test_silent_channels_return_floor(self) -> None:
        samples = np.zeros((SR, 4), dtype=np.float64)
        result = lufs_channels(samples, SR)
        assert all(v == SILENCE_FLOOR_LUFS for v in result)

    def test_rejects_1d_input(self) -> None:
        with pytest.raises(ValueError, match="2D"):
            lufs_channels(_sine(amplitude=0.1), SR)

    def test_rejects_empty(self) -> None:
        samples = np.zeros((0, 2), dtype=np.float64)
        with pytest.raises(ValueError, match="empty"):
            lufs_channels(samples, SR)

    def test_rejects_too_short_per_channel(self) -> None:
        # 짧은 다채널 신호 → 채널별 측정에서 ValueError 전파.
        samples = np.zeros((int(SR * 0.1), 2), dtype=np.float64)
        with pytest.raises(ValueError, match="too short"):
            lufs_channels(samples, SR)
