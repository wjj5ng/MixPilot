"""자동 액션 이력 — ADR-0008 §3.6 롤백 윈도우 기반.

실 *역 OSC 송신*(롤백)은 콘솔 현재 상태 읽기가 선행돼야 의미 있음
(docs/hardware-dependent.md #4). 이 모듈은 우선 *기록·조회*만 제공:
- 적용된 액션을 시간순으로 저장.
- 윈도우(기본 60초)를 벗어난 항목은 자동 가지치기.
- API 엔드포인트가 운영자에게 "최근 어떤 자동 액션이 적용됐는지"를 보여줄 수 있다.

결정성을 위해 `clock` 의존성 주입.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """한 건의 자동 액션 적용 이력."""

    timestamp: float
    channel_id: int
    kind: str
    osc_messages: tuple[tuple[str, float], ...]
    reason: str = ""


class ActionHistory:
    """슬라이딩 윈도우 액션 이력.

    `add()`로 항목 추가, `recent()`로 *현재 윈도우 안*의 항목을 시간순으로 조회.
    조회 시점에 만료 항목이 자동으로 가지치기되어 메모리 누수 없다.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        self._window = window_seconds
        self._clock = clock
        self._entries: deque[HistoryEntry] = deque()

    @property
    def window_seconds(self) -> float:
        return self._window

    def add(
        self,
        *,
        channel_id: int,
        kind: str,
        osc_messages: Iterable[tuple[str, float]] = (),
        reason: str = "",
    ) -> HistoryEntry:
        """현재 시각으로 이력 추가 + 만료 가지치기."""
        now = self._clock()
        self._prune(now)
        entry = HistoryEntry(
            timestamp=now,
            channel_id=channel_id,
            kind=kind,
            osc_messages=tuple((a, float(v)) for a, v in osc_messages),
            reason=reason,
        )
        self._entries.append(entry)
        return entry

    def recent(self) -> list[HistoryEntry]:
        """현재 윈도우 안의 항목들. 가장 오래된 것이 앞."""
        self._prune(self._clock())
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._entries and self._entries[0].timestamp <= cutoff:
            self._entries.popleft()
