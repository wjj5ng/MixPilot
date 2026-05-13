"""infra.m32_control 단위 테스트 — 운영 모드 분기 + Recommendation → OSC 변환."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mixpilot.config import M32Config, OperatingMode
from mixpilot.domain import (
    ChannelId,
    Recommendation,
    RecommendationKind,
    Source,
    SourceCategory,
)
from mixpilot.infra import AuditLogger, AuditOutcome
from mixpilot.infra.m32_control import (
    MAX_DELTA_DB,
    MAX_FEEDBACK_CUT_DB,
    M32OscController,
    _clamp_delta_db,
)
from mixpilot.runtime import AutoGuard


class FakeOscClient:
    """sent 메시지를 기록하는 테스트용 OSC 클라이언트."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, float | int]] = []

    def send_message(self, address: str, value: float | int) -> None:
        self.sent.append((address, value))


def _rec(
    kind: RecommendationKind,
    *,
    channel: int = 1,
    category: SourceCategory = SourceCategory.VOCAL,
    confidence: float = 0.9,
    params: dict[str, float] | None = None,
    reason: str = "test",
) -> Recommendation:
    return Recommendation(
        target=Source(ChannelId(channel), category),
        kind=kind,
        params=params or {},
        confidence=confidence,
        reason=reason,
    )


class TestShouldApplyKindDispatch:
    """ADR-0008 §1 Kind x Mode 매트릭스."""

    @pytest.mark.parametrize("mode", list(OperatingMode))
    def test_info_never_applied_in_any_mode(self, mode: OperatingMode) -> None:
        cfg = M32Config(operating_mode=mode, auto_apply_confidence_threshold=0.0)
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl._should_apply(_rec(RecommendationKind.INFO, confidence=1.0)) is False

    @pytest.mark.parametrize("kind", list(RecommendationKind))
    def test_dry_run_blocks_all_kinds(self, kind: RecommendationKind) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.DRY_RUN, auto_apply_confidence_threshold=0.0
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl._should_apply(_rec(kind, confidence=1.0)) is False

    @pytest.mark.parametrize(
        "kind",
        [
            RecommendationKind.GAIN_ADJUST,
            RecommendationKind.UNMUTE,
            RecommendationKind.FEEDBACK_ALERT,
        ],
    )
    def test_assist_allows_select_kinds(self, kind: RecommendationKind) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.ASSIST,
            auto_apply_confidence_threshold=0.5,
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl._should_apply(_rec(kind, confidence=0.9)) is True

    @pytest.mark.parametrize(
        "kind", [RecommendationKind.MUTE, RecommendationKind.EQ_ADJUST]
    )
    def test_assist_blocks_disruptive_kinds(self, kind: RecommendationKind) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.ASSIST,
            auto_apply_confidence_threshold=0.0,
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl._should_apply(_rec(kind, confidence=1.0)) is False

    @pytest.mark.parametrize(
        "kind",
        [
            RecommendationKind.GAIN_ADJUST,
            RecommendationKind.UNMUTE,
            RecommendationKind.FEEDBACK_ALERT,
            RecommendationKind.MUTE,
            RecommendationKind.EQ_ADJUST,
        ],
    )
    def test_auto_allows_all_non_info(self, kind: RecommendationKind) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.AUTO, auto_apply_confidence_threshold=0.5
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl._should_apply(_rec(kind, confidence=0.9)) is True


class TestConfidenceThresholdUniversal:
    """ADR-0008 §3 — confidence 임계는 모든 모드에 적용."""

    def test_assist_below_threshold_blocked(self) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.ASSIST,
            auto_apply_confidence_threshold=0.9,
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert (
            ctl._should_apply(_rec(RecommendationKind.GAIN_ADJUST, confidence=0.5))
            is False
        )

    def test_auto_below_threshold_blocked(self) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.AUTO,
            auto_apply_confidence_threshold=0.9,
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert (
            ctl._should_apply(_rec(RecommendationKind.GAIN_ADJUST, confidence=0.5))
            is False
        )

    def test_boundary_at_threshold_allowed(self) -> None:
        cfg = M32Config(
            operating_mode=OperatingMode.AUTO,
            auto_apply_confidence_threshold=0.9,
        )
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert (
            ctl._should_apply(_rec(RecommendationKind.GAIN_ADJUST, confidence=0.9))
            is True
        )


class TestTranslate:
    def _ctl(self) -> M32OscController:
        return M32OscController(
            M32Config(operating_mode=OperatingMode.AUTO), osc_client=FakeOscClient()
        )

    def test_mute(self) -> None:
        msgs = list(self._ctl()._translate(_rec(RecommendationKind.MUTE, channel=3)))
        assert msgs == [("/ch/03/mix/on", 0)]

    def test_unmute(self) -> None:
        msgs = list(self._ctl()._translate(_rec(RecommendationKind.UNMUTE, channel=7)))
        assert msgs == [("/ch/07/mix/on", 1)]

    def test_gain_adjust_with_fader(self) -> None:
        rec = _rec(RecommendationKind.GAIN_ADJUST, channel=2, params={"fader": 0.6})
        msgs = list(self._ctl()._translate(rec))
        assert msgs == [("/ch/02/mix/fader", 0.6)]

    def test_gain_adjust_clamps_fader_to_unit_interval(self) -> None:
        ctl = self._ctl()
        msgs_hi = list(
            ctl._translate(
                _rec(RecommendationKind.GAIN_ADJUST, channel=4, params={"fader": 1.5})
            )
        )
        msgs_lo = list(
            ctl._translate(
                _rec(RecommendationKind.GAIN_ADJUST, channel=4, params={"fader": -0.3})
            )
        )
        assert msgs_hi == [("/ch/04/mix/fader", 1.0)]
        assert msgs_lo == [("/ch/04/mix/fader", 0.0)]

    def test_gain_adjust_without_fader_param_emits_nothing(self) -> None:
        # delta_db only는 아직 미지원 — 메시지 없음(경고 로깅).
        rec = _rec(RecommendationKind.GAIN_ADJUST, params={"delta_db": -2.0})
        assert list(self._ctl()._translate(rec)) == []

    def test_info_emits_nothing(self) -> None:
        assert list(self._ctl()._translate(_rec(RecommendationKind.INFO))) == []

    def test_unimplemented_kinds_emit_nothing(self) -> None:
        ctl = self._ctl()
        for kind in (
            RecommendationKind.FEEDBACK_ALERT,
            RecommendationKind.EQ_ADJUST,
        ):
            assert list(ctl._translate(_rec(kind))) == []

    @pytest.mark.parametrize(
        ("channel", "expected_prefix"),
        [(1, "/ch/01"), (10, "/ch/10"), (32, "/ch/32")],
    )
    def test_channel_padded_to_two_digits(
        self, channel: int, expected_prefix: str
    ) -> None:
        msgs = list(
            self._ctl()._translate(_rec(RecommendationKind.MUTE, channel=channel))
        )
        assert msgs[0][0].startswith(expected_prefix)


class TestApply:
    def test_dry_run_sends_nothing(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(operating_mode=OperatingMode.DRY_RUN), osc_client=client
        )
        asyncio.run(ctl.apply(_rec(RecommendationKind.MUTE, confidence=1.0)))
        assert client.sent == []

    def test_info_sends_nothing_even_in_auto(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(operating_mode=OperatingMode.AUTO), osc_client=client
        )
        asyncio.run(ctl.apply(_rec(RecommendationKind.INFO, confidence=1.0)))
        assert client.sent == []

    def test_auto_sends_mute(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.AUTO,
                auto_apply_confidence_threshold=0.5,
            ),
            osc_client=client,
        )
        asyncio.run(
            ctl.apply(_rec(RecommendationKind.MUTE, channel=5, confidence=0.95))
        )
        assert client.sent == [("/ch/05/mix/on", 0)]

    def test_assist_mute_blocked_by_kind(self) -> None:
        # MUTE는 ASSIST에서 자동 적용 안 됨 (confidence 무관, ADR-0008 §1).
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.ASSIST,
                auto_apply_confidence_threshold=0.0,
            ),
            osc_client=client,
        )
        asyncio.run(ctl.apply(_rec(RecommendationKind.MUTE, confidence=1.0)))
        assert client.sent == []

    def test_assist_gain_adjust_below_threshold_skips(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.ASSIST,
                auto_apply_confidence_threshold=0.9,
            ),
            osc_client=client,
        )
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.5,
                    params={"fader": 0.7},
                )
            )
        )
        assert client.sent == []

    def test_assist_gain_adjust_above_threshold_sends(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.ASSIST,
                auto_apply_confidence_threshold=0.9,
            ),
            osc_client=client,
        )
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.95,
                    channel=12,
                    params={"fader": 0.7},
                )
            )
        )
        assert client.sent == [("/ch/12/mix/fader", 0.7)]


class TestMagnitudeCaps:
    """ADR-0008 §3.2 변화량 캡 — 클램프 헬퍼·delta_db 경로 클램핑.

    실 OSC 송신은 delta_db 적용에 현재 페이더 읽기가 필요해 미구현
    (docs/hardware-dependent.md #2). 여기서는 *클램프 정책*만 검증한다.
    """

    def test_constants_match_adr(self) -> None:
        assert MAX_DELTA_DB == 3.0
        assert MAX_FEEDBACK_CUT_DB == 2.0

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (0.0, 0.0),
            (1.5, 1.5),
            (-1.5, -1.5),
            (3.0, 3.0),
            (-3.0, -3.0),
            (5.0, 3.0),
            (-5.0, -3.0),
            (10.0, 3.0),
            (-10.0, -3.0),
        ],
    )
    def test_clamp_delta_db(self, raw: float, expected: float) -> None:
        assert _clamp_delta_db(raw) == expected

    def test_clamp_custom_cap(self) -> None:
        assert _clamp_delta_db(5.0, cap=MAX_FEEDBACK_CUT_DB) == 2.0
        assert _clamp_delta_db(-5.0, cap=MAX_FEEDBACK_CUT_DB) == -2.0

    def test_gain_adjust_with_delta_emits_nothing_yet(self) -> None:
        # delta_db 경로는 현재 페이더 읽기 미구현 → 송신 없음 (캡만 로그).
        ctl = M32OscController(
            M32Config(operating_mode=OperatingMode.AUTO),
            osc_client=FakeOscClient(),
        )
        msgs = list(
            ctl._translate(
                _rec(RecommendationKind.GAIN_ADJUST, params={"delta_db": 10.0})
            )
        )
        assert msgs == []

    def test_gain_adjust_with_absolute_fader_still_works(self) -> None:
        # 절대 fader 경로는 여전히 정상 — 캡과 무관.
        ctl = M32OscController(
            M32Config(operating_mode=OperatingMode.AUTO),
            osc_client=FakeOscClient(),
        )
        msgs = list(
            ctl._translate(
                _rec(RecommendationKind.GAIN_ADJUST, channel=3, params={"fader": 0.5})
            )
        )
        assert msgs == [("/ch/03/mix/fader", 0.5)]


class TestKillSwitch:
    """ADR-0008 §3 킬 스위치 — force_dry_run / clear_override."""

    def test_initial_effective_mode_matches_config(self) -> None:
        cfg = M32Config(operating_mode=OperatingMode.AUTO)
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        assert ctl.effective_mode is OperatingMode.AUTO

    def test_force_dry_run_overrides_effective_mode(self) -> None:
        cfg = M32Config(operating_mode=OperatingMode.AUTO)
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        ctl.force_dry_run()
        assert ctl.effective_mode is OperatingMode.DRY_RUN

    def test_force_dry_run_blocks_subsequent_apply(self) -> None:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.AUTO,
                auto_apply_confidence_threshold=0.0,
            ),
            osc_client=client,
        )
        ctl.force_dry_run()
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=1.0,
                    params={"fader": 0.5},
                )
            )
        )
        assert client.sent == []

    def test_clear_override_restores_config_mode(self) -> None:
        cfg = M32Config(operating_mode=OperatingMode.AUTO)
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        ctl.force_dry_run()
        ctl.clear_override()
        assert ctl.effective_mode is OperatingMode.AUTO

    def test_clear_override_when_no_override_is_safe(self) -> None:
        cfg = M32Config(operating_mode=OperatingMode.AUTO)
        ctl = M32OscController(cfg, osc_client=FakeOscClient())
        # override 없이 호출해도 예외 없이 종료.
        ctl.clear_override()
        assert ctl.effective_mode is OperatingMode.AUTO


class TestAutoGuardIntegration:
    """ADR-0008 §3 — AutoGuard 연동."""

    def _ctl(
        self, *, auto_guard: AutoGuard | None = None, threshold: float = 0.5
    ) -> tuple[M32OscController, FakeOscClient]:
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.AUTO,
                auto_apply_confidence_threshold=threshold,
            ),
            osc_client=client,
            auto_guard=auto_guard,
        )
        return ctl, client

    def test_no_guard_means_no_extra_check(self) -> None:
        ctl, client = self._ctl()
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.99,
                    channel=1,
                    params={"fader": 0.5},
                )
            )
        )
        assert client.sent == [("/ch/01/mix/fader", 0.5)]

    def test_permissive_guard_passes_through(self) -> None:
        guard = AutoGuard(bootstrap_silence_seconds=0.0)
        ctl, client = self._ctl(auto_guard=guard)
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.99,
                    channel=1,
                    params={"fader": 0.5},
                )
            )
        )
        assert client.sent == [("/ch/01/mix/fader", 0.5)]

    def test_guard_during_bootstrap_blocks_send(self) -> None:
        # 무한히 부트스트랩 침묵 — 항상 차단.
        guard = AutoGuard(bootstrap_silence_seconds=10_000.0)
        ctl, client = self._ctl(auto_guard=guard)
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.99,
                    channel=1,
                    params={"fader": 0.5},
                )
            )
        )
        assert client.sent == []

    def test_guard_consumes_quota_only_on_apply(self) -> None:
        # 정책 미통과(예: INFO)는 가드까지 가지 않아 세션 카운터 미증가.
        guard = AutoGuard(bootstrap_silence_seconds=0.0)
        ctl, _ = self._ctl(auto_guard=guard)
        asyncio.run(ctl.apply(_rec(RecommendationKind.INFO, confidence=1.0)))
        assert guard.session_action_count == 0


class TestAuditIntegration:
    """ADR-0008 §3 — AuditLogger 연동."""

    def _ctl_with_audit(
        self, tmp_path: Path, *, mode: OperatingMode = OperatingMode.AUTO
    ) -> tuple[M32OscController, FakeOscClient, Path]:
        path = tmp_path / "audit.jsonl"
        logger = AuditLogger(path=path, clock=lambda: 1000.0)
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=mode,
                auto_apply_confidence_threshold=0.5,
            ),
            osc_client=client,
            audit_logger=logger,
        )
        return ctl, client, path

    def _read_records(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text("utf-8").splitlines()]

    def test_applied_action_logged_as_applied(self, tmp_path: Path) -> None:
        ctl, _, path = self._ctl_with_audit(tmp_path)
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.99,
                    channel=2,
                    params={"fader": 0.5},
                )
            )
        )
        recs = self._read_records(path)
        assert len(recs) == 1
        assert recs[0]["outcome"] == AuditOutcome.APPLIED.value
        assert recs[0]["osc_messages"] == [["/ch/02/mix/fader", 0.5]]

    def test_policy_block_logged_as_blocked_policy(self, tmp_path: Path) -> None:
        ctl, _, path = self._ctl_with_audit(tmp_path)
        asyncio.run(ctl.apply(_rec(RecommendationKind.INFO, confidence=1.0)))
        recs = self._read_records(path)
        assert len(recs) == 1
        assert recs[0]["outcome"] == AuditOutcome.BLOCKED_POLICY.value
        assert "kind info not allowed" in recs[0]["reason"]

    def test_below_threshold_logged_as_blocked_policy(self, tmp_path: Path) -> None:
        ctl, _, path = self._ctl_with_audit(tmp_path)
        asyncio.run(ctl.apply(_rec(RecommendationKind.GAIN_ADJUST, confidence=0.1)))
        recs = self._read_records(path)
        assert len(recs) == 1
        assert recs[0]["outcome"] == AuditOutcome.BLOCKED_POLICY.value
        assert "confidence" in recs[0]["reason"]

    def test_guard_block_logged_as_blocked_guard(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        logger = AuditLogger(path=path, clock=lambda: 1000.0)
        client = FakeOscClient()
        # 무한 부트스트랩 — 항상 가드 차단.
        guard = AutoGuard(bootstrap_silence_seconds=10_000.0)
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.AUTO,
                auto_apply_confidence_threshold=0.0,
            ),
            osc_client=client,
            auto_guard=guard,
            audit_logger=logger,
        )
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.99,
                    params={"fader": 0.5},
                )
            )
        )
        recs = self._read_records(path)
        assert len(recs) == 1
        assert recs[0]["outcome"] == AuditOutcome.BLOCKED_GUARD.value
        assert "bootstrap" in recs[0]["reason"]

    def test_no_logger_means_no_file_writes(self, tmp_path: Path) -> None:
        # audit_logger 없이도 정상 동작 — 어떤 파일도 생성되지 않음.
        client = FakeOscClient()
        ctl = M32OscController(
            M32Config(
                operating_mode=OperatingMode.AUTO,
                auto_apply_confidence_threshold=0.0,
            ),
            osc_client=client,
        )
        asyncio.run(
            ctl.apply(
                _rec(
                    RecommendationKind.GAIN_ADJUST,
                    confidence=0.99,
                    params={"fader": 0.5},
                )
            )
        )
        # tmp_path 안에 어떤 파일도 없어야 함.
        assert list(tmp_path.iterdir()) == []
