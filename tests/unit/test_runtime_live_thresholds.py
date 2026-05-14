"""runtime.live_thresholds 단위 테스트 — in-place mutation + dict 참조 유지."""

from __future__ import annotations

from mixpilot.runtime.live_thresholds import LiveThresholds


class TestDefaults:
    def test_default_construction(self) -> None:
        lt = LiveThresholds()
        assert lt.rms_targets == {}
        assert lt.lufs_targets == {}
        assert lt.peak_headroom_threshold_dbfs == -1.0
        assert lt.peak_persistence_frames == 1
        assert lt.dynamic_range_persistence_frames == 1
        assert lt.feedback_pnr_threshold_db == 15.0


class TestApplyThresholdSettings:
    def _apply(self, lt: LiveThresholds, **overrides: object) -> None:
        defaults: dict[str, object] = {
            "rms_targets": {"vocal": -18.0, "unknown": -22.0},
            "lufs_targets": {"vocal": -16.0, "unknown": -23.0},
            "peak_headroom_threshold_dbfs": -2.0,
            "peak_oversample": 4,
            "peak_persistence_frames": 3,
            "dynamic_range_low_threshold_db": 5.0,
            "dynamic_range_high_threshold_db": 25.0,
            "dynamic_range_silence_threshold_db": 0.4,
            "dynamic_range_persistence_frames": 2,
            "lra_low_threshold_lu": 4.0,
            "lra_high_threshold_lu": 18.0,
            "lra_silence_threshold_lu": 0.05,
            "phase_warn_threshold": -0.4,
            "feedback_pnr_threshold_db": 12.5,
        }
        defaults.update(overrides)
        lt.apply_threshold_settings(**defaults)  # type: ignore[arg-type]

    def test_applies_all_fields(self) -> None:
        lt = LiveThresholds()
        self._apply(lt)
        assert lt.peak_headroom_threshold_dbfs == -2.0
        assert lt.peak_persistence_frames == 3
        assert lt.dynamic_range_low_threshold_db == 5.0
        assert lt.dynamic_range_persistence_frames == 2
        assert lt.lra_low_threshold_lu == 4.0
        assert lt.phase_warn_threshold == -0.4
        assert lt.feedback_pnr_threshold_db == 12.5
        assert lt.rms_targets == {"vocal": -18.0, "unknown": -22.0}
        assert lt.lufs_targets == {"vocal": -16.0, "unknown": -23.0}

    def test_dict_references_preserved(self) -> None:
        """processing loop이 갖는 rms_targets 참조가 유지되어야 한다."""
        lt = LiveThresholds()
        # 첫 적용 후 dict 객체 ref 캡처.
        self._apply(lt, rms_targets={"vocal": -18.0})
        rms_ref = lt.rms_targets
        lufs_ref = lt.lufs_targets
        # 두 번째 적용 — 동일 dict 객체가 in-place 갱신되어야.
        self._apply(
            lt,
            rms_targets={"vocal": -20.0, "preacher": -19.0},
            lufs_targets={"vocal": -14.0},
        )
        assert lt.rms_targets is rms_ref
        assert lt.lufs_targets is lufs_ref
        assert lt.rms_targets["vocal"] == -20.0
        assert "preacher" in lt.rms_targets
        assert lt.lufs_targets == {"vocal": -14.0}


class TestSnapshot:
    def test_snapshot_returns_all_fields(self) -> None:
        lt = LiveThresholds()
        snap = lt.snapshot()
        expected_keys = {
            "rms_targets",
            "lufs_targets",
            "peak_headroom_threshold_dbfs",
            "peak_oversample",
            "peak_persistence_frames",
            "dynamic_range_low_threshold_db",
            "dynamic_range_high_threshold_db",
            "dynamic_range_silence_threshold_db",
            "dynamic_range_persistence_frames",
            "lra_low_threshold_lu",
            "lra_high_threshold_lu",
            "lra_silence_threshold_lu",
            "phase_warn_threshold",
            "feedback_pnr_threshold_db",
        }
        assert set(snap.keys()) == expected_keys

    def test_snapshot_copies_dicts(self) -> None:
        """snapshot 후 lt mutate가 응답에 반영되면 안 됨."""
        lt = LiveThresholds()
        lt.rms_targets["vocal"] = -18.0
        snap = lt.snapshot()
        lt.rms_targets["vocal"] = -99.0
        assert snap["rms_targets"] == {"vocal": -18.0}  # type: ignore[comparison-overlap]
