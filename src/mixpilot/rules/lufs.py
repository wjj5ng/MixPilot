"""LUFS 기반 라우드니스 추천 — EBU R128 측정.

`rules.loudness`(RMS dBFS 기반)와 짝을 이룬다. 차이:
- RMS 룰: 짧은 프레임(수~수십 ms)에서도 즉시 측정. 라이브 처리 루프에 직접 사용.
- LUFS 룰: K-weighted 인지 라우드니스. 측정에 최소 ~400ms 신호가 필요해
  라이브 프레임 단위로는 사용 못 하고 *누적 버퍼* 또는 오프라인 분석에서 적용.

신호 길이 검증·결정성·무음 처리는 `dsp.lufs_integrated`에 위임된다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from mixpilot.domain import Channel, Recommendation, RecommendationKind
from mixpilot.dsp import lufs_integrated

DEFAULT_TOLERANCE_LU: float = 2.0
"""기본 허용 오차. LUFS 차이는 LU(Loudness Units)."""

DEFAULT_UNKNOWN_TARGET_LUFS: float = -23.0
"""카테고리 미정·미매칭 채널의 보수적 LUFS 목표(EBU R128 broadcast)."""


def evaluate_channel_lufs(
    channel: Channel,
    target_lufs: float,
    tolerance_lu: float = DEFAULT_TOLERANCE_LU,
) -> Recommendation | None:
    """단일 채널의 integrated LUFS를 타깃과 비교해 INFO 추천 생성.

    Args:
        channel: 평가할 채널. samples는 `dsp.lufs.MIN_DURATION_SECONDS`(~400ms)
            이상이어야 함. 미만이면 `lufs_integrated`가 ValueError를 raise.
        target_lufs: 목표 LUFS(보통 음수).
        tolerance_lu: 허용 오차(LU, 양수). |delta| <= tolerance면 None.

    Returns:
        INFO Recommendation 또는 None. confidence는 |delta|/10에 비례
        (10 LU 이상이면 1.0으로 클램프).

    Raises:
        ValueError: tolerance_lu가 음수이거나, 채널 신호가 LUFS 최소 길이 미만.
    """
    if tolerance_lu < 0:
        raise ValueError(f"tolerance_lu must be non-negative, got {tolerance_lu}")

    measured = lufs_integrated(channel.samples, channel.format.sample_rate)
    delta = measured - target_lufs

    if abs(delta) <= tolerance_lu:
        return None

    direction = "초과" if delta > 0 else "부족"
    label = channel.source.label or channel.source.category.value
    confidence = min(1.0, abs(delta) / 10.0)

    return Recommendation(
        target=channel.source,
        kind=RecommendationKind.INFO,
        params={
            "measured_lufs": measured,
            "target_lufs": target_lufs,
            "delta_lu": delta,
        },
        confidence=confidence,
        reason=(
            f"ch{int(channel.source.channel):02d} {label} 라우드니스 "
            f"{abs(delta):.1f} LU {direction} "
            f"(현재 {measured:.1f} LUFS / 타깃 {target_lufs:.1f} LUFS)"
        ),
    )


def evaluate_all_channels_lufs(
    channels: Iterable[Channel],
    targets_by_category: Mapping[str, float],
    tolerance_lu: float = DEFAULT_TOLERANCE_LU,
    *,
    unknown_fallback_lufs: float = DEFAULT_UNKNOWN_TARGET_LUFS,
) -> list[Recommendation]:
    """여러 채널 일괄 평가 — 카테고리별 LUFS 타깃 매핑.

    결정성: 입력 채널 순서를 유지하며 같은 입력 → 같은 출력 시퀀스.
    """
    recommendations: list[Recommendation] = []
    for channel in channels:
        category = channel.source.category.value
        target = targets_by_category.get(category, unknown_fallback_lufs)
        rec = evaluate_channel_lufs(channel, target, tolerance_lu)
        if rec is not None:
            recommendations.append(rec)
    return recommendations
