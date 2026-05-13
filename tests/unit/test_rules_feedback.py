"""rules.feedback 단위 테스트 — FeedbackPeak → Recommendation 변환."""

from __future__ import annotations

import pytest

from mixpilot.domain import (
    ChannelId,
    RecommendationKind,
    Source,
    SourceCategory,
)
from mixpilot.dsp import FeedbackPeak
from mixpilot.rules import evaluate_all_feedback, evaluate_feedback


def _peak(
    *,
    frequency_hz: float = 1000.0,
    bin_index: int = 21,
    magnitude_dbfs: float = -3.0,
    pnr_db: float = 20.0,
) -> FeedbackPeak:
    return FeedbackPeak(
        frequency_hz=frequency_hz,
        bin_index=bin_index,
        magnitude_dbfs=magnitude_dbfs,
        pnr_db=pnr_db,
    )


def _source(
    channel: int = 1,
    category: SourceCategory = SourceCategory.VOCAL,
    label: str = "",
) -> Source:
    return Source(ChannelId(channel), category, label)


class TestEvaluateFeedback:
    def test_empty_peaks_returns_empty(self) -> None:
        assert evaluate_feedback(_source(), []) == []

    def test_single_peak_yields_one_recommendation(self) -> None:
        recs = evaluate_feedback(_source(), [_peak()])
        assert len(recs) == 1
        assert recs[0].kind is RecommendationKind.FEEDBACK_ALERT

    def test_multiple_peaks_preserve_order(self) -> None:
        peaks = [
            _peak(frequency_hz=500.0, bin_index=10),
            _peak(frequency_hz=2000.0, bin_index=42),
            _peak(frequency_hz=5000.0, bin_index=106),
        ]
        recs = evaluate_feedback(_source(), peaks)
        assert [r.params["frequency_hz"] for r in recs] == [500.0, 2000.0, 5000.0]

    def test_target_matches_source(self) -> None:
        src = _source(channel=7, category=SourceCategory.PREACHER, label="설교자")
        recs = evaluate_feedback(src, [_peak()])
        assert recs[0].target is src

    def test_params_contain_peak_metadata(self) -> None:
        peak = _peak(
            frequency_hz=1500.0, bin_index=32, magnitude_dbfs=-1.5, pnr_db=22.0
        )
        rec = evaluate_feedback(_source(), [peak])[0]
        assert rec.params["frequency_hz"] == 1500.0
        assert rec.params["bin_index"] == 32.0
        assert rec.params["magnitude_dbfs"] == -1.5
        assert rec.params["pnr_db"] == 22.0


class TestReason:
    def test_includes_channel_and_frequency(self) -> None:
        src = _source(channel=3)
        rec = evaluate_feedback(src, [_peak(frequency_hz=1234.0, pnr_db=18.0)])[0]
        assert "ch03" in rec.reason
        assert "1234" in rec.reason
        assert "PNR 18.0 dB" in rec.reason
        assert "하울링" in rec.reason

    def test_label_used_when_present(self) -> None:
        src = _source(label="설교자 메인")
        rec = evaluate_feedback(src, [_peak()])[0]
        assert "설교자 메인" in rec.reason

    def test_category_used_when_label_empty(self) -> None:
        src = _source(category=SourceCategory.CHOIR, label="")
        rec = evaluate_feedback(src, [_peak()])[0]
        assert "choir" in rec.reason

    def test_channel_zero_padded(self) -> None:
        for ch, expected in [(1, "ch01"), (10, "ch10"), (32, "ch32")]:
            rec = evaluate_feedback(_source(channel=ch), [_peak()])[0]
            assert expected in rec.reason


class TestConfidence:
    def test_at_threshold_yields_floor(self) -> None:
        rec = evaluate_feedback(_source(), [_peak(pnr_db=15.0)])[0]
        assert rec.confidence == pytest.approx(0.5, abs=1e-6)

    def test_threshold_plus_15db_yields_one(self) -> None:
        rec = evaluate_feedback(_source(), [_peak(pnr_db=30.0)])[0]
        assert rec.confidence == pytest.approx(1.0, abs=1e-6)

    def test_beyond_full_clamps_to_one(self) -> None:
        rec = evaluate_feedback(_source(), [_peak(pnr_db=60.0)])[0]
        assert rec.confidence == 1.0

    def test_higher_pnr_higher_confidence(self) -> None:
        a = evaluate_feedback(_source(), [_peak(pnr_db=16.0)])[0]
        b = evaluate_feedback(_source(), [_peak(pnr_db=22.0)])[0]
        assert b.confidence > a.confidence

    def test_custom_threshold_shifts_floor(self) -> None:
        rec = evaluate_feedback(_source(), [_peak(pnr_db=25.0)], pnr_threshold_db=25.0)[
            0
        ]
        # 임계값과 PNR이 같으면 floor.
        assert rec.confidence == pytest.approx(0.5, abs=1e-6)


class TestEvaluateAllFeedback:
    def test_empty_mapping_returns_empty(self) -> None:
        assert evaluate_all_feedback({}) == []

    def test_sources_processed_in_channel_id_order(self) -> None:
        # 입력 mapping 순서와 무관하게 channel 오름차순으로 처리.
        s1 = _source(channel=1)
        s3 = _source(channel=3)
        s7 = _source(channel=7)
        peaks_by_source = {
            s7: [_peak(frequency_hz=500.0)],
            s1: [_peak(frequency_hz=1000.0)],
            s3: [_peak(frequency_hz=2000.0)],
        }
        recs = evaluate_all_feedback(peaks_by_source)
        channels = [int(r.target.channel) for r in recs]
        assert channels == [1, 3, 7]

    def test_per_source_peak_order_preserved(self) -> None:
        s1 = _source(channel=1)
        peaks_by_source = {
            s1: [
                _peak(frequency_hz=300.0, bin_index=6),
                _peak(frequency_hz=900.0, bin_index=19),
            ],
        }
        recs = evaluate_all_feedback(peaks_by_source)
        assert [r.params["frequency_hz"] for r in recs] == [300.0, 900.0]

    def test_empty_peaks_per_source_skipped(self) -> None:
        s1 = _source(channel=1)
        s2 = _source(channel=2)
        peaks_by_source = {s1: [], s2: [_peak()]}
        recs = evaluate_all_feedback(peaks_by_source)
        assert len(recs) == 1
        assert int(recs[0].target.channel) == 2


class TestDeterminism:
    def test_evaluate_feedback_deterministic(self) -> None:
        src = _source(channel=5, category=SourceCategory.VOCAL, label="보컬")
        peaks = [_peak(frequency_hz=1200.0, pnr_db=20.0)]
        a = evaluate_feedback(src, peaks)
        b = evaluate_feedback(src, peaks)
        assert a == b

    def test_evaluate_all_feedback_deterministic(self) -> None:
        s1 = _source(channel=1)
        s2 = _source(channel=2)
        peaks_by_source = {s1: [_peak(frequency_hz=500.0)], s2: [_peak()]}
        a = evaluate_all_feedback(peaks_by_source)
        b = evaluate_all_feedback(peaks_by_source)
        assert a == b
