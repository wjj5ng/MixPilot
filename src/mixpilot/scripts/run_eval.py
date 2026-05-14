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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from mixpilot.dsp.lufs import lufs_integrated
from mixpilot.dsp.rms import rms


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    function_under_test: str
    passed: bool
    measured: float | None
    expected_summary: str
    reason: str = ""


def _generate_sine(params: Mapping[str, Any]) -> np.ndarray:
    sr = int(params["sample_rate"])
    freq = float(params["frequency_hz"])
    amp = float(params["amplitude"])
    duration = float(params["duration_seconds"])
    n = int(sr * duration)
    t = np.arange(n) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def _generate_dc(params: Mapping[str, Any]) -> np.ndarray:
    sr = int(params["sample_rate"])
    value = float(params["value"])
    duration = float(params["duration_seconds"])
    return np.full(int(sr * duration), value, dtype=np.float64)


def _generate_silence(params: Mapping[str, Any]) -> np.ndarray:
    sr = int(params["sample_rate"])
    duration = float(params["duration_seconds"])
    return np.zeros(int(sr * duration), dtype=np.float64)


def _generate_impulse(params: Mapping[str, Any]) -> np.ndarray:
    length = int(params["length"])
    position = int(params.get("position", 0))
    amplitude = float(params.get("amplitude", 1.0))
    signal = np.zeros(length, dtype=np.float64)
    signal[position] = amplitude
    return signal


_SIGNAL_GENERATORS: dict[str, Callable[[Mapping[str, Any]], np.ndarray]] = {
    "sine": _generate_sine,
    "dc": _generate_dc,
    "silence": _generate_silence,
    "impulse": _generate_impulse,
}


_DSP_DISPATCH: dict[str, Callable[[np.ndarray, Mapping[str, Any]], float]] = {
    "mixpilot.dsp.rms.rms": lambda samples, _input: rms(samples),
    "mixpilot.dsp.lufs.lufs_integrated": lambda samples, input_spec: lufs_integrated(
        samples, int(input_spec["sample_rate"])
    ),
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


def run_yaml_file(path: Path) -> list[CaseResult]:
    """단일 eval YAML을 실행해 케이스 결과 리스트 반환."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    function_under_test = str(data.get("function_under_test", ""))
    cases = data.get("cases", []) or []
    prior_measured: dict[str, float | None] = {}
    results: list[CaseResult] = []
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
