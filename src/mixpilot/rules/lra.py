"""채널 LRA(EBU R128 Loudness Range) 모니터링 — INFO 추천 생성.

라이브 운영에서 LRA는 *압축 정도* 가시화 — 자동 액션은 부적절하다(콤프
세팅·소스 선택은 운영자 판단). 따라서 임계 밖일 때 INFO만 발화.

기본 임계값(EBU 권장 + 라이브 환경 보수적 조정):

| LRA (LU) | 해석 |
|---|---|
| < 5  | 매우 강한 압축. 의도적이라면 OK, 그렇지 않으면 콤프 점검. |
| 5-15 | 정상 범위. 알림 없음. |
| > 15 | 트랜션트 폭이 큼 — 페이더 추격·콤프 튜닝 검토. |

LRA는 *누적 메트릭*이므로 호출자가 충분한 버퍼(>= 3s)를 가진 Channel을
주입해야 한다. main.py의 processing 루프에서 RollingBuffer.snapshot()으로
만든 Channel을 사용.

설계 원칙:
- 순수 함수. 시간·랜덤·환경 변수 의존 없음.
- 본 모듈은 `mixpilot.dsp.lra.lra`만 사용 — sample_rate 검증은 dsp 측 가드.
"""

from __future__ import annotations

from collections.abc import Iterable

from mixpilot.domain import Channel, Recommendation, RecommendationKind, Source
from mixpilot.dsp.lra import NO_LRA, lra

DEFAULT_LOW_THRESHOLD_LU: float = 5.0
"""이 미만이면 "압축 매우 강함" INFO 발화."""

DEFAULT_HIGH_THRESHOLD_LU: float = 15.0
"""이 초과면 "다이내믹 폭 큼" INFO 발화."""

DEFAULT_SILENCE_THRESHOLD_LU: float = 0.1
"""LRA가 이 미만이면 무음/단조 — 평가 스킵."""


def evaluate_lra_value(
    source: Source,
    lra_value: float,
    *,
    low_threshold_lu: float = DEFAULT_LOW_THRESHOLD_LU,
    high_threshold_lu: float = DEFAULT_HIGH_THRESHOLD_LU,
    silence_threshold_lu: float = DEFAULT_SILENCE_THRESHOLD_LU,
) -> Recommendation | None:
    """이미 계산된 LRA 값으로 추천 생성 — 중복 계산 회피용.

    main.py 처리 루프가 LRA를 한 번 계산해 meter publish에도 사용하고
    동일 값을 본 함수에 넘겨 추천 평가도 수행 — DSP 두 번 호출 방지.

    Args / Returns / Raises: 임계 동작은 `evaluate_channel_lra`와 동일.
    """
    if low_threshold_lu >= high_threshold_lu:
        raise ValueError(
            f"low_threshold_lu ({low_threshold_lu}) must be < "
            f"high_threshold_lu ({high_threshold_lu})"
        )
    if lra_value <= NO_LRA or lra_value < silence_threshold_lu:
        return None
    if low_threshold_lu <= lra_value <= high_threshold_lu:
        return None

    label = source.label or source.category.value
    channel_id = int(source.channel)
    if lra_value < low_threshold_lu:
        margin = low_threshold_lu - lra_value
        direction = "압축 매우 강함"
        detail = f"LRA {lra_value:.1f} LU (임계 {low_threshold_lu:.1f} 미만)"
    else:
        margin = lra_value - high_threshold_lu
        direction = "다이내믹 폭 큼"
        detail = f"LRA {lra_value:.1f} LU (임계 {high_threshold_lu:.1f} 초과)"
    confidence = min(1.0, margin / 5.0)
    return Recommendation(
        target=source,
        kind=RecommendationKind.INFO,
        params={
            "lra_lu": lra_value,
            "low_threshold_lu": low_threshold_lu,
            "high_threshold_lu": high_threshold_lu,
        },
        confidence=confidence,
        reason=f"ch{channel_id:02d} {label} {direction} — {detail}",
    )


def evaluate_channel_lra(
    channel: Channel,
    *,
    low_threshold_lu: float = DEFAULT_LOW_THRESHOLD_LU,
    high_threshold_lu: float = DEFAULT_HIGH_THRESHOLD_LU,
    silence_threshold_lu: float = DEFAULT_SILENCE_THRESHOLD_LU,
) -> Recommendation | None:
    """단일 채널의 LRA를 평가해 INFO 추천 생성.

    Args:
        channel: 평가할 채널. samples는 >= 3초 분량이어야 함 (dsp.lra 가드).
        low_threshold_lu: 이 미만이면 "압축 강함".
        high_threshold_lu: 이 초과면 "트랜션트 폭 큼".
        silence_threshold_lu: LRA가 이 미만이면 스킵 (NO_LRA 케이스 포함).

    Returns:
        INFO Recommendation 또는 None.

    Raises:
        ValueError: 임계가 비합리적(low >= high)이거나 sample_rate가 48000이 아닐 때.
    """
    # LRA를 직접 계산 → evaluate_lra_value로 위임. main.py가 캐시 라우트를
    # 사용할 때는 evaluate_lra_value를 직접 호출해 중복 계산을 피한다.
    lra_value = lra(channel.samples, channel.format.sample_rate)
    return evaluate_lra_value(
        channel.source,
        lra_value,
        low_threshold_lu=low_threshold_lu,
        high_threshold_lu=high_threshold_lu,
        silence_threshold_lu=silence_threshold_lu,
    )


def evaluate_all_channels_lra(
    channels: Iterable[Channel],
    *,
    low_threshold_lu: float = DEFAULT_LOW_THRESHOLD_LU,
    high_threshold_lu: float = DEFAULT_HIGH_THRESHOLD_LU,
    silence_threshold_lu: float = DEFAULT_SILENCE_THRESHOLD_LU,
) -> list[Recommendation]:
    """여러 채널을 일괄 평가. 결정적 순서 보존."""
    out: list[Recommendation] = []
    for channel in channels:
        rec = evaluate_channel_lra(
            channel,
            low_threshold_lu=low_threshold_lu,
            high_threshold_lu=high_threshold_lu,
            silence_threshold_lu=silence_threshold_lu,
        )
        if rec is not None:
            out.append(rec)
    return out
