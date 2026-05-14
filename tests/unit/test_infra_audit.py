"""infra.audit 단위 테스트 — JSONL 감사 로그 기록·결정성."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mixpilot.domain import (
    ChannelId,
    Recommendation,
    RecommendationKind,
    Source,
    SourceCategory,
)
from mixpilot.infra import AuditLogger, AuditOutcome


def _rec(
    channel: int = 1,
    kind: RecommendationKind = RecommendationKind.GAIN_ADJUST,
    *,
    category: SourceCategory = SourceCategory.VOCAL,
    label: str = "",
    confidence: float = 0.9,
    params: dict[str, float] | None = None,
    reason: str = "테스트 사유",
) -> Recommendation:
    return Recommendation(
        target=Source(ChannelId(channel), category, label),
        kind=kind,
        params=params or {},
        confidence=confidence,
        reason=reason,
    )


class TestNoOpMode:
    def test_path_none_writes_nothing(self) -> None:
        logger = AuditLogger(path=None)
        # 어떤 record 호출도 예외 없이 통과.
        logger.record(
            _rec(),
            outcome=AuditOutcome.APPLIED,
            effective_mode="auto",
        )

    def test_path_property_reflects_init(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        assert AuditLogger(path=p).path == p
        assert AuditLogger(path=None).path is None


class TestRecord:
    def test_writes_one_line_per_record(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        logger = AuditLogger(path=p, clock=lambda: 1000.0)
        logger.record(
            _rec(channel=1),
            outcome=AuditOutcome.APPLIED,
            effective_mode="auto",
            osc_messages=[("/ch/01/mix/fader", 0.5)],
        )
        logger.record(
            _rec(channel=2),
            outcome=AuditOutcome.BLOCKED_GUARD,
            effective_mode="auto",
            reason="channel rate limit",
        )
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_record_fields_present(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        logger = AuditLogger(path=p, clock=lambda: 1700000000.0)
        logger.record(
            _rec(
                channel=5,
                kind=RecommendationKind.MUTE,
                category=SourceCategory.PREACHER,
                label="설교자",
                confidence=0.97,
                reason="dynamic dB 초과",
            ),
            outcome=AuditOutcome.APPLIED,
            effective_mode="auto",
            osc_messages=[("/ch/05/mix/on", 0)],
        )
        line = p.read_text(encoding="utf-8").splitlines()[0]
        data = json.loads(line)
        assert data == {
            "timestamp": 1700000000.0,
            "outcome": "applied",
            "effective_mode": "auto",
            "reason": "",
            "channel": 5,
            "category": "preacher",
            "label": "설교자",
            "kind": "mute",
            "confidence": 0.97,
            "rec_reason": "dynamic dB 초과",
            "osc_messages": [["/ch/05/mix/on", 0]],
        }

    def test_korean_text_preserved(self, tmp_path: Path) -> None:
        # ensure_ascii=False 검증 — 한국어 그대로 저장.
        p = tmp_path / "audit.jsonl"
        logger = AuditLogger(path=p)
        logger.record(
            _rec(label="성가대 SOP", reason="LUFS 부족"),
            outcome=AuditOutcome.BLOCKED_POLICY,
            effective_mode="dry-run",
            reason="kind info not allowed",
        )
        text = p.read_text(encoding="utf-8")
        assert "성가대 SOP" in text
        assert "LUFS 부족" in text
        assert "한국어" not in text  # sanity — non-recorded text 없음

    def test_appends_not_overwrites(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        # 사전 내용.
        p.write_text("existing line\n", encoding="utf-8")
        logger = AuditLogger(path=p)
        logger.record(
            _rec(),
            outcome=AuditOutcome.APPLIED,
            effective_mode="auto",
        )
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "existing line"
        assert len(lines) == 2


class TestOutcomes:
    @pytest.mark.parametrize("outcome", list(AuditOutcome))
    def test_each_outcome_value_persists(
        self, outcome: AuditOutcome, tmp_path: Path
    ) -> None:
        p = tmp_path / "audit.jsonl"
        logger = AuditLogger(path=p)
        logger.record(
            _rec(),
            outcome=outcome,
            effective_mode="auto",
            reason="reason text",
        )
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["outcome"] == outcome.value


class TestReadRecent:
    def test_no_path_returns_empty(self) -> None:
        logger = AuditLogger(path=None)
        assert logger.read_recent(limit=10) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        logger = AuditLogger(path=tmp_path / "nope.jsonl")
        assert logger.read_recent(limit=10) == []

    def test_limit_zero_or_negative_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "a.jsonl"
        logger = AuditLogger(path=p)
        logger.record(_rec(), outcome=AuditOutcome.APPLIED, effective_mode="auto")
        assert logger.read_recent(limit=0) == []
        assert logger.read_recent(limit=-5) == []

    def test_returns_records_in_reverse_chronological_order(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "a.jsonl"
        timestamps = iter([1.0, 2.0, 3.0])
        logger = AuditLogger(path=p, clock=lambda: next(timestamps))
        for ch in (1, 2, 3):
            logger.record(
                _rec(channel=ch),
                outcome=AuditOutcome.APPLIED,
                effective_mode="auto",
            )
        records = logger.read_recent(limit=10)
        # 최신 → 과거.
        assert [r["timestamp"] for r in records] == [3.0, 2.0, 1.0]
        assert [r["channel"] for r in records] == [3, 2, 1]

    def test_limit_truncates_to_last_n(self, tmp_path: Path) -> None:
        p = tmp_path / "a.jsonl"
        timestamps = iter([float(i) for i in range(10)])
        logger = AuditLogger(path=p, clock=lambda: next(timestamps))
        for _ in range(10):
            logger.record(
                _rec(), outcome=AuditOutcome.APPLIED, effective_mode="auto"
            )
        records = logger.read_recent(limit=3)
        assert len(records) == 3
        # 마지막 3개를 최신 순으로: 9, 8, 7.
        assert [r["timestamp"] for r in records] == [9.0, 8.0, 7.0]

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "a.jsonl"
        # 정상 1줄 + 깨진 1줄 + 정상 1줄.
        logger = AuditLogger(path=p, clock=lambda: 1.0)
        logger.record(_rec(), outcome=AuditOutcome.APPLIED, effective_mode="auto")
        with p.open("a", encoding="utf-8") as f:
            f.write("this is not json\n")
        logger2 = AuditLogger(path=p, clock=lambda: 3.0)
        logger2.record(_rec(), outcome=AuditOutcome.APPLIED, effective_mode="auto")
        records = logger.read_recent(limit=10)
        # 깨진 줄은 스킵 — 두 정상 줄만 반환.
        assert len(records) == 2
        assert {r["timestamp"] for r in records} == {1.0, 3.0}

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "a.jsonl"
        logger = AuditLogger(path=p, clock=lambda: 5.0)
        logger.record(_rec(), outcome=AuditOutcome.APPLIED, effective_mode="auto")
        with p.open("a", encoding="utf-8") as f:
            f.write("\n\n   \n")
        records = logger.read_recent(limit=10)
        assert len(records) == 1


class TestDeterminism:
    def test_same_inputs_same_line(self, tmp_path: Path) -> None:
        rec = _rec(channel=3, confidence=0.85, reason="동일 입력")
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        for path in (a, b):
            logger = AuditLogger(path=path, clock=lambda: 42.0)
            logger.record(
                rec,
                outcome=AuditOutcome.APPLIED,
                effective_mode="auto",
                osc_messages=[("/ch/03/mix/on", 1)],
            )
        assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
