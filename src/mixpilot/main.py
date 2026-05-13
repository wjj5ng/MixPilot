"""FastAPI 진입점 — 의존성 와이어링과 라이프스팬 관리.

ARCHITECTURE.md 규약: `main`만 조립자 권한 — 모든 모듈 import 가능하고
DI·라이프스팬을 담당. 도메인 로직·DSP 로직은 여기서 직접 구현하지 않는다.

실행:
    uv run fastapi dev src/mixpilot/main.py
    uv run uvicorn mixpilot.main:app --host 0.0.0.0 --port 8000

오디오 캡처는 `MIXPILOT_AUDIO__ENABLED=true`로 켤 때만 시작된다. 기본은
False — M32 미연결 환경에서도 서버가 떠서 /health·/docs·/recommendations를
열어둔다(추천 스트림은 비어 있음).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from mixpilot.config import Settings, get_settings
from mixpilot.domain import (
    Channel,
    ChannelId,
    Recommendation,
    Signal,
    Source,
    SourceCategory,
)
from mixpilot.infra.audio_capture import SoundDeviceAudioSource
from mixpilot.infra.channel_map import YamlChannelMetadata
from mixpilot.infra.m32_control import M32OscController
from mixpilot.rules import evaluate_all_channels

logger = logging.getLogger(__name__)


class RecommendationBroker:
    """Recommendation을 SSE 구독자에게 fan-out 하는 in-memory pub/sub.

    단일 프로세스용. 분산 fan-out이 필요해지면 별도 ADR.
    느린 구독자는 큐가 가득 차면 메시지가 드롭된다 — 라이브 우선.
    """

    def __init__(self, max_queue_size: int = 128) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: set[asyncio.Queue[Recommendation]] = set()

    def subscribe(self) -> asyncio.Queue[Recommendation]:
        queue: asyncio.Queue[Recommendation] = asyncio.Queue(
            maxsize=self._max_queue_size
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Recommendation]) -> None:
        self._subscribers.discard(queue)

    def publish(self, recommendation: Recommendation) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(recommendation)
            except asyncio.QueueFull:
                logger.warning(
                    "subscriber queue full; dropping rec for ch%d",
                    int(recommendation.target.channel),
                )

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def _split_signal_to_channels(
    signal: Signal,
    sources_by_id: dict[int, Source],
) -> list[Channel]:
    """다채널 Signal → 채널별 `Channel` 분리.

    1-based 채널 번호(M32 컨벤션). 매핑되지 않은 채널은 UNKNOWN 카테고리로
    Source를 생성한다.
    """
    samples = signal.samples
    if samples.ndim == 1:
        samples = samples.reshape(-1, 1)
    num_channels = int(samples.shape[1])

    channels: list[Channel] = []
    for idx in range(num_channels):
        ch_id = idx + 1
        source = sources_by_id.get(ch_id) or Source(
            channel=ChannelId(ch_id),
            category=SourceCategory.UNKNOWN,
        )
        channels.append(
            Channel(
                source=source,
                samples=samples[:, idx],
                format=signal.format,
                capture_seq=signal.capture_seq,
            )
        )
    return channels


def _serialize_recommendation(rec: Recommendation) -> dict[str, Any]:
    """Recommendation → JSON 친화 dict."""
    return {
        "channel": int(rec.target.channel),
        "category": rec.target.category.value,
        "label": rec.target.label,
        "kind": rec.kind.value,
        "params": dict(rec.params),
        "confidence": rec.confidence,
        "reason": rec.reason,
    }


def _build_targets(settings: Settings) -> dict[str, float]:
    """settings → 카테고리별 타깃 dict.

    현재는 LUFS DSP가 미구현이라 `settings.lufs` 필드를 *임시로* dBFS 타깃으로
    사용한다(`rules.evaluate_all_channels`가 dBFS를 기대). LUFS 함수가 들어오면
    별도 `LufsTargets`와 `RmsDbfsTargets`로 분리하고 룰 함수도 LUFS 버전을 추가.
    """
    lufs = settings.lufs
    return {
        "vocal": lufs.vocal,
        "preacher": lufs.preacher,
        "choir": lufs.choir,
        "instrument": lufs.instrument,
        "unknown": lufs.unknown,
    }


async def _processing_loop(
    audio: SoundDeviceAudioSource,
    controller: M32OscController,
    broker: RecommendationBroker,
    sources_by_id: dict[int, Source],
    targets: dict[str, float],
) -> None:
    """오디오 프레임 → 룰 평가 → 제어 송신 + 브로커 푸시."""
    try:
        async for signal in audio.stream():
            channels = _split_signal_to_channels(signal, sources_by_id)
            recommendations = evaluate_all_channels(channels, targets)
            for rec in recommendations:
                await controller.apply(rec)
                broker.publish(rec)
    except asyncio.CancelledError:
        logger.info("processing loop cancelled")
        raise
    except Exception:
        logger.exception("processing loop crashed")
        raise


def create_app(settings: Settings | None = None) -> FastAPI:
    """FastAPI 앱 팩토리.

    settings를 명시 주입 가능(테스트 격리). `cfg.audio.enabled`가 False면
    인프라 어댑터를 초기화하지 않는다 — 하드웨어 없이도 서버 가동 가능.
    """
    cfg = settings or get_settings()
    broker = RecommendationBroker()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        audio: SoundDeviceAudioSource | None = None

        if cfg.audio.enabled:
            try:
                audio = SoundDeviceAudioSource(cfg.audio)
                controller = M32OscController(cfg.m32)
                channel_map = YamlChannelMetadata(cfg.channel_map_path)
                sources = list(await channel_map.get_all_channels())
                sources_by_id = {int(s.channel): s for s in sources}
                targets = _build_targets(cfg)
                task = asyncio.create_task(
                    _processing_loop(audio, controller, broker, sources_by_id, targets)
                )
                logger.info(
                    "audio processing started (mode=%s, device=%s)",
                    cfg.m32.operating_mode.value,
                    cfg.audio.device_substring,
                )
            except Exception:
                logger.exception(
                    "failed to start audio processing — server runs degraded"
                )
                if audio is not None:
                    with contextlib.suppress(Exception):
                        await audio.close()
                    audio = None
        else:
            logger.info("audio processing disabled (MIXPILOT_AUDIO__ENABLED=false)")

        try:
            yield
        finally:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            if audio is not None:
                with contextlib.suppress(Exception):
                    await audio.close()

    app = FastAPI(
        title="MixPilot",
        description="실시간 오디오 분석 및 믹싱 어시스턴트 (M32 / 라이브)",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.broker = broker

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """헬스 체크 — 운영 모드·오디오 설정·캡처 활성 여부 반환."""
        return {
            "status": "ok",
            "operating_mode": cfg.m32.operating_mode.value,
            "sample_rate": cfg.audio.sample_rate,
            "num_channels": cfg.audio.num_channels,
            "audio_enabled": cfg.audio.enabled,
        }

    @app.get("/recommendations")
    async def stream_recommendations(request: Request) -> StreamingResponse:
        """Recommendation의 Server-Sent Events 스트림.

        각 이벤트는 JSON 본문 + 빈 줄. 15초 동안 새 이벤트가 없으면
        `: keep-alive` 코멘트로 연결 유지.
        """
        queue = broker.subscribe()

        async def event_generator() -> AsyncIterator[str]:
            try:
                # 첫 'event'를 즉시 전송 — 클라이언트가 구독 성립을 확인할 수 있게.
                yield "event: subscribed\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        rec = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    payload = _serialize_recommendation(rec)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            finally:
                broker.unsubscribe(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app


# uvicorn / fastapi CLI가 import할 모듈 레벨 인스턴스.
app = create_app()
