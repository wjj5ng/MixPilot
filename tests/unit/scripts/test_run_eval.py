"""Eval 러너 단위 테스트 — 신호 생성·tolerance 비교·dispatch 동작."""

from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import pytest

from mixpilot.scripts import run_eval


class TestSignalGenerators:
    def test_sine_amplitude_matches_peak(self) -> None:
        params = {
            "sample_rate": 48000,
            "frequency_hz": 1000,
            "amplitude": 0.5,
            "duration_seconds": 0.1,
        }
        signal = run_eval._generate_sine(params)
        assert signal.shape == (4800,)
        assert signal.dtype == np.float64
        assert np.max(np.abs(signal)) == pytest.approx(0.5, abs=1e-6)

    def test_dc_constant(self) -> None:
        signal = run_eval._generate_dc(
            {"sample_rate": 48000, "value": 0.3, "duration_seconds": 0.5}
        )
        assert signal.shape == (24000,)
        np.testing.assert_array_equal(signal, np.full(24000, 0.3))

    def test_silence_all_zero(self) -> None:
        signal = run_eval._generate_silence(
            {"sample_rate": 8000, "duration_seconds": 1.0}
        )
        assert signal.shape == (8000,)
        assert np.all(signal == 0.0)

    def test_impulse_default_position(self) -> None:
        signal = run_eval._generate_impulse({"length": 100})
        assert signal.shape == (100,)
        assert signal[0] == 1.0
        assert np.sum(signal != 0.0) == 1

    def test_impulse_custom_position_amplitude(self) -> None:
        signal = run_eval._generate_impulse(
            {"length": 10, "position": 5, "amplitude": 0.25}
        )
        assert signal[5] == 0.25
        assert np.sum(signal != 0.0) == 1


class TestToleranceCheck:
    def test_abs_tol_passes_within(self) -> None:
        assert run_eval._within_tolerance(0.30001, 0.3, abs_tol=1e-4, rel_tol=None)

    def test_abs_tol_fails_outside(self) -> None:
        assert not run_eval._within_tolerance(0.301, 0.3, abs_tol=1e-4, rel_tol=None)

    def test_rel_tol_passes(self) -> None:
        assert run_eval._within_tolerance(
            1000.5, 1000.0, abs_tol=None, rel_tol=1e-3
        )

    def test_rel_tol_fails(self) -> None:
        assert not run_eval._within_tolerance(
            1010.0, 1000.0, abs_tol=None, rel_tol=1e-3
        )

    def test_either_tol_passes(self) -> None:
        # abs는 실패하지만 rel은 통과 → 통과 처리.
        assert run_eval._within_tolerance(
            1000.5, 1000.0, abs_tol=0.1, rel_tol=1e-2
        )

    def test_default_when_neither_specified(self) -> None:
        # 둘 다 None → 기본 abs_tol=1e-9.
        assert run_eval._within_tolerance(0.3, 0.3, abs_tol=None, rel_tol=None)
        assert not run_eval._within_tolerance(
            0.3 + 1e-6, 0.3, abs_tol=None, rel_tol=None
        )


class TestRunCase:
    def test_rms_sine_passes(self) -> None:
        case = {
            "id": "rms-sine-test",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 440,
                "amplitude": 0.5,
                "duration_seconds": 1.0,
            },
            "expected": {"value": 0.3535533905932738, "tolerance_rel": 1e-4},
        }
        result = run_eval.run_case("mixpilot.dsp.rms.rms", case)
        assert result.passed
        assert result.case_id == "rms-sine-test"

    def test_unknown_signal_kind_fails(self) -> None:
        case = {
            "id": "weird",
            "input": {"kind": "chirp", "sample_rate": 48000},
            "expected": {"value": 0.0},
        }
        result = run_eval.run_case("mixpilot.dsp.rms.rms", case)
        assert not result.passed
        assert "unsupported signal kind" in result.reason

    def test_unknown_function_fails(self) -> None:
        case = {
            "id": "x",
            "input": {"kind": "silence", "sample_rate": 48000, "duration_seconds": 0.1},
            "expected": {"value": 0.0},
        }
        result = run_eval.run_case("mixpilot.dsp.unknown.func", case)
        assert not result.passed
        assert "unsupported function" in result.reason

    def test_missing_expected_value(self) -> None:
        case = {
            "id": "no-expected",
            "input": {"kind": "silence", "sample_rate": 48000, "duration_seconds": 0.1},
            "expected": {},
        }
        result = run_eval.run_case("mixpilot.dsp.rms.rms", case)
        assert not result.passed
        assert "expected.value missing" in result.reason


class TestRunYamlFile:
    def test_load_and_run(self, tmp_path: Path) -> None:
        yaml_text = textwrap.dedent(
            """\
            id: test-set
            function_under_test: mixpilot.dsp.rms.rms
            cases:
              - id: silence-zero
                input:
                  kind: silence
                  sample_rate: 48000
                  duration_seconds: 0.1
                expected:
                  value: 0.0
                  tolerance_abs: 1.0e-12
              - id: sine-half-amp
                input:
                  kind: sine
                  sample_rate: 48000
                  frequency_hz: 1000
                  amplitude: 0.5
                  duration_seconds: 0.5
                expected:
                  value: 0.3535533905932738
                  tolerance_rel: 1.0e-4
            """
        )
        path = tmp_path / "case.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        results = run_eval.run_yaml_file(path)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_empty_yaml_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        assert run_eval.run_yaml_file(path) == []


class TestMain:
    def test_main_passes_for_real_rms_baseline(self) -> None:
        path = (
            Path(__file__).resolve().parents[3]
            / "evals"
            / "cases"
            / "rms-baseline.yaml"
        )
        exit_code = run_eval.main([str(path)])
        assert exit_code == 0

    def test_main_fails_when_any_case_fails(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            textwrap.dedent(
                """\
                id: bad-set
                function_under_test: mixpilot.dsp.rms.rms
                cases:
                  - id: wrong-expected
                    input:
                      kind: silence
                      sample_rate: 48000
                      duration_seconds: 0.1
                    expected:
                      value: 0.5
                      tolerance_abs: 1.0e-9
                """
            ),
            encoding="utf-8",
        )
        exit_code = run_eval.main([str(bad)])
        assert exit_code == 1
