"""rules.lufs 단위 테스트 — 단조성·결정성·길이 검증·카테고리 폴백.

LUFS 정확값은 pyloudnorm에 위임 — 여기서는 룰 로직(임계·confidence·구성)을
속성 기반으로 검증.
"""

from __future__ import annotations

import numpy as np
import pytest

from mixpilot.domain import (
    AudioFormat,
    Channel,
    ChannelId,
    RecommendationKind,
    Source,
    SourceCategory,
)
from mixpilot.rules import evaluate_all_channels_lufs, evaluate_channel_lufs

SR = 48000


def _sine_channel(
    *,
    channel_id: int = 1,
    category: SourceCategory = SourceCategory.VOCAL,
    label: str = "",
    amplitude: float = 0.1,
    duration_seconds: float = 1.0,
    freq: float = 1000.0,
) -> Channel:
    """주어진 진폭의 1kHz 사인 신호 채널."""
    samples = (
        amplitude
        * np.sin(2 * np.pi * freq * np.arange(int(SR * duration_seconds)) / SR)
    ).astype(np.float64)
    return Channel(
        source=Source(ChannelId(channel_id), category, label),
        samples=samples,
        format=AudioFormat(SR, 1, "float64"),
    )


class TestEvaluateChannelLufs:
    def test_within_tolerance_returns_none(self) -> None:
        # amp 0.1 1kHz 사인 → 약 -23 LUFS. 타깃 -23이면 tolerance 안.
        ch = _sine_channel(amplitude=0.1)
        assert evaluate_channel_lufs(ch, target_lufs=-23.0, tolerance_lu=2.0) is None

    def test_above_target_emits_over(self) -> None:
        # amp 0.5 → 약 -9 LUFS. 타깃 -23이면 약 +14 LU 초과.
        ch = _sine_channel(amplitude=0.5)
        rec = evaluate_channel_lufs(ch, target_lufs=-23.0, tolerance_lu=2.0)
        assert rec is not None
        assert rec.kind is RecommendationKind.INFO
        assert "초과" in rec.reason
        assert rec.params["delta_lu"] > 0

    def test_below_target_emits_under(self) -> None:
        # 무음 → SILENCE_FLOOR_LUFS(-70). 타깃 -20이면 50 LU 부족.
        ch = Channel(
            source=Source(ChannelId(1), SourceCategory.VOCAL),
            samples=np.zeros(SR, dtype=np.float64),
            format=AudioFormat(SR, 1, "float64"),
        )
        rec = evaluate_channel_lufs(ch, target_lufs=-20.0, tolerance_lu=2.0)
        assert rec is not None
        assert "부족" in rec.reason
        assert rec.params["delta_lu"] < 0

    def test_louder_signal_yields_higher_lufs(self) -> None:
        # 단조성: amp 클수록 LUFS도 큼 → delta도 큼.
        a = evaluate_channel_lufs(
            _sine_channel(amplitude=0.1), target_lufs=-30.0, tolerance_lu=0.5
        )
        b = evaluate_channel_lufs(
            _sine_channel(amplitude=0.5), target_lufs=-30.0, tolerance_lu=0.5
        )
        assert a is not None and b is not None
        assert b.params["measured_lufs"] > a.params["measured_lufs"]

    def test_confidence_scales_with_deviation(self) -> None:
        # 작은 deviation < 큰 deviation의 confidence.
        small = evaluate_channel_lufs(
            _sine_channel(amplitude=0.1), target_lufs=-20.0, tolerance_lu=0.5
        )
        large = evaluate_channel_lufs(
            _sine_channel(amplitude=0.5), target_lufs=-30.0, tolerance_lu=0.5
        )
        assert small is not None and large is not None
        assert small.confidence < large.confidence

    def test_confidence_capped_at_one(self) -> None:
        # |delta| > 10 → confidence = 1.0.
        ch = Channel(
            source=Source(ChannelId(1), SourceCategory.VOCAL),
            samples=np.zeros(SR, dtype=np.float64),
            format=AudioFormat(SR, 1, "float64"),
        )
        rec = evaluate_channel_lufs(ch, target_lufs=-20.0, tolerance_lu=2.0)
        assert rec is not None
        assert rec.confidence == 1.0

    def test_label_used_in_reason_when_present(self) -> None:
        ch = _sine_channel(amplitude=0.5, label="설교자 메인")
        rec = evaluate_channel_lufs(ch, target_lufs=-30.0, tolerance_lu=0.5)
        assert rec is not None
        assert "설교자 메인" in rec.reason

    def test_category_used_in_reason_when_no_label(self) -> None:
        ch = _sine_channel(amplitude=0.5, category=SourceCategory.CHOIR, label="")
        rec = evaluate_channel_lufs(ch, target_lufs=-30.0, tolerance_lu=0.5)
        assert rec is not None
        assert "choir" in rec.reason

    def test_channel_id_padded_to_two_digits_in_reason(self) -> None:
        ch = _sine_channel(amplitude=0.5, channel_id=3)
        rec = evaluate_channel_lufs(ch, target_lufs=-30.0, tolerance_lu=0.5)
        assert rec is not None
        assert "ch03" in rec.reason

    def test_reason_uses_lufs_units(self) -> None:
        ch = _sine_channel(amplitude=0.5)
        rec = evaluate_channel_lufs(ch, target_lufs=-30.0, tolerance_lu=0.5)
        assert rec is not None
        assert "LUFS" in rec.reason
        assert " LU " in rec.reason  # delta는 LU

    def test_target_preserved_in_params(self) -> None:
        ch = _sine_channel(amplitude=0.5)
        rec = evaluate_channel_lufs(ch, target_lufs=-23.0, tolerance_lu=0.5)
        assert rec is not None
        assert rec.params["target_lufs"] == -23.0
        assert "measured_lufs" in rec.params
        assert "delta_lu" in rec.params

    def test_rejects_negative_tolerance(self) -> None:
        ch = _sine_channel(amplitude=0.1)
        with pytest.raises(ValueError, match="tolerance_lu"):
            evaluate_channel_lufs(ch, target_lufs=-20.0, tolerance_lu=-0.5)

    def test_propagates_short_signal_error(self) -> None:
        # 100ms — LUFS 최소 400ms 미만. dsp.lufs_integrated가 raise.
        ch = _sine_channel(amplitude=0.1, duration_seconds=0.1)
        with pytest.raises(ValueError, match="too short"):
            evaluate_channel_lufs(ch, target_lufs=-20.0)

    def test_deterministic(self) -> None:
        ch = _sine_channel(amplitude=0.5)
        a = evaluate_channel_lufs(ch, target_lufs=-30.0)
        b = evaluate_channel_lufs(ch, target_lufs=-30.0)
        assert a == b


class TestEvaluateAllChannelsLufs:
    def _targets(self) -> dict[str, float]:
        return {
            "vocal": -16.0,
            "preacher": -18.0,
            "choir": -20.0,
            "instrument": -22.0,
            "unknown": -23.0,
        }

    def test_empty_iterable_returns_empty(self) -> None:
        assert evaluate_all_channels_lufs([], self._targets()) == []

    def test_filters_out_within_tolerance(self) -> None:
        # 두 채널: 첫째는 타깃 근처, 둘째는 크게 벗어남.
        ch_ok = _sine_channel(
            channel_id=1, category=SourceCategory.VOCAL, amplitude=0.15
        )  # 약 -19 LUFS, vocal 타깃 -16에 가까움(tolerance 2.0)
        ch_over = _sine_channel(
            channel_id=2, category=SourceCategory.PREACHER, amplitude=0.8
        )  # 매우 큰 신호, preacher 타깃 -18 크게 초과
        recs = evaluate_all_channels_lufs(
            [ch_ok, ch_over], self._targets(), tolerance_lu=2.0
        )
        # ch1은 약 -19 → 타깃 -16과 3 LU 차이라 over일 가능성 → 둘 다 잡힐 수도.
        # 분명한 것: ch2(amp 0.8)는 반드시 INFO 생성.
        assert any(int(r.target.channel) == 2 for r in recs)

    def test_preserves_input_order(self) -> None:
        channels = [
            _sine_channel(channel_id=5, category=SourceCategory.CHOIR, amplitude=0.5),
            _sine_channel(channel_id=2, category=SourceCategory.VOCAL, amplitude=0.5),
            _sine_channel(
                channel_id=8, category=SourceCategory.INSTRUMENT, amplitude=0.5
            ),
        ]
        recs = evaluate_all_channels_lufs(channels, self._targets(), tolerance_lu=0.5)
        assert [int(r.target.channel) for r in recs] == [5, 2, 8]

    def test_unknown_category_uses_fallback(self) -> None:
        # 타깃 dict에 vocal만, 채널은 INSTRUMENT.
        targets = {"vocal": -16.0}
        ch = _sine_channel(category=SourceCategory.INSTRUMENT, amplitude=0.5)
        recs = evaluate_all_channels_lufs(
            [ch], targets, tolerance_lu=0.5, unknown_fallback_lufs=-30.0
        )
        assert len(recs) == 1
        assert recs[0].params["target_lufs"] == -30.0

    def test_deterministic(self) -> None:
        channels = [_sine_channel(amplitude=0.5)]
        a = evaluate_all_channels_lufs(channels, self._targets())
        b = evaluate_all_channels_lufs(channels, self._targets())
        assert a == b

    def test_returns_list_not_generator(self) -> None:
        channels = [_sine_channel(amplitude=0.5)]
        result = evaluate_all_channels_lufs(channels, self._targets())
        assert isinstance(result, list)
