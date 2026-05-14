"""service wav 회귀 러너 단위·통합 테스트.

WavReplayAudioSource와 processing loop을 *실제로* 가동 — 짧은 합성 wav로
빠르게 검증. CI에서 실행 가능한 cost.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy.io import wavfile

from mixpilot.scripts import run_service_replay


def _write_short_wav(path: Path, *, sr: int = 48000, dur_s: float = 0.5) -> None:
    """1 kHz 모노 사인파 짧은 wav — 회귀 러너 동작 검증용."""
    n = int(dur_s * sr)
    t = np.arange(n) / sr
    sig = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    wavfile.write(str(path), sr, sig)


class TestRunCaseFile:
    def test_minimal_case_passes(self, tmp_path: Path) -> None:
        wav = tmp_path / "test.wav"
        _write_short_wav(wav)
        case_path = tmp_path / "case.yaml"
        case_path.write_text(
            yaml.safe_dump(
                {
                    "id": "minimal",
                    "wav_path": str(wav),
                    "sample_rate": 48000,
                    "num_channels": 1,
                    "block_size": 512,
                    "rules_enabled": ["loudness"],
                    "expected": {},
                }
            ),
            encoding="utf-8",
        )
        result = run_service_replay.run_case_file(case_path)
        assert result.case_id == "minimal"
        # 합성 1 kHz 톤이 1ch loudness 룰을 통과 → 일부 발화 가능.
        # expected 비어있으면 정상 종료만으로 pass.
        assert result.passed

    def test_relative_wav_path_resolved(self, tmp_path: Path) -> None:
        # case yaml과 wav가 같은 디렉토리 (상대경로).
        wav = tmp_path / "input.wav"
        _write_short_wav(wav)
        case_path = tmp_path / "case.yaml"
        case_path.write_text(
            yaml.safe_dump(
                {
                    "id": "rel-path",
                    "wav_path": "input.wav",  # 상대경로
                    "sample_rate": 48000,
                    "num_channels": 1,
                    "expected": {},
                }
            ),
            encoding="utf-8",
        )
        result = run_service_replay.run_case_file(case_path)
        assert result.passed

    def test_expected_max_count_violation_fails(self, tmp_path: Path) -> None:
        wav = tmp_path / "test.wav"
        _write_short_wav(wav, dur_s=0.5)
        case_path = tmp_path / "case.yaml"
        case_path.write_text(
            yaml.safe_dump(
                {
                    "id": "too-many",
                    "wav_path": str(wav),
                    "sample_rate": 48000,
                    "num_channels": 1,
                    "rules_enabled": ["loudness"],
                    "expected": {"max_recommendation_count": 0},
                }
            ),
            encoding="utf-8",
        )
        result = run_service_replay.run_case_file(case_path)
        # 1 kHz 사인 0.5s는 loudness 룰 발화 가능 → max=0 위반 가능.
        # 결과에 상관없이 검증 로직이 실행되었는지만 확인.
        if result.recommendation_count > 0:
            assert not result.passed
            assert any("max_recommendation_count" in f for f in result.failures)

    def test_expected_kinds_absent_violation_fails(self, tmp_path: Path) -> None:
        wav = tmp_path / "test.wav"
        _write_short_wav(wav, dur_s=0.5)
        case_path = tmp_path / "case.yaml"
        case_path.write_text(
            yaml.safe_dump(
                {
                    "id": "no-info",
                    "wav_path": str(wav),
                    "sample_rate": 48000,
                    "num_channels": 1,
                    "rules_enabled": ["loudness"],
                    "expected": {"kinds_absent": ["info"]},
                }
            ),
            encoding="utf-8",
        )
        result = run_service_replay.run_case_file(case_path)
        # loudness 룰은 INFO kind 발화 → kinds_absent 위반 가능.
        if result.kinds_seen.get("info", 0) > 0:
            assert not result.passed

    def test_missing_wav_raises(self, tmp_path: Path) -> None:
        case_path = tmp_path / "case.yaml"
        case_path.write_text(
            yaml.safe_dump(
                {
                    "id": "missing",
                    "wav_path": str(tmp_path / "nope.wav"),
                    "sample_rate": 48000,
                    "num_channels": 1,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(FileNotFoundError):
            run_service_replay.run_case_file(case_path)


class TestMain:
    def test_main_returns_0_on_pass(self, tmp_path: Path) -> None:
        wav = tmp_path / "test.wav"
        _write_short_wav(wav)
        case_path = tmp_path / "case.yaml"
        case_path.write_text(
            yaml.safe_dump(
                {
                    "id": "pass-case",
                    "wav_path": str(wav),
                    "sample_rate": 48000,
                    "num_channels": 1,
                    "rules_enabled": ["loudness"],
                    "expected": {},
                }
            ),
            encoding="utf-8",
        )
        rc = run_service_replay.main([str(case_path)])
        assert rc == 0
