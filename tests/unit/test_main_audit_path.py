"""`_resolve_audit_log_path` 단위 테스트 — strftime expansion + mkdir."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from mixpilot.main import _resolve_audit_log_path


class TestResolveAuditLogPath:
    def test_none_returns_none(self) -> None:
        assert _resolve_audit_log_path(None) is None

    def test_plain_path_returned_as_is(self, tmp_path: Path) -> None:
        # strftime 패턴 없으면 그대로(단, 부모 디렉토리는 mkdir).
        target = tmp_path / "audit.jsonl"
        resolved = _resolve_audit_log_path(target)
        assert resolved == target

    def test_strftime_pattern_expanded(self, tmp_path: Path) -> None:
        pattern = tmp_path / "audit-%Y%m%d.jsonl"
        resolved = _resolve_audit_log_path(pattern)
        assert resolved is not None
        # 결과 path가 yyyymmdd 형식의 8자리 숫자 포함.
        assert re.search(r"audit-\d{8}\.jsonl", str(resolved))

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        # 존재하지 않는 하위 디렉토리도 생성.
        target = tmp_path / "service-logs" / "audit.jsonl"
        assert not (tmp_path / "service-logs").exists()
        resolved = _resolve_audit_log_path(target)
        assert resolved is not None
        assert resolved.parent.exists()
        assert resolved.parent.is_dir()

    def test_existing_directory_no_error(self, tmp_path: Path) -> None:
        # 이미 존재하는 디렉토리에도 idempotent.
        target = tmp_path / "audit.jsonl"
        _resolve_audit_log_path(target)
        _resolve_audit_log_path(target)  # 두 번째 호출도 에러 없음.

    def test_expansion_uses_current_time(self, tmp_path: Path) -> None:
        # 가동 시점의 *연도*가 결과에 들어가는지 검증.
        pattern = tmp_path / "audit-%Y.jsonl"
        resolved = _resolve_audit_log_path(pattern)
        assert resolved is not None
        current_year = datetime.now().strftime("%Y")
        assert current_year in str(resolved)
