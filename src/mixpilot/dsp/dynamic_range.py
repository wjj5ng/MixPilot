"""Dynamic Range — crest factor (peak ÷ RMS) in dB.

라이브 음향에서 "다이내믹 레인지"는 보통 한 프레임의 peak와 RMS의 비율(crest
factor)을 dB로 표현한 값을 의미한다. 신호가 압축될수록 이 값이 작아지므로
콤프레서 과도 적용·라우드니스 워 단서로 사용 가능.

EBU R128 LRA(Loudness Range)와는 *다른* 메트릭이다. LRA는 곡 전체의 단기
LUFS 분포(95% - 10%)이며 별도 ADR이 필요한 큰 구현. 여기서는 라이브 운영에
즉시 쓸 수 있는 프레임 단위 crest factor만 제공.

표준 신호의 기대값:

| 신호 | DR (dB) |
|---|---|
| DC | 0 |
| 사인파 | 20·log10(√2) ≈ 3.01 |
| 무음 | 0 (정의상 0/0이지만 합리적 디폴트) |
| 가우시안 화이트 노이즈 | ≈ 11~13 (분포·길이 의존) |
| 임펄스 | 매우 큼 (peak=1, RMS≈0) → 길이 의존 |
| 압축된 commercial 음악 | 4~7 |
| 무압축 오케스트라 | > 15 |
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

# RMS가 이 값보다 작으면 신호는 무음 — DR 계산 분모로 사용 불가. 0.0 반환.
_RMS_SILENCE_THRESHOLD: float = 1e-10


def dynamic_range_db(samples: npt.NDArray[np.floating]) -> float:
    """1D 신호의 dynamic range (crest factor in dB).

    `DR_dB = 20 · log10(peak ÷ RMS)`.

    peak는 `max|samples|`, RMS는 `sqrt(mean(samples²))`.

    Args:
        samples: 1D ndarray. 길이 >= 1.

    Returns:
        DR (dB, >= 0). 무음 신호는 0.0 반환 — 정의상 0/0이지만 운영상
        "DR이 없음"을 0으로 표현하는 게 합리적.

    Raises:
        ValueError: 1D가 아니거나 빈 배열.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if samples.size == 0:
        raise ValueError("samples must not be empty")

    abs_samples = np.abs(samples.astype(np.float64))
    pk = float(abs_samples.max())
    rms_val = float(math.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms_val < _RMS_SILENCE_THRESHOLD or pk < _RMS_SILENCE_THRESHOLD:
        return 0.0
    return 20.0 * math.log10(pk / rms_val)


def dynamic_range_channels(
    samples: npt.NDArray[np.floating],
) -> npt.NDArray[np.float64]:
    """다채널 신호의 채널별 dynamic range.

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
    data = samples.astype(np.float64)
    peaks = np.abs(data).max(axis=0)
    rms_vals = np.sqrt(np.mean(data**2, axis=0))
    out = np.zeros(data.shape[1], dtype=np.float64)
    mask = (rms_vals >= _RMS_SILENCE_THRESHOLD) & (peaks >= _RMS_SILENCE_THRESHOLD)
    out[mask] = 20.0 * np.log10(peaks[mask] / rms_vals[mask])
    return out
