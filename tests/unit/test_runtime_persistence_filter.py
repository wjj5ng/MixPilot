"""runtime.persistence_filter 단위 테스트."""

from __future__ import annotations

import pytest

from mixpilot.runtime.persistence_filter import PersistenceFilter


class TestPersistenceFrame1:
    """persistence_frames=1 → 필터 부재와 동일."""

    def test_immediate_pass(self) -> None:
        f = PersistenceFilter()
        assert f.observe("peak", [1, 3, 5], 1) == {1, 3, 5}

    def test_empty_input_returns_empty(self) -> None:
        f = PersistenceFilter()
        assert f.observe("peak", [], 1) == set()


class TestPersistenceFrame3:
    """3 연속 frame 후에만 통과."""

    def test_blocks_first_two_frames(self) -> None:
        f = PersistenceFilter()
        assert f.observe("peak", [1], 3) == set()
        assert f.observe("peak", [1], 3) == set()

    def test_passes_on_third_frame(self) -> None:
        f = PersistenceFilter()
        f.observe("peak", [1], 3)
        f.observe("peak", [1], 3)
        assert f.observe("peak", [1], 3) == {1}

    def test_continues_passing_while_sustained(self) -> None:
        f = PersistenceFilter()
        for _ in range(3):
            f.observe("peak", [1], 3)
        assert f.observe("peak", [1], 3) == {1}
        assert f.observe("peak", [1], 3) == {1}


class TestStreakReset:
    """미발화 frame은 streak 리셋."""

    def test_missed_frame_resets_streak(self) -> None:
        f = PersistenceFilter()
        f.observe("peak", [1], 3)
        f.observe("peak", [1], 3)  # streak=2
        f.observe("peak", [], 3)  # streak=0
        assert f.observe("peak", [1], 3) == set()  # 다시 1부터

    def test_partial_channels_reset_only_missing(self) -> None:
        f = PersistenceFilter()
        f.observe("peak", [1, 2], 3)
        f.observe("peak", [1, 2], 3)
        f.observe("peak", [1, 2], 3)  # 둘 다 통과
        # ch1만 살아있음 — ch2 reset.
        result = f.observe("peak", [1], 3)
        assert result == {1}
        assert f.streak("peak", 2) == 0


class TestTagIsolation:
    """룰 태그별 streak 격리."""

    def test_peak_streak_independent_from_dynamic_range(self) -> None:
        f = PersistenceFilter()
        f.observe("peak", [1], 3)
        f.observe("peak", [1], 3)
        f.observe("peak", [1], 3)
        # peak ch1은 통과, dynamic_range ch1은 0부터.
        assert f.observe("peak", [1], 3) == {1}
        assert f.observe("dynamic_range", [1], 3) == set()
        assert f.streak("dynamic_range", 1) == 1


class TestValidation:
    def test_persistence_frames_zero_raises(self) -> None:
        f = PersistenceFilter()
        with pytest.raises(ValueError, match="persistence_frames must be >= 1"):
            f.observe("peak", [1], 0)


class TestReset:
    def test_reset_specific_tag(self) -> None:
        f = PersistenceFilter()
        f.observe("peak", [1], 3)
        f.observe("dynamic_range", [1], 3)
        f.reset("peak")
        assert f.streak("peak", 1) == 0
        assert f.streak("dynamic_range", 1) == 1

    def test_reset_all(self) -> None:
        f = PersistenceFilter()
        f.observe("peak", [1], 3)
        f.observe("dynamic_range", [1], 3)
        f.reset()
        assert f.streak("peak", 1) == 0
        assert f.streak("dynamic_range", 1) == 0


class TestStreakAccessor:
    def test_streak_returns_zero_for_unknown(self) -> None:
        f = PersistenceFilter()
        assert f.streak("peak", 999) == 0

    def test_streak_increments(self) -> None:
        f = PersistenceFilter()
        f.observe("peak", [1], 3)
        assert f.streak("peak", 1) == 1
        f.observe("peak", [1], 3)
        assert f.streak("peak", 1) == 2
