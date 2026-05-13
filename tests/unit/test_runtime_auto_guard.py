"""runtime.auto_guard 단위 테스트 — 부트스트랩·레이트·세션 한도.

`FakeClock`을 주입해 결정적으로 검증.
"""

from __future__ import annotations

import pytest

from mixpilot.runtime import AutoGuard, GuardDecision


class FakeClock:
    """`AutoGuard`의 시계 의존성 주입용."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def _guard(
    clock: FakeClock,
    *,
    bootstrap: float = 0.0,
    per_channel: float = 5.0,
    global_window: float = 1.0,
    global_max: int = 3,
    session_max: int = 50,
) -> AutoGuard:
    return AutoGuard(
        bootstrap_silence_seconds=bootstrap,
        per_channel_window_seconds=per_channel,
        global_window_seconds=global_window,
        global_max_in_window=global_max,
        session_max_actions=session_max,
        clock=clock,
    )


class TestConstruction:
    def test_initial_state(self, clock: FakeClock) -> None:
        g = _guard(clock)
        assert g.session_action_count == 0
        assert g.session_max_actions == 50

    def test_rejects_invalid_params(self, clock: FakeClock) -> None:
        with pytest.raises(ValueError):
            AutoGuard(global_window_seconds=0, clock=clock)
        with pytest.raises(ValueError):
            AutoGuard(global_max_in_window=0, clock=clock)
        with pytest.raises(ValueError):
            AutoGuard(session_max_actions=0, clock=clock)
        with pytest.raises(ValueError):
            AutoGuard(bootstrap_silence_seconds=-1, clock=clock)


class TestBootstrapSilence:
    def test_blocks_during_silence(self, clock: FakeClock) -> None:
        g = _guard(clock, bootstrap=10.0)
        clock.advance(5.0)  # 절반만 지남
        decision = g.try_register(channel_id=1)
        assert decision.allowed is False
        assert "bootstrap" in decision.reason

    def test_allows_after_silence_expires(self, clock: FakeClock) -> None:
        g = _guard(clock, bootstrap=10.0)
        clock.advance(10.0)  # 정확히 만료
        assert g.try_register(channel_id=1).allowed is True

    def test_no_silence_when_zero(self, clock: FakeClock) -> None:
        g = _guard(clock, bootstrap=0.0)
        assert g.try_register(channel_id=1).allowed is True

    def test_blocked_actions_dont_count_toward_session(self, clock: FakeClock) -> None:
        g = _guard(clock, bootstrap=10.0)
        g.try_register(channel_id=1)
        g.try_register(channel_id=2)
        # 부트스트랩 중에 차단된 호출은 세션 카운터에 들어가지 않음.
        assert g.session_action_count == 0


class TestPerChannelRateLimit:
    def test_blocks_within_window(self, clock: FakeClock) -> None:
        g = _guard(clock, per_channel=5.0)
        assert g.try_register(channel_id=1).allowed is True
        clock.advance(2.0)
        decision = g.try_register(channel_id=1)
        assert decision.allowed is False
        assert "channel rate" in decision.reason

    def test_allows_after_window(self, clock: FakeClock) -> None:
        g = _guard(clock, per_channel=5.0)
        g.try_register(channel_id=1)
        clock.advance(5.0)
        assert g.try_register(channel_id=1).allowed is True

    def test_different_channels_independent(self, clock: FakeClock) -> None:
        g = _guard(clock, per_channel=5.0, global_max=100)
        assert g.try_register(channel_id=1).allowed is True
        # 같은 시각 다른 채널은 영향 없음.
        assert g.try_register(channel_id=2).allowed is True
        assert g.try_register(channel_id=3).allowed is True


class TestGlobalRateLimit:
    def test_allows_up_to_max(self, clock: FakeClock) -> None:
        g = _guard(clock, global_window=1.0, global_max=3, per_channel=0.0)
        assert g.try_register(channel_id=1).allowed is True
        assert g.try_register(channel_id=2).allowed is True
        assert g.try_register(channel_id=3).allowed is True

    def test_blocks_at_max_within_window(self, clock: FakeClock) -> None:
        g = _guard(clock, global_window=1.0, global_max=3, per_channel=0.0)
        for ch in (1, 2, 3):
            g.try_register(channel_id=ch)
        clock.advance(0.5)
        decision = g.try_register(channel_id=4)
        assert decision.allowed is False
        assert "global rate" in decision.reason

    def test_recovers_after_window_slides(self, clock: FakeClock) -> None:
        g = _guard(clock, global_window=1.0, global_max=3, per_channel=0.0)
        for ch in (1, 2, 3):
            g.try_register(channel_id=ch)
        clock.advance(1.0)  # 모든 기존 액션이 만료
        assert g.try_register(channel_id=4).allowed is True


class TestSessionLimit:
    def test_allows_up_to_max(self, clock: FakeClock) -> None:
        g = _guard(
            clock,
            session_max=3,
            per_channel=0.0,
            global_window=0.001,
            global_max=100,
        )
        for ch in (1, 2, 3):
            assert g.try_register(channel_id=ch).allowed is True
        assert g.session_action_count == 3

    def test_blocks_above_max(self, clock: FakeClock) -> None:
        g = _guard(
            clock,
            session_max=3,
            per_channel=0.0,
            global_window=0.001,
            global_max=100,
        )
        for ch in (1, 2, 3):
            g.try_register(channel_id=ch)
        decision = g.try_register(channel_id=4)
        assert decision.allowed is False
        assert "session" in decision.reason

    def test_blocked_actions_do_not_increment_counter(self, clock: FakeClock) -> None:
        # 채널 rate limit으로 막혀도 세션 카운터는 그대로.
        g = _guard(clock, per_channel=5.0, session_max=10)
        g.try_register(channel_id=1)
        assert g.session_action_count == 1
        # 같은 채널 즉시 재시도 — rate limit으로 차단.
        g.try_register(channel_id=1)
        assert g.session_action_count == 1


class TestReset:
    def test_reset_clears_session_counter(self, clock: FakeClock) -> None:
        g = _guard(clock, per_channel=0.0)
        for ch in (1, 2, 3):
            g.try_register(channel_id=ch)
        g.reset()
        assert g.session_action_count == 0

    def test_reset_clears_channel_rate_limit(self, clock: FakeClock) -> None:
        g = _guard(clock, per_channel=5.0)
        g.try_register(channel_id=1)
        # 평소면 차단되지만 reset 후엔 허용.
        g.reset()
        # reset은 시작 시각도 재설정 — bootstrap=0이므로 즉시 허용.
        assert g.try_register(channel_id=1).allowed is True

    def test_reset_reinstates_bootstrap_silence(self, clock: FakeClock) -> None:
        g = _guard(clock, bootstrap=5.0)
        clock.advance(10.0)  # 1차 bootstrap 만료
        assert g.try_register(channel_id=1).allowed is True
        # 새 service 시작 — reset.
        g.reset()
        # 부트스트랩 재시작.
        assert g.try_register(channel_id=1).allowed is False
        clock.advance(5.0)
        assert g.try_register(channel_id=1).allowed is True


class TestGuardDecision:
    def test_allowed_default_no_reason(self) -> None:
        d = GuardDecision(True)
        assert d.allowed is True
        assert d.reason == ""

    def test_blocked_has_reason(self) -> None:
        d = GuardDecision(False, "test")
        assert d.allowed is False
        assert d.reason == "test"

    def test_frozen(self) -> None:
        import dataclasses

        d = GuardDecision(True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.allowed = False  # type: ignore[misc]


class TestDeterminism:
    def test_same_clock_sequence_same_outcome(self) -> None:
        # 두 가드에 동일 시간 + 동일 호출 시퀀스를 주면 같은 결과.
        c1 = FakeClock()
        c2 = FakeClock()
        g1 = _guard(c1, per_channel=2.0)
        g2 = _guard(c2, per_channel=2.0)

        steps = [
            ("advance", 1.0),
            ("call", 1),
            ("advance", 0.5),
            ("call", 1),  # rate limited
            ("advance", 1.5),
            ("call", 1),  # OK
        ]
        for op, val in steps:
            if op == "advance":
                c1.advance(val)
                c2.advance(val)
            else:
                assert g1.try_register(channel_id=val) == g2.try_register(
                    channel_id=val
                )
