"""Peak / True Peak 분석.

- **Sample peak**: 신호 도메인의 최댓값(`max |samples|`). 빠르고 결정적.
- **True peak**: 4x 오버샘플링 후 *inter-sample* 최댓값. ITU-R BS.1770-4 권장.
  DAC가 출력 가능한 *연속 신호*의 진폭을 반영하기 때문에 디지털 클리핑
  예방·헤드룸 분석에 sample peak보다 정확하다.

모두 순수 함수. 같은 입력 → 같은 출력. 채널별 처리는 `*_channels` 버전.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy import signal

DEFAULT_TRUE_PEAK_OVERSAMPLE: int = 4
"""ITU-R BS.1770-4 권고 — 4x 오버샘플링."""


def peak(samples: npt.NDArray[np.floating]) -> float:
    """1D 신호의 sample peak — `max |samples|`.

    Args:
        samples: 1D ndarray. 길이 >= 1.

    Returns:
        Sample peak (>= 0). 단위는 입력과 동일 (float 오디오면 선형 dimensionless).

    Raises:
        ValueError: 1D가 아니거나 빈 배열.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if samples.size == 0:
        raise ValueError("samples must not be empty")
    return float(np.abs(samples.astype(np.float64)).max())


def peak_channels(
    samples: npt.NDArray[np.floating],
) -> npt.NDArray[np.float64]:
    """다채널 신호의 채널별 sample peak.

    Args:
        samples: 2D ndarray, shape (frames, channels). 양 축 모두 > 0.

    Returns:
        1D float64 ndarray, shape (channels,).

    Raises:
        ValueError: 2D가 아니거나 빈 배열.
    """
    if samples.ndim != 2:
        raise ValueError(
            f"samples must be 2D (frames, channels), got shape {samples.shape}"
        )
    if samples.size == 0:
        raise ValueError("samples must not be empty")
    return np.abs(samples.astype(np.float64)).max(axis=0)


def true_peak(
    samples: npt.NDArray[np.floating],
    *,
    oversample: int = DEFAULT_TRUE_PEAK_OVERSAMPLE,
) -> float:
    """1D 신호의 true peak — 오버샘플링 후 inter-sample 최댓값.

    `scipy.signal.resample_poly`로 `oversample`배 업샘플링 (Kaiser-window FIR).
    결과는 항상 *sample peak 이상*. `oversample=1`이면 sample peak와 동일.

    Args:
        samples: 1D ndarray. 길이 >= 1.
        oversample: 업샘플링 배수 (1 이상). 기본 4 (BS.1770-4 권고).

    Returns:
        True peak (>= 0).

    Raises:
        ValueError: 1D가 아니거나 빈 배열, oversample < 1.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if samples.size == 0:
        raise ValueError("samples must not be empty")
    if oversample < 1:
        raise ValueError(f"oversample must be >= 1, got {oversample}")
    if oversample == 1:
        return peak(samples)
    upsampled = signal.resample_poly(samples.astype(np.float64), up=oversample, down=1)
    return float(np.abs(upsampled).max())


def true_peak_channels(
    samples: npt.NDArray[np.floating],
    *,
    oversample: int = DEFAULT_TRUE_PEAK_OVERSAMPLE,
) -> npt.NDArray[np.float64]:
    """다채널 신호의 채널별 true peak.

    Args:
        samples: 2D ndarray, shape (frames, channels). 양 축 > 0.
        oversample: 업샘플링 배수.

    Returns:
        1D float64 ndarray, shape (channels,).

    Raises:
        ValueError: 2D가 아니거나 빈 배열, oversample < 1.
    """
    if samples.ndim != 2:
        raise ValueError(
            f"samples must be 2D (frames, channels), got shape {samples.shape}"
        )
    if samples.size == 0:
        raise ValueError("samples must not be empty")
    if oversample < 1:
        raise ValueError(f"oversample must be >= 1, got {oversample}")
    if oversample == 1:
        return peak_channels(samples)
    upsampled = signal.resample_poly(
        samples.astype(np.float64), up=oversample, down=1, axis=0
    )
    return np.abs(upsampled).max(axis=0)
