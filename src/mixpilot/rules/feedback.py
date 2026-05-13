"""Feedback 룰 — `FeedbackPeak` 리스트 → `Recommendation(FEEDBACK_ALERT)`.

이 룰은 *순수 변환*만 한다 — 분석은 `dsp.detect_peak_bins`가 하고, 지속성
검증은 `runtime.FeedbackDetector`가 한다. 여기서는 이미 sustained 검증된
peaks를 받아 도메인 추천으로 매핑할 뿐.

자동 적용(자동 게인 감쇠 등)은 *별도 ADR 후* 결정. 현재는 INFO-스타일
FEEDBACK_ALERT만 발화 — consumer가 운영자 알림·수동 조치를 결정한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from mixpilot.domain import Recommendation, RecommendationKind, Source
from mixpilot.dsp import FeedbackPeak

DEFAULT_PNR_THRESHOLD_DB: float = 15.0
"""PNR 임계값. `dsp.feedback`의 디폴트와 일치 — confidence 매핑의 기준점."""

CONFIDENCE_FLOOR: float = 0.5
"""임계값에 막 도달했을 때의 최소 confidence. 그 이상 PNR일수록 1.0으로 상승."""

CONFIDENCE_FULL_AT_EXCESS_DB: float = 15.0
"""임계값 대비 이 만큼 초과하면 confidence가 1.0에 도달."""


def _pnr_to_confidence(
    pnr_db: float, threshold_db: float = DEFAULT_PNR_THRESHOLD_DB
) -> float:
    """PNR → confidence [CONFIDENCE_FLOOR, 1.0].

    임계값에 도달하면 CONFIDENCE_FLOOR, +15 dB이면 1.0. 그 사이는 선형 보간.
    임계값 미만은 (정상적으로는 안 들어오겠지만) 0.0 가능.
    """
    excess = pnr_db - threshold_db
    if excess < 0:
        return max(0.0, CONFIDENCE_FLOOR + excess / CONFIDENCE_FULL_AT_EXCESS_DB)
    return min(1.0, CONFIDENCE_FLOOR + excess / CONFIDENCE_FULL_AT_EXCESS_DB)


def _peak_to_recommendation(
    source: Source,
    peak: FeedbackPeak,
    pnr_threshold_db: float,
) -> Recommendation:
    label = source.label or source.category.value
    return Recommendation(
        target=source,
        kind=RecommendationKind.FEEDBACK_ALERT,
        params={
            "frequency_hz": float(peak.frequency_hz),
            "bin_index": float(peak.bin_index),
            "magnitude_dbfs": float(peak.magnitude_dbfs),
            "pnr_db": float(peak.pnr_db),
        },
        confidence=_pnr_to_confidence(peak.pnr_db, pnr_threshold_db),
        reason=(
            f"ch{int(source.channel):02d} {label} 하울링 의심 — "
            f"{peak.frequency_hz:.0f} Hz, PNR {peak.pnr_db:.1f} dB"
        ),
    )


def evaluate_feedback(
    source: Source,
    peaks: Iterable[FeedbackPeak],
    *,
    pnr_threshold_db: float = DEFAULT_PNR_THRESHOLD_DB,
) -> list[Recommendation]:
    """단일 채널의 FeedbackPeaks → FEEDBACK_ALERT Recommendations.

    각 peak가 별개의 Recommendation으로 변환된다. 입력 순서 유지.

    Args:
        source: 어느 채널의 peaks인지.
        peaks: `FeedbackDetector.update()` 결과(이미 sustained 검증됨).
        pnr_threshold_db: confidence 매핑의 기준 PNR. 보통 detector와 같은 값.

    Returns:
        Recommendation 리스트. 빈 peaks → 빈 리스트.
    """
    return [_peak_to_recommendation(source, peak, pnr_threshold_db) for peak in peaks]


def evaluate_all_feedback(
    peaks_by_source: Mapping[Source, Iterable[FeedbackPeak]],
    *,
    pnr_threshold_db: float = DEFAULT_PNR_THRESHOLD_DB,
) -> list[Recommendation]:
    """여러 채널의 peaks를 통합 Recommendation 리스트로 변환.

    결정성: 채널은 channel id 오름차순으로 처리, peak는 입력 순서 유지.

    Args:
        peaks_by_source: Source → 해당 채널의 peaks 매핑.
        pnr_threshold_db: confidence 기준 임계.

    Returns:
        통합 Recommendation 리스트.
    """
    sorted_sources = sorted(peaks_by_source.keys(), key=lambda s: int(s.channel))
    recommendations: list[Recommendation] = []
    for source in sorted_sources:
        recommendations.extend(
            evaluate_feedback(
                source, peaks_by_source[source], pnr_threshold_db=pnr_threshold_db
            )
        )
    return recommendations
