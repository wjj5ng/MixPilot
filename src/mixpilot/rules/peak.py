"""채널 True Peak 클리핑·헤드룸 룰 — DSP 결과를 추천으로 매핑.

True peak가 임계 이상으로 올라가면 INFO 추천을 생성한다. 라이브 운영자는
이 알림을 보고 *수동으로* 게인을 내리거나 콘솔에서 처리한다 — 자동 게인
감쇠는 별도 ADR(예정) 후 활성화.

설계 원칙:
- 순수 함수 — 같은 입력 → 같은 출력. 시간·랜덤·환경 의존 없음.
- domain.Channel + dsp.true_peak만 사용. config·infra·api 의존 금지.
"""

from __future__ import annotations

from collections.abc import Iterable

from mixpilot.domain import Channel, Recommendation, RecommendationKind
from mixpilot.dsp import DEFAULT_TRUE_PEAK_OVERSAMPLE, to_dbfs, true_peak

DEFAULT_HEADROOM_THRESHOLD_DBFS: float = -1.0
"""기본 헤드룸 임계. 이 위(이상)의 true peak는 클리핑 위험으로 본다."""

CLIPPING_THRESHOLD_DBFS: float = 0.0
"""디지털 풀-스케일 = 0 dBFS. 이 이상이면 사실상 클리핑."""


def evaluate_channel_peak(
    channel: Channel,
    *,
    headroom_threshold_dbfs: float = DEFAULT_HEADROOM_THRESHOLD_DBFS,
    oversample: int = DEFAULT_TRUE_PEAK_OVERSAMPLE,
) -> Recommendation | None:
    """단일 채널의 true peak를 임계와 비교 → INFO Recommendation.

    Args:
        channel: 평가할 채널.
        headroom_threshold_dbfs: 이 미만이면 None. 이상이면 INFO 발화.
        oversample: true peak 오버샘플링 배수. `dsp.true_peak` 참조.

    Returns:
        INFO Recommendation (`measured_tp_dbfs` 기준 confidence 부여) 또는 None.
        - `>= CLIPPING_THRESHOLD_DBFS`: confidence 1.0, reason "클리핑".
        - `[headroom_threshold, 0)`: 선형 보간 confidence [0.5, 1.0], "헤드룸 부족".

    Raises:
        ValueError: oversample < 1.
    """
    if oversample < 1:
        raise ValueError(f"oversample must be >= 1, got {oversample}")

    measured_tp = true_peak(channel.samples, oversample=oversample)
    measured_tp_dbfs = to_dbfs(measured_tp)

    if measured_tp_dbfs < headroom_threshold_dbfs:
        return None

    is_clipping = measured_tp_dbfs >= CLIPPING_THRESHOLD_DBFS
    label = channel.source.label or channel.source.category.value

    if is_clipping:
        confidence = 1.0
        descr = "클리핑"
    else:
        # 선형 보간: threshold에서 0.5, 0 dBFS에서 1.0.
        span = CLIPPING_THRESHOLD_DBFS - headroom_threshold_dbfs
        ratio = (measured_tp_dbfs - headroom_threshold_dbfs) / span
        confidence = 0.5 + 0.5 * ratio
        descr = "헤드룸 부족"

    headroom_db = CLIPPING_THRESHOLD_DBFS - measured_tp_dbfs

    return Recommendation(
        target=channel.source,
        kind=RecommendationKind.INFO,
        params={
            "true_peak_dbfs": measured_tp_dbfs,
            "headroom_db": headroom_db,
            "threshold_dbfs": headroom_threshold_dbfs,
            "is_clipping": 1.0 if is_clipping else 0.0,
        },
        confidence=confidence,
        reason=(
            f"ch{int(channel.source.channel):02d} {label} {descr} — "
            f"true peak {measured_tp_dbfs:+.1f} dBFS "
            f"(헤드룸 {headroom_db:+.1f} dB)"
        ),
    )


def evaluate_all_channels_peak(
    channels: Iterable[Channel],
    *,
    headroom_threshold_dbfs: float = DEFAULT_HEADROOM_THRESHOLD_DBFS,
    oversample: int = DEFAULT_TRUE_PEAK_OVERSAMPLE,
) -> list[Recommendation]:
    """여러 채널 일괄 평가. 입력 순서 유지(다른 채널 룰과 동일 컨벤션).

    Args:
        channels: 평가할 채널 iterable.
        headroom_threshold_dbfs: 채널 공통 임계.
        oversample: true peak 오버샘플링 배수.

    Returns:
        Recommendation 리스트. 임계 미만 채널은 자동 제외.
    """
    recommendations: list[Recommendation] = []
    for channel in channels:
        rec = evaluate_channel_peak(
            channel,
            headroom_threshold_dbfs=headroom_threshold_dbfs,
            oversample=oversample,
        )
        if rec is not None:
            recommendations.append(rec)
    return recommendations
