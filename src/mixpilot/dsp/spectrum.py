"""옥타브 밴드 스펙트럼 — 라이브 운영자가 채널별 톤 밸런스를 한눈에 확인.

8개 옥타브 밴드(125 Hz ~ 16 kHz 중심)의 dB 레벨을 추출. 라이브 디스플레이용
*근사*이며 정밀한 정량 분석용(BS.1770-4·EBU 등)이 아님 — Hann 윈도잉으로
충분한 leakage 억제, 전체 SNR이 시각적으로 의미 있도록 정규화.

8개 옥타브 중심:
- 125, 250, 500, 1000, 2000, 4000, 8000, 16000 Hz

각 밴드 폭은 ±1/√2 fc → (88-177), (177-354), ... 옥타브 정의 표준.

레벨 정규화:
- 풀-스케일 사인 (amplitude 1, RMS 1/√2)이 본인 밴드에서 약 -3 dBFS로 표시.
- Hann leakage로 인접 밴드에도 약간 새지만 시각 영향 작음.
- 짧은 프레임(예: 512 샘플 @ 48 kHz)에서 저주파 밴드 bin 부족으로 부정확 —
  운영자에게 *상대 변화* 추적용으로 충분.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from .rms import SILENCE_FLOOR_DBFS

OCTAVE_CENTERS_HZ: tuple[float, ...] = (
    125.0,
    250.0,
    500.0,
    1000.0,
    2000.0,
    4000.0,
    8000.0,
    16000.0,
)
"""표시 옥타브 밴드 중심 주파수. 모듈 외부에서도 카운트·라벨 정렬에 사용."""

# Hann window coherent gain ≈ 0.5. 풀-스케일 사인의 본인 bin 정점이
# N * coherent_gain / 2 = N/4. 이를 정규화해 dBFS RMS scale로 매핑.
_HANN_COHERENT_GAIN: float = 0.5
_HANN_COHERENT_GAIN_SQ: float = _HANN_COHERENT_GAIN**2  # = 0.25
_SQRT_TWO: float = math.sqrt(2.0)


def octave_band_levels_dbfs(
    samples: npt.NDArray[np.floating], sample_rate: int
) -> list[float]:
    """8개 옥타브 밴드의 근사 dBFS 레벨 — 라이브 표시용.

    Args:
        samples: 1D 신호. 길이 < 4면 모든 밴드 SILENCE_FLOOR_DBFS.
        sample_rate: Hz. > 0.

    Returns:
        `OCTAVE_CENTERS_HZ`와 같은 길이의 list. 각 원소는 해당 옥타브의 dBFS
        근사. 정의된 bin이 없는 밴드는 `SILENCE_FLOOR_DBFS`.

    Raises:
        ValueError: 1D가 아니거나 sample_rate가 비양수.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")

    n = int(samples.size)
    n_bands = len(OCTAVE_CENTERS_HZ)
    if n < 4:
        return [SILENCE_FLOOR_DBFS] * n_bands

    window = np.hanning(n)
    windowed = samples.astype(np.float64) * window
    spectrum_sq = np.abs(np.fft.rfft(windowed)) ** 2
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    # 정규화: 한 옥타브에 풀-스케일 사인이 있을 때 RMS²(=0.5)와 일치하도록.
    # rFFT 한쪽 스펙트럼이므로 *2, Hann coherent gain² 보정.
    scale = 2.0 / (n * n * _HANN_COHERENT_GAIN_SQ)

    bands: list[float] = []
    for fc in OCTAVE_CENTERS_HZ:
        f_low = fc / _SQRT_TWO
        f_high = fc * _SQRT_TWO
        mask = (freqs >= f_low) & (freqs < f_high)
        if not mask.any():
            bands.append(SILENCE_FLOOR_DBFS)
            continue
        band_power = float(np.sum(spectrum_sq[mask])) * scale
        if band_power <= 1e-12:
            bands.append(SILENCE_FLOOR_DBFS)
        else:
            bands.append(10.0 * math.log10(band_power))
    return bands
