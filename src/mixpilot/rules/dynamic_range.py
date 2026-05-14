"""채널 dynamic range (crest factor in dB) 모니터링 — 정보성 추천 생성.

라이브 운영에서 dynamic range가 *너무 낮으면* 콤프레서 과도 적용·소스 클립을
의심해야 한다. *너무 높으면* 안정적 라우드니스 유지가 어려워(트랜션트 폭이
커 페이더 추격 곤란) 운영자가 인지해야 한다.

자동 액션은 *없다* — DR을 어떻게 다룰지는 운영자 판단(콤프 설정·소스 교체·
페이더). 여기서는 INFO만 발행해 운영자 주의를 끌고, 추후 카테고리별 임계값
정밀 튜닝은 ADR 또는 evals 회고로.

기본 임계값(보수적 — false positive 줄이는 방향):

| Range (dB) | 해석 |
|---|---|
| < 3 | 매우 과도한 압축 또는 사실상 DC. 점검 필요. |
| 3-6 | 압축 강함. 의도적이라면 OK, 그렇지 않으면 콤프 점검. |
| 6-20 | 정상 범위(라이브 마이크·신호). |
| > 20 | 트랜션트 폭이 큼. 페이더 추격·콤프 튜닝 검토. |

INFO confidence는 임계 경계로부터의 거리에 비례. 임계와 정확히 같으면 0.0,
멀어질수록 1.0에 점근.

설계 원칙:
- 순수 함수. 시간·랜덤·환경 변수 의존 없음.
- 카테고리별 임계 동적 조정은 향후 — 일단 글로벌 임계 적용.
"""

from __future__ import annotations

from collections.abc import Iterable

from mixpilot.domain import Channel, Recommendation, RecommendationKind
from mixpilot.dsp import dynamic_range_db

DEFAULT_LOW_DR_THRESHOLD_DB: float = 6.0
"""이 미만은 과도 압축 의심 — INFO 발행."""

DEFAULT_HIGH_DR_THRESHOLD_DB: float = 20.0
"""이 초과는 트랜션트 폭이 너무 큼 — INFO 발행."""

DEFAULT_SILENCE_DR_THRESHOLD_DB: float = 0.5
"""DR이 이 미만이면 무음에 가까운 것으로 보고 평가 자체를 스킵."""


def evaluate_channel_dynamic_range(
    channel: Channel,
    *,
    low_threshold_db: float = DEFAULT_LOW_DR_THRESHOLD_DB,
    high_threshold_db: float = DEFAULT_HIGH_DR_THRESHOLD_DB,
    silence_threshold_db: float = DEFAULT_SILENCE_DR_THRESHOLD_DB,
) -> Recommendation | None:
    """단일 채널의 DR을 평가해 INFO 추천 생성.

    무음에 가까운 채널(`measured < silence_threshold_db`)은 None 반환 — 라이브
    "정적" 상태에서 매 프레임 알림이 뜨는 것을 방지.

    Args:
        channel: 평가할 채널.
        low_threshold_db: 이 미만이면 "과도 압축" 알림.
        high_threshold_db: 이 초과면 "트랜션트 폭 큼" 알림.
        silence_threshold_db: 이 미만은 무음으로 간주 — 평가 스킵.

    Returns:
        INFO Recommendation 또는 None.

    Raises:
        ValueError: 임계 조합이 비합리적(low >= high)일 때.
    """
    if low_threshold_db >= high_threshold_db:
        raise ValueError(
            f"low_threshold_db ({low_threshold_db}) must be < "
            f"high_threshold_db ({high_threshold_db})"
        )

    dr_db = dynamic_range_db(channel.samples)
    if dr_db < silence_threshold_db:
        return None
    if low_threshold_db <= dr_db <= high_threshold_db:
        return None

    label = channel.source.label or channel.source.category.value
    channel_id = int(channel.source.channel)
    if dr_db < low_threshold_db:
        margin = low_threshold_db - dr_db
        direction = "압축 강함"
        detail = f"DR {dr_db:.1f}dB (임계 {low_threshold_db:.1f}dB 미만)"
    else:
        margin = dr_db - high_threshold_db
        direction = "트랜션트 폭 큼"
        detail = f"DR {dr_db:.1f}dB (임계 {high_threshold_db:.1f}dB 초과)"

    confidence = min(1.0, margin / 6.0)

    return Recommendation(
        target=channel.source,
        kind=RecommendationKind.INFO,
        params={
            "dynamic_range_db": dr_db,
            "low_threshold_db": low_threshold_db,
            "high_threshold_db": high_threshold_db,
        },
        confidence=confidence,
        reason=f"ch{channel_id:02d} {label} {direction} — {detail}",
    )


def evaluate_all_channels_dynamic_range(
    channels: Iterable[Channel],
    *,
    low_threshold_db: float = DEFAULT_LOW_DR_THRESHOLD_DB,
    high_threshold_db: float = DEFAULT_HIGH_DR_THRESHOLD_DB,
    silence_threshold_db: float = DEFAULT_SILENCE_DR_THRESHOLD_DB,
) -> list[Recommendation]:
    """여러 채널을 일괄 평가."""
    recommendations: list[Recommendation] = []
    for channel in channels:
        rec = evaluate_channel_dynamic_range(
            channel,
            low_threshold_db=low_threshold_db,
            high_threshold_db=high_threshold_db,
            silence_threshold_db=silence_threshold_db,
        )
        if rec is not None:
            recommendations.append(rec)
    return recommendations
