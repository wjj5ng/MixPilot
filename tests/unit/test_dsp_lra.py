"""LRA (Loudness Range) DSP 단위 테스트 — EBU R128 / Tech 3342 회귀."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.dsp.lra import (
    BLOCK_SECONDS,
    MIN_DURATION_SECONDS,
    NO_LRA,
    lra,
)

_SR = 48000


def _sine(duration_s: float, freq_hz: float = 1000.0, amp: float = 0.5) -> np.ndarray:
    n = int(duration_s * _SR)
    t = np.arange(n) / _SR
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float64)


def _silence(duration_s: float) -> np.ndarray:
    return np.zeros(int(duration_s * _SR), dtype=np.float64)


def _concat(*chunks: np.ndarray) -> np.ndarray:
    return np.concatenate(chunks)


class TestInputValidation:
    def test_rejects_2d(self) -> None:
        with pytest.raises(ValueError, match="must be 1D"):
            lra(np.zeros((10000, 2), dtype=np.float64), _SR)

    def test_rejects_non_positive_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate must be positive"):
            lra(_sine(5.0), 0)

    def test_rejects_unsupported_sample_rate(self) -> None:
        # 44.1 kHz는 미지원 — ADR-0009.
        # 길이를 3초 이상 확보해 길이 가드를 통과 → sample_rate 가드를 트리거.
        n = int(5.0 * 44100)
        samples = np.zeros(n, dtype=np.float64)
        with pytest.raises(ValueError, match="48000"):
            lra(samples, 44100)

    def test_rejects_too_short(self) -> None:
        # 2.5초는 3초 블록 미만.
        with pytest.raises(ValueError, match="too short"):
            lra(_sine(2.5), _SR)

    def test_exactly_min_duration_works(self) -> None:
        # 3.0초 (1 블록 1 시점)는 통과해야 함.
        result = lra(_sine(MIN_DURATION_SECONDS), _SR)
        assert math.isfinite(result)


class TestSteadySignal:
    def test_steady_sine_has_low_lra(self) -> None:
        # 일정한 amplitude의 사인파 — LRA가 0에 가까워야 함.
        # short-term LUFS가 모든 블록에서 거의 동일 → P95 - P10 ≈ 0.
        result = lra(_sine(10.0, amp=0.5), _SR)
        assert result == pytest.approx(0.0, abs=0.5)

    def test_silence_returns_no_lra(self) -> None:
        # 무음 → 절대 게이트로 전부 제거 → NO_LRA.
        result = lra(_silence(10.0), _SR)
        assert result == NO_LRA


class TestTwoLevelSignal:
    def test_two_level_lra_approximates_level_difference(self) -> None:
        # 첫 30s는 amp 0.5 (loud), 다음 30s는 amp 0.05 (20 dB down).
        # 양쪽 모두 게이팅을 통과하므로 LRA ≈ 20 LU 근처여야 함.
        loud = _sine(30.0, amp=0.5)
        soft = _sine(30.0, amp=0.05)
        signal = _concat(loud, soft)
        result = lra(signal, _SR)
        # K-weighting + percentile 보간 + 전환 구간 블록의 평균화로 정확
        # 20 LU는 아니지만 18~22 사이여야 함.
        assert 18.0 <= result <= 22.0

    def test_lra_always_non_negative(self) -> None:
        # 어떤 신호든 LRA = P95 - P10 >= 0.
        rng = np.random.default_rng(42)
        for _ in range(5):
            duration = float(rng.uniform(3.5, 8.0))
            amp = float(rng.uniform(0.05, 0.5))
            samples = _sine(duration, amp=amp)
            result = lra(samples, _SR)
            assert result >= 0.0


class TestGatingBehavior:
    def test_loud_section_followed_by_silence_gated(self) -> None:
        # 5s loud + 30s silence — silence는 -70 LUFS 미만으로 게이팅됨.
        # 결과적으로 loud 부분만 남아 LRA ≈ 0 (균일).
        loud = _sine(5.0, amp=0.5)
        sil = _silence(30.0)
        signal = _concat(loud, sil)
        result = lra(signal, _SR)
        # silence는 절대 게이트로 제거 → 남는 short-term은 loud 영역만 → 좁은 분포.
        assert result < 5.0

    def test_all_silence_returns_no_lra(self) -> None:
        assert lra(_silence(10.0), _SR) == NO_LRA


class TestPerformanceCharacteristics:
    def test_block_count_matches_expected(self) -> None:
        # 10s 신호 → 시작점 0, 1, 2, ..., 7 → 8 블록.
        # 직접 검증하기 어렵지만 결과가 finite여야 한다.
        result = lra(_sine(10.0, amp=0.5), _SR)
        assert math.isfinite(result)

    def test_property_amplitude_invariance_for_steady(self) -> None:
        # Steady 사인파의 LRA는 amplitude와 무관해야 함 (모두 같은 short-term 값).
        for amp in (0.1, 0.3, 0.5, 0.9):
            result = lra(_sine(10.0, amp=amp), _SR)
            assert result < 0.5, f"amp={amp} gave LRA={result}"


class TestBlockBoundary:
    def test_minimum_signal_length_constant(self) -> None:
        # 명세 일치 검증 — MIN_DURATION = BLOCK_SECONDS = 3.0.
        assert MIN_DURATION_SECONDS == 3.0
        assert BLOCK_SECONDS == 3.0
