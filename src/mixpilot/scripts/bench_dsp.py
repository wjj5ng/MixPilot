"""DSP 함수 성능 벤치마크 — 운영자·개발자가 로컬에서 latency 확인.

CI에서는 실행하지 않는다(러너 변동성으로 회귀 판정이 부정확). 개발자가
필요할 때 실행해 *현재 머신*에서의 성능을 확인하고, 큰 변경 전후로 직접
비교한다.

사용:
    uv run python -m mixpilot.scripts.bench_dsp
    uv run python -m mixpilot.scripts.bench_dsp --sizes 256,512,1024,4096
    uv run python -m mixpilot.scripts.bench_dsp --repeat 200

출력은 함수 x 버퍼 크기 매트릭스. 단위는 ms. 각 셀은 median과 p99.

해석:
- 라이브 처리 루프 budget: block_size / sample_rate. 예: 512 @ 48kHz = 10.67 ms.
- 한 채널 DSP가 이 budget의 ~10% 안에 들어와야 32채널을 처리할 여유.
- 큰 p99 - p50 차는 GC pause·메모리 할당 등 변동성 시그널.
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections.abc import Callable

import numpy as np

from mixpilot.dsp.dynamic_range import dynamic_range_db
from mixpilot.dsp.feedback import detect_peak_bins
from mixpilot.dsp.lufs import lufs_integrated
from mixpilot.dsp.peak import peak, true_peak
from mixpilot.dsp.rms import rms

# 벤치 대상 — 1D 신호 (samples,) + 옵션 kwargs(sample_rate 등) 받는 함수.
_BENCH_FNS: dict[str, Callable[[np.ndarray, int], object]] = {
    "rms": lambda s, _sr: rms(s),
    "peak": lambda s, _sr: peak(s),
    "true_peak": lambda s, _sr: true_peak(s),
    "lufs_integrated": lambda s, sr: lufs_integrated(s, sr),
    "detect_peak_bins": lambda s, sr: detect_peak_bins(s, sr),
    "dynamic_range_db": lambda s, _sr: dynamic_range_db(s),
}

# LUFS는 최소 400ms 필요 — 작은 크기에서 스킵.
_MIN_LUFS_SAMPLES = 19_200  # 400 ms @ 48kHz


def _generate_signal(n_samples: int, sample_rate: int = 48000) -> np.ndarray:
    """1 kHz 사인파 amplitude 0.5 — 일반적 라이브 신호와 유사."""
    t = np.arange(n_samples) / sample_rate
    return (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)


def _measure_ms(
    fn: Callable[[np.ndarray, int], object],
    samples: np.ndarray,
    sample_rate: int,
    repeat: int,
) -> tuple[float, float]:
    """함수를 `repeat`번 호출하고 (median_ms, p99_ms) 반환."""
    # 워밍업 — 첫 호출은 cache miss·JIT 영향이 큼.
    for _ in range(3):
        fn(samples, sample_rate)
    times_ms: list[float] = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn(samples, sample_rate)
        times_ms.append((time.perf_counter() - t0) * 1000.0)
    times_ms.sort()
    median = statistics.median(times_ms)
    # p99 — 표본이 적을 땐 최댓값에 가깝지만 그래도 일관된 정의.
    p99_idx = max(0, int(0.99 * len(times_ms)) - 1)
    return median, times_ms[p99_idx]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MixPilot DSP 벤치마크.")
    parser.add_argument(
        "--sizes",
        type=str,
        default="256,512,1024,4096",
        help="콤마로 구분된 버퍼 크기(샘플 단위). 기본 256,512,1024,4096.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=48000,
        help="샘플레이트. 기본 48000.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=100,
        help="함수당 호출 횟수. 기본 100.",
    )
    args = parser.parse_args(argv)

    sizes = [int(s.strip()) for s in args.sizes.split(",") if s.strip()]
    sample_rate = int(args.sample_rate)
    repeat = int(args.repeat)

    print(
        f"DSP benchmark — sample_rate={sample_rate} Hz, repeat={repeat}, "
        f"sizes={sizes}"
    )
    print(
        f"라이브 처리 luxury budget(block_size / sr): "
        f"{[f'{n / sample_rate * 1000:.2f}ms' for n in sizes]}"
    )
    print()

    # 헤더.
    header = "function".ljust(22) + "  " + "  ".join(
        f"{n:>6} (med / p99 ms)" for n in sizes
    )
    print(header)
    print("-" * len(header))

    for fn_name, fn in _BENCH_FNS.items():
        row = fn_name.ljust(22)
        for n in sizes:
            samples = _generate_signal(n, sample_rate)
            if fn_name == "lufs_integrated" and n < _MIN_LUFS_SAMPLES:
                row += "  " + "  too short      "
                continue
            median, p99 = _measure_ms(fn, samples, sample_rate, repeat)
            cell = f"{median:>6.3f} / {p99:>6.3f}"
            row += "  " + cell.ljust(17)
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
