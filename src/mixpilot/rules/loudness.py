"""채널 RMS dBFS 라우드니스 vs 카테고리 타깃 비교 — 알림 추천 생성.

여기서 "loudness"는 **RMS dBFS** 기반(단순 평균 에너지). 인지 라우드니스
(K-weighted, EBU R128)는 `rules.lufs`에서 다룬다. 차이:
- 이 모듈: 짧은 프레임(수~수십 ms)에서도 측정 가능 → 라이브 처리 루프 직접 사용.
- `rules.lufs`: ~400ms 누적 버퍼 필요 → 오프라인 또는 누적 시점에만 사용.

현재는 INFO 추천만 생성한다. 자동 GAIN_ADJUST는 콘솔의 *현재* 페이더 읽기
기능이 들어온 뒤(ConsoleMetadata OSC 확장) 활성화될 예정.

설계 원칙:
- 순수 함수 — 같은 입력 → 같은 출력.
- 시간·랜덤·환경 변수 의존 없음.
- 타깃·허용 오차는 호출자가 주입(config 직접 import 금지).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from mixpilot.domain import Channel, Recommendation, RecommendationKind
from mixpilot.dsp import rms, to_dbfs

DEFAULT_TOLERANCE_DB: float = 2.0
"""기본 허용 오차 — 라이브 운영에서 ±2dB가 사람 귀에 잡힐 즈음."""

DEFAULT_UNKNOWN_TARGET_DBFS: float = -26.0
"""카테고리 미정·미매칭 채널의 보수적 타깃."""


def evaluate_channel_loudness(
    channel: Channel,
    target_dbfs: float,
    tolerance_db: float = DEFAULT_TOLERANCE_DB,
) -> Recommendation | None:
    """단일 채널의 RMS 라우드니스를 타깃과 비교해 INFO 추천 생성.

    Args:
        channel: 평가할 채널 (1D samples + Source 매핑).
        target_dbfs: 목표 RMS 레벨 (dBFS, 보통 음수).
        tolerance_db: 허용 오차(양수). |delta| <= tolerance면 None.

    Returns:
        INFO Recommendation 또는 None. confidence는 |delta|/10에 비례
        (10dB 이상이면 1.0으로 클램프).

    Raises:
        ValueError: tolerance_db가 음수일 때.
    """
    if tolerance_db < 0:
        raise ValueError(f"tolerance_db must be non-negative, got {tolerance_db}")

    rms_linear = rms(channel.samples)
    measured_dbfs = to_dbfs(rms_linear)
    delta = measured_dbfs - target_dbfs

    if abs(delta) <= tolerance_db:
        return None

    direction = "초과" if delta > 0 else "부족"
    label = channel.source.label or channel.source.category.value
    confidence = min(1.0, abs(delta) / 10.0)

    return Recommendation(
        target=channel.source,
        kind=RecommendationKind.INFO,
        params={
            "measured_dbfs": measured_dbfs,
            "target_dbfs": target_dbfs,
            "delta_db": delta,
        },
        confidence=confidence,
        reason=(
            f"ch{int(channel.source.channel):02d} {label} 라우드니스 "
            f"{abs(delta):.1f}dB {direction} "
            f"(현재 {measured_dbfs:.1f} / 타깃 {target_dbfs:.1f})"
        ),
    )


def evaluate_all_channels(
    channels: Iterable[Channel],
    targets_by_category: Mapping[str, float],
    tolerance_db: float = DEFAULT_TOLERANCE_DB,
    *,
    unknown_fallback_dbfs: float = DEFAULT_UNKNOWN_TARGET_DBFS,
) -> list[Recommendation]:
    """여러 채널을 일괄 평가해 추천 목록 생성.

    결정성: 입력 채널 순서를 그대로 유지하며, 같은 입력 → 같은 출력 시퀀스.

    Args:
        channels: 평가할 채널 iterable.
        targets_by_category: 카테고리 string → 타깃 dBFS.
        tolerance_db: 채널 공통 허용 오차.
        unknown_fallback_dbfs: 카테고리 미매칭 시 폴백 타깃.

    Returns:
        Recommendation 리스트 (빈 리스트 가능).
    """
    recommendations: list[Recommendation] = []
    for channel in channels:
        category = channel.source.category.value
        target = targets_by_category.get(category, unknown_fallback_dbfs)
        rec = evaluate_channel_loudness(channel, target, tolerance_db)
        if rec is not None:
            recommendations.append(rec)
    return recommendations
