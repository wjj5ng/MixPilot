"""JsonlMetricsSink 단위 테스트 — throttling·write·no-op."""

from __future__ import annotations

import json
from pathlib import Path

from mixpilot.infra.metrics_sink import JsonlMetricsSink


def _payload(channel: int, rms: float = -20.0, peak: float = -10.0) -> dict:
    return {
        "channel": channel,
        "label": "vox",
        "category": "vocal",
        "rms_dbfs": rms,
        "peak_dbfs": peak,
        "lra_lu": 8.5,
        "phase_with_pair": None,
        "octave_bands_dbfs": [0.0] * 8,  # 시계열에선 제외돼야
    }


class TestNoPath:
    def test_none_path_writes_nothing(self) -> None:
        sink = JsonlMetricsSink(path=None)
        # 어떤 호출도 안전.
        wrote = sink.maybe_write([_payload(1)], capture_seq=1)
        assert wrote is False

    def test_enabled_false_when_no_path(self) -> None:
        assert JsonlMetricsSink(path=None).enabled is False

    def test_enabled_true_with_path(self, tmp_path: Path) -> None:
        sink = JsonlMetricsSink(path=tmp_path / "m.jsonl")
        assert sink.enabled is True


class TestThrottle:
    def test_first_call_writes(self, tmp_path: Path) -> None:
        p = tmp_path / "m.jsonl"
        clock = iter([100.0])
        sink = JsonlMetricsSink(p, interval_seconds=1.0, clock=lambda: next(clock))
        assert sink.maybe_write([_payload(1)], capture_seq=1) is True
        assert p.exists()

    def test_within_interval_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "m.jsonl"
        times = iter([100.0, 100.5])  # 0.5s 차 < 1.0s interval
        sink = JsonlMetricsSink(p, interval_seconds=1.0, clock=lambda: next(times))
        assert sink.maybe_write([_payload(1)], capture_seq=1) is True
        assert sink.maybe_write([_payload(1)], capture_seq=2) is False
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_after_interval_writes_again(self, tmp_path: Path) -> None:
        p = tmp_path / "m.jsonl"
        times = iter([100.0, 100.5, 101.5])
        sink = JsonlMetricsSink(p, interval_seconds=1.0, clock=lambda: next(times))
        sink.maybe_write([_payload(1)], capture_seq=1)
        sink.maybe_write([_payload(1)], capture_seq=2)  # skipped
        sink.maybe_write([_payload(1)], capture_seq=3)  # writes (1.5s 경과)
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2


class TestPayload:
    def test_slim_channels_excludes_octave_bands(self, tmp_path: Path) -> None:
        p = tmp_path / "m.jsonl"
        times = iter([100.0])
        sink = JsonlMetricsSink(p, interval_seconds=0.1, clock=lambda: next(times))
        sink.maybe_write(
            [_payload(1, rms=-23.4, peak=-18.0)],
            capture_seq=42,
            wall_timestamp=1700000000.0,
        )
        record = json.loads(p.read_text(encoding="utf-8").strip())
        assert record["timestamp"] == 1700000000.0
        assert record["capture_seq"] == 42
        ch = record["channels"][0]
        # 핵심 필드만.
        assert ch == {
            "channel": 1,
            "rms_dbfs": -23.4,
            "peak_dbfs": -18.0,
            "lra_lu": 8.5,
            "phase_with_pair": None,
        }
        # 부피 큰 필드는 제외.
        assert "octave_bands_dbfs" not in ch
        assert "label" not in ch

    def test_multiple_channels_in_one_line(self, tmp_path: Path) -> None:
        p = tmp_path / "m.jsonl"
        times = iter([100.0])
        sink = JsonlMetricsSink(p, interval_seconds=0.1, clock=lambda: next(times))
        sink.maybe_write(
            [_payload(1), _payload(2), _payload(3)],
            capture_seq=1,
        )
        record = json.loads(p.read_text(encoding="utf-8").strip())
        assert len(record["channels"]) == 3
        assert [c["channel"] for c in record["channels"]] == [1, 2, 3]

    def test_appends_not_overwrites(self, tmp_path: Path) -> None:
        p = tmp_path / "m.jsonl"
        # 기존 내용.
        p.write_text("previous line\n", encoding="utf-8")
        times = iter([100.0])
        sink = JsonlMetricsSink(p, interval_seconds=0.1, clock=lambda: next(times))
        sink.maybe_write([_payload(1)], capture_seq=1)
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "previous line"
        assert len(lines) == 2
