"""Per-channel persistence filter — 룰 추천이 N 연속 frame 유지될 때만 통과.

라이브 신호는 단일 frame에서 일시적으로 임계를 넘는 transient가 흔하다(짧은
어택, 음성 어택, 발걸음, 마이크 핸들링 노이즈 등). 이런 1-frame 발화를 그대로
운영자 추천으로 띄우면 노이즈가 된다.

`FeedbackDetector`가 FFT bin 단위로 같은 패턴을 한다면, 이 필터는 *(채널 ID,
룰 태그)* 단위로 같은 규약을 적용 — 룰별 임계를 N 연속 frame 만족했을 때만
추천을 통과시킨다.

`persistence_frames=1`이면 필터 부재와 동일한 동작 — 디폴트 안전.

Stateful: 한 번 sustained되면 추천이 매 frame 계속 통과한다. 채널이 임계 아래로
떨어진 frame이 한 번이라도 있으면 streak는 0으로 reset (히스테리시스 없음).
"""

from __future__ import annotations

from collections.abc import Iterable


class PersistenceFilter:
    """(룰 태그) x (채널 ID) 별 연속 frame streak를 추적해 임계 통과 여부를 보고.

    각 룰이 독립 streak를 가짐 — peak rule이 ch3에서 streak를 쌓아도
    dynamic_range rule의 ch3 streak에는 영향 없음.
    """

    def __init__(self) -> None:
        # tag → {channel_id → consecutive_frame_count}.
        self._streaks: dict[str, dict[int, int]] = {}

    def observe(
        self,
        tag: str,
        channel_ids: Iterable[int],
        persistence_frames: int,
    ) -> set[int]:
        """이번 frame의 candidate 채널 집합을 보고, sustained 채널 집합 반환.

        Args:
            tag: 룰 식별자(예: `"peak"`, `"dynamic_range"`). 룰별 streak 격리.
            channel_ids: 이번 frame에 룰이 발화한 채널 ID들.
            persistence_frames: 통과 임계(>=1). 1이면 즉시 통과(필터 부재 동치).

        Returns:
            연속 `persistence_frames` 이상 frame에서 발화한 채널 ID 집합.

        Raises:
            ValueError: persistence_frames < 1.
        """
        if persistence_frames < 1:
            raise ValueError(
                f"persistence_frames must be >= 1, got {persistence_frames}"
            )
        seen = {int(ch) for ch in channel_ids}
        prev = self._streaks.get(tag, {})
        new_streaks: dict[int, int] = {}
        for ch in seen:
            new_streaks[ch] = prev.get(ch, 0) + 1
        # 이번 frame에 빠진 채널은 streak 리셋(new_streaks에 없음).
        self._streaks[tag] = new_streaks
        if persistence_frames <= 1:
            return seen
        return {ch for ch, n in new_streaks.items() if n >= persistence_frames}

    def streak(self, tag: str, channel_id: int) -> int:
        """디버깅·테스트용 — 현재 streak 카운트."""
        return self._streaks.get(tag, {}).get(int(channel_id), 0)

    def reset(self, tag: str | None = None) -> None:
        """streak 초기화. tag 지정이면 그 룰만, None이면 전체."""
        if tag is None:
            self._streaks.clear()
        else:
            self._streaks.pop(tag, None)
