"""config 단위 테스트 — 디폴트, 환경 변수 오버라이드, 검증, 카테고리 폴백."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from mixpilot.config import (
    AudioConfig,
    FeedbackAnalysisConfig,
    LufsAnalysisConfig,
    LufsTargets,
    M32Config,
    OperatingMode,
    RmsDbfsTargets,
    Settings,
)


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경 변수에서 MIXPILOT_*를 모두 제거해 디폴트 테스트를 격리."""
    for k in [k for k in os.environ if k.startswith("MIXPILOT_")]:
        monkeypatch.delenv(k, raising=False)


class TestSettingsDefaults:
    def test_audio_defaults_match_m32_usb(self) -> None:
        s = Settings()
        assert s.audio.enabled is False
        assert s.audio.device_substring == "M32"
        assert s.audio.sample_rate == 48000
        assert s.audio.block_size == 512
        assert s.audio.num_channels == 32

    def test_m32_defaults(self) -> None:
        s = Settings()
        assert s.m32.host == "192.168.1.100"
        assert s.m32.port == 10023
        assert s.m32.operating_mode is OperatingMode.DRY_RUN
        assert s.m32.auto_apply_confidence_threshold == 0.95

    def test_lufs_defaults(self) -> None:
        s = Settings()
        assert s.lufs.vocal == -16.0
        assert s.lufs.preacher == -18.0
        assert s.lufs.choir == -20.0
        assert s.lufs.instrument == -22.0
        assert s.lufs.unknown == -23.0

    def test_rms_dbfs_defaults(self) -> None:
        s = Settings()
        assert s.rms_dbfs.vocal == -18.0
        assert s.rms_dbfs.preacher == -20.0
        assert s.rms_dbfs.choir == -22.0
        assert s.rms_dbfs.instrument == -24.0
        assert s.rms_dbfs.unknown == -26.0

    def test_lufs_analysis_defaults(self) -> None:
        s = Settings()
        assert s.lufs_analysis.enabled is False
        assert s.lufs_analysis.buffer_seconds == 1.0
        assert s.lufs_analysis.eval_interval_frames == 50

    def test_feedback_analysis_defaults(self) -> None:
        s = Settings()
        assert s.feedback_analysis.enabled is False
        assert s.feedback_analysis.pnr_threshold_db == 15.0
        assert s.feedback_analysis.persistence_frames == 3
        assert s.feedback_analysis.min_frequency_hz == 100.0
        assert s.feedback_analysis.max_frequency_hz == 8000.0

    def test_channel_map_path_default(self) -> None:
        s = Settings()
        assert s.channel_map_path == Path("config/channels.yaml")


class TestEnvOverride:
    def test_audio_sample_rate_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_AUDIO__SAMPLE_RATE", "44100")
        s = Settings()
        assert s.audio.sample_rate == 44100

    def test_audio_enabled_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_AUDIO__ENABLED", "true")
        s = Settings()
        assert s.audio.enabled is True

    def test_m32_host_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_M32__HOST", "10.0.0.42")
        s = Settings()
        assert s.m32.host == "10.0.0.42"

    def test_operating_mode_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_M32__OPERATING_MODE", "auto")
        s = Settings()
        assert s.m32.operating_mode is OperatingMode.AUTO

    def test_lufs_vocal_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_LUFS__VOCAL", "-14.5")
        s = Settings()
        assert s.lufs.vocal == -14.5

    def test_rms_dbfs_vocal_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_RMS_DBFS__VOCAL", "-19.0")
        s = Settings()
        assert s.rms_dbfs.vocal == -19.0

    def test_lufs_analysis_enabled_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MIXPILOT_LUFS_ANALYSIS__ENABLED", "true")
        monkeypatch.setenv("MIXPILOT_LUFS_ANALYSIS__BUFFER_SECONDS", "2.5")
        monkeypatch.setenv("MIXPILOT_LUFS_ANALYSIS__EVAL_INTERVAL_FRAMES", "30")
        s = Settings()
        assert s.lufs_analysis.enabled is True
        assert s.lufs_analysis.buffer_seconds == 2.5
        assert s.lufs_analysis.eval_interval_frames == 30

    def test_feedback_analysis_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_FEEDBACK_ANALYSIS__ENABLED", "true")
        monkeypatch.setenv("MIXPILOT_FEEDBACK_ANALYSIS__PNR_THRESHOLD_DB", "18.0")
        monkeypatch.setenv("MIXPILOT_FEEDBACK_ANALYSIS__PERSISTENCE_FRAMES", "5")
        monkeypatch.setenv("MIXPILOT_FEEDBACK_ANALYSIS__MAX_FREQUENCY_HZ", "10000")
        s = Settings()
        assert s.feedback_analysis.enabled is True
        assert s.feedback_analysis.pnr_threshold_db == 18.0
        assert s.feedback_analysis.persistence_frames == 5
        assert s.feedback_analysis.max_frequency_hz == 10000.0

    def test_channel_map_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIXPILOT_CHANNEL_MAP_PATH", "/etc/mixpilot/channels.yaml")
        s = Settings()
        assert s.channel_map_path == Path("/etc/mixpilot/channels.yaml")


class TestLufsTargets:
    def test_for_category_known(self) -> None:
        lufs = LufsTargets()
        assert lufs.for_category("vocal") == -16.0
        assert lufs.for_category("preacher") == -18.0
        assert lufs.for_category("choir") == -20.0
        assert lufs.for_category("instrument") == -22.0

    def test_for_category_unknown_falls_back(self) -> None:
        lufs = LufsTargets()
        assert lufs.for_category("nonexistent") == lufs.unknown
        assert lufs.for_category("") == lufs.unknown

    def test_unknown_category_returns_unknown_target(self) -> None:
        lufs = LufsTargets()
        assert lufs.for_category("unknown") == lufs.unknown


class TestRmsDbfsTargets:
    def test_for_category_known(self) -> None:
        t = RmsDbfsTargets()
        assert t.for_category("vocal") == -18.0
        assert t.for_category("preacher") == -20.0
        assert t.for_category("choir") == -22.0
        assert t.for_category("instrument") == -24.0

    def test_for_category_unknown_falls_back(self) -> None:
        t = RmsDbfsTargets()
        assert t.for_category("nonexistent") == t.unknown
        assert t.for_category("") == t.unknown

    def test_rms_dbfs_targets_lower_than_lufs(self) -> None:
        # 같은 카테고리에서 RMS dBFS 타깃이 LUFS 타깃보다 더 음수여야 함
        # (K-weighting boost 보정).
        lufs = LufsTargets()
        rms = RmsDbfsTargets()
        for cat in ("vocal", "preacher", "choir", "instrument", "unknown"):
            assert rms.for_category(cat) < lufs.for_category(cat)


class TestValidation:
    def test_rejects_confidence_above_one(self) -> None:
        with pytest.raises(ValidationError):
            M32Config(auto_apply_confidence_threshold=1.5)

    def test_rejects_negative_confidence(self) -> None:
        with pytest.raises(ValidationError):
            M32Config(auto_apply_confidence_threshold=-0.1)

    def test_accepts_boundary_confidence(self) -> None:
        for c in (0.0, 1.0):
            cfg = M32Config(auto_apply_confidence_threshold=c)
            assert cfg.auto_apply_confidence_threshold == c

    def test_rejects_invalid_operating_mode(self) -> None:
        with pytest.raises(ValidationError):
            M32Config(operating_mode="nope")  # type: ignore[arg-type]

    def test_rejects_non_positive_sample_rate(self) -> None:
        with pytest.raises(ValidationError):
            AudioConfig(sample_rate=0)
        with pytest.raises(ValidationError):
            AudioConfig(sample_rate=-1)

    def test_rejects_port_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            M32Config(port=0)
        with pytest.raises(ValidationError):
            M32Config(port=70000)

    def test_rejects_non_positive_buffer_seconds(self) -> None:
        with pytest.raises(ValidationError):
            LufsAnalysisConfig(buffer_seconds=0.0)
        with pytest.raises(ValidationError):
            LufsAnalysisConfig(buffer_seconds=-1.0)

    def test_rejects_buffer_seconds_above_cap(self) -> None:
        with pytest.raises(ValidationError):
            LufsAnalysisConfig(buffer_seconds=20.0)

    def test_rejects_non_positive_eval_interval(self) -> None:
        with pytest.raises(ValidationError):
            LufsAnalysisConfig(eval_interval_frames=0)
        with pytest.raises(ValidationError):
            LufsAnalysisConfig(eval_interval_frames=-1)

    def test_rejects_non_positive_persistence_frames(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackAnalysisConfig(persistence_frames=0)

    def test_rejects_negative_pnr_threshold(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackAnalysisConfig(pnr_threshold_db=-1.0)

    def test_rejects_non_positive_frequency_range(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackAnalysisConfig(min_frequency_hz=0)
        with pytest.raises(ValidationError):
            FeedbackAnalysisConfig(max_frequency_hz=0)


class TestOperatingMode:
    def test_string_values(self) -> None:
        assert OperatingMode.DRY_RUN.value == "dry-run"
        assert OperatingMode.ASSIST.value == "assist"
        assert OperatingMode.AUTO.value == "auto"

    def test_constructible_from_string(self) -> None:
        assert OperatingMode("dry-run") is OperatingMode.DRY_RUN
        assert OperatingMode("auto") is OperatingMode.AUTO
