"""Unit tests for domain models — validation, immutability, value semantics."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from mixpilot.domain import (
    AudioFormat,
    ChannelId,
    Recommendation,
    RecommendationKind,
    Signal,
    Source,
    SourceCategory,
)


class TestAudioFormat:
    def test_creates_valid_format(self) -> None:
        fmt = AudioFormat(sample_rate=48000, num_channels=32, sample_dtype="float32")
        assert fmt.sample_rate == 48000
        assert fmt.num_channels == 32
        assert fmt.sample_dtype == "float32"

    def test_is_frozen(self) -> None:
        fmt = AudioFormat(48000, 32, "float32")
        with pytest.raises(dataclasses.FrozenInstanceError):
            fmt.sample_rate = 44100  # type: ignore[misc]

    def test_equality_is_value_based(self) -> None:
        a = AudioFormat(48000, 32, "float32")
        b = AudioFormat(48000, 32, "float32")
        assert a == b
        assert hash(a) == hash(b)

    def test_rejects_non_positive_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            AudioFormat(sample_rate=0, num_channels=1, sample_dtype="float32")
        with pytest.raises(ValueError, match="sample_rate"):
            AudioFormat(sample_rate=-1, num_channels=1, sample_dtype="float32")

    def test_rejects_non_positive_num_channels(self) -> None:
        with pytest.raises(ValueError, match="num_channels"):
            AudioFormat(sample_rate=48000, num_channels=0, sample_dtype="float32")


class TestSignal:
    def test_num_frames_from_samples_shape(self) -> None:
        samples = np.zeros((256, 2), dtype=np.float32)
        fmt = AudioFormat(48000, 2, "float32")
        sig = Signal(samples=samples, format=fmt)
        assert sig.num_frames == 256

    def test_duration_seconds(self) -> None:
        samples = np.zeros((48000, 1), dtype=np.float32)
        fmt = AudioFormat(48000, 1, "float32")
        sig = Signal(samples=samples, format=fmt)
        assert sig.duration_seconds == pytest.approx(1.0)

    def test_capture_seq_defaults_to_zero(self) -> None:
        samples = np.zeros((128,), dtype=np.float32)
        fmt = AudioFormat(48000, 1, "float32")
        sig = Signal(samples=samples, format=fmt)
        assert sig.capture_seq == 0

    def test_is_frozen(self) -> None:
        samples = np.zeros((128, 1), dtype=np.float32)
        fmt = AudioFormat(48000, 1, "float32")
        sig = Signal(samples=samples, format=fmt)
        with pytest.raises(dataclasses.FrozenInstanceError):
            sig.capture_seq = 1  # type: ignore[misc]


class TestSource:
    def test_creates_with_category_and_label(self) -> None:
        src = Source(
            channel=ChannelId(1), category=SourceCategory.PREACHER, label="설교자"
        )
        assert src.channel == 1
        assert src.category is SourceCategory.PREACHER
        assert src.label == "설교자"

    def test_default_label_is_empty(self) -> None:
        src = Source(channel=ChannelId(5), category=SourceCategory.UNKNOWN)
        assert src.label == ""

    def test_equality_value_based(self) -> None:
        a = Source(ChannelId(5), SourceCategory.CHOIR, "성가대 SOP")
        b = Source(ChannelId(5), SourceCategory.CHOIR, "성가대 SOP")
        assert a == b
        assert hash(a) == hash(b)


class TestRecommendation:
    @staticmethod
    def _src() -> Source:
        return Source(ChannelId(1), SourceCategory.VOCAL)

    def test_creates_valid(self) -> None:
        rec = Recommendation(
            target=self._src(),
            kind=RecommendationKind.GAIN_ADJUST,
            params={"delta_db": -2.0},
            confidence=0.8,
            reason="LUFS over target",
        )
        assert rec.kind is RecommendationKind.GAIN_ADJUST
        assert rec.confidence == 0.8
        assert rec.params == {"delta_db": -2.0}

    @pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0, -1.0])
    def test_rejects_out_of_range_confidence(self, bad: float) -> None:
        with pytest.raises(ValueError, match="confidence"):
            Recommendation(
                target=self._src(),
                kind=RecommendationKind.INFO,
                params={},
                confidence=bad,
                reason="test",
            )

    def test_accepts_boundary_confidence(self) -> None:
        for c in (0.0, 1.0):
            rec = Recommendation(
                target=self._src(),
                kind=RecommendationKind.INFO,
                params={},
                confidence=c,
                reason="boundary",
            )
            assert rec.confidence == c

    def test_is_frozen(self) -> None:
        rec = Recommendation(
            target=self._src(),
            kind=RecommendationKind.INFO,
            params={},
            confidence=0.5,
            reason="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rec.confidence = 0.9  # type: ignore[misc]


class TestSourceCategory:
    def test_all_values_are_lowercase_strings(self) -> None:
        for cat in SourceCategory:
            assert isinstance(cat.value, str)
            assert cat.value == cat.value.lower()

    def test_includes_unknown_for_unmapped(self) -> None:
        assert SourceCategory.UNKNOWN in set(SourceCategory)
