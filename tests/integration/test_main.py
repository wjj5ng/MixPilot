"""main.py 통합 테스트 — TestClient로 /health와 OpenAPI 메타데이터 검증."""

from __future__ import annotations

import os
from pathlib import Path

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

    def test_reports_feedback_analysis_default_false(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["feedback_analysis_enabled"] is False

    def test_reports_peak_analysis_default_false(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["peak_analysis_enabled"] is False

    def test_reports_dr_analysis_default_false(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["dynamic_range_analysis_enabled"] is False

    def test_reports_meter_stream_default_false(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["meter_stream_enabled"] is False

    def test_reports_lra_analysis_default_false(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json()["lra_analysis_enabled"] is False

    def test_response_has_no_unexpected_fields(self, client: TestClient) -> None:
        response = client.get("/health")
        assert set(response.json().keys()) == {
            "status",
            "operating_mode",
            "sample_rate",
            "num_channels",
            "audio_enabled",
            "lufs_analysis_enabled",
            "feedback_analysis_enabled",
            "peak_analysis_enabled",
            "dynamic_range_analysis_enabled",
            "lra_analysis_enabled",
            "phase_analysis_enabled",
            "meter_stream_enabled",
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

    def test_control_dry_run_route_is_documented(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        paths = response.json()["paths"]
        assert "/control/dry-run" in paths
        assert "post" in paths["/control/dry-run"]

    def test_recent_actions_route_is_documented(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        paths = response.json()["paths"]
        assert "/control/recent-actions" in paths
        assert "get" in paths["/control/recent-actions"]


class TestRecentActionsEndpoint:
    """ADR-0008 §3.6 — GET /control/recent-actions."""

    def test_empty_when_no_actions(self, client: TestClient) -> None:
        response = client.get("/control/recent-actions")
        assert response.status_code == 200
        body = response.json()
        assert body["entries"] == []
        assert body["window_seconds"] == 60.0

    def test_lists_recorded_actions(self) -> None:
        from mixpilot.runtime import ActionHistory

        app = create_app(settings=Settings())
        history: ActionHistory = app.state.action_history
        history.add(
            channel_id=5,
            kind="mute",
            osc_messages=[("/ch/05/mix/on", 0)],
            reason="테스트",
        )
        client = TestClient(app)
        body = client.get("/control/recent-actions").json()
        assert len(body["entries"]) == 1
        entry = body["entries"][0]
        assert entry["channel"] == 5
        assert entry["kind"] == "mute"
        assert entry["osc_messages"] == [{"address": "/ch/05/mix/on", "value": 0.0}]
        assert entry["reason"] == "테스트"


class TestChannelMapEndpoint:
    """GET /channels — 현재 채널맵 조회."""

    def test_returns_entries_from_yaml(self, client: TestClient) -> None:
        # 디폴트 settings는 config/channels.yaml을 가리킴 — 프로젝트 fixture 사용.
        response = client.get("/channels")
        assert response.status_code == 200
        body = response.json()
        assert "entries" in body
        # 채널맵에 적어도 1개 엔트리가 있어야 함.
        assert len(body["entries"]) > 0
        # 각 항목 구조 검증.
        first = body["entries"][0]
        assert "channel" in first
        assert "category" in first
        assert "label" in first
        assert isinstance(first["channel"], int)

    def test_returns_known_categories(self, client: TestClient) -> None:
        body = client.get("/channels").json()
        valid_categories = {
            "vocal",
            "preacher",
            "choir",
            "instrument",
            "unknown",
        }
        for entry in body["entries"]:
            assert entry["category"] in valid_categories

    def test_works_without_audio(self) -> None:
        # audio.enabled=False(디폴트)에서도 채널맵 endpoint는 동작.
        app = create_app(settings=Settings())
        client = TestClient(app)
        with client:
            response = client.get("/channels")
        assert response.status_code == 200
        assert len(response.json()["entries"]) > 0

    def test_update_channel_persists(self, tmp_path: Path) -> None:
        # tmp_path에 fresh channels.yaml 작성 후 PUT으로 갱신.
        channels_path = tmp_path / "channels.yaml"
        channels_path.write_text(
            "channels:\n  - id: 1\n    category: vocal\n    label: orig\n",
            encoding="utf-8",
        )
        settings = Settings(channel_map_path=channels_path)
        app = create_app(settings=settings)
        client = TestClient(app)
        with client:
            response = client.put(
                "/channels/1",
                json={"category": "preacher", "label": "설교자 메인"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body == {
            "channel": 1,
            "category": "preacher",
            "label": "설교자 메인",
            "stereo_pair_with": None,
        }
        # YAML이 갱신됐는지 — 새 GET으로.
        with TestClient(app) as c2:
            entries = c2.get("/channels").json()["entries"]
        assert entries[0]["category"] == "preacher"
        assert entries[0]["label"] == "설교자 메인"

    def test_update_channel_rejects_invalid_category(self, tmp_path: Path) -> None:
        channels_path = tmp_path / "channels.yaml"
        channels_path.write_text(
            "channels:\n  - id: 1\n    category: vocal\n",
            encoding="utf-8",
        )
        settings = Settings(channel_map_path=channels_path)
        app = create_app(settings=settings)
        client = TestClient(app)
        with client:
            response = client.put(
                "/channels/1",
                json={"category": "drum", "label": "x"},
            )
        assert response.status_code == 400
        assert "invalid category" in response.json()["detail"]

    def test_update_channel_creates_new_id(self, tmp_path: Path) -> None:
        channels_path = tmp_path / "channels.yaml"
        channels_path.write_text("channels: []\n", encoding="utf-8")
        settings = Settings(channel_map_path=channels_path)
        app = create_app(settings=settings)
        client = TestClient(app)
        with client:
            response = client.put(
                "/channels/7",
                json={"category": "choir", "label": "성가대 TEN"},
            )
        assert response.status_code == 200
        # 1개 entry 확인.
        with TestClient(app) as c2:
            entries = c2.get("/channels").json()["entries"]
        assert len(entries) == 1
        assert entries[0]["channel"] == 7


class TestRulesEndpoint:
    """GET /control/rules + PUT /control/rules/{name}."""

    def test_lists_all_rules(self, client: TestClient) -> None:
        body = client.get("/control/rules").json()
        names = {r["name"] for r in body["rules"]}
        assert names == {
            "loudness",
            "lufs",
            "peak",
            "feedback",
            "dynamic_range",
            "lra",
            "phase",
        }

    def test_default_state_reflects_config(self, client: TestClient) -> None:
        # 디폴트 Settings에서 loudness만 True, 나머지 모두 False.
        body = client.get("/control/rules").json()
        states = {r["name"]: r["enabled"] for r in body["rules"]}
        assert states["loudness"] is True
        for name in ("lufs", "peak", "feedback", "dynamic_range", "lra"):
            assert states[name] is False

    def test_put_toggles_rule(self, client: TestClient) -> None:
        response = client.put("/control/rules/peak", json={"enabled": True})
        assert response.status_code == 200
        assert response.json() == {"name": "peak", "enabled": True}
        # GET이 새 상태 반영.
        states = {
            r["name"]: r["enabled"]
            for r in client.get("/control/rules").json()["rules"]
        }
        assert states["peak"] is True

    def test_put_rejects_unknown_rule(self, client: TestClient) -> None:
        response = client.put("/control/rules/madeup", json={"enabled": True})
        assert response.status_code == 400
        assert "unknown rule" in response.json()["detail"]

    def test_put_persists_across_requests(self, client: TestClient) -> None:
        # 같은 app 인스턴스에서 mutation이 보존되는지 검증.
        client.put("/control/rules/lufs", json={"enabled": True})
        client.put("/control/rules/peak", json={"enabled": True})
        client.put("/control/rules/loudness", json={"enabled": False})
        states = {
            r["name"]: r["enabled"]
            for r in client.get("/control/rules").json()["rules"]
        }
        assert states["lufs"] is True
        assert states["peak"] is True
        assert states["loudness"] is False


class TestAuditLogEndpoint:
    """ADR-0008 §3 — GET /control/audit-log/recent."""

    def test_disabled_when_no_path(self, client: TestClient) -> None:
        # 기본 Settings는 audit_log_path=None → enabled=false.
        response = client.get("/control/audit-log/recent")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["entries"] == []

    def test_returns_entries_from_jsonl(self, tmp_path: Path) -> None:
        from mixpilot.infra import AuditLogger, AuditOutcome

        audit_path = tmp_path / "audit.jsonl"
        settings = Settings(audit_log_path=audit_path)
        app = create_app(settings=settings)

        # 직접 logger 객체에 write — controller wiring 우회.
        ts_iter = iter([1.0, 2.0, 3.0])
        logger = AuditLogger(path=audit_path, clock=lambda: next(ts_iter))
        from mixpilot.domain import (
            ChannelId,
            Recommendation,
            RecommendationKind,
            Source,
            SourceCategory,
        )

        def make_rec(ch: int) -> Recommendation:
            return Recommendation(
                target=Source(ChannelId(ch), SourceCategory.VOCAL, f"vox{ch}"),
                kind=RecommendationKind.GAIN_ADJUST,
                params={},
                confidence=0.8,
                reason=f"테스트 ch{ch}",
            )

        logger.record(
            make_rec(1),
            outcome=AuditOutcome.APPLIED,
            effective_mode="auto",
            osc_messages=[("/ch/01/mix/fader", 0.5)],
        )
        logger.record(
            make_rec(2),
            outcome=AuditOutcome.BLOCKED_GUARD,
            effective_mode="auto",
            reason="rate limit",
        )
        logger.record(
            make_rec(3),
            outcome=AuditOutcome.BLOCKED_POLICY,
            effective_mode="assist",
            reason="confidence below threshold",
        )

        client = TestClient(app)
        body = client.get("/control/audit-log/recent").json()
        assert body["enabled"] is True
        assert len(body["entries"]) == 3
        # 최신 → 과거 순.
        outcomes = [e["outcome"] for e in body["entries"]]
        assert outcomes == ["blocked_policy", "blocked_guard", "applied"]
        # applied 항목의 OSC payload 확인.
        applied = body["entries"][-1]
        assert applied["osc_messages"] == [
            {"address": "/ch/01/mix/fader", "value": 0.5}
        ]
        assert applied["label"] == "vox1"

    def test_limit_query_param(self, tmp_path: Path) -> None:
        from mixpilot.infra import AuditLogger, AuditOutcome

        audit_path = tmp_path / "audit.jsonl"
        settings = Settings(audit_log_path=audit_path)
        app = create_app(settings=settings)
        ts_iter = iter([float(i) for i in range(5)])
        logger = AuditLogger(path=audit_path, clock=lambda: next(ts_iter))
        from mixpilot.domain import (
            ChannelId,
            Recommendation,
            RecommendationKind,
            Source,
            SourceCategory,
        )

        for _ in range(5):
            logger.record(
                Recommendation(
                    target=Source(ChannelId(1), SourceCategory.VOCAL, "v"),
                    kind=RecommendationKind.INFO,
                    params={},
                    confidence=0.5,
                    reason="x",
                ),
                outcome=AuditOutcome.APPLIED,
                effective_mode="auto",
            )

        client = TestClient(app)
        body = client.get("/control/audit-log/recent?limit=2").json()
        assert len(body["entries"]) == 2
        # 5개 중 마지막 2개 → 타임스탬프 4.0, 3.0.
        assert [e["timestamp"] for e in body["entries"]] == [4.0, 3.0]


class TestKillSwitchEndpoint:
    """ADR-0008 §3 — POST /control/dry-run."""

    def test_without_controller_returns_helpful_status(
        self, client: TestClient
    ) -> None:
        # audio.enabled=False 디폴트 → controller는 None.
        response = client.post("/control/dry-run")
        assert response.status_code == 200
        body = response.json()
        assert "no controller" in body["status"]
        assert body["effective_mode"] is None

    def test_with_controller_forces_dry_run(self) -> None:
        # 가짜 controller를 app.state에 주입해 동작 확인.
        from unittest.mock import MagicMock

        from mixpilot.config import OperatingMode

        app = create_app(settings=Settings())
        fake_controller = MagicMock()
        fake_controller.effective_mode = OperatingMode.DRY_RUN
        app.state.controller = fake_controller
        client = TestClient(app)

        response = client.post("/control/dry-run")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "forced dry-run"
        assert body["effective_mode"] == "dry-run"
        fake_controller.force_dry_run.assert_called_once()


class TestCors:
    def test_default_no_cors_header(self, client: TestClient) -> None:
        # 디폴트 (dev_cors_enabled=False)에서는 CORS 미들웨어 미장착 — 헤더 없음.
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert "access-control-allow-origin" not in response.headers

    def test_dev_cors_enabled_allows_vite_origin(self) -> None:
        settings = Settings()
        settings.dev_cors_enabled = True  # type: ignore[misc]
        client = TestClient(create_app(settings=settings))
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:5173"
        )

    # NOTE: SSE 본문 라운드트립(open → publish → stream → assert)은 sync
    # TestClient + asyncio.Queue 조합이 안정적이지 않다(thread-safe 아님,
    # iter_lines 블로킹). 발행/구독/직렬화 흐름은 단위 테스트로 커버:
    # tests/unit/test_main_helpers.py 의 TestRecommendationBroker /
    # TestSerializeRecommendation. 향후 httpx.AsyncClient + ASGITransport로
    # 진짜 async 통합 테스트 추가 예정.
