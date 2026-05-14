"""Eval 러너 단위 테스트 — 신호 생성·tolerance 비교·dispatch 동작."""

from __future__ import annotations

import json
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
        assert run_eval._within_tolerance(1000.5, 1000.0, abs_tol=None, rel_tol=1e-3)

    def test_rel_tol_fails(self) -> None:
        assert not run_eval._within_tolerance(
            1010.0, 1000.0, abs_tol=None, rel_tol=1e-3
        )

    def test_either_tol_passes(self) -> None:
        # abs는 실패하지만 rel은 통과 → 통과 처리.
        assert run_eval._within_tolerance(1000.5, 1000.0, abs_tol=0.1, rel_tol=1e-2)

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


class TestMultiFunctionCase:
    def test_peak_case_with_both_functions(self) -> None:
        # peak-sine-1khz-amp0.5처럼 peak/true_peak 둘 다 검증되는 케이스.
        case = {
            "id": "peak-sine",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.5,
                "duration_seconds": 0.1,
            },
            "expected": {
                "peak": 0.5,
                "tolerance_rel": 1.0e-3,
                "true_peak_at_least": 0.5,
                "true_peak_at_most": 0.55,
            },
        }
        cached: dict[str, dict[str, float]] = {}
        results = run_eval._run_multi_function_case(case, cached)
        assert len(results) == 3
        assert all(r.passed for r in results)
        # true_peak가 한 번만 호출되었는지 — at_least/at_most 둘 다 같은 값을 봄.
        true_peak_results = [r for r in results if "true_peak" in r.case_id]
        assert len(true_peak_results) == 2
        assert true_peak_results[0].measured == true_peak_results[1].measured

    def test_silence_supports_num_samples(self) -> None:
        case = {
            "id": "peak-silence",
            "input": {"kind": "silence", "sample_rate": 48000, "num_samples": 1024},
            "expected": {"peak": 0.0, "true_peak": 0.0, "tolerance_abs": 1.0e-9},
        }
        results = run_eval._run_multi_function_case(case, {})
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_at_least_threshold_violation(self) -> None:
        case = {
            "id": "should-fail-at-least",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.1,
                "duration_seconds": 0.1,
            },
            "expected": {"true_peak_at_least": 0.99},  # 0.1 amp는 절대 못 넘음
        }
        results = run_eval._run_multi_function_case(case, {})
        assert len(results) == 1
        assert not results[0].passed
        assert "below threshold" in results[0].reason

    def test_no_recognized_assertion_keys(self) -> None:
        case = {
            "id": "no-keys",
            "input": {"kind": "silence", "sample_rate": 48000, "num_samples": 100},
            "expected": {"some_unknown_field": 1.0},
        }
        results = run_eval._run_multi_function_case(case, {})
        assert len(results) == 1
        assert not results[0].passed
        assert "no recognized assertion keys" in results[0].reason


class TestFeedbackCase:
    def test_silence_zero_peaks(self) -> None:
        case = {
            "id": "fb-silence",
            "input": {"kind": "silence", "sample_rate": 48000, "num_samples": 1024},
            "expected": {"result_count": 0},
        }
        results = run_eval._run_feedback_case(case)
        assert len(results) == 1
        assert results[0].passed

    def test_pure_tone_strongest_frequency(self) -> None:
        case = {
            "id": "fb-pure",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.5,
                "num_samples": 1024,
            },
            "expected": {
                "min_result_count": 1,
                "strongest_frequency_hz": 1000.0,
                "strongest_frequency_tolerance_hz": 50.0,
            },
        }
        results = run_eval._run_feedback_case(case)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_sum_of_sines_two_peaks(self) -> None:
        case = {
            "id": "fb-two",
            "input": {
                "kind": "sum_of_sines",
                "sample_rate": 48000,
                "frequencies_hz": [500, 3000],
                "amplitudes": [0.5, 0.5],
                "num_samples": 1024,
            },
            "expected": {
                "min_result_count": 2,
                "frequencies_hz": [500, 3000],
                "frequency_tolerance_hz": 50.0,
            },
        }
        results = run_eval._run_feedback_case(case)
        assert all(r.passed for r in results)

    def test_white_noise_few_peaks(self) -> None:
        case = {
            "id": "fb-noise",
            "input": {
                "kind": "white_noise",
                "sample_rate": 48000,
                "seed": 42,
                "amplitude": 0.1,
                "num_samples": 1024,
            },
            "expected": {"max_result_count": 5},
        }
        results = run_eval._run_feedback_case(case)
        assert results[0].passed

    def test_params_min_frequency_filters(self) -> None:
        # 80 Hz sine은 min_frequency_hz=100으로 필터링되어 빠짐.
        case = {
            "id": "fb-low",
            "input": {
                "kind": "sine",
                "sample_rate": 48000,
                "frequency_hz": 80,
                "amplitude": 0.5,
                "num_samples": 1024,
            },
            "params": {"min_frequency_hz": 100.0},
            "expected": {"assert": "no peak near 80 Hz"},
        }
        results = run_eval._run_feedback_case(case)
        assert results[0].passed

    def test_unknown_assert_phrasing_fails(self) -> None:
        case = {
            "id": "fb-bad-assert",
            "input": {"kind": "silence", "sample_rate": 48000, "num_samples": 1024},
            "expected": {"assert": "the quick brown fox"},
        }
        results = run_eval._run_feedback_case(case)
        assert not results[0].passed
        assert "unknown assert phrasing" in results[0].reason


class TestSignalGeneratorsExtended:
    def test_sine_with_num_samples(self) -> None:
        signal = run_eval._generate_sine(
            {
                "sample_rate": 48000,
                "frequency_hz": 1000,
                "amplitude": 0.5,
                "num_samples": 1024,
            }
        )
        assert signal.shape == (1024,)

    def test_sum_of_sines_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            run_eval._generate_sum_of_sines(
                {
                    "sample_rate": 48000,
                    "frequencies_hz": [500],
                    "amplitudes": [0.5, 0.5],
                    "num_samples": 1024,
                }
            )

    def test_white_noise_deterministic_with_seed(self) -> None:
        params = {
            "sample_rate": 48000,
            "amplitude": 0.1,
            "seed": 42,
            "num_samples": 1024,
        }
        a = run_eval._generate_white_noise(params)
        b = run_eval._generate_white_noise(params)
        np.testing.assert_array_equal(a, b)


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

    def test_main_passes_for_real_peak_baseline(self) -> None:
        path = (
            Path(__file__).resolve().parents[3]
            / "evals"
            / "cases"
            / "peak-baseline.yaml"
        )
        exit_code = run_eval.main([str(path)])
        assert exit_code == 0

    def test_main_passes_for_real_feedback_baseline(self) -> None:
        path = (
            Path(__file__).resolve().parents[3]
            / "evals"
            / "cases"
            / "feedback-baseline.yaml"
        )
        exit_code = run_eval.main([str(path)])
        assert exit_code == 0

    def test_main_writes_results_json(self, tmp_path: Path) -> None:
        rms_path = (
            Path(__file__).resolve().parents[3]
            / "evals"
            / "cases"
            / "rms-baseline.yaml"
        )
        out_dir = tmp_path / "results"
        exit_code = run_eval.main([str(rms_path), "--output-dir", str(out_dir)])
        assert exit_code == 0
        # 정확히 하나의 timestamp 디렉토리.
        timestamp_dirs = list(out_dir.iterdir())
        assert len(timestamp_dirs) == 1
        # 그 안에 rms-baseline.json.
        result_files = list(timestamp_dirs[0].iterdir())
        assert len(result_files) == 1
        assert result_files[0].name == "rms-baseline.json"
        payload = json.loads(result_files[0].read_text(encoding="utf-8"))
        assert payload["total"] == 4
        assert payload["passed"] == 4
        assert payload["failed"] == 0
        assert len(payload["results"]) == 4
        assert all(r["passed"] for r in payload["results"])

    def test_main_failed_run_still_writes_json(self, tmp_path: Path) -> None:
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
        out_dir = tmp_path / "results"
        exit_code = run_eval.main([str(bad), "--output-dir", str(out_dir)])
        assert exit_code == 1
        # 실패한 실행도 결과는 영속화됨.
        timestamp_dirs = list(out_dir.iterdir())
        assert len(timestamp_dirs) == 1
        payload = json.loads((timestamp_dirs[0] / "bad.json").read_text("utf-8"))
        assert payload["failed"] == 1
        assert payload["results"][0]["passed"] is False

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
