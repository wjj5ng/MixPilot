"""EBU R128 / EBU Tech 3342 Loudness Range (LRA).

LRA는 곡 전체의 단기 LUFS 분포를 LU 단위로 요약한다. 라이브 운영에서는
*압축 정도* 가시화에 사용:

- LRA < 5 LU: 라우드니스 워 의심 (commercial radio·broadcasting).
- LRA 5~15 LU: 일반 음악·연설.
- LRA > 15 LU: 무압축 콘텐츠 (오케스트라, 라이브 다이내믹).

ADR-0009 참조. 핵심 결정:

- K-weighting 계수는 48 kHz 전용 하드코드. 다른 rate는 ValueError.
- 3초 블록 / 1초 hop으로 short-term LUFS 추출.
- 절대 게이트(-70 LUFS) + 상대 게이트(power-mean - 20 LU).
- LRA = P95 - P10 (numpy.percentile linear 보간).
- 입력 < 3초이면 ValueError, 게이트로 모두 제거되면 0.0.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
from scipy import signal as scipy_signal

# EBU R128 LRA 파라미터.
BLOCK_SECONDS: float = 3.0
"""Short-term loudness 블록 길이 (EBU R128 §4.1)."""

HOP_SECONDS: float = 1.0
"""블록 간 이동 간격 — EBU Tech 3342 §3.1: 66.7% 오버랩."""

ABSOLUTE_GATE_LUFS: float = -70.0
"""절대 게이트 — 이 미만 블록은 무조건 제외 (EBU R128 §4.2)."""

RELATIVE_GATE_LU: float = -20.0
"""상대 게이트 — power-mean으로부터 이만큼 아래는 제외 (EBU Tech 3342 §3.3)."""

MIN_DURATION_SECONDS: float = BLOCK_SECONDS
"""LRA 계산에 필요한 최소 신호 길이 — 단일 블록도 못 만들면 의미 없음."""

NO_LRA: float = 0.0
"""모든 블록이 게이팅으로 제거됐을 때의 반환값. "다이내믹 없음"의 약속."""

_SUPPORTED_SAMPLE_RATE: int = 48000
"""ADR-0009: M32 USB가 48 kHz 고정이므로 본 모듈은 48 kHz만 지원."""

# BS.1770-4 reference K-weighting filter (48 kHz).
# 2-section SOS: [b0, b1, b2, a0, a1, a2].
# Pre-filter(high-shelf ~1.5 kHz, +4 dB) + RLB(high-pass ~38 Hz).
_K_FILTER_SOS_48000 = np.array(
    [
        # Pre-filter (high-shelf)
        [
            1.53512485958697,
            -2.69169618940638,
            1.19839281085285,
            1.0,
            -1.69065929318241,
            0.73248077421585,
        ],
        # RLB (high-pass)
        [
            1.0,
            -2.0,
            1.0,
            1.0,
            -1.99004745483398,
            0.99007225036621,
        ],
    ],
    dtype=np.float64,
)


def _k_weight(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate != _SUPPORTED_SAMPLE_RATE:
        raise ValueError(
            f"LRA K-weighting supports only {_SUPPORTED_SAMPLE_RATE} Hz, "
            f"got {sample_rate}"
        )
    return scipy_signal.sosfilt(_K_FILTER_SOS_48000, samples.astype(np.float64))


def _short_term_lufs(k_filtered_block: np.ndarray) -> float:
    """단일 블록의 short-term LUFS — BS.1770-4 §3.1."""
    mean_square = float(np.mean(k_filtered_block**2))
    if mean_square <= 0.0:
        return -math.inf
    return -0.691 + 10.0 * math.log10(mean_square)


def _power_mean_db(values_db: list[float]) -> float:
    """EBU Tech 3342 §3.3 power-mean — 에너지 평균을 dB로 환산.

    log_10(mean(10^(L/10))) * 10. 산술 평균 대신 사용해야 표준 준수.
    """
    energies = [10.0 ** (v / 10.0) for v in values_db]
    return 10.0 * math.log10(sum(energies) / len(energies))


def lra(samples: npt.NDArray[np.floating], sample_rate: int) -> float:
    """EBU R128 / EBU Tech 3342 Loudness Range (LU).

    Args:
        samples: 1D 신호. 길이 >= 3초 (= 3 * sample_rate 샘플).
        sample_rate: 48000만 지원 (ADR-0009).

    Returns:
        LRA (LU). 음수가 될 수 없음(P95 >= P10). 모든 블록이 게이팅으로
        제거되면 0.0 (NO_LRA).

    Raises:
        ValueError: 1D가 아니거나 sample_rate가 48000이 아니거나 입력이 3초 미만.
    """
    if samples.ndim != 1:
        raise ValueError(f"samples must be 1D, got shape {samples.shape}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")
    duration = samples.size / sample_rate
    if duration < MIN_DURATION_SECONDS:
        raise ValueError(
            f"signal too short for LRA: {duration * 1000:.1f}ms < "
            f"{MIN_DURATION_SECONDS * 1000:.1f}ms"
        )

    # K-weight 전체 신호 한 번 (블록마다 다시 필터링하면 epoch 효과 발생).
    k_signal = _k_weight(samples, sample_rate)

    block_size = int(BLOCK_SECONDS * sample_rate)
    hop_size = int(HOP_SECONDS * sample_rate)

    short_term: list[float] = []
    last_start = k_signal.size - block_size
    if last_start < 0:
        return NO_LRA
    for start in range(0, last_start + 1, hop_size):
        block = k_signal[start : start + block_size]
        lufs = _short_term_lufs(block)
        if math.isfinite(lufs):
            short_term.append(lufs)

    if not short_term:
        return NO_LRA

    # 절대 게이트 — -70 LUFS 미만 제거.
    above_abs = [v for v in short_term if v >= ABSOLUTE_GATE_LUFS]
    if not above_abs:
        return NO_LRA

    # 상대 게이트 — power-mean - 20 LU.
    relative_gate = _power_mean_db(above_abs) + RELATIVE_GATE_LU
    survivors = [v for v in above_abs if v >= relative_gate]
    if not survivors:
        return NO_LRA

    # P95 - P10.
    p10 = float(np.percentile(survivors, 10))
    p95 = float(np.percentile(survivors, 95))
    return p95 - p10
