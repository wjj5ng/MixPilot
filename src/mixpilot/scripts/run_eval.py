"""Eval 케이스 러너 — `evals/cases/*.yaml` 회귀 검증.

각 케이스는 `input`(신호 생성 파라미터)·`expected`(기대값 + 허용 오차)를 가지며,
러너는 신호를 합성해 `function_under_test`를 호출하고 결과를 비교한다.

사용:
    uv run python -m mixpilot.scripts.run_eval evals/cases/rms-baseline.yaml
    uv run python -m mixpilot.scripts.run_eval evals/cases/lufs-baseline.yaml

지원하는 신호 종류: sine, dc, silence, impulse.
지원하는 DSP 함수:
    - mixpilot.dsp.rms.rms
    - mixpilot.dsp.lufs.lufs_integrated

지원하는 expected 스키마:
    - value + (tolerance_abs | tolerance_rel)
    - value_range: [min, max]
    - delta_from: <case_id> + delta_value + tolerance_abs
    - raises: <ExceptionTypeName> + match: <substring>

다른 DSP 함수·expected 스키마는 점진적으로 dispatch 테이블에 추가.
"""

from __future__ import annotations

import argparse
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from mixpilot.dsp.feedback import FeedbackPeak, detect_peak_bins
from mixpilot.dsp.lufs import lufs_integrated
from mixpilot.dsp.peak import peak, true_peak
from mixpilot.dsp.rms import rms


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    function_under_test: str
    passed: bool
    measured: float | None
    expected_summary: str
    reason: str = ""


def _length_from_params(params: Mapping[str, Any]) -> int:
    if "num_samples" in params:
        return int(params["num_samples"])
    sr = int(params["sample_rate"])
    return int(sr * float(params["duration_seconds"]))


def _generate_sine(params: Mapping[str, Any]) -> np.ndarray:
    sr = int(params["sample_rate"])
    freq = float(params["frequency_hz"])
    amp = float(params["amplitude"])
    n = _length_from_params(params)
    t = np.arange(n) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def _generate_sum_of_sines(params: Mapping[str, Any]) -> np.ndarray:
    sr = int(params["sample_rate"])
    freqs = params["frequencies_hz"]
    amps = params["amplitudes"]
    if len(freqs) != len(amps):
        raise ValueError("frequencies_hz and amplitudes must have same length")
    n = _length_from_params(params)
    t = np.arange(n) / sr
    signal = np.zeros(n, dtype=np.float64)
    for f, a in zip(freqs, amps, strict=True):
        signal += float(a) * np.sin(2 * np.pi * float(f) * t)
    return signal


def _generate_white_noise(params: Mapping[str, Any]) -> np.ndarray:
    amp = float(params["amplitude"])
    seed = int(params.get("seed", 0))
    n = _length_from_params(params)
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) * amp).astype(np.float64)


def _generate_dc(params: Mapping[str, Any]) -> np.ndarray:
    sr = int(params["sample_rate"])
    value = float(params["value"])
    duration = float(params["duration_seconds"])
    return np.full(int(sr * duration), value, dtype=np.float64)


def _generate_silence(params: Mapping[str, Any]) -> np.ndarray:
    return np.zeros(_length_from_params(params), dtype=np.float64)


def _generate_impulse(params: Mapping[str, Any]) -> np.ndarray:
    length = int(params["length"])
    position = int(params.get("position", 0))
    amplitude = float(params.get("amplitude", 1.0))
    signal = np.zeros(length, dtype=np.float64)
    signal[position] = amplitude
    return signal


_SIGNAL_GENERATORS: dict[str, Callable[[Mapping[str, Any]], np.ndarray]] = {
    "sine": _generate_sine,
    "sum_of_sines": _generate_sum_of_sines,
    "dc": _generate_dc,
    "silence": _generate_silence,
    "impulse": _generate_impulse,
    "white_noise": _generate_white_noise,
}


_DSP_DISPATCH: dict[str, Callable[[np.ndarray, Mapping[str, Any]], float]] = {
    "mixpilot.dsp.rms.rms": lambda samples, _input: rms(samples),
    "mixpilot.dsp.lufs.lufs_integrated": lambda samples, input_spec: lufs_integrated(
        samples, int(input_spec["sample_rate"])
    ),
    "mixpilot.dsp.peak.peak": lambda samples, _input: peak(samples),
    "mixpilot.dsp.peak.true_peak": lambda samples, _input: true_peak(samples),
}


# Peak YAML의 expected 키 → (DSP 함수 path, 비교 종류) 매핑.
# `equal`은 tolerance_abs/tolerance_rel과 함께 사용. `at_least`/`at_most`는 단방향.
_PEAK_ASSERTIONS: dict[str, tuple[str, str]] = {
    "peak": ("mixpilot.dsp.peak.peak", "equal"),
    "true_peak": ("mixpilot.dsp.peak.true_peak", "equal"),
    "true_peak_at_least": ("mixpilot.dsp.peak.true_peak", "at_least"),
    "true_peak_at_most": ("mixpilot.dsp.peak.true_peak", "at_most"),
}


def _within_tolerance(
    measured: float, expected: float, *, abs_tol: float | None, rel_tol: float | None
) -> bool:
    if abs_tol is not None and abs_tol >= 0:
        if abs(measured - expected) <= abs_tol:
            return True
    if rel_tol is not None and rel_tol > 0:
        return math.isclose(measured, expected, rel_tol=rel_tol)
    if abs_tol is None and rel_tol is None:
        return math.isclose(measured, expected, abs_tol=1e-9)
    return False


def _evaluate_expected(
    measured: float,
    expected: Mapping[str, Any],
    prior_measured: Mapping[str, float | None],
) -> tuple[bool, str, str]:
    """Returns (passed, expected_summary, failure_reason)."""
    if "value" in expected:
        target = float(expected["value"])
        abs_tol = expected.get("tolerance_abs")
        rel_tol = expected.get("tolerance_rel")
        passed = _within_tolerance(
            measured,
            target,
            abs_tol=float(abs_tol) if abs_tol is not None else None,
            rel_tol=float(rel_tol) if rel_tol is not None else None,
        )
        tol_str = ""
        if abs_tol is not None:
            tol_str = f" abs_tol={float(abs_tol):.2g}"
        elif rel_tol is not None:
            tol_str = f" rel_tol={float(rel_tol):.2g}"
        summary = f"expected={target:.6g}{tol_str}"
        return passed, summary, "" if passed else "value out of tolerance"

    if "value_range" in expected:
        lo, hi = expected["value_range"]
        lo_f, hi_f = float(lo), float(hi)
        passed = lo_f <= measured <= hi_f
        summary = f"range=[{lo_f:.6g}, {hi_f:.6g}]"
        return passed, summary, "" if passed else "value outside range"

    if "delta_from" in expected:
        ref_id = str(expected["delta_from"])
        delta_value = float(expected["delta_value"])
        abs_tol = float(expected.get("tolerance_abs", 0.0))
        ref_measured = prior_measured.get(ref_id)
        summary = (
            f"delta_from={ref_id} delta={delta_value:.6g} abs_tol={abs_tol:.2g}"
        )
        if ref_measured is None:
            return (
                False,
                summary,
                f"reference case {ref_id!r} not measured (missing or failed earlier)",
            )
        actual_delta = measured - ref_measured
        passed = abs(actual_delta - delta_value) <= abs_tol
        if not passed:
            return False, summary, f"delta={actual_delta:.6g} differs from expected"
        return True, summary, ""

    return False, "<unknown expected schema>", (
        "expected has no recognized field (value | value_range | delta_from | raises)"
    )


def run_case(
    function_under_test: str,
    case: Mapping[str, Any],
    prior_measured: Mapping[str, float | None] | None = None,
) -> CaseResult:
    case_id = str(case.get("id", "<unnamed>"))
    input_spec = case.get("input", {})
    expected_spec = case.get("expected", {})
    prior = prior_measured if prior_measured is not None else {}

    kind = input_spec.get("kind")
    if kind not in _SIGNAL_GENERATORS:
        return CaseResult(
            case_id=case_id,
            function_under_test=function_under_test,
            passed=False,
            measured=None,
            expected_summary="<n/a>",
            reason=f"unsupported signal kind: {kind!r}",
        )
    if function_under_test not in _DSP_DISPATCH:
        return CaseResult(
            case_id=case_id,
            function_under_test=function_under_test,
            passed=False,
            measured=None,
            expected_summary="<n/a>",
            reason=f"unsupported function: {function_under_test!r}",
        )

    samples = _SIGNAL_GENERATORS[kind](input_spec)
    dsp_fn = _DSP_DISPATCH[function_under_test]

    if "raises" in expected_spec:
        exc_name = str(expected_spec["raises"])
        match_substr = expected_spec.get("match")
        match_part = f" match={match_substr!r}" if match_substr else ""
        summary = f"raises={exc_name}{match_part}"
        try:
            dsp_fn(samples, input_spec)
        except Exception as e:
            actual_name = type(e).__name__
            if actual_name != exc_name:
                return CaseResult(
                    case_id=case_id,
                    function_under_test=function_under_test,
                    passed=False,
                    measured=None,
                    expected_summary=summary,
                    reason=f"got {actual_name}: {e}",
                )
            if match_substr is not None and str(match_substr) not in str(e):
                msg = str(e)
                return CaseResult(
                    case_id=case_id,
                    function_under_test=function_under_test,
                    passed=False,
                    measured=None,
                    expected_summary=summary,
                    reason=f"exception message {msg!r} doesn't match {match_substr!r}",
                )
            return CaseResult(
                case_id=case_id,
                function_under_test=function_under_test,
                passed=True,
                measured=None,
                expected_summary=summary,
            )
        return CaseResult(
            case_id=case_id,
            function_under_test=function_under_test,
            passed=False,
            measured=None,
            expected_summary=summary,
            reason=f"expected {exc_name} but no exception raised",
        )

    measured = float(dsp_fn(samples, input_spec))
    passed, summary, failure = _evaluate_expected(measured, expected_spec, prior)
    return CaseResult(
        case_id=case_id,
        function_under_test=function_under_test,
        passed=passed,
        measured=measured,
        expected_summary=summary,
        reason=failure,
    )


def _run_multi_function_case(
    case: Mapping[str, Any],
    cached_measurements: dict[str, dict[str, float]],
) -> list[CaseResult]:
    """`functions_under_test`(복수) YAML의 한 케이스를 평가.

    `expected`에 있는 어설션 키들(peak/true_peak/true_peak_at_least/...)을
    순회하며 각각의 CaseResult를 생성. 동일 함수의 측정값은 케이스 내에서
    캐싱(`cached_measurements[case_id][fn_path]`)해 중복 호출 회피.
    """
    case_id = str(case.get("id", "<unnamed>"))
    input_spec = case.get("input", {})
    expected_spec = case.get("expected", {})

    kind = input_spec.get("kind")
    if kind not in _SIGNAL_GENERATORS:
        return [
            CaseResult(
                case_id=case_id,
                function_under_test="<multi>",
                passed=False,
                measured=None,
                expected_summary="<n/a>",
                reason=f"unsupported signal kind: {kind!r}",
            )
        ]

    samples = _SIGNAL_GENERATORS[kind](input_spec)
    abs_tol = expected_spec.get("tolerance_abs")
    rel_tol = expected_spec.get("tolerance_rel")
    cached = cached_measurements.setdefault(case_id, {})

    results: list[CaseResult] = []
    for key, (fn_path, op) in _PEAK_ASSERTIONS.items():
        if key not in expected_spec:
            continue
        target = float(expected_spec[key])
        if fn_path not in _DSP_DISPATCH:
            results.append(
                CaseResult(
                    case_id=f"{case_id}::{key}",
                    function_under_test=fn_path,
                    passed=False,
                    measured=None,
                    expected_summary=f"{key}={target:.6g}",
                    reason=f"unsupported function: {fn_path!r}",
                )
            )
            continue
        if fn_path not in cached:
            cached[fn_path] = float(_DSP_DISPATCH[fn_path](samples, input_spec))
        measured = cached[fn_path]

        passed: bool
        summary: str
        reason = ""
        if op == "equal":
            passed = _within_tolerance(
                measured,
                target,
                abs_tol=float(abs_tol) if abs_tol is not None else None,
                rel_tol=float(rel_tol) if rel_tol is not None else None,
            )
            tol_str = ""
            if abs_tol is not None:
                tol_str = f" abs_tol={float(abs_tol):.2g}"
            elif rel_tol is not None:
                tol_str = f" rel_tol={float(rel_tol):.2g}"
            summary = f"{key}={target:.6g}{tol_str}"
            if not passed:
                reason = "value out of tolerance"
        elif op == "at_least":
            passed = measured >= target
            summary = f"{key}={target:.6g}"
            if not passed:
                reason = "measured below threshold"
        elif op == "at_most":
            passed = measured <= target
            summary = f"{key}={target:.6g}"
            if not passed:
                reason = "measured above threshold"
        else:  # pragma: no cover — defensive.
            passed = False
            summary = f"<unknown op: {op}>"
            reason = "internal: unknown assertion op"

        results.append(
            CaseResult(
                case_id=f"{case_id}::{key}",
                function_under_test=fn_path,
                passed=passed,
                measured=measured,
                expected_summary=summary,
                reason=reason,
            )
        )

    if not results:
        return [
            CaseResult(
                case_id=case_id,
                function_under_test="<multi>",
                passed=False,
                measured=None,
                expected_summary="<n/a>",
                reason="expected has no recognized assertion keys",
            )
        ]
    return results


_NO_PEAK_NEAR_PATTERN = re.compile(
    r"no peak near\s+(?P<freq>[\d.]+)\s*Hz(?:\s*\(±\s*(?P<tol>[\d.]+)\s*Hz\))?",
    re.IGNORECASE,
)


def _eval_feedback_assertions(
    peaks: list[FeedbackPeak], expected_spec: Mapping[str, Any]
) -> list[tuple[str, bool, str, str]]:
    """피드백 케이스의 어설션 평가.

    Returns: (sub_id, passed, summary, reason) 리스트.
    """
    out: list[tuple[str, bool, str, str]] = []

    if "result_count" in expected_spec:
        target = int(expected_spec["result_count"])
        passed = len(peaks) == target
        out.append(
            (
                "result_count",
                passed,
                f"result_count={target}",
                "" if passed else f"got {len(peaks)} peaks",
            )
        )

    if "min_result_count" in expected_spec:
        target = int(expected_spec["min_result_count"])
        passed = len(peaks) >= target
        out.append(
            (
                "min_result_count",
                passed,
                f"min_result_count={target}",
                "" if passed else f"got {len(peaks)} peaks",
            )
        )

    if "max_result_count" in expected_spec:
        target = int(expected_spec["max_result_count"])
        passed = len(peaks) <= target
        out.append(
            (
                "max_result_count",
                passed,
                f"max_result_count={target}",
                "" if passed else f"got {len(peaks)} peaks",
            )
        )

    if "strongest_frequency_hz" in expected_spec:
        target_freq = float(expected_spec["strongest_frequency_hz"])
        tol = float(expected_spec.get("strongest_frequency_tolerance_hz", 50.0))
        summary = f"strongest_freq={target_freq}±{tol}Hz"
        if not peaks:
            out.append(("strongest_frequency_hz", False, summary, "no peaks detected"))
        else:
            strongest = max(peaks, key=lambda p: p.magnitude_dbfs)
            passed = abs(strongest.frequency_hz - target_freq) <= tol
            actual = f"{strongest.frequency_hz:.1f}"
            out.append(
                (
                    "strongest_frequency_hz",
                    passed,
                    summary,
                    "" if passed else f"got strongest at {actual} Hz",
                )
            )

    if "frequencies_hz" in expected_spec:
        targets = [float(f) for f in expected_spec["frequencies_hz"]]
        tol = float(expected_spec.get("frequency_tolerance_hz", 50.0))
        summary = f"frequencies={targets}±{tol}Hz"
        peak_freqs = [p.frequency_hz for p in peaks]
        missing = [
            f for f in targets if not any(abs(pf - f) <= tol for pf in peak_freqs)
        ]
        passed = not missing
        out.append(
            (
                "frequencies_hz",
                passed,
                summary,
                "" if passed else f"missing peaks near {missing} Hz",
            )
        )

    if "assert" in expected_spec:
        assertion = str(expected_spec["assert"])
        m = _NO_PEAK_NEAR_PATTERN.search(assertion)
        if m:
            target = float(m.group("freq"))
            tol = float(m.group("tol") or 50.0)
            summary = f'assert "no peak near {target} Hz (±{tol})"'
            offenders = [
                p.frequency_hz for p in peaks if abs(p.frequency_hz - target) <= tol
            ]
            passed = not offenders
            out.append(
                (
                    "assert",
                    passed,
                    summary,
                    "" if passed else f"unexpected peaks near {offenders} Hz",
                )
            )
        else:
            out.append(
                (
                    "assert",
                    False,
                    f"assert {assertion!r}",
                    f"unknown assert phrasing: {assertion!r}",
                )
            )

    return out


def _run_feedback_case(case: Mapping[str, Any]) -> list[CaseResult]:
    """단일 feedback 케이스 → 어설션별 CaseResult."""
    case_id = str(case.get("id", "<unnamed>"))
    input_spec = case.get("input", {})
    expected_spec = case.get("expected", {})
    params = case.get("params", {}) or {}
    fn_path = "mixpilot.dsp.feedback.detect_peak_bins"

    kind = input_spec.get("kind")
    if kind not in _SIGNAL_GENERATORS:
        return [
            CaseResult(
                case_id=case_id,
                function_under_test=fn_path,
                passed=False,
                measured=None,
                expected_summary="<n/a>",
                reason=f"unsupported signal kind: {kind!r}",
            )
        ]

    samples = _SIGNAL_GENERATORS[kind](input_spec)
    sample_rate = int(input_spec["sample_rate"])
    kwargs: dict[str, Any] = {}
    if "min_frequency_hz" in params:
        kwargs["min_frequency_hz"] = float(params["min_frequency_hz"])
    if "max_frequency_hz" in params:
        kwargs["max_frequency_hz"] = float(params["max_frequency_hz"])
    if "pnr_threshold_db" in params:
        kwargs["pnr_threshold_db"] = float(params["pnr_threshold_db"])
    if "neighbor_band_hz" in params:
        kwargs["neighbor_band_hz"] = float(params["neighbor_band_hz"])

    peaks = detect_peak_bins(samples, sample_rate, **kwargs)
    assertions = _eval_feedback_assertions(peaks, expected_spec)

    if not assertions:
        return [
            CaseResult(
                case_id=case_id,
                function_under_test=fn_path,
                passed=False,
                measured=float(len(peaks)),
                expected_summary="<n/a>",
                reason="expected has no recognized feedback assertion keys",
            )
        ]

    return [
        CaseResult(
            case_id=f"{case_id}::{sub_id}",
            function_under_test=fn_path,
            passed=passed,
            measured=float(len(peaks)),
            expected_summary=summary,
            reason=reason,
        )
        for sub_id, passed, summary, reason in assertions
    ]


def run_yaml_file(path: Path) -> list[CaseResult]:
    """단일 eval YAML을 실행해 케이스 결과 리스트 반환."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = data.get("cases", []) or []

    # 피드백 YAML — list[FeedbackPeak] 결과의 특수 어설션 처리.
    if data.get("function_under_test") == "mixpilot.dsp.feedback.detect_peak_bins":
        results: list[CaseResult] = []
        for c in cases:
            if not isinstance(c, dict):
                continue
            results.extend(_run_feedback_case(c))
        return results

    # 멀티 함수 YAML(`functions_under_test`) 처리.
    if "functions_under_test" in data:
        cached_measurements: dict[str, dict[str, float]] = {}
        results: list[CaseResult] = []
        for c in cases:
            if not isinstance(c, dict):
                continue
            results.extend(_run_multi_function_case(c, cached_measurements))
        return results

    function_under_test = str(data.get("function_under_test", ""))
    prior_measured: dict[str, float | None] = {}
    results = []
    for c in cases:
        if not isinstance(c, dict):
            continue
        r = run_case(function_under_test, c, prior_measured)
        prior_measured[r.case_id] = r.measured if r.passed else None
        results.append(r)
    return results


def _format_report(file_path: Path, results: list[CaseResult]) -> str:
    lines = [f"=== {file_path} ==="]
    for r in results:
        mark = "✅" if r.passed else "❌"
        if r.measured is not None:
            detail = f"measured={r.measured:.6g} {r.expected_summary}"
        else:
            detail = r.expected_summary
        if r.reason:
            detail += f" — {r.reason}"
        lines.append(f"  {mark} {r.case_id} — {detail}")
    passed = sum(1 for r in results if r.passed)
    lines.append(f"  → {passed}/{len(results)} passed")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MixPilot eval cases.")
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="YAML 파일 경로(여러 개 가능).",
    )
    args = parser.parse_args(argv)

    any_failed = False
    for path in args.paths:
        results = run_yaml_file(path)
        print(_format_report(path, results))
        if any(not r.passed for r in results):
            any_failed = True
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
