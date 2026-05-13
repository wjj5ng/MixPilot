"""runtime.action_history 단위 테스트 — 윈도우·가지치기·결정성."""

from __future__ import annotations

import pytest

from mixpilot.runtime import ActionHistory, HistoryEntry


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


class TestConstruction:
    def test_initial_recent_is_empty(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        assert h.recent() == []

    def test_window_seconds_property(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=30.0, clock=clock)
        assert h.window_seconds == 30.0

    def test_rejects_non_positive_window(self, clock: FakeClock) -> None:
        with pytest.raises(ValueError, match="window_seconds"):
            ActionHistory(window_seconds=0, clock=clock)
        with pytest.raises(ValueError, match="window_seconds"):
            ActionHistory(window_seconds=-1, clock=clock)


class TestAdd:
    def test_returns_entry_with_clock_timestamp(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        entry = h.add(channel_id=1, kind="gain_adjust")
        assert isinstance(entry, HistoryEntry)
        assert entry.timestamp == clock.t

    def test_stores_osc_messages_as_tuple_of_tuples(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        entry = h.add(
            channel_id=5,
            kind="mute",
            osc_messages=[("/ch/05/mix/on", 0)],
        )
        assert entry.osc_messages == (("/ch/05/mix/on", 0.0),)

    def test_appears_in_recent(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        h.add(channel_id=1, kind="mute")
        recent = h.recent()
        assert len(recent) == 1
        assert recent[0].channel_id == 1


class TestWindowPruning:
    def test_entries_within_window_kept(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        h.add(channel_id=1, kind="mute")
        clock.advance(30.0)
        assert len(h.recent()) == 1

    def test_entries_beyond_window_pruned(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        h.add(channel_id=1, kind="mute")
        clock.advance(61.0)
        assert h.recent() == []

    def test_at_window_boundary_pruned(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        h.add(channel_id=1, kind="mute")
        clock.advance(60.0)  # 정확히 만료.
        assert h.recent() == []

    def test_mixed_old_and_new(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        h.add(channel_id=1, kind="mute")
        clock.advance(40.0)
        h.add(channel_id=2, kind="gain_adjust")
        clock.advance(30.0)  # 첫째: 70s, 둘째: 30s.
        recent = h.recent()
        assert [e.channel_id for e in recent] == [2]

    def test_chronological_order_preserved(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        for ch in (5, 2, 8, 1):
            h.add(channel_id=ch, kind="mute")
            clock.advance(1.0)
        recent = h.recent()
        assert [e.channel_id for e in recent] == [5, 2, 8, 1]


class TestClear:
    def test_clear_empties_history(self, clock: FakeClock) -> None:
        h = ActionHistory(window_seconds=60.0, clock=clock)
        h.add(channel_id=1, kind="mute")
        h.add(channel_id=2, kind="unmute")
        h.clear()
        assert h.recent() == []


class TestDeterminism:
    def test_same_calls_same_state(self) -> None:
        a_clock = FakeClock()
        b_clock = FakeClock()
        a = ActionHistory(window_seconds=60.0, clock=a_clock)
        b = ActionHistory(window_seconds=60.0, clock=b_clock)
        steps = [
            ("advance", 5.0),
            ("add", 1, "mute"),
            ("advance", 10.0),
            ("add", 2, "unmute"),
            ("advance", 50.0),  # 첫째 만료.
        ]
        for step in steps:
            if step[0] == "advance":
                a_clock.advance(step[1])
                b_clock.advance(step[1])
            else:
                a.add(channel_id=step[1], kind=step[2])
                b.add(channel_id=step[1], kind=step[2])
        assert a.recent() == b.recent()
