"""자동 액션 보편 안전장치 — ADR-0008 §3 구현.

처리하는 안전 한도:
- 부트스트랩 침묵: 시작 후 N초간 자동 액션 금지.
- 채널별 레이트 리미트: 채널당 윈도우 안 최대 1회.
- 글로벌 레이트 리미트: 전역 윈도우 안 최대 N회.
- 세션 한도: service당 최대 N회 누적.

본 모듈은 *결정성 보장*을 위해 `clock` 함수를 의존성 주입으로 받는다 —
프로덕션은 `time.monotonic`, 테스트는 가짜 시계를 주입.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuardDecision:
    """`try_register` 결과."""

    allowed: bool
    reason: str = ""


class AutoGuard:
    """자동 액션 게이트. `try_register` 한 번에 검사 + 등록을 원자적으로 처리.

    호출자는 액션을 적용하기 *직전* `try_register(channel_id)`를 호출한다:
    - `allowed=True`: 모든 카운터·이력이 *이미* 갱신됨. 호출자는 액션 적용.
    - `allowed=False`: 상태 변경 없음. 호출자는 액션 건너뜀.

    상태:
    - 시작 시각(부트스트랩 침묵 계산용)
    - 채널별 마지막 액션 시각 (per-channel 윈도우 체크)
    - 글로벌 액션 시각 deque (글로벌 윈도우 체크)
    - 세션 누적 카운터
    """

    def __init__(
        self,
        *,
        per_channel_window_seconds: float = 5.0,
        global_window_seconds: float = 1.0,
        global_max_in_window: int = 3,
        session_max_actions: int = 50,
        bootstrap_silence_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_channel_window_seconds < 0:
            raise ValueError("per_channel_window_seconds must be >= 0")
        if global_window_seconds <= 0:
            raise ValueError("global_window_seconds must be > 0")
        if global_max_in_window <= 0:
            raise ValueError("global_max_in_window must be > 0")
        if session_max_actions <= 0:
            raise ValueError("session_max_actions must be > 0")
        if bootstrap_silence_seconds < 0:
            raise ValueError("bootstrap_silence_seconds must be >= 0")

        self._per_channel_window = per_channel_window_seconds
        self._global_window = global_window_seconds
        self._global_max = global_max_in_window
        self._session_max = session_max_actions
        self._bootstrap = bootstrap_silence_seconds
        self._clock = clock
        self._start_time = clock()
        self._channel_last: dict[int, float] = {}
        self._global_history: deque[float] = deque()
        self._session_count = 0

    @property
    def session_action_count(self) -> int:
        return self._session_count

    @property
    def session_max_actions(self) -> int:
        return self._session_max

    def try_register(self, channel_id: int) -> GuardDecision:
        """검사 + 등록. allowed면 상태 갱신, 차단되면 변동 없음."""
        now = self._clock()

        if now - self._start_time < self._bootstrap:
            return GuardDecision(False, "bootstrap silence")

        if self._session_count >= self._session_max:
            return GuardDecision(False, "session limit")

        last = self._channel_last.get(channel_id)
        if last is not None and (now - last) < self._per_channel_window:
            return GuardDecision(False, "channel rate limit")

        # 글로벌 윈도우 — 만료 항목 제거 후 카운트.
        # 경계 의미는 채널 윈도우와 일치 — `now - t == window`이면 만료.
        cutoff = now - self._global_window
        while self._global_history and self._global_history[0] <= cutoff:
            self._global_history.popleft()
        if len(self._global_history) >= self._global_max:
            return GuardDecision(False, "global rate limit")

        # 통과 — 카운터 갱신.
        self._channel_last[channel_id] = now
        self._global_history.append(now)
        self._session_count += 1
        return GuardDecision(True)

    def reset(self) -> None:
        """새 service 시작 시 모든 상태 초기화. 시작 시각도 *지금*으로 재설정 →
        부트스트랩 침묵도 다시 적용."""
        self._start_time = self._clock()
        self._channel_last.clear()
        self._global_history.clear()
        self._session_count = 0
