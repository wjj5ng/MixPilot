"""Domain ports — abstract interfaces that infra adapters implement.

`domain`은 외부 라이브러리에 의존하지 않으므로, 외부 시스템(M32, 메트릭
저장소 등)과의 접점은 Protocol로 *모양만* 정의한다. 구현은 `infra/`에 두고
`main.py`에서 와이어링한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from typing import Protocol, runtime_checkable

from .models import AudioFormat, ChannelId, Recommendation, Signal, Source


@runtime_checkable
class AudioSource(Protocol):
    """오디오 입력 어댑터 (예: M32 USB 캡처 — ADR-0004)."""

    @property
    def format(self) -> AudioFormat: ...

    def stream(self) -> AsyncIterator[Signal]:
        """다채널 신호 프레임의 비동기 스트림. 보통 무한 이터레이터이며
        종료는 close() 또는 컨텍스트 매니저로."""
        ...

    async def close(self) -> None: ...


@runtime_checkable
class ConsoleControl(Protocol):
    """콘솔 제어 어댑터 (예: M32 X32 OSC — ADR-0005).

    운영 모드(dry-run/assist/auto)에 따라 실제 송신 여부는 구현체가
    결정한다. 모든 시도는 결정 로그로 기록.
    """

    async def apply(self, recommendation: Recommendation) -> None: ...


@runtime_checkable
class ConsoleMetadata(Protocol):
    """콘솔 메타데이터 조회 (라벨·게인·라우팅).

    M32 OSC `/ch/XX/config/name` 등을 통한 라벨 읽기 — 채널 자동 카테고리화의
    시드.
    """

    async def get_channel_label(self, channel: ChannelId) -> str: ...

    async def get_all_channels(self) -> Iterable[Source]: ...


@runtime_checkable
class MetricsSink(Protocol):
    """분석 메트릭·결정 로그 저장 (ADR-0003 미결)."""

    async def write(self, key: str, value: float, tags: Mapping[str, str]) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    """대시보드·외부 알림 (ADR-0002 미결 — WebSocket/SSE 등)."""

    async def push(self, payload: Mapping[str, object]) -> None: ...
