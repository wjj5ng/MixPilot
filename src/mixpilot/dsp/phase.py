"""Phase correlation — 두 채널(보통 L/R) 사이의 정규화 상관 계수.

스테레오 페어가 *모노 다운믹스* 됐을 때 어떻게 들리는지를 예측하는 지표.
운영 환경에서 PA·녹화·송출 어디든 모노 합산되는 경로가 있으므로 phase
문제는 라이브에서 자주 발생하는 사고 원인.

알고리즘 (Pearson correlation):

    r = sum(L*R) / sqrt(sum(L²) * sum(R²))

DC를 제거하지 않은 형태 — 오디오 신호는 보통 평균 0이고 DC 컴포넌트는 제거
대상이 아님(모노 합산에서 그대로 누적되므로). 표준 라이브 미터의 phase
correlation meter도 동일 방식.

해석:

| r | 의미 |
|---|---|
| +1.0 | 완전 동상(코히어런트) — 모노 합산 시 +6 dB |
| 0 | 무상관(전형적 stereo) — 모노 합산 정상 |
| -1.0 | 완전 역상 — 모노 합산 시 *침묵* |

라이브 임계 (운영 컨벤션):
- > +0.5: 본질적으로 모노. mid/side 보강 검토.
- -0.3 ~ +0.5: 정상 stereo.
- < -0.3: 위험. 모노 다운믹스 경로에서 음량/명료도 손실. 즉시 점검.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

UNDEFINED_PHASE: float = 0.0
"""한쪽 채널이 무음(zero variance)이거나 신호가 너무 짧을 때의 디폴트.

엄밀히는 *정의되지 않음*이지만 운영상 "phase 문제 없음(0)"으로 약속해
임계 룰을 단순화한다. 호출자는 함께 RMS도 확인하면 무음 케이스 식별 가능.
"""


def phase_correlation(
    left: npt.NDArray[np.floating],
    right: npt.NDArray[np.floating],
) -> float:
    """1D 두 신호 사이의 phase correlation (Pearson, DC 제거 없음).

    Args:
        left, right: 1D float ndarray. 길이 동일. 길이 >= 2.

    Returns:
        [-1.0, +1.0] 범위 float. 한쪽 채널이 사실상 무음(L²·R² 합이 매우
        작으면) `UNDEFINED_PHASE` 반환.

    Raises:
        ValueError: 1D 아님 / 길이 불일치 / 빈 배열.
    """
    if left.ndim != 1 or right.ndim != 1:
        raise ValueError(
            f"both inputs must be 1D, got left.shape={left.shape}, "
            f"right.shape={right.shape}"
        )
    if left.size != right.size:
        raise ValueError(f"length mismatch: left={left.size}, right={right.size}")
    if left.size == 0:
        raise ValueError("inputs must not be empty")

    a = left.astype(np.float64)
    b = right.astype(np.float64)
    num = float(np.sum(a * b))
    denom_sq = float(np.sum(a * a)) * float(np.sum(b * b))
    if denom_sq < 1e-20:
        return UNDEFINED_PHASE
    return num / math.sqrt(denom_sq)


def phase_correlation_pair(
    samples_2d: npt.NDArray[np.floating],
    left_index: int,
    right_index: int,
) -> float:
    """다채널 신호(shape (frames, channels))에서 두 채널의 phase correlation.

    `left_index`·`right_index`는 *0-based* numpy 인덱스. 호출자가 채널 번호
    (1-based M32 컨벤션)에서 변환 책임.
    """
    if samples_2d.ndim != 2:
        raise ValueError(
            f"samples must be 2D (frames, channels), got shape {samples_2d.shape}"
        )
    n_channels = samples_2d.shape[1]
    if not (0 <= left_index < n_channels):
        raise ValueError(f"left_index {left_index} out of range [0, {n_channels})")
    if not (0 <= right_index < n_channels):
        raise ValueError(f"right_index {right_index} out of range [0, {n_channels})")
    if left_index == right_index:
        # 같은 채널끼리는 항상 +1 (자기 상관).
        return 1.0
    return phase_correlation(samples_2d[:, left_index], samples_2d[:, right_index])
