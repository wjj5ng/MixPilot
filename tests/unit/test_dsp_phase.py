"""Phase correlation DSP 단위 테스트."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.dsp.phase import (
    UNDEFINED_PHASE,
    phase_correlation,
    phase_correlation_pair,
)


def _sine(freq_hz: float, *, amp: float = 0.5, n: int = 4800) -> np.ndarray:
    t = np.arange(n) / 48000
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float64)


class TestInputValidation:
    def test_rejects_2d_left(self) -> None:
        with pytest.raises(ValueError, match="must be 1D"):
            phase_correlation(np.zeros((10, 2)), np.zeros(20))

    def test_rejects_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="length mismatch"):
            phase_correlation(np.zeros(100), np.zeros(50))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            phase_correlation(np.zeros(0), np.zeros(0))


class TestKnownSignals:
    def test_identical_signals_correlation_one(self) -> None:
        sig = _sine(1000.0, amp=0.5)
        assert phase_correlation(sig, sig) == pytest.approx(1.0, abs=1e-9)

    def test_antiphase_signals_correlation_negative_one(self) -> None:
        # 같은 신호에 -1 곱 → 완전 역상.
        sig = _sine(1000.0, amp=0.5)
        assert phase_correlation(sig, -sig) == pytest.approx(-1.0, abs=1e-9)

    def test_uncorrelated_sines_near_zero(self) -> None:
        # 다른 주파수 + 충분한 길이 → ~0 (정확히 0은 아니지만 작음).
        lhs = _sine(1000.0, amp=0.5, n=48000)
        rhs = _sine(2500.0, amp=0.5, n=48000)
        assert abs(phase_correlation(lhs, rhs)) < 0.05

    def test_one_silent_channel_returns_undefined(self) -> None:
        # L은 신호, R은 무음 → 분모 ≈ 0 → UNDEFINED_PHASE.
        lhs = _sine(1000.0, amp=0.5)
        rhs = np.zeros_like(lhs)
        assert phase_correlation(lhs, rhs) == UNDEFINED_PHASE

    def test_both_silent_undefined(self) -> None:
        lhs = np.zeros(1024, dtype=np.float64)
        rhs = np.zeros(1024, dtype=np.float64)
        assert phase_correlation(lhs, rhs) == UNDEFINED_PHASE


class TestProperties:
    def test_result_in_unit_range(self) -> None:
        rng = np.random.default_rng(42)
        for _ in range(20):
            n = int(rng.integers(100, 8000))
            lhs = (rng.standard_normal(n) * rng.uniform(0.05, 0.5)).astype(np.float64)
            rhs = (rng.standard_normal(n) * rng.uniform(0.05, 0.5)).astype(np.float64)
            result = phase_correlation(lhs, rhs)
            assert -1.0 <= result <= 1.0

    def test_symmetric(self) -> None:
        # corr(L, R) == corr(R, L).
        rng = np.random.default_rng(0)
        lhs = rng.standard_normal(2000).astype(np.float64)
        rhs = rng.standard_normal(2000).astype(np.float64)
        assert phase_correlation(lhs, rhs) == pytest.approx(
            phase_correlation(rhs, lhs), abs=1e-12
        )

    def test_scale_invariance(self) -> None:
        # 한쪽에 양수 scalar를 곱해도 correlation은 동일.
        sig_a = _sine(1000.0, amp=0.3)
        sig_b = _sine(1100.0, amp=0.4)
        base = phase_correlation(sig_a, sig_b)
        scaled = phase_correlation(sig_a, sig_b * 2.5)
        assert scaled == pytest.approx(base, abs=1e-9)

    def test_partial_phase_inversion_between_minus_one_and_zero(self) -> None:
        # 90도 위상 차 → correlation 0 근처(같은 sine이지만 cos이므로 직교).
        n = 48000
        t = np.arange(n) / 48000
        lhs = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
        rhs = (0.5 * np.cos(2 * np.pi * 1000 * t)).astype(np.float64)
        # 직교 신호 → 거의 0.
        assert abs(phase_correlation(lhs, rhs)) < 0.05

    def test_180_degree_phase_shift_gives_minus_one(self) -> None:
        n = 48000
        t = np.arange(n) / 48000
        lhs = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
        # 180도 phase shift = -L.
        rhs = (0.5 * np.sin(2 * np.pi * 1000 * t + math.pi)).astype(np.float64)
        assert phase_correlation(lhs, rhs) == pytest.approx(-1.0, abs=1e-9)


class TestPairChannelAccess:
    def test_extracts_channels_correctly(self) -> None:
        # ch0 sine, ch1 sine x -1, ch2 noise.
        sig = _sine(1000.0, amp=0.5, n=4800)
        rng = np.random.default_rng(0)
        noise = (rng.standard_normal(4800) * 0.1).astype(np.float64)
        samples = np.stack([sig, -sig, noise], axis=1)
        # ch0/ch1: 역상 → -1.
        assert phase_correlation_pair(samples, 0, 1) == pytest.approx(-1.0, abs=1e-9)
        # ch0/ch2: 사인 vs 노이즈 → 약한 상관.
        assert abs(phase_correlation_pair(samples, 0, 2)) < 0.1

    def test_same_index_returns_one(self) -> None:
        rng = np.random.default_rng(0)
        samples = rng.standard_normal((100, 4)).astype(np.float64)
        assert phase_correlation_pair(samples, 2, 2) == 1.0

    def test_index_out_of_range_raises(self) -> None:
        samples = np.zeros((10, 2), dtype=np.float64)
        with pytest.raises(ValueError, match="out of range"):
            phase_correlation_pair(samples, 0, 5)
        with pytest.raises(ValueError, match="out of range"):
            phase_correlation_pair(samples, -1, 0)

    def test_rejects_1d_input(self) -> None:
        with pytest.raises(ValueError, match="must be 2D"):
            phase_correlation_pair(np.zeros(100), 0, 0)
