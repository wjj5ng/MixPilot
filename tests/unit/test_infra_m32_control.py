"""infra.m32_control 단위 테스트 — 운영 모드 분기 + Recommendation → OSC 변환."""

from __future__ import annotations

import asyncio

import pytest

from mixpilot.config import M32Config, OperatingMode
from mixpilot.domain import (
    ChannelId,
    Recommendation,
    RecommendationKind,
    Source,
    SourceCategory,
)
from mixpilot.infra.m32_control import M32OscController


class FakeOscClient:
    """sent 메시지를 기록하는 테스트용 OSC 클라이언트."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, float | int]] = []

    def send_message(self, address: str, value: float | int) -> None:
        self.sent.append((address, value))


def _rec(
    kind: RecommendationKind,
    *,
    channel: int = 1,
    category: SourceCategory = SourceCategory.VOCAL,
    confidence: float = 0.9,
    params: dict[str, float] | None = None,
    reason: str = "test",
) -> Recommendation:
    return Recommendation(
        target=Source(ChannelId(channel), category),
        kind=kind,
        params=params or {},
        confidence=confidence,
        reason=reason,
    )


class TestShouldApply:
    def test_dry_run_never_applies(self) -> None:
        cfg = M32Config(operating_mode=OperatingMode.DRY_RUN)
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl._should_apply(_rec(RecommendationKind.MUTE, confidence=1.0)) is False

    def test_assist_applies_only_at_or_above_threshold(self) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.ASSIST,
            auto_apply_confidence_threshold=0.8,
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert (
            ctl._should_apply(_rec(RecommendationKind.MUTE, confidence=0.79)) is False
        )
        assert ctl._should_apply(_rec(RecommendationKind.MUTE, confidence=0.80)) is True
        assert ctl._should_apply(_rec(RecommendationKind.MUTE, confidence=0.95)) is True

    def test_auto_always_applies(self) -> None:
        cfg = M32Config(operating_mode=OperatingMode.AUTO)
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl._should_apply(_rec(RecommendationKind.MUTE, confidence=0.0)) is True


class TestTranslate:
    def _ctl(self) -> M32OscController:
        return M32OscController(
            M32Config(operating_mode=OperatingMode.AUTO), osc_client=FakeOscClient()
        )

    def test_mute(self) -> None:
        msgs = list(self._ctl()._translate(_rec(RecommendationKind.MUTE, channel=3)))
        assert msgs == [("/ch/03/mix/on", 0)]

    def test_unmute(self) -> None:
        msgs = list(self._ctl()._translate(_rec(RecommendationKind.UNMUTE, channel=7)))
        assert msgs == [("/ch/07/mix/on", 1)]

    def test_gain_adjust_with_fader(self) -> None:
        rec = _rec(RecommendationKind.GAIN_ADJUST, channel=2, params={"fader": 0.6})
        msgs = list(self._ctl()._translate(rec))
        assert msgs == [("/ch/02/mix/fader", 0.6)]

    def test_gain_adjust_clamps_fader_to_unit_interval(self) -> None:
        ctl = self._ctl()
        msgs_hi = list(
            ctl._translate(
                _rec(RecommendationKind.GAIN_ADJUST, channel=4, params={"fader": 1.5})
            )
        )
        msgs_lo = list(
            ctl._translate(
                _rec(RecommendationKind.GAIN_ADJUST, channel=4, params={"fader": -0.3})
            )
        )
        assert msgs_hi == [("/ch/04/mix/fader", 1.0)]
        assert msgs_lo == [("/ch/04/mix/fader", 0.0)]

    def test_gain_adjust_without_fader_param_emits_nothing(self) -> None:
        # delta_db only는 아직 미지원 — 메시지 없음(경고 로깅).
        rec = _rec(RecommendationKind.GAIN_ADJUST, params={"delta_db": -2.0})
        assert list(self._ctl()._translate(rec)) == []

    def test_info_emits_nothing(self) -> None:
        assert list(self._ctl()._translate(_rec(RecommendationKind.INFO))) == []

    def test_unimplemented_kinds_emit_nothing(self) -> None:
        ctl = self._ctl()
        for kind in (
            RecommendationKind.FEEDBACK_ALERT,
            RecommendationKind.EQ_ADJUST,
        ):
            assert list(ctl._translate(_rec(kind))) == []

    @pytest.mark.parametrize(
        ("channel", "expected_prefix"),
        [(1, "/ch/01"), (10, "/ch/10"), (32, "/ch/32")],
    )
    def test_channel_padded_to_two_digits(
        self, channel: int, expected_prefix: str
    ) -> None:
        msgs = list(
            self._ctl()._translate(_rec(RecommendationKind.MUTE, channel=channel))
        )
        assert msgs[0][0].startswith(expected_prefix)


class TestApply:
    def test_dry_run_sends_nothing(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(operating_mode=OperatingMode.DRY_RUN), osc_client=client
        )
        asyncio.run(ctl.apply(_rec(RecommendationKind.MUTE, confidence=1.0)))
        assert client.sent == []

    def test_auto_sends_to_client(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(operating_mode=OperatingMode.AUTO), osc_client=client
        )
        asyncio.run(ctl.apply(_rec(RecommendationKind.MUTE, channel=5)))
        assert client.sent == [("/ch/05/mix/on", 0)]

    def test_assist_below_threshold_skips(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.ASSIST,
                auto_apply_confidence_threshold=0.9,
            ),
            osc_client=client,
        )
        asyncio.run(ctl.apply(_rec(RecommendationKind.MUTE, confidence=0.5)))
        assert client.sent == []

    def test_assist_above_threshold_sends(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.ASSIST,
                auto_apply_confidence_threshold=0.9,
            ),
            osc_client=client,
        )
        asyncio.run(
            ctl.apply(_rec(RecommendationKind.MUTE, confidence=0.95, channel=12))
        )
        assert client.sent == [("/ch/12/mix/on", 0)]
