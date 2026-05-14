"""LRA 룰 단위 테스트."""

from __future__ import annotations

import numpy as np
import pytest

from mixpilot.domain import (
    AudioFormat,
    Channel,
    RecommendationKind,
    Source,
    SourceCategory,
)
from mixpilot.rules.lra import (
    DEFAULT_HIGH_THRESHOLD_LU,
    DEFAULT_LOW_THRESHOLD_LU,
    evaluate_all_channels_lra,
    evaluate_channel_lra,
)

_SR = 48000
_FMT = AudioFormat(sample_rate=_SR, num_channels=1, sample_dtype="float64")


def _channel(samples: np.ndarray, *, channel_id: int = 1) -> Channel:
    source = Source(
        channel=channel_id, category=SourceCategory.VOCAL, label=f"ch{channel_id}"
    )
    return Channel(source=source, samples=samples, format=_FMT)


def _sine(duration_s: float, *, amp: float = 0.5) -> np.ndarray:
    n = int(duration_s * _SR)
    t = np.arange(n) / _SR
    return (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)


def _two_level(
    loud_s: float, soft_s: float, loud_amp: float, soft_amp: float
) -> np.ndarray:
    return np.concatenate([_sine(loud_s, amp=loud_amp), _sine(soft_s, amp=soft_amp)])


class TestEvaluateChannelLra:
    def test_steady_sine_returns_none(self) -> None:
        # Steady 사인파는 LRA가 거의 0 → silence_threshold 미만 → None.
        rec = evaluate_channel_lra(_channel(_sine(10.0)))
        assert rec is None

    def test_silence_returns_none(self) -> None:
        rec = evaluate_channel_lra(_channel(np.zeros(int(10 * _SR), dtype=np.float64)))
        assert rec is None

    def test_two_level_high_dynamic_emits_high_warning(self) -> None:
        # 30s loud + 30s soft (20 dB 차) → LRA ~20 LU → high_threshold(15) 초과.
        sig = _two_level(30.0, 30.0, loud_amp=0.5, soft_amp=0.05)
        rec = evaluate_channel_lra(_channel(sig))
        assert rec is not None
        assert rec.kind == RecommendationKind.INFO
        assert "다이내믹 폭 큼" in rec.reason
        assert rec.params["lra_lu"] > DEFAULT_HIGH_THRESHOLD_LU

    def test_low_threshold_custom_triggers_compression_warning(self) -> None:
        # 인위적으로 low_threshold를 매우 높여서 steady-ish 신호가 임계 미만이 되게.
        # two_level 8 dB 차 → LRA ~8 LU. low_threshold=10 / high=15 사이라 알림 없음.
        # → low_threshold=10 / high=12 → LRA 8은 low 미만이라 "압축 강함".
        sig = _two_level(30.0, 30.0, loud_amp=0.5, soft_amp=0.2)
        rec = evaluate_channel_lra(
            _channel(sig),
            low_threshold_lu=10.0,
            high_threshold_lu=12.0,
        )
        assert rec is not None
        assert "압축 매우 강함" in rec.reason

    def test_invalid_threshold_combination_raises(self) -> None:
        with pytest.raises(ValueError, match="must be <"):
            evaluate_channel_lra(
                _channel(_sine(5.0)),
                low_threshold_lu=10.0,
                high_threshold_lu=10.0,
            )

    def test_short_signal_propagates_dsp_error(self) -> None:
        # < 3초 신호는 dsp.lra가 raise — 룰은 통과만.
        with pytest.raises(ValueError, match="too short"):
            evaluate_channel_lra(_channel(_sine(2.0)))

    def test_confidence_clamps_to_one(self) -> None:
        # LRA ~20 LU, high_threshold=15 → margin=5 → confidence=5/5=1.0.
        # 더 극단적 차이는 EBU 상대 게이트로 quiet 영역이 제거되어 오히려
        # LRA가 감소하는 비단조성이 있음 — 적당한 amp 차로 안정 검증.
        sig = _two_level(30.0, 30.0, loud_amp=0.5, soft_amp=0.05)
        rec = evaluate_channel_lra(_channel(sig))
        assert rec is not None
        assert rec.confidence == 1.0

    def test_params_carry_thresholds(self) -> None:
        sig = _two_level(30.0, 30.0, loud_amp=0.5, soft_amp=0.05)
        rec = evaluate_channel_lra(_channel(sig))
        assert rec is not None
        assert rec.params["low_threshold_lu"] == DEFAULT_LOW_THRESHOLD_LU
        assert rec.params["high_threshold_lu"] == DEFAULT_HIGH_THRESHOLD_LU
        assert rec.params["lra_lu"] > 0


class TestEvaluateAllChannelsLra:
    def test_returns_only_warning_channels(self) -> None:
        channels = [
            _channel(_sine(10.0), channel_id=1),  # steady → None
            _channel(
                _two_level(30.0, 30.0, loud_amp=0.5, soft_amp=0.05),
                channel_id=2,
            ),  # high LRA → 알림
            _channel(
                np.zeros(int(10 * _SR), dtype=np.float64),
                channel_id=3,
            ),  # silence → None
        ]
        recs = evaluate_all_channels_lra(channels)
        assert len(recs) == 1
        assert recs[0].target.channel == 2

    def test_input_order_preserved(self) -> None:
        ch_a = _channel(
            _two_level(30.0, 30.0, loud_amp=0.5, soft_amp=0.05), channel_id=7
        )
        ch_b = _channel(
            _two_level(30.0, 30.0, loud_amp=0.5, soft_amp=0.05), channel_id=2
        )
        recs = evaluate_all_channels_lra([ch_a, ch_b])
        assert [r.target.channel for r in recs] == [7, 2]

    def test_empty_input(self) -> None:
        assert evaluate_all_channels_lra([]) == []
