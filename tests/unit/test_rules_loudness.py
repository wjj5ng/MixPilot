"""rules.loudness 단위 테스트 — 결정성·경계 조건·카테고리 폴백 검증.

DC 신호로 RMS를 정확히 통제 — DC=v면 RMS=|v|, 따라서 dBFS=20·log10|v|.
"""

from __future__ import annotations

import math

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
from mixpilot.rules import evaluate_all_channels, evaluate_channel_loudness


def _channel(
    *,
    channel_id: int = 1,
    category: SourceCategory = SourceCategory.VOCAL,
    label: str = "",
    dbfs: float = -20.0,
    num_samples: int = 1024,
) -> Channel:
    """`dbfs` 만큼의 RMS를 가지는 DC 신호 채널 생성."""
    amplitude = 10.0 ** (dbfs / 20.0)
    samples = np.full(num_samples, amplitude, dtype=np.float32)
    return Channel(
        source=Source(ChannelId(channel_id), category, label),
        samples=samples,
        format=AudioFormat(48000, 1, "float32"),
    )


class TestEvaluateChannelLoudness:
    def test_within_tolerance_returns_none(self) -> None:
        ch = _channel(dbfs=-20.0)
        assert (
            evaluate_channel_loudness(ch, target_dbfs=-20.0, tolerance_db=2.0) is None
        )

    def test_at_exact_tolerance_returns_none(self) -> None:
        ch = _channel(dbfs=-18.0)
        # |delta| == tolerance → None (경계는 허용 측).
        assert (
            evaluate_channel_loudness(ch, target_dbfs=-20.0, tolerance_db=2.0) is None
        )

    def test_above_target_emits_over(self) -> None:
        ch = _channel(dbfs=-15.0)  # 5 dB 초과
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0, tolerance_db=2.0)
        assert rec is not None
        assert rec.kind is RecommendationKind.INFO
        assert "초과" in rec.reason
        assert rec.params["delta_db"] == pytest.approx(5.0, abs=1e-3)

    def test_below_target_emits_under(self) -> None:
        ch = _channel(dbfs=-25.0)  # 5 dB 부족
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0, tolerance_db=2.0)
        assert rec is not None
        assert rec.kind is RecommendationKind.INFO
        assert "부족" in rec.reason
        assert rec.params["delta_db"] == pytest.approx(-5.0, abs=1e-3)

    def test_confidence_scales_with_deviation(self) -> None:
        ch_small = _channel(dbfs=-17.0)  # 3 dB 초과 → confidence 0.3
        ch_large = _channel(dbfs=-12.0)  # 8 dB 초과 → confidence 0.8
        rec_small = evaluate_channel_loudness(ch_small, target_dbfs=-20.0)
        rec_large = evaluate_channel_loudness(ch_large, target_dbfs=-20.0)
        assert rec_small is not None
        assert rec_large is not None
        assert rec_small.confidence == pytest.approx(0.3, abs=1e-3)
        assert rec_large.confidence == pytest.approx(0.8, abs=1e-3)

    def test_confidence_capped_at_one(self) -> None:
        ch = _channel(dbfs=0.0)  # 20 dB 초과
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        assert rec is not None
        assert rec.confidence == 1.0

    def test_silent_channel_emits_under(self) -> None:
        # 무음 신호: RMS=0 → to_dbfs는 SILENCE_FLOOR_DBFS(-120) 반환.
        ch = Channel(
            source=Source(ChannelId(1), SourceCategory.VOCAL),
            samples=np.zeros(1024, dtype=np.float32),
            format=AudioFormat(48000, 1, "float32"),
        )
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        assert rec is not None
        assert "부족" in rec.reason
        assert rec.confidence == 1.0  # |delta| >> 10 → clamp 1.0

    def test_label_used_in_reason_when_present(self) -> None:
        ch = _channel(label="설교자 메인", dbfs=-15.0)
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        assert rec is not None
        assert "설교자 메인" in rec.reason

    def test_category_used_in_reason_when_no_label(self) -> None:
        ch = _channel(category=SourceCategory.CHOIR, label="", dbfs=-15.0)
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        assert rec is not None
        assert "choir" in rec.reason

    def test_channel_id_padded_to_two_digits_in_reason(self) -> None:
        ch = _channel(channel_id=3, dbfs=-15.0)
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        assert rec is not None
        assert "ch03" in rec.reason

    def test_target_preserved_in_params(self) -> None:
        ch = _channel(dbfs=-15.0)
        rec = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        assert rec is not None
        assert rec.params["target_dbfs"] == -20.0
        assert rec.params["measured_dbfs"] == pytest.approx(-15.0, abs=1e-3)

    def test_rejects_negative_tolerance(self) -> None:
        ch = _channel(dbfs=-20.0)
        with pytest.raises(ValueError, match="tolerance_db"):
            evaluate_channel_loudness(ch, target_dbfs=-20.0, tolerance_db=-0.5)

    def test_deterministic(self) -> None:
        ch = _channel(dbfs=-15.0)
        a = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        b = evaluate_channel_loudness(ch, target_dbfs=-20.0)
        assert a == b


class TestEvaluateAllChannels:
    def _targets(self) -> dict[str, float]:
        return {
            "vocal": -18.0,
            "preacher": -20.0,
            "choir": -22.0,
            "instrument": -24.0,
            "unknown": -26.0,
        }

    def test_empty_iterable_returns_empty(self) -> None:
        assert evaluate_all_channels([], self._targets()) == []

    def test_all_within_tolerance_returns_empty(self) -> None:
        channels = [
            _channel(channel_id=1, category=SourceCategory.VOCAL, dbfs=-18.0),
            _channel(channel_id=2, category=SourceCategory.PREACHER, dbfs=-20.0),
        ]
        assert evaluate_all_channels(channels, self._targets()) == []

    def test_filters_out_within_tolerance(self) -> None:
        channels = [
            _channel(channel_id=1, category=SourceCategory.VOCAL, dbfs=-18.0),  # OK
            _channel(
                channel_id=2, category=SourceCategory.PREACHER, dbfs=-10.0
            ),  # 10 dB 초과
            _channel(channel_id=3, category=SourceCategory.CHOIR, dbfs=-22.0),  # OK
        ]
        recs = evaluate_all_channels(channels, self._targets())
        assert len(recs) == 1
        assert int(recs[0].target.channel) == 2

    def test_preserves_input_order(self) -> None:
        channels = [
            _channel(channel_id=5, category=SourceCategory.CHOIR, dbfs=-10.0),
            _channel(channel_id=2, category=SourceCategory.VOCAL, dbfs=-30.0),
            _channel(channel_id=8, category=SourceCategory.INSTRUMENT, dbfs=-10.0),
        ]
        recs = evaluate_all_channels(channels, self._targets())
        assert [int(r.target.channel) for r in recs] == [5, 2, 8]

    def test_unknown_category_uses_fallback(self) -> None:
        # 타깃 dict에 vocal만 있고, 채널은 INSTRUMENT.
        targets = {"vocal": -18.0}
        ch = _channel(category=SourceCategory.INSTRUMENT, dbfs=-10.0)
        recs = evaluate_all_channels([ch], targets, unknown_fallback_dbfs=-26.0)
        assert len(recs) == 1
        # delta = -10 - (-26) = 16 dB
        assert recs[0].params["target_dbfs"] == -26.0
        assert recs[0].params["delta_db"] == pytest.approx(16.0, abs=1e-3)

    def test_deterministic_same_inputs_same_outputs(self) -> None:
        channels = [_channel(channel_id=i, dbfs=-10.0 - i) for i in range(1, 5)]
        a = evaluate_all_channels(channels, self._targets())
        b = evaluate_all_channels(channels, self._targets())
        assert a == b

    def test_returns_list_not_generator(self) -> None:
        channels = [_channel(dbfs=-10.0)]
        result = evaluate_all_channels(channels, self._targets())
        assert isinstance(result, list)


class TestDbfsControl:
    """헬퍼 자체 검증 — DC=v → RMS dBFS가 의도한 값이 되는지."""

    @pytest.mark.parametrize("dbfs", [-30.0, -20.0, -10.0, -6.0, 0.0])
    def test_dc_signal_matches_target_dbfs(self, dbfs: float) -> None:
        # 룰이 신호 생성에 종속되지 않도록, 헬퍼의 정확성을 명시 검증.
        ch = _channel(dbfs=dbfs)
        amplitude = float(ch.samples[0])
        assert amplitude == pytest.approx(10.0 ** (dbfs / 20.0), rel=1e-6)
        # RMS = |amplitude| (DC), dBFS = 20·log10(amplitude).
        measured = 20.0 * math.log10(amplitude)
        assert measured == pytest.approx(dbfs, abs=1e-5)
