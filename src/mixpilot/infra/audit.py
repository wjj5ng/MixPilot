"""ADR-0008 §3 — 자동 액션 감사 로그 (JSONL).

`M32OscController.apply()`가 *모든* 자동 액션 시도(적용·정책 차단·가드 차단
무관)에 대해 한 줄 JSON을 기록한다. 사후 추적·운영자 검토·회귀 분석에 사용.

설계:
- JSONL — 각 줄이 독립 JSON 객체. grep / jq / 로그 시스템 ingest 친화.
- append-only. 회전은 OS 도구(logrotate)에 위임.
- `path=None`이면 no-op — 로깅 비활성. 테스트에서는 tmp_path 주입.
- `ensure_ascii=False`로 한국어 reason 보존.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from mixpilot.domain import Recommendation

logger = logging.getLogger(__name__)


class AuditOutcome(StrEnum):
    """감사 레코드의 결과 분류."""

    APPLIED = "applied"
    """정책·가드 모두 통과해 OSC 송신."""

    BLOCKED_POLICY = "blocked_policy"
    """ADR-0008 §1/§3 정책 검사 실패 (kind/mode/confidence)."""

    BLOCKED_GUARD = "blocked_guard"
    """ADR-0008 §3 가드 검사 실패 (레이트·세션·부트스트랩)."""


class AuditLogger:
    """자동 액션 감사 로그 — JSONL append.

    `record()` 호출 시 한 줄 JSON을 append. path가 None이면 모든 호출이 no-op.
    """

    def __init__(
        self,
        path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._clock = clock

    @property
    def path(self) -> Path | None:
        return self._path

    def record(
        self,
        recommendation: Recommendation,
        *,
        outcome: AuditOutcome,
        effective_mode: str,
        reason: str = "",
        osc_messages: Sequence[tuple[str, float | int]] = (),
    ) -> None:
        """감사 레코드 한 줄 append. path=None이면 no-op."""
        if self._path is None:
            return
        record = {
            "timestamp": self._clock(),
            "outcome": outcome.value,
            "effective_mode": effective_mode,
            "reason": reason,
            "channel": int(recommendation.target.channel),
            "category": recommendation.target.category.value,
            "label": recommendation.target.label,
            "kind": recommendation.kind.value,
            "confidence": recommendation.confidence,
            "rec_reason": recommendation.reason,
            "osc_messages": [list(m) for m in osc_messages],
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        # append-only — crash 시에도 직전까지 내용 보존.
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)

    def read_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """JSONL의 마지막 `limit` 레코드를 최신 순으로 반환.

        - `path=None` 또는 파일이 아직 없으면 빈 리스트.
        - 파싱 실패한 라인은 스킵 + 경고 로그 (감사 로그는 신뢰성 우선).
        - 큰 파일에서도 O(n) 전체 스캔 — 회전(logrotate)으로 크기 제한 권장.

        Args:
            limit: 반환할 최대 레코드 수. 양수.

        Returns:
            최신 → 과거 순서의 dict 리스트. 각 항목 키는 `record()`가
            기록한 필드 셋과 동일.
        """
        if limit <= 0:
            return []
        if self._path is None or not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("skipping malformed audit line: %s", e)
                    continue
        # 마지막 limit개를 최신 → 과거 순서로.
        return list(reversed(records[-limit:]))
