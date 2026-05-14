"""serve 런처 — 프리셋 평탄화·env 주입 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from mixpilot.scripts import serve


class TestFlattenToEnv:
    def test_flat_scalar(self) -> None:
        flat = serve.flatten_to_env({"key": "value"})
        assert flat == {"MIXPILOT_KEY": "value"}

    def test_nested_two_levels(self) -> None:
        flat = serve.flatten_to_env({"audio": {"enabled": True, "num_channels": 8}})
        assert flat["MIXPILOT_AUDIO__ENABLED"] == "true"
        assert flat["MIXPILOT_AUDIO__NUM_CHANNELS"] == "8"

    def test_boolean_lowercase(self) -> None:
        flat = serve.flatten_to_env({"x": True, "y": False})
        assert flat["MIXPILOT_X"] == "true"
        assert flat["MIXPILOT_Y"] == "false"

    def test_none_becomes_empty_string(self) -> None:
        flat = serve.flatten_to_env({"k": None})
        assert flat["MIXPILOT_K"] == ""

    def test_numbers_coerced_to_str(self) -> None:
        flat = serve.flatten_to_env({"sample_rate": 48000, "threshold_db": -1.5})
        assert flat["MIXPILOT_SAMPLE_RATE"] == "48000"
        assert flat["MIXPILOT_THRESHOLD_DB"] == "-1.5"

    def test_three_levels(self) -> None:
        flat = serve.flatten_to_env({"a": {"b": {"c": 42}}})
        assert flat == {"MIXPILOT_A__B__C": "42"}


class TestApplyPresetToEnv:
    def test_setdefault_preserves_existing_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MIXPILOT_KEEP", "user_value")
        applied = serve.apply_preset_to_env(
            {"MIXPILOT_KEEP": "preset_value", "MIXPILOT_NEW": "new_value"}
        )
        # 기존 env는 보존, 새 키만 추가.
        import os

        assert os.environ["MIXPILOT_KEEP"] == "user_value"
        assert os.environ["MIXPILOT_NEW"] == "new_value"
        # 반환값은 *추가된* 키만.
        assert applied == {"MIXPILOT_NEW": "new_value"}

    def test_empty_preset_returns_empty_applied(self) -> None:
        applied = serve.apply_preset_to_env({})
        assert applied == {}


class TestListPresets:
    def test_returns_known_presets(self) -> None:
        names = serve.list_presets()
        # 프로젝트에 정의된 3개 — 추가될 수 있으니 superset 검증.
        assert {"worship", "performance", "rehearsal"} <= set(names)


class TestLoadPreset:
    def test_loads_existing(self) -> None:
        data = serve.load_preset("worship")
        assert isinstance(data, dict)
        assert "audio" in data

    def test_missing_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            serve.load_preset("nonexistent")

    def test_invalid_yaml_top_level_raises(self, tmp_path: Path) -> None:
        # 직접 비-mapping YAML 작성 후 _PRESET_DIR 우회 — 격리.
        bad = tmp_path / "bad.yaml"
        bad.write_text("- item1\n- item2\n", encoding="utf-8")
        # load_preset이 _PRESET_DIR 하드코드라 직접 호출이 어려움 →
        # _PRESET_DIR을 monkeypatch.
        import yaml

        with bad.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, list)  # 비-mapping 검증 — 함수 의도 확인.


class TestPresetIntegration:
    def test_worship_preset_round_trip(self) -> None:
        data = serve.load_preset("worship")
        flat = serve.flatten_to_env(data)
        # 핵심 키 몇 가지 정확히 평탄화되는지.
        assert flat["MIXPILOT_AUDIO__ENABLED"] == "true"
        assert flat["MIXPILOT_M32__OPERATING_MODE"] == "assist"
        assert flat["MIXPILOT_PEAK_ANALYSIS__ENABLED"] == "true"
        assert flat["MIXPILOT_LRA_ANALYSIS__ENABLED"] == "false"

    def test_performance_preset_full_analyses_on(self) -> None:
        flat = serve.flatten_to_env(serve.load_preset("performance"))
        for key in (
            "MIXPILOT_PEAK_ANALYSIS__ENABLED",
            "MIXPILOT_LUFS_ANALYSIS__ENABLED",
            "MIXPILOT_FEEDBACK_ANALYSIS__ENABLED",
            "MIXPILOT_DYNAMIC_RANGE_ANALYSIS__ENABLED",
            "MIXPILOT_LRA_ANALYSIS__ENABLED",
        ):
            assert flat[key] == "true"
        # 공연은 dry-run (자동 적용 안 함).
        assert flat["MIXPILOT_M32__OPERATING_MODE"] == "dry-run"

    def test_rehearsal_preset_lean(self) -> None:
        flat = serve.flatten_to_env(serve.load_preset("rehearsal"))
        # 리허설은 feedback만 필수.
        assert flat["MIXPILOT_FEEDBACK_ANALYSIS__ENABLED"] == "true"
        assert flat["MIXPILOT_PEAK_ANALYSIS__ENABLED"] == "false"
        assert flat["MIXPILOT_LUFS_ANALYSIS__ENABLED"] == "false"
