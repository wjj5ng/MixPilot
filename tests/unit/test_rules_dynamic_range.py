"""Dynamic Range 룰 단위 테스트."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mixpilot.domain import (
    AudioFormat,
    Channel,
    RecommendationKind,
    Source,
    SourceCategory,
)
from mixpilot.rules.dynamic_range import (
    DEFAULT_HIGH_DR_THRESHOLD_DB,
    DEFAULT_LOW_DR_THRESHOLD_DB,
    evaluate_all_channels_dynamic_range,
    evaluate_channel_dynamic_range,
)

_FORMAT = AudioFormat(sample_rate=48000, num_channels=1, sample_dtype="float64")


def _channel(
    samples: np.ndarray, *, channel_id: int = 1, label: str = "test"
) -> Channel:
    source = Source(channel=channel_id, category=SourceCategory.VOCAL, label=label)
    return Channel(source=source, samples=samples, format=_FORMAT)


def _sine(amp: float, length: int = 4800) -> np.ndarray:
    t = np.arange(length) / 48000
    return (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)


def _dc(value: float, length: int = 1024) -> np.ndarray:
    return np.full(length, value, dtype=np.float64)


def _impulse(length: int = 1024) -> np.ndarray:
    sig = np.zeros(length, dtype=np.float64)
    sig[0] = 1.0
    return sig


class TestEvaluateChannelDynamicRange:
    def test_sine_in_compressed_range_emits_low_warning(self) -> None:
        # 사인파 DR ≈ 3 dB → 6 dB 임계 미만 → 압축 강함 알림.
        rec = evaluate_channel_dynamic_range(_channel(_sine(0.5)))
        assert rec is not None
        assert rec.kind == RecommendationKind.INFO
        assert "압축 강함" in rec.reason
        assert "ch01" in rec.reason

    def test_silence_returns_none(self) -> None:
        # 무음 → DR=0 → silence_threshold(0.5) 미만 → 알림 안 함.
        rec = evaluate_channel_dynamic_range(_channel(np.zeros(1000)))
        assert rec is None

    def test_dc_returns_none_as_silence(self) -> None:
        # DC도 DR=0이므로 silence_threshold 적용 → None.
        rec = evaluate_channel_dynamic_range(_channel(_dc(0.5)))
        assert rec is None

    def test_normal_range_returns_none(self) -> None:
        # 가우시안 노이즈 ≈ 11 dB → 정상 범위(6-20) → 알림 안 함.
        rng = np.random.default_rng(42)
        sig = (rng.standard_normal(4800) * 0.1).astype(np.float64)
        rec = evaluate_channel_dynamic_range(_channel(sig))
        assert rec is None

    def test_impulse_emits_high_warning(self) -> None:
        # 임펄스 DR ≈ 30 dB → 20 dB 임계 초과 → 트랜션트 폭 큼 알림.
        rec = evaluate_channel_dynamic_range(_channel(_impulse(1024)))
        assert rec is not None
        assert rec.kind == RecommendationKind.INFO
        assert "트랜션트 폭 큼" in rec.reason

    def test_confidence_scales_with_distance_from_threshold(self) -> None:
        # 임계와 가까울수록 낮은 confidence, 멀수록 1.0에 점근.
        # 사인파(DR≈3.01)는 임계 6에서 2.99 dB 이탈 → confidence ≈ 0.498.
        rec = evaluate_channel_dynamic_range(_channel(_sine(0.5)))
        assert rec is not None
        # 임계-DR = 6.0 - 3.0103 = 2.9897 → /6 → 0.498.
        assert rec.confidence == pytest.approx(2.9897 / 6.0, abs=0.01)

    def test_confidence_clamps_to_one(self) -> None:
        # 임펄스는 DR ≈ 30 → 임계 20에서 10 이탈 → /6 = 1.67 → 1.0으로 클램프.
        rec = evaluate_channel_dynamic_range(_channel(_impulse(1024)))
        assert rec is not None
        assert rec.confidence == 1.0

    def test_invalid_threshold_combination_raises(self) -> None:
        with pytest.raises(ValueError, match="must be <"):
            evaluate_channel_dynamic_range(
                _channel(_sine(0.5)),
                low_threshold_db=10.0,
                high_threshold_db=10.0,
            )

    def test_custom_thresholds_take_effect(self) -> None:
        # 임계를 사인파 DR(3 dB)보다 작게 → 알림 안 함.
        rec = evaluate_channel_dynamic_range(
            _channel(_sine(0.5)),
            low_threshold_db=2.0,
            high_threshold_db=20.0,
        )
        assert rec is None

    def test_label_fallback_to_category(self) -> None:
        # label이 빈 문자열이면 SourceCategory의 value 사용.
        source = Source(channel=3, category=SourceCategory.VOCAL, label="")
        channel = Channel(source=source, samples=_sine(0.5), format=_FORMAT)
        rec = evaluate_channel_dynamic_range(channel)
        assert rec is not None
        assert SourceCategory.VOCAL.value in rec.reason

    def test_reason_includes_measured_value(self) -> None:
        rec = evaluate_channel_dynamic_range(_channel(_sine(0.5)))
        assert rec is not None
        assert "3.0" in rec.reason  # measured ≈ 3.01

    def test_params_carry_thresholds(self) -> None:
        rec = evaluate_channel_dynamic_range(_channel(_sine(0.5)))
        assert rec is not None
        assert rec.params["low_threshold_db"] == DEFAULT_LOW_DR_THRESHOLD_DB
        assert rec.params["high_threshold_db"] == DEFAULT_HIGH_DR_THRESHOLD_DB
        assert math.isclose(rec.params["dynamic_range_db"], 3.0103, abs_tol=0.01)


class TestEvaluateAllChannels:
    def test_returns_only_warning_channels(self) -> None:
        rng = np.random.default_rng(42)
        channels = [
            _channel(_sine(0.5), channel_id=1, label="ch1"),  # 압축 강함
            _channel(
                (rng.standard_normal(4800) * 0.1).astype(np.float64),
                channel_id=2,
                label="ch2",
            ),  # 정상 — 빠짐
            _channel(_impulse(1024), channel_id=3, label="ch3"),  # 트랜션트 큼
            _channel(np.zeros(1000), channel_id=4, label="ch4"),  # 무음 — 빠짐
        ]
        recs = evaluate_all_channels_dynamic_range(channels)
        assert len(recs) == 2
        assert recs[0].target.channel == 1
        assert recs[1].target.channel == 3

    def test_input_order_preserved(self) -> None:
        # 결정성: 입력 순서 그대로 유지.
        channels = [
            _channel(_impulse(1024), channel_id=5, label="a"),
            _channel(_sine(0.5), channel_id=2, label="b"),
        ]
        recs = evaluate_all_channels_dynamic_range(channels)
        assert [r.target.channel for r in recs] == [5, 2]

    def test_empty_input(self) -> None:
        assert evaluate_all_channels_dynamic_range([]) == []
