"""RuleToggles 단위 테스트 — 초기화·토글·snapshot 격리."""

from __future__ import annotations

import pytest

from mixpilot.runtime.rule_toggles import RULE_NAMES, RuleToggles


class TestFromConfigFlags:
    def test_default_all_off_except_loudness(self) -> None:
        toggles = RuleToggles.from_config_flags()
        # loudness만 디폴트 True.
        assert toggles.is_enabled("loudness") is True
        for name in ("lufs", "peak", "feedback", "dynamic_range", "lra"):
            assert toggles.is_enabled(name) is False

    def test_all_explicit_true(self) -> None:
        toggles = RuleToggles.from_config_flags(
            loudness=True,
            lufs=True,
            peak=True,
            feedback=True,
            dynamic_range=True,
            lra=True,
        )
        for name in RULE_NAMES:
            assert toggles.is_enabled(name) is True


class TestSetEnabled:
    def test_toggles_flip_value(self) -> None:
        toggles = RuleToggles.from_config_flags(peak=False)
        assert toggles.is_enabled("peak") is False
        toggles.set_enabled("peak", True)
        assert toggles.is_enabled("peak") is True
        toggles.set_enabled("peak", False)
        assert toggles.is_enabled("peak") is False

    def test_unknown_rule_raises(self) -> None:
        toggles = RuleToggles.from_config_flags()
        with pytest.raises(ValueError, match="unknown rule"):
            toggles.set_enabled("nonexistent", True)

    def test_coerces_truthy_values_to_bool(self) -> None:
        toggles = RuleToggles.from_config_flags()
        toggles.set_enabled("peak", 1)  # type: ignore[arg-type]
        assert toggles.is_enabled("peak") is True
        toggles.set_enabled("peak", "")  # type: ignore[arg-type]
        assert toggles.is_enabled("peak") is False


class TestSnapshot:
    def test_returns_all_rules(self) -> None:
        toggles = RuleToggles.from_config_flags(lufs=True, peak=True)
        snap = toggles.snapshot()
        assert set(snap.keys()) == set(RULE_NAMES)
        assert snap["lufs"] is True
        assert snap["peak"] is True

    def test_snapshot_is_isolated_copy(self) -> None:
        # snapshot 호출 시점의 상태가 후속 변경에 영향받지 않아야 함.
        toggles = RuleToggles.from_config_flags(peak=True)
        snap = toggles.snapshot()
        toggles.set_enabled("peak", False)
        # snap에 변경이 새지 않음.
        assert snap["peak"] is True
        # 새 snapshot은 새 값.
        assert toggles.snapshot()["peak"] is False


class TestConstructor:
    def test_extra_keys_ignored(self) -> None:
        toggles = RuleToggles({"loudness": True, "made_up": True})  # type: ignore[arg-type]
        # 알려진 룰만 보유.
        snap = toggles.snapshot()
        assert "made_up" not in snap
        assert set(snap.keys()) == set(RULE_NAMES)

    def test_missing_keys_default_false(self) -> None:
        toggles = RuleToggles({"peak": True})
        assert toggles.is_enabled("peak") is True
        # 누락 키는 False.
        assert toggles.is_enabled("lufs") is False
