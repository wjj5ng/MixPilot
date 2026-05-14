"""Stereo phase 룰 단위 테스트."""

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
from mixpilot.rules.phase import (
    DEFAULT_WARN_THRESHOLD,
    evaluate_all_phase_pairs,
    evaluate_pair_phase,
)

_SR = 48000
_FMT = AudioFormat(sample_rate=_SR, num_channels=1, sample_dtype="float64")


def _ch(
    samples: np.ndarray,
    *,
    channel_id: int,
    label: str = "",
    pair: int | None = None,
) -> Channel:
    src = Source(
        channel=channel_id,
        category=SourceCategory.INSTRUMENT,
        label=label,
        stereo_pair_with=pair,
    )
    return Channel(source=src, samples=samples, format=_FMT)


def _sine(amp: float = 0.5, *, n: int = 4800) -> np.ndarray:
    t = np.arange(n) / _SR
    return (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)


class TestEvaluatePairPhase:
    def test_in_phase_no_warning(self) -> None:
        sig = _sine()
        left = _ch(sig, channel_id=1, label="L")
        right = _ch(sig.copy(), channel_id=2, label="R")
        rec = evaluate_pair_phase(left, right)
        assert rec is None

    def test_anti_phase_emits_warning(self) -> None:
        sig = _sine()
        left = _ch(sig, channel_id=1, label="L")
        right = _ch(-sig, channel_id=2, label="R")
        rec = evaluate_pair_phase(left, right)
        assert rec is not None
        assert rec.kind == RecommendationKind.INFO
        assert "phase 위험" in rec.reason
        assert "ch01-ch02" in rec.reason
        # 완전 역상 → margin = -0.3 - (-1) = 0.7 → confidence = 1.0.
        assert rec.confidence == pytest.approx(1.0, abs=1e-6)

    def test_silence_returns_none(self) -> None:
        zero = np.zeros(1024, dtype=np.float64)
        left = _ch(zero, channel_id=1)
        right = _ch(zero, channel_id=2)
        rec = evaluate_pair_phase(left, right)
        assert rec is None

    def test_marginal_correlation_no_warning(self) -> None:
        # correlation ≈ 0 (직교) → 임계 -0.3 통과 → None.
        n = 4800
        t = np.arange(n) / _SR
        left_sig = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
        right_sig = (0.5 * np.cos(2 * np.pi * 1000 * t)).astype(np.float64)
        left = _ch(left_sig, channel_id=1)
        right = _ch(right_sig, channel_id=2)
        assert evaluate_pair_phase(left, right) is None

    def test_custom_threshold(self) -> None:
        # 임계를 +0.5로 두면 거의 모든 신호가 발화 (in-phase여도).
        sig = _sine()
        left = _ch(sig, channel_id=1, label="L")
        right = _ch(sig.copy(), channel_id=2, label="R")
        rec = evaluate_pair_phase(left, right, warn_threshold=0.5)
        # in-phase 1.0 > 0.5 → None.
        assert rec is None
        # 임계를 +1.5(논리적으로 안 되는 값이지만 룰은 그대로 적용) → 모두 발화.
        # 더 현실적 케이스 — quadrature(0.0)에 -0.05 임계.
        t = np.arange(4800) / _SR
        l2 = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
        r2 = (0.5 * np.cos(2 * np.pi * 1000 * t)).astype(np.float64)
        rec2 = evaluate_pair_phase(
            _ch(l2, channel_id=1),
            _ch(r2, channel_id=2),
            warn_threshold=0.05,
        )
        # quadrature ≈ 0 < 0.05 → 발화.
        assert rec2 is not None

    def test_params_carry_correlation(self) -> None:
        sig = _sine()
        rec = evaluate_pair_phase(_ch(sig, channel_id=1), _ch(-sig, channel_id=2))
        assert rec is not None
        assert rec.params["phase_correlation"] == pytest.approx(-1.0, abs=1e-9)
        assert rec.params["pair_channel"] == 2.0


class TestEvaluateAllPhasePairs:
    def test_skips_channels_without_pair(self) -> None:
        sig = _sine()
        # ch3·ch4가 pair, ch1·ch2는 mono.
        channels = [
            _ch(sig, channel_id=1, pair=None),
            _ch(sig.copy(), channel_id=2, pair=None),
            _ch(sig.copy(), channel_id=3, pair=4, label="L"),
            _ch(-sig, channel_id=4, pair=3, label="R"),
        ]
        recs = evaluate_all_phase_pairs(channels)
        assert len(recs) == 1
        assert int(recs[0].target.channel) == 3  # smaller id가 target.

    def test_pair_evaluated_once(self) -> None:
        # ch1↔ch2 + ch2↔ch1 양방향 표기여도 한 번만 평가.
        sig = _sine()
        channels = [
            _ch(sig, channel_id=1, pair=2),
            _ch(-sig, channel_id=2, pair=1),
        ]
        recs = evaluate_all_phase_pairs(channels)
        assert len(recs) == 1

    def test_partner_missing_skips(self) -> None:
        # ch1은 pair=2를 가리키지만 채널 리스트에 ch2 없음.
        sig = _sine()
        channels = [_ch(sig, channel_id=1, pair=2)]
        recs = evaluate_all_phase_pairs(channels)
        assert recs == []

    def test_threshold_propagated(self) -> None:
        # 임계 매우 보수적(-0.95) → in-phase는 안 잡힘.
        sig = _sine()
        channels = [
            _ch(sig, channel_id=1, pair=2),
            _ch(-sig, channel_id=2, pair=1),
        ]
        recs = evaluate_all_phase_pairs(channels, warn_threshold=-0.95)
        # -1.0 < -0.95 → 여전히 발화.
        assert len(recs) == 1

    def test_default_threshold_constant(self) -> None:
        assert DEFAULT_WARN_THRESHOLD == -0.3
