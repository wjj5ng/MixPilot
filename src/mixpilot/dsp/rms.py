"""RMS (Root Mean Square) 분석.

순수 함수 — 외부 상태·시간·랜덤 없음. ARCHITECTURE.md "결정성 보장" 준수.
입력은 1D 또는 2D ndarray, 출력은 단위 일관성을 위해 항상 float64.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

# 무음 처리 — log(0) = -inf 대신 안전한 최솟값(dBFS).
# ARCHITECTURE.md "수치 안정성" 원칙.
SILENCE_FLOOR_DBFS: float = -120.0


def rms(samples: npt.NDArray[np.floating]) -> float:
    """1D 신호의 RMS 값.

    RMS = sqrt(mean(samples**2)).

    Args:
        samples: 1D ndarray. 길이 >= 1.

    Returns:
        RMS 값 (>= 0). 단위는 입력과 동일(float 오디오면 선형 dimensionless).

    Raises:
        ValueError: 빈 배열이거나 1D가 아닐 때.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if samples.size == 0:
        raise ValueError("samples must not be empty")
    # float64로 캐스팅 — float32 누적 오차·overflow 방지.
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def rms_channels(samples: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
    """다채널 신호의 채널별 RMS.

    32채널(M32) 시나리오의 기본 진입점. numpy axis 연산으로 한 번에 처리.

    Args:
        samples: 2D ndarray, shape (frames, channels). 두 축 모두 > 0.

    Returns:
        1D float64 ndarray, shape (channels,).

    Raises:
        ValueError: 2D가 아니거나 빈 배열일 때.
    """
    if samples.ndim != 2:
        raise ValueError(
            f"samples must be 2D (frames, channels), got shape {samples.shape}"
        )
    if samples.size == 0:
        raise ValueError("samples must not be empty")
    return np.sqrt(np.mean(samples.astype(np.float64) ** 2, axis=0))


def to_dbfs(linear: float, ref: float = 1.0) -> float:
    """선형 amplitude를 dBFS(decibels relative to full scale)로 변환.

    dBFS = 20 * log10(linear / ref).

    무음(0 이하)은 SILENCE_FLOOR_DBFS로 안전 처리 — log(0) = -inf 방지.

    Args:
        linear: 선형 amplitude(RMS, peak 등). 음수 입력도 무음 취급.
        ref: 풀-스케일 기준. float 오디오는 1.0.

    Returns:
        dBFS 값. 무음은 SILENCE_FLOOR_DBFS.

    Raises:
        ValueError: ref가 0 이하일 때.
    """
    if ref <= 0:
        raise ValueError(f"ref must be positive, got {ref}")
    if linear <= 0:
        return SILENCE_FLOOR_DBFS
    return 20.0 * math.log10(linear / ref)
