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
        assert "no recognized field" in result.reason

    def test_value_range_passes(self) -> None:
        case = {
            "id": "lufs-range",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.1,
                "duration_seconds": 1.0,
            },
            "expected": {"value_range": [-25.0, -21.0]},
        }
        result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", case)
        assert result.passed
        assert result.measured is not None
        assert -25.0 <= result.measured <= -21.0

    def test_value_range_fails(self) -> None:
        case = {
            "id": "narrow-range",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.1,
                "duration_seconds": 1.0,
            },
            "expected": {"value_range": [0.0, 1.0]},  # 의도적으로 잘못된 범위
        }
        result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", case)
        assert not result.passed
        assert "outside range" in result.reason

    def test_raises_passes(self) -> None:
        case = {
            "id": "lufs-too-short",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.1,
                "duration_seconds": 0.1,  # < 400ms
            },
            "expected": {"raises": "ValueError", "match": "too short"},
        }
        result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", case)
        assert result.passed

    def test_raises_wrong_exception_fails(self) -> None:
        case = {
            "id": "lufs-too-short-wrong-exc",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.1,
                "duration_seconds": 0.1,
            },
            "expected": {"raises": "RuntimeError"},
        }
        result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", case)
        assert not result.passed
        assert "ValueError" in result.reason

    def test_raises_but_no_exception_fails(self) -> None:
        case = {
            "id": "silence-no-exc",
            "input": {"kind": "silence", "sample_rate": 48000, "duration_seconds": 1.0},
            "expected": {"raises": "ValueError"},
        }
        result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", case)
        assert not result.passed
        assert "no exception" in result.reason

    def test_raises_match_mismatch_fails(self) -> None:
        case = {
            "id": "msg-mismatch",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.1,
                "duration_seconds": 0.1,
            },
            "expected": {"raises": "ValueError", "match": "completely wrong text"},
        }
        result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", case)
        assert not result.passed
        assert "doesn't match" in result.reason

    def test_delta_from_passes(self) -> None:
        # 두 케이스를 순서대로 실행: amp 0.1 ref, 그 다음 amp 0.2 delta.
        ref_case = {
            "id": "ref-amp0.1",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.1,
                "duration_seconds": 1.0,
            },
            "expected": {"value_range": [-25.0, -21.0]},
        }
        ref_result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", ref_case)
        assert ref_result.passed and ref_result.measured is not None

        delta_case = {
            "id": "delta-amp0.2",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.2,
                "duration_seconds": 1.0,
            },
            "expected": {
                "delta_from": "ref-amp0.1",
                "delta_value": 6.0,
                "tolerance_abs": 0.1,
            },
        }
        delta_result = run_eval.run_case(
            "mixpilot.dsp.lufs.lufs_integrated",
            delta_case,
            prior_measured={"ref-amp0.1": ref_result.measured},
        )
        assert delta_result.passed

    def test_delta_from_missing_reference_fails(self) -> None:
        case = {
            "id": "needs-ref",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.2,
                "duration_seconds": 1.0,
            },
            "expected": {
                "delta_from": "missing-id",
                "delta_value": 6.0,
                "tolerance_abs": 0.1,
            },
        }
        result = run_eval.run_case("mixpilot.dsp.lufs.lufs_integrated", case)
        assert not result.passed
        assert "missing-id" in result.reason


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

    def test_main_passes_for_real_lufs_baseline(self) -> None:
        path = (
            Path(__file__).resolve().parents[3]
            / "evals"
            / "cases"
            / "lufs-baseline.yaml"
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
