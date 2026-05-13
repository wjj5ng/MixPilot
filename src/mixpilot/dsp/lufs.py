"""LUFS (Loudness Units relative to Full Scale) — EBU R128 통합 라우드니스.

pyloudnorm 위에 얇은 래퍼. K-weighting + 게이팅 적용. 정확성은 pyloudnorm에
위임하고 여기서는 *결정성*과 도메인-친화 인터페이스, 무음 안전 처리에 집중.

라이브 사용 시 호출자가 최소 ~400ms 분량의 신호를 모아 전달해야 한다.
미만이면 ValueError를 raise — pyloudnorm이 의미 있는 측정을 못 함.

채널 처리 방침: 각 채널을 *독립 mono*로 분석 (BS.1770의 LRC/Ls/Rs 가중치는
M32 라이브 채널과 정합하지 않음).
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
import pyloudnorm as pyln

# 무음·게이트 차단 시 pyloudnorm이 -inf를 반환할 수 있어 안전 floor로 대체.
# EBU R128 절대 게이트가 -70 LUFS이므로 그 아래는 의미 없음.
SILENCE_FLOOR_LUFS: float = -70.0

# EBU R128 측정에 필요한 최소 신호 길이 (1 block = 400ms).
MIN_DURATION_SECONDS: float = 0.4


def lufs_integrated(samples: npt.NDArray[np.floating], sample_rate: int) -> float:
    """1D 신호의 integrated LUFS (EBU R128).

    K-weighting + 절대 게이트(-70 LUFS) + 상대 게이트(-10 LU) 적용.

    Args:
        samples: 1D ndarray. 길이가 `MIN_DURATION_SECONDS * sample_rate` 이상.
        sample_rate: 샘플레이트(Hz). > 0.

    Returns:
        LUFS 값. 무음·게이트 차단 시 `SILENCE_FLOOR_LUFS`.

    Raises:
        ValueError: 1D가 아닐 때, sample_rate가 양수가 아닐 때, 신호가
            EBU R128 최소 길이 미만일 때.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")

    duration = samples.size / sample_rate
    if duration < MIN_DURATION_SECONDS:
        raise ValueError(
            f"signal too short for LUFS: {duration * 1000:.1f}ms "
            f"(minimum {MIN_DURATION_SECONDS * 1000:.0f}ms required by EBU R128)"
        )

    meter = pyln.Meter(sample_rate)
    loudness = float(meter.integrated_loudness(samples.astype(np.float64)))

    # 무음·과도 무신호는 -inf 또는 매우 낮은 값 → 안전 floor.
    if not math.isfinite(loudness) or loudness < SILENCE_FLOOR_LUFS:
        return SILENCE_FLOOR_LUFS
    return loudness


def lufs_channels(
    samples: npt.NDArray[np.floating], sample_rate: int
) -> npt.NDArray[np.float64]:
    """다채널 신호의 채널별 integrated LUFS.

    각 채널을 독립 mono로 처리 — surround 가중치 미적용.

    Args:
        samples: 2D ndarray, shape (frames, channels). 각 채널 길이
            `MIN_DURATION_SECONDS * sample_rate` 이상.
        sample_rate: Hz. > 0.

    Returns:
        1D float64 ndarray, shape (channels,).

    Raises:
        ValueError: 2D가 아니거나, 빈 배열, sample_rate 비양수, 길이 부족.
    """
    if samples.ndim != 2:
        raise ValueError(
            f"samples must be 2D (frames, channels), got shape {samples.shape}"
        )
    if samples.size == 0:
        raise ValueError("samples must not be empty")

    num_channels = int(samples.shape[1])
    result = np.empty(num_channels, dtype=np.float64)
    for idx in range(num_channels):
        result[idx] = lufs_integrated(samples[:, idx], sample_rate)
    return result
