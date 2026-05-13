"""Feedback (하울링) 감지 DSP — Peak-to-Neighbor Ratio (PNR).

라이브 사운드에서 마이크 ↔ 스피커 루프가 특정 주파수에서 공진할 때 하울링이
발생한다. FFT 도메인 시그니처:
1. 특정 bin의 에너지가 이웃 bin들보다 *압도적으로* 높다 (높은 PNR).
2. 그 상태가 N 프레임 이상 *지속*된다 (음악적 짧은 톤은 곧 사라짐).

이 모듈은 **1.단일 프레임 PNR 분석**만 한다 — 순수 함수. 지속성 추적은
`runtime.FeedbackDetector`가 담당.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

DEFAULT_PNR_THRESHOLD_DB: float = 15.0
"""기본 PNR 임계값. 일반적으로 12~20 dB 범위에서 운영."""

DEFAULT_NEIGHBOR_BAND_HZ: float = 200.0
"""기본 이웃 대역폭 — 좌우 ±200 Hz 평균과 비교."""


@dataclass(frozen=True, slots=True)
class FeedbackPeak:
    """FFT에서 검출된 잠재 feedback 주파수."""

    frequency_hz: float
    bin_index: int
    magnitude_dbfs: float
    pnr_db: float


def detect_peak_bins(
    samples: npt.NDArray[np.floating],
    sample_rate: int,
    *,
    pnr_threshold_db: float = DEFAULT_PNR_THRESHOLD_DB,
    min_frequency_hz: float = 100.0,
    max_frequency_hz: float | None = None,
    neighbor_band_hz: float = DEFAULT_NEIGHBOR_BAND_HZ,
) -> list[FeedbackPeak]:
    """단일 프레임에서 PNR 기반 잠재 feedback peaks 추출.

    절차:
    1. Hann 윈도잉 + rFFT.
    2. dBFS 정규화 (윈도우 coherent gain 보정).
    3. 로컬 최댓값만 후보로 추림 — FFT 사이드로브 노이즈 제거.
    4. 각 후보 bin에 대해 ±`neighbor_band_hz` 평균과 비교해 PNR 계산.
       (자기 자신과 ±1 인접 bin은 제외 — FFT 누설 영향 배제.)
    5. PNR > 임계값 + 주파수 범위 통과면 `FeedbackPeak` 추가.

    Args:
        samples: 1D 신호 (float). 최소 4 샘플.
        sample_rate: Hz. > 0.
        pnr_threshold_db: PNR 임계. 더 높을수록 까다로움.
        min_frequency_hz: 이 미만 bin은 무시 (베이스 영역).
        max_frequency_hz: 이 초과 bin은 무시 (None이면 Nyquist까지).
        neighbor_band_hz: 좌우 이웃 평균을 위한 대역폭.

    Returns:
        `FeedbackPeak` 리스트. 빈 리스트 가능. bin_index 오름차순.

    Raises:
        ValueError: 잘못된 입력 형태/크기/sample_rate/임계값.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")
    if pnr_threshold_db < 0:
        raise ValueError(f"pnr_threshold_db must be >= 0, got {pnr_threshold_db}")
    if samples.size < 4:
        return []

    n = int(samples.size)
    window = np.hanning(n)
    window_coherent_gain = float(window.mean())  # ≈ 0.5 for Hann

    spectrum = np.fft.rfft(samples.astype(np.float64) * window)
    # 정규화 — 풀-스케일 사인 amplitude=1이면 그 bin에서 0 dBFS가 되도록.
    magnitudes = np.abs(spectrum) * 2.0 / (n * window_coherent_gain)
    magnitudes_db = 20.0 * np.log10(np.maximum(magnitudes, 1e-12))

    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    # 로컬 최댓값 마스크 — 양 끝점 제외.
    local_max = np.zeros(len(magnitudes_db), dtype=bool)
    if len(magnitudes_db) >= 3:
        local_max[1:-1] = (magnitudes_db[1:-1] > magnitudes_db[:-2]) & (
            magnitudes_db[1:-1] > magnitudes_db[2:]
        )

    freq_mask = freqs >= min_frequency_hz
    if max_frequency_hz is not None:
        freq_mask &= freqs <= max_frequency_hz

    candidates = np.where(local_max & freq_mask)[0]

    bin_resolution_hz = sample_rate / n
    neighbor_bins = max(1, int(neighbor_band_hz / bin_resolution_hz))

    peaks: list[FeedbackPeak] = []
    for bin_idx in candidates:
        start = max(0, int(bin_idx) - neighbor_bins)
        end = min(len(magnitudes_db), int(bin_idx) + neighbor_bins + 1)
        neighbor_idx = np.arange(start, end)
        # 자기 자신 + ±1 인접 bin 제외 (FFT 누설).
        neighbor_idx = neighbor_idx[
            (neighbor_idx != bin_idx) & (np.abs(neighbor_idx - bin_idx) > 1)
        ]
        if neighbor_idx.size == 0:
            continue
        neighbor_mean_db = float(magnitudes_db[neighbor_idx].mean())
        pnr_db = float(magnitudes_db[bin_idx]) - neighbor_mean_db
        if pnr_db > pnr_threshold_db:
            peaks.append(
                FeedbackPeak(
                    frequency_hz=float(freqs[bin_idx]),
                    bin_index=int(bin_idx),
                    magnitude_dbfs=float(magnitudes_db[bin_idx]),
                    pnr_db=pnr_db,
                )
            )

    return peaks
