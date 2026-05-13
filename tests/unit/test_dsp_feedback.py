"""dsp.feedback 단위 테스트 — PNR 기반 peak 검출."""

from __future__ import annotations

import numpy as np
import pytest

from mixpilot.dsp import (
    DEFAULT_PNR_THRESHOLD_DB,
    FeedbackPeak,
    detect_peak_bins,
)

SR = 48000
N = 1024  # FFT 길이 — bin resolution ≈ 46.875 Hz @ 48 kHz


def _sine(freq: float, amplitude: float = 0.5, n: int = N) -> np.ndarray:
    t = np.arange(n) / SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def _white_noise(n: int = N, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n).astype(np.float64) * 0.1


class TestPureSineDetection:
    def test_single_tone_detected(self) -> None:
        sig = _sine(1000.0)
        peaks = detect_peak_bins(sig, SR, pnr_threshold_db=10.0)
        assert len(peaks) >= 1
        # 가장 강한 peak가 1000 Hz 근처 (bin resolution 만큼 오차).
        strongest = max(peaks, key=lambda p: p.pnr_db)
        assert abs(strongest.frequency_hz - 1000.0) < SR / N

    def test_two_separated_tones_both_detected(self) -> None:
        # 멀리 떨어진 두 톤은 둘 다 잡혀야 함.
        sig = _sine(500.0) + _sine(3000.0, amplitude=0.5)
        peaks = detect_peak_bins(sig, SR, pnr_threshold_db=10.0)
        freqs = [p.frequency_hz for p in peaks]
        assert any(abs(f - 500.0) < SR / N for f in freqs)
        assert any(abs(f - 3000.0) < SR / N for f in freqs)

    def test_peak_has_positive_pnr_above_threshold(self) -> None:
        sig = _sine(1500.0)
        peaks = detect_peak_bins(sig, SR, pnr_threshold_db=10.0)
        for p in peaks:
            assert p.pnr_db > 10.0


class TestSilenceAndNoise:
    def test_silence_returns_empty(self) -> None:
        sig = np.zeros(N, dtype=np.float64)
        assert detect_peak_bins(sig, SR) == []

    def test_pure_white_noise_yields_few_or_no_peaks(self) -> None:
        # 백색 잡음은 PNR이 낮아 임계 15 dB에서는 거의 안 잡힘.
        peaks = detect_peak_bins(_white_noise(), SR, pnr_threshold_db=15.0)
        # 매우 관대한 상한 — 노이즈에 운 좋은 high-PNR bin은 있을 수 있음.
        assert len(peaks) < 10

    def test_dc_signal_yields_no_peaks(self) -> None:
        # DC는 0 Hz에만 에너지. min_frequency_hz=100 필터로 잘림.
        sig = np.full(N, 0.5, dtype=np.float64)
        assert detect_peak_bins(sig, SR, min_frequency_hz=100.0) == []


class TestFrequencyRangeFilter:
    def test_tone_below_min_frequency_not_detected(self) -> None:
        sig = _sine(80.0)
        peaks = detect_peak_bins(sig, SR, min_frequency_hz=200.0)
        for p in peaks:
            assert p.frequency_hz >= 200.0

    def test_tone_above_max_frequency_not_detected(self) -> None:
        sig = _sine(8000.0)
        peaks = detect_peak_bins(
            sig, SR, min_frequency_hz=100.0, max_frequency_hz=5000.0
        )
        for p in peaks:
            assert p.frequency_hz <= 5000.0

    def test_range_includes_target_tone(self) -> None:
        sig = _sine(2000.0)
        peaks = detect_peak_bins(
            sig,
            SR,
            min_frequency_hz=1500.0,
            max_frequency_hz=2500.0,
            pnr_threshold_db=10.0,
        )
        assert any(abs(p.frequency_hz - 2000.0) < SR / N for p in peaks)


class TestThresholdSensitivity:
    def test_higher_threshold_yields_fewer_or_equal_peaks(self) -> None:
        sig = _sine(1000.0) + _white_noise() * 0.3
        low = detect_peak_bins(sig, SR, pnr_threshold_db=5.0)
        high = detect_peak_bins(sig, SR, pnr_threshold_db=20.0)
        assert len(high) <= len(low)

    def test_extremely_high_threshold_yields_empty(self) -> None:
        sig = _sine(1000.0)
        # 80 dB는 일반 신호 도달 불가능 (FFT 누설로 인한 천장).
        assert detect_peak_bins(sig, SR, pnr_threshold_db=80.0) == []


class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        sig = _sine(1500.0) + _white_noise()
        a = detect_peak_bins(sig, SR)
        b = detect_peak_bins(sig, SR)
        assert a == b

    def test_output_sorted_by_bin_index(self) -> None:
        sig = _sine(500.0) + _sine(3000.0) + _sine(5000.0)
        peaks = detect_peak_bins(sig, SR, pnr_threshold_db=10.0)
        bin_indices = [p.bin_index for p in peaks]
        assert bin_indices == sorted(bin_indices)


class TestInputValidation:
    def test_rejects_2d_input(self) -> None:
        with pytest.raises(ValueError, match="1D"):
            detect_peak_bins(np.zeros((N, 2)), SR)

    def test_rejects_zero_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            detect_peak_bins(_sine(1000.0), 0)

    def test_rejects_negative_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            detect_peak_bins(_sine(1000.0), -1)

    def test_rejects_negative_threshold(self) -> None:
        with pytest.raises(ValueError, match="pnr_threshold_db"):
            detect_peak_bins(_sine(1000.0), SR, pnr_threshold_db=-1.0)

    def test_very_short_signal_returns_empty(self) -> None:
        assert detect_peak_bins(np.array([0.1, 0.2]), SR) == []


class TestDtypeHandling:
    def test_float32_input_accepted(self) -> None:
        sig = _sine(1000.0).astype(np.float32)
        peaks = detect_peak_bins(sig, SR, pnr_threshold_db=10.0)
        assert any(abs(p.frequency_hz - 1000.0) < SR / N for p in peaks)


class TestFeedbackPeak:
    def test_frozen_dataclass(self) -> None:
        peak = FeedbackPeak(
            frequency_hz=1000.0, bin_index=21, magnitude_dbfs=-3.0, pnr_db=20.0
        )
        import dataclasses

        with pytest.raises(dataclasses.FrozenInstanceError):
            peak.frequency_hz = 2000.0  # type: ignore[misc]

    def test_default_constants_reasonable(self) -> None:
        # 디폴트 PNR 임계는 실제 운영에서 쓸 만한 값(12~20 dB)이어야 한다.
        assert 10.0 < DEFAULT_PNR_THRESHOLD_DB < 25.0
