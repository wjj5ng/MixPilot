"""main.py 통합 테스트 — TestClient로 /health와 OpenAPI 메타데이터 검증."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from mixpilot.config import Settings
from mixpilot.main import create_app


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """MIXPILOT_* 환경 변수 제거 — 디폴트 설정으로 테스트."""
    for k in [k for k in os.environ if k.startswith("MIXPILOT_")]:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def client() -> TestClient:
    app = create_app(settings=Settings())
    return TestClient(app)


class TestHealth:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_status_field_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["status"] == "ok"

    def test_reports_default_operating_mode(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["operating_mode"] == "dry-run"

    def test_reports_audio_defaults(self, client: TestClient) -> None:
        response = client.get("/health")
        body = response.json()
        assert body["sample_rate"] == 48000
        assert body["num_channels"] == 32

    def test_reports_audio_enabled_default_false(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["audio_enabled"] is False

    def test_reports_lufs_analysis_default_false(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["lufs_analysis_enabled"] is False

    def test_response_has_no_unexpected_fields(self, client: TestClient) -> None:
        response = client.get("/health")
        assert set(response.json().keys()) == {
            "status",
            "operating_mode",
            "sample_rate",
            "num_channels",
            "audio_enabled",
            "lufs_analysis_enabled",
        }


class TestSettingsInjection:
    def test_injected_settings_reflected_in_health(self) -> None:
        # 명시 주입한 settings가 응답에 반영되는지 — 캐시 우회 확인.
        custom = Settings()
        custom.audio.sample_rate = 44100  # type: ignore[misc]
        client = TestClient(create_app(settings=custom))
        body = client.get("/health").json()
        assert body["sample_rate"] == 44100


class TestOpenAPI:
    def test_openapi_title_and_version(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        info = response.json()["info"]
        assert info["title"] == "MixPilot"
        assert info["version"] == "0.1.0"

    def test_health_route_is_documented(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        paths = response.json()["paths"]
        assert "/health" in paths
        assert "get" in paths["/health"]

    def test_recommendations_route_is_documented(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        paths = response.json()["paths"]
        assert "/recommendations" in paths
        assert "get" in paths["/recommendations"]

    # NOTE: SSE 본문 라운드트립(open → publish → stream → assert)은 sync
    # TestClient + asyncio.Queue 조합이 안정적이지 않다(thread-safe 아님,
    # iter_lines 블로킹). 발행/구독/직렬화 흐름은 단위 테스트로 커버:
    # tests/unit/test_main_helpers.py 의 TestRecommendationBroker /
    # TestSerializeRecommendation. 향후 httpx.AsyncClient + ASGITransport로
    # 진짜 async 통합 테스트 추가 예정.
