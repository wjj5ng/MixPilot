"""runtime.feedback_detector 단위 테스트 — 지속성 추적."""

from __future__ import annotations

import numpy as np
import pytest

from mixpilot.runtime import FeedbackDetector

SR = 48000
N = 1024


def _sine(freq: float, amplitude: float = 0.5, n: int = N) -> np.ndarray:
    t = np.arange(n) / SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def _silence(n: int = N) -> np.ndarray:
    return np.zeros(n, dtype=np.float64)


class TestConstruction:
    def test_initial_state_no_active_bins(self) -> None:
        det = FeedbackDetector(SR)
        assert det.active_bins == 0

    def test_default_persistence_is_3(self) -> None:
        det = FeedbackDetector(SR)
        assert det.persistence_frames == 3

    def test_rejects_non_positive_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            FeedbackDetector(0)
        with pytest.raises(ValueError, match="sample_rate"):
            FeedbackDetector(-1)

    def test_rejects_persistence_less_than_one(self) -> None:
        with pytest.raises(ValueError, match="persistence_frames"):
            FeedbackDetector(SR, persistence_frames=0)


class TestPersistence:
    def test_single_frame_does_not_meet_persistence(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=3)
        assert det.update(_sine(1000.0)) == []

    def test_two_frames_does_not_meet_persistence_3(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=3)
        det.update(_sine(1000.0))
        assert det.update(_sine(1000.0)) == []

    def test_three_consecutive_frames_triggers(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=3, pnr_threshold_db=10.0)
        det.update(_sine(1000.0))
        det.update(_sine(1000.0))
        peaks = det.update(_sine(1000.0))
        assert len(peaks) >= 1
        # 가장 강한 것이 1000 Hz 근처.
        strongest = max(peaks, key=lambda p: p.pnr_db)
        assert abs(strongest.frequency_hz - 1000.0) < SR / N

    def test_sustained_continues_to_emit(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=3, pnr_threshold_db=10.0)
        for _ in range(3):
            det.update(_sine(1000.0))
        # 3번째에 sustained 됐고, 이후 프레임마다 계속 emit.
        peaks4 = det.update(_sine(1000.0))
        peaks5 = det.update(_sine(1000.0))
        assert len(peaks4) >= 1
        assert len(peaks5) >= 1

    def test_streak_resets_when_bin_disappears(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=3, pnr_threshold_db=10.0)
        det.update(_sine(1000.0))
        det.update(_sine(1000.0))
        # 무음 한 프레임 — streak 리셋.
        assert det.update(_silence()) == []
        # 다시 사인 하나만으로는 부족.
        assert det.update(_sine(1000.0)) == []

    def test_persistence_one_emits_immediately(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=1, pnr_threshold_db=10.0)
        peaks = det.update(_sine(1000.0))
        assert len(peaks) >= 1


class TestMultipleBins:
    def test_independent_streaks_per_bin(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=2, pnr_threshold_db=10.0)
        # Frame 1: 1000 Hz only.
        det.update(_sine(1000.0))
        # Frame 2: 1000 + 3000. 1000은 sustained, 3000은 새 streak.
        peaks = det.update(_sine(1000.0) + _sine(3000.0))
        freqs = [p.frequency_hz for p in peaks]
        # 1000 Hz는 2 frames 지속 → sustained.
        assert any(abs(f - 1000.0) < SR / N for f in freqs)
        # 3000 Hz는 1 frame만 → not sustained.
        assert not any(abs(f - 3000.0) < SR / N for f in freqs)

    def test_output_sorted_by_bin_index(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=1, pnr_threshold_db=10.0)
        peaks = det.update(_sine(500.0) + _sine(3000.0) + _sine(5000.0))
        bin_indices = [p.bin_index for p in peaks]
        assert bin_indices == sorted(bin_indices)


class TestSilenceAndNoise:
    def test_silence_streams_no_peaks(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=1)
        for _ in range(5):
            assert det.update(_silence()) == []

    def test_silence_keeps_active_bins_at_zero(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=1)
        det.update(_silence())
        det.update(_silence())
        assert det.active_bins == 0


class TestReset:
    def test_reset_clears_streaks(self) -> None:
        det = FeedbackDetector(SR, persistence_frames=3, pnr_threshold_db=10.0)
        det.update(_sine(1000.0))
        det.update(_sine(1000.0))
        assert det.active_bins > 0
        det.reset()
        assert det.active_bins == 0
        # reset 후엔 다시 처음부터 카운트.
        assert det.update(_sine(1000.0)) == []


class TestDeterminism:
    def test_same_input_sequence_same_output_sequence(self) -> None:
        a = FeedbackDetector(SR, persistence_frames=2, pnr_threshold_db=10.0)
        b = FeedbackDetector(SR, persistence_frames=2, pnr_threshold_db=10.0)
        sigs = [_sine(1000.0), _sine(1000.0), _silence(), _sine(2500.0)]
        for sig in sigs:
            assert a.update(sig) == b.update(sig)
