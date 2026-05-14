"""DSP 벤치 스크립트 스모크 테스트 — 크래시 없이 끝까지 돈다."""

from __future__ import annotations

import contextlib
import io

from mixpilot.scripts import bench_dsp


class TestMain:
    def test_runs_without_crash(self) -> None:
        # 빠른 변형 — 작은 크기·repeat로 한 번 돌려 0 반환 확인.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bench_dsp.main(["--sizes", "256", "--repeat", "5"])
        assert rc == 0
        out = buf.getvalue()
        # 모든 DSP가 표 안에 나타나는지.
        for fn_name in ("rms", "peak", "true_peak", "dynamic_range_db"):
            assert fn_name in out
        # LUFS는 너무 짧으면 "too short" 표시.
        assert "lufs_integrated" in out
        assert "too short" in out

    def test_lufs_runs_with_sufficient_size(self) -> None:
        # 19200 샘플(400ms @ 48kHz)이면 LUFS 통과.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bench_dsp.main(["--sizes", "19200", "--repeat", "3"])
        assert rc == 0
        out = buf.getvalue()
        # 충분한 크기에서는 too short 메시지가 lufs 라인에 없어야 함.
        for line in out.splitlines():
            if line.startswith("lufs_integrated"):
                assert "too short" not in line


class TestMeasureMs:
    def test_returns_finite_median_and_p99(self) -> None:
        import numpy as np

        samples = bench_dsp._generate_signal(1024)
        median, p99 = bench_dsp._measure_ms(
            lambda s, _sr: np.sqrt(np.mean(s**2)),  # 간단한 RMS 흉내
            samples,
            sample_rate=48000,
            repeat=10,
        )
        assert median >= 0.0
        assert p99 >= median  # p99 >= median by definition.

    def test_returns_for_zero_arg_function(self) -> None:
        # 일정한 시간을 반환하는 함수도 깨지지 않음.
        samples = bench_dsp._generate_signal(256)
        median, p99 = bench_dsp._measure_ms(
            lambda _s, _sr: None, samples, sample_rate=48000, repeat=5
        )
        assert median >= 0.0
        assert p99 >= median
