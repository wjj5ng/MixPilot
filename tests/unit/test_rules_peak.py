"""rules.peak 단위 테스트 — 클리핑·헤드룸 임계 + 변환."""

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
from mixpilot.rules import evaluate_all_channels_peak, evaluate_channel_peak

SR = 48000


def _channel_at_peak_dbfs(
    dbfs: float,
    *,
    channel_id: int = 1,
    category: SourceCategory = SourceCategory.VOCAL,
    label: str = "",
    num_samples: int = 4800,  # 100 ms — 사인 다수 주기.
    freq: float = 1000.0,
) -> Channel:
    """주어진 dBFS의 1 kHz 사인 신호 채널.

    DC를 쓰면 신호 시작점의 불연속으로 resample_poly가 ~1 dB overshoot을 만들어
    true_peak가 부풀려진다. 사인파는 0에서 시작·매끄러워 그런 transient가 없다.
    1 kHz @ 48 kHz는 주기당 48 샘플로 sin 최대(π/2)가 정확히 샘플 12에 떨어져
    sample peak = amplitude.
    """
    amp = 10.0 ** (dbfs / 20.0)
    t = np.arange(num_samples) / SR
    samples = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)
    return Channel(
        source=Source(ChannelId(channel_id), category, label),
        samples=samples,
        format=AudioFormat(SR, 1, "float64"),
    )


class TestEvaluateChannelPeak:
    def test_well_below_threshold_returns_none(self) -> None:
        ch = _channel_at_peak_dbfs(-5.0)
        assert evaluate_channel_peak(ch, headroom_threshold_dbfs=-1.0) is None

    def test_at_threshold_emits_info_with_floor_confidence(self) -> None:
        # -1 dBFS, 임계 -1 → 경계에서 INFO + confidence 0.5.
        ch = _channel_at_peak_dbfs(-1.0)
        rec = evaluate_channel_peak(ch, headroom_threshold_dbfs=-1.0)
        assert rec is not None
        assert rec.kind is RecommendationKind.INFO
        assert rec.confidence == pytest.approx(0.5, abs=0.05)
        assert "헤드룸" in rec.reason
        assert rec.params["is_clipping"] == 0.0

    def test_clipping_yields_max_confidence(self) -> None:
        # 0 dBFS — 디지털 풀 스케일. confidence 1.0.
        ch = _channel_at_peak_dbfs(0.0)
        rec = evaluate_channel_peak(ch, headroom_threshold_dbfs=-1.0)
        assert rec is not None
        assert rec.confidence == 1.0
        assert "클리핑" in rec.reason
        assert rec.params["is_clipping"] == 1.0

    def test_midway_confidence_linear(self) -> None:
        # -0.5 dBFS, threshold -1 → ratio 0.5 → confidence 0.75.
        ch = _channel_at_peak_dbfs(-0.5)
        rec = evaluate_channel_peak(ch, headroom_threshold_dbfs=-1.0)
        assert rec is not None
        assert rec.confidence == pytest.approx(0.75, abs=0.05)
        assert "헤드룸" in rec.reason

    def test_just_below_threshold_returns_none(self) -> None:
        # -1.5 dBFS는 threshold -1.0 미만.
        ch = _channel_at_peak_dbfs(-1.5)
        assert evaluate_channel_peak(ch, headroom_threshold_dbfs=-1.0) is None

    def test_silence_returns_none(self) -> None:
        # 무음 → SILENCE_FLOOR_DBFS(-120) → 임계 한참 미만.
        ch = Channel(
            source=Source(ChannelId(1), SourceCategory.VOCAL),
            samples=np.zeros(1024, dtype=np.float64),
            format=AudioFormat(SR, 1, "float64"),
        )
        assert evaluate_channel_peak(ch) is None

    def test_params_contain_diagnostic_fields(self) -> None:
        ch = _channel_at_peak_dbfs(-0.5)
        rec = evaluate_channel_peak(ch, headroom_threshold_dbfs=-1.0)
        assert rec is not None
        assert "true_peak_dbfs" in rec.params
        assert "headroom_db" in rec.params
        assert "threshold_dbfs" in rec.params
        assert "is_clipping" in rec.params
        assert rec.params["threshold_dbfs"] == -1.0
        # headroom_db = 0 - measured.
        assert rec.params["headroom_db"] == pytest.approx(
            -rec.params["true_peak_dbfs"], abs=0.01
        )

    def test_custom_threshold(self) -> None:
        # threshold -3 dBFS면 -2 dBFS 신호도 잡힘.
        ch = _channel_at_peak_dbfs(-2.0)
        rec = evaluate_channel_peak(ch, headroom_threshold_dbfs=-3.0)
        assert rec is not None

    def test_label_used_in_reason_when_present(self) -> None:
        ch = _channel_at_peak_dbfs(-0.5, label="설교자 메인")
        rec = evaluate_channel_peak(ch)
        assert rec is not None
        assert "설교자 메인" in rec.reason

    def test_category_used_when_no_label(self) -> None:
        ch = _channel_at_peak_dbfs(-0.5, category=SourceCategory.CHOIR, label="")
        rec = evaluate_channel_peak(ch)
        assert rec is not None
        assert "choir" in rec.reason

    def test_channel_zero_padded(self) -> None:
        for ch_id, expected in [(1, "ch01"), (10, "ch10"), (32, "ch32")]:
            rec = evaluate_channel_peak(_channel_at_peak_dbfs(-0.5, channel_id=ch_id))
            assert rec is not None
            assert expected in rec.reason

    def test_reason_has_dbfs_units(self) -> None:
        rec = evaluate_channel_peak(_channel_at_peak_dbfs(-0.5))
        assert rec is not None
        assert "dBFS" in rec.reason
        assert "dB)" in rec.reason  # headroom 단위

    def test_rejects_oversample_zero(self) -> None:
        ch = _channel_at_peak_dbfs(-0.5)
        with pytest.raises(ValueError, match="oversample"):
            evaluate_channel_peak(ch, oversample=0)

    def test_deterministic(self) -> None:
        ch = _channel_at_peak_dbfs(-0.5)
        a = evaluate_channel_peak(ch)
        b = evaluate_channel_peak(ch)
        assert a == b


class TestEvaluateAllChannelsPeak:
    def test_empty_iterable_returns_empty(self) -> None:
        assert evaluate_all_channels_peak([]) == []

    def test_all_below_threshold_returns_empty(self) -> None:
        channels = [
            _channel_at_peak_dbfs(-10.0, channel_id=1),
            _channel_at_peak_dbfs(-5.0, channel_id=2),
        ]
        assert evaluate_all_channels_peak(channels) == []

    def test_filters_out_within_safe_range(self) -> None:
        channels = [
            _channel_at_peak_dbfs(-10.0, channel_id=1),  # 안전
            _channel_at_peak_dbfs(0.0, channel_id=2),  # 클리핑
            _channel_at_peak_dbfs(-3.0, channel_id=3),  # 안전
            _channel_at_peak_dbfs(-0.3, channel_id=4),  # 헤드룸 부족
        ]
        recs = evaluate_all_channels_peak(channels)
        assert [int(r.target.channel) for r in recs] == [2, 4]

    def test_preserves_input_order(self) -> None:
        channels = [
            _channel_at_peak_dbfs(-0.5, channel_id=5),
            _channel_at_peak_dbfs(-0.5, channel_id=2),
            _channel_at_peak_dbfs(-0.5, channel_id=8),
        ]
        recs = evaluate_all_channels_peak(channels)
        assert [int(r.target.channel) for r in recs] == [5, 2, 8]

    def test_deterministic(self) -> None:
        channels = [_channel_at_peak_dbfs(-0.5)]
        a = evaluate_all_channels_peak(channels)
        b = evaluate_all_channels_peak(channels)
        assert a == b

    def test_returns_list_not_generator(self) -> None:
        result = evaluate_all_channels_peak([_channel_at_peak_dbfs(-0.5)])
        assert isinstance(result, list)


class TestSineControl:
    """헬퍼 자체 검증 — 1 kHz @ 48 kHz 사인 sample peak가 의도한 dBFS인지."""

    @pytest.mark.parametrize("dbfs", [-10.0, -3.0, -1.0, -0.5, 0.0])
    def test_sine_yields_expected_peak_dbfs(self, dbfs: float) -> None:
        ch = _channel_at_peak_dbfs(dbfs)
        expected_amp = 10.0 ** (dbfs / 20.0)
        # sample peak는 amplitude에 정확히 도달해야 함.
        assert float(np.abs(ch.samples).max()) == pytest.approx(expected_amp, rel=1e-6)
