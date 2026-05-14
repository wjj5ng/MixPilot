"""Stereo phase correlation 룰 — 모노 다운믹스 안전성 진단.

채널맵에 `stereo_pair_with`가 설정된 채널끼리 매 프레임 phase correlation
계산. correlation이 음의 임계 미만이면 INFO 발화 (자동 액션 없음 — phase
교정은 콘솔/HW 레벨 작업이라 시스템이 자동으로 처리하기 부적합).

라이브 운영 임계:
- < -0.3: 위험. 모노 합산에서 음량/명료도 손실 발생 가능.
- -0.3 ~ +0.5: 정상 stereo.
- > +0.5: 거의 모노. 정보성.

채널이 무음이면 phase가 정의되지 않으므로 evaluate 시 None 반환(스킵).

설계 원칙:
- 순수 함수. 시간·랜덤·환경 변수 의존 없음.
- pair는 양방향 정합성 보장(channel_map이 reverse 자동 채움). 한 페어당 INFO
  한 번만 발화하도록 (left_index < right_index인 페어만 평가).
"""

from __future__ import annotations

from collections.abc import Iterable

from mixpilot.domain import Channel, Recommendation, RecommendationKind
from mixpilot.dsp.phase import UNDEFINED_PHASE, phase_correlation

DEFAULT_WARN_THRESHOLD: float = -0.3
"""이 미만이면 INFO 발화."""

DEFAULT_SILENCE_GUARD: float = 1e-6
"""두 채널 모두 RMS² 합이 이보다 작으면 무음 — 평가 스킵."""


def evaluate_pair_phase(
    left_channel: Channel,
    right_channel: Channel,
    *,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
) -> Recommendation | None:
    """페어 채널의 phase correlation을 평가해 INFO 추천 생성.

    Args:
        left_channel, right_channel: 같은 frame의 채널 페어. samples 길이 동일.
        warn_threshold: 이 값 이하면 INFO. 디폴트 -0.3.

    Returns:
        INFO Recommendation 또는 None.
    """
    corr = phase_correlation(left_channel.samples, right_channel.samples)
    if corr == UNDEFINED_PHASE:
        return None
    if corr > warn_threshold:
        return None

    left = left_channel.source
    right = right_channel.source
    label_l = left.label or left.category.value
    label_r = right.label or right.category.value
    margin = warn_threshold - corr
    confidence = min(1.0, margin / 0.7)  # -1.0(완전 역상)에서 confidence 1.0.
    return Recommendation(
        target=left,
        kind=RecommendationKind.INFO,
        params={
            "phase_correlation": corr,
            "pair_channel": float(int(right.channel)),
            "warn_threshold": warn_threshold,
        },
        confidence=confidence,
        reason=(
            f"ch{int(left.channel):02d}-ch{int(right.channel):02d} "
            f"{label_l} ↔ {label_r} phase 위험 — correlation {corr:+.2f} "
            f"(임계 {warn_threshold:+.2f} 이하; 모노 다운믹스 캔슬 위험)"
        ),
    )


def evaluate_all_phase_pairs(
    channels: Iterable[Channel],
    *,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
) -> list[Recommendation]:
    """모든 stereo 페어를 평가. 페어당 1회만(left_id < right_id).

    `channel.source.stereo_pair_with`가 설정된 채널만 후보. 페어 한 쌍에서
    (left_id < right_id) 인덱스 한쪽만 발화 — 중복 회피.
    """
    by_id: dict[int, Channel] = {int(c.source.channel): c for c in channels}
    out: list[Recommendation] = []
    seen_pairs: set[tuple[int, int]] = set()
    for ch_id, channel in by_id.items():
        partner_id = channel.source.stereo_pair_with
        if partner_id is None:
            continue
        if partner_id not in by_id:
            continue
        pair_key = (min(ch_id, partner_id), max(ch_id, partner_id))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        # 결정성: 항상 left = smaller id.
        left_ch = by_id[pair_key[0]]
        right_ch = by_id[pair_key[1]]
        rec = evaluate_pair_phase(left_ch, right_ch, warn_threshold=warn_threshold)
        if rec is not None:
            out.append(rec)
    return out
