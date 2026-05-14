"""scripts.export_openapi 단위 테스트 — 스키마 무결성과 CLI 입출력 검증."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mixpilot.scripts.export_openapi import export_openapi, main


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """MIXPILOT_* 환경 변수 제거 — 디폴트 설정으로 격리."""
    for k in [k for k in os.environ if k.startswith("MIXPILOT_")]:
        monkeypatch.delenv(k, raising=False)


class TestExportOpenapi:
    def test_returns_openapi_dict(self) -> None:
        schema = export_openapi()
        assert "openapi" in schema
        assert isinstance(schema["openapi"], str)
        assert schema["openapi"].startswith("3.")

    def test_includes_known_paths(self) -> None:
        schema = export_openapi()
        paths = schema["paths"]
        assert "/health" in paths
        assert "/recommendations" in paths

    def test_includes_known_schemas(self) -> None:
        schema = export_openapi()
        schemas = schema["components"]["schemas"]
        assert "HealthResponse" in schemas
        assert "RecommendationEvent" in schemas

    def test_health_response_has_expected_fields(self) -> None:
        schema = export_openapi()
        props = schema["components"]["schemas"]["HealthResponse"]["properties"]
        assert set(props.keys()) == {
            "status",
            "operating_mode",
            "sample_rate",
            "num_channels",
            "audio_enabled",
            "lufs_analysis_enabled",
            "feedback_analysis_enabled",
            "peak_analysis_enabled",
            "dynamic_range_analysis_enabled",
            "meter_stream_enabled",
        }

    def test_recommendation_event_has_expected_fields(self) -> None:
        schema = export_openapi()
        props = schema["components"]["schemas"]["RecommendationEvent"]["properties"]
        assert set(props.keys()) == {
            "channel",
            "category",
            "label",
            "kind",
            "params",
            "confidence",
            "reason",
        }

    def test_deterministic(self) -> None:
        a = export_openapi()
        b = export_openapi()
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


class TestMainCli:
    def test_writes_to_file_when_output_given(self, tmp_path: Path) -> None:
        out = tmp_path / "openapi.json"
        code = main(["-o", str(out)])
        assert code == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "/health" in data["paths"]

    def test_writes_to_stdout_when_no_output(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main([])
        assert code == 0
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert "/recommendations" in data["paths"]

    def test_output_is_valid_json(self, tmp_path: Path) -> None:
        out = tmp_path / "schema.json"
        main(["--output", str(out)])
        # 두 번째 파싱이 실패 없이 되면 유효한 JSON.
        json.loads(out.read_text(encoding="utf-8"))
