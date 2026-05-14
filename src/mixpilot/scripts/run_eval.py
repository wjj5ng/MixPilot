"""Eval 케이스 러너 — `evals/cases/*.yaml` 회귀 검증.

각 케이스는 `input`(신호 생성 파라미터)·`expected`(기대값 + 허용 오차)를 가지며,
러너는 신호를 합성해 `function_under_test`를 호출하고 결과를 비교한다.

사용:
    uv run python -m mixpilot.scripts.run_eval evals/cases/rms-baseline.yaml
    uv run python -m mixpilot.scripts.run_eval evals/cases/*.yaml

지원하는 신호 종류: sine, dc, silence, impulse.
지원하는 DSP 함수: mixpilot.dsp.rms.rms.

다른 DSP 함수는 점진적으로 dispatch 테이블에 추가. 알 수 없는
`function_under_test`는 케이스를 SKIP하고 보고서에 표시.
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

from mixpilot.dsp.rms import rms


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    function_under_test: str
    passed: bool
    measured: float | None
    expected: float | None
    tolerance: float | None
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
        # 기본 허용 오차.
        return math.isclose(measured, expected, abs_tol=1e-9)
    return False


def run_case(
    function_under_test: str, case: Mapping[str, Any]
) -> CaseResult:
    case_id = str(case.get("id", "<unnamed>"))
    input_spec = case.get("input", {})
    expected_spec = case.get("expected", {})

    kind = input_spec.get("kind")
    if kind not in _SIGNAL_GENERATORS:
        return CaseResult(
            case_id=case_id,
            function_under_test=function_under_test,
            passed=False,
            measured=None,
            expected=None,
            tolerance=None,
            reason=f"unsupported signal kind: {kind!r}",
        )
    if function_under_test not in _DSP_DISPATCH:
        return CaseResult(
            case_id=case_id,
            function_under_test=function_under_test,
            passed=False,
            measured=None,
            expected=None,
            tolerance=None,
            reason=f"unsupported function: {function_under_test!r}",
        )
    if "value" not in expected_spec:
        return CaseResult(
            case_id=case_id,
            function_under_test=function_under_test,
            passed=False,
            measured=None,
            expected=None,
            tolerance=None,
            reason="expected.value missing — runner only supports scalar value cases",
        )

    samples = _SIGNAL_GENERATORS[kind](input_spec)
    measured = _DSP_DISPATCH[function_under_test](samples, input_spec)
    expected = float(expected_spec["value"])
    abs_tol = expected_spec.get("tolerance_abs")
    rel_tol = expected_spec.get("tolerance_rel")
    passed = _within_tolerance(
        measured,
        expected,
        abs_tol=float(abs_tol) if abs_tol is not None else None,
        rel_tol=float(rel_tol) if rel_tol is not None else None,
    )
    return CaseResult(
        case_id=case_id,
        function_under_test=function_under_test,
        passed=passed,
        measured=float(measured),
        expected=expected,
        tolerance=(
            float(abs_tol) if abs_tol is not None
            else (float(rel_tol) if rel_tol is not None else None)
        ),
    )


def run_yaml_file(path: Path) -> list[CaseResult]:
    """단일 eval YAML을 실행해 케이스 결과 리스트 반환."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    function_under_test = str(data.get("function_under_test", ""))
    cases = data.get("cases", []) or []
    return [run_case(function_under_test, c) for c in cases if isinstance(c, dict)]


def _format_report(file_path: Path, results: list[CaseResult]) -> str:
    lines = [f"=== {file_path} ==="]
    for r in results:
        mark = "✅" if r.passed else "❌"
        if r.measured is not None and r.expected is not None:
            detail = (
                f"measured={r.measured:.6g} expected={r.expected:.6g}"
                + (f" tol={r.tolerance:.2g}" if r.tolerance is not None else "")
            )
        else:
            detail = r.reason
        lines.append(f"  {mark} {r.case_id} — {detail}")
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
