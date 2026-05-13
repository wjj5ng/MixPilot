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

import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from mixpilot.api.schemas import (
    ActionEntry,
    ControlResponse,
    HealthResponse,
    OscMessage,
    RecentActionsResponse,
    RecommendationEvent,
)
from mixpilot.config import Settings, get_settings
from mixpilot.domain import (
    Channel,
    ChannelId,
    Recommendation,
    Signal,
    Source,
    SourceCategory,
)
from mixpilot.dsp import MIN_DURATION_SECONDS
from mixpilot.infra.audio_capture import SoundDeviceAudioSource
from mixpilot.infra.audit import AuditLogger
from mixpilot.infra.channel_map import YamlChannelMetadata
from mixpilot.infra.m32_control import M32OscController
from mixpilot.rules import (
    evaluate_all_channels,
    evaluate_all_channels_lufs,
    evaluate_all_channels_peak,
    evaluate_all_feedback,
)
from mixpilot.runtime import ActionHistory, FeedbackDetector, RollingBuffer

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


def _build_rms_dbfs_targets(settings: Settings) -> dict[str, float]:
    """settings.rms_dbfs → 카테고리별 RMS dBFS 타깃 dict.

    `rules.evaluate_all_channels`에 주입 — 라이브 매 프레임 평가용.
    """
    t = settings.rms_dbfs
    return {
        "vocal": t.vocal,
        "preacher": t.preacher,
        "choir": t.choir,
        "instrument": t.instrument,
        "unknown": t.unknown,
    }


def _build_lufs_targets(settings: Settings) -> dict[str, float]:
    """settings.lufs → 카테고리별 LUFS 타깃 dict.

    `rules.evaluate_all_channels_lufs`에 주입. 처리 루프는 `RollingBuffer`에
    누적된 ~400ms+ 신호 위에서 주기적으로 평가한다.
    """
    t = settings.lufs
    return {
        "vocal": t.vocal,
        "preacher": t.preacher,
        "choir": t.choir,
        "instrument": t.instrument,
        "unknown": t.unknown,
    }


async def _processing_loop(
    audio: SoundDeviceAudioSource,
    controller: M32OscController,
    broker: RecommendationBroker,
    sources_by_id: dict[int, Source],
    rms_targets: dict[str, float],
    *,
    lufs_buffer: RollingBuffer | None = None,
    lufs_targets: dict[str, float] | None = None,
    lufs_eval_interval_frames: int = 50,
    feedback_detectors: dict[int, FeedbackDetector] | None = None,
    feedback_pnr_threshold_db: float = 15.0,
    peak_enabled: bool = False,
    peak_headroom_threshold_dbfs: float = -1.0,
    peak_oversample: int = 4,
) -> None:
    """오디오 프레임 → 룰 평가 → 제어 송신 + 브로커 푸시.

    - RMS 룰: 매 프레임.
    - LUFS 룰: `lufs_buffer`가 주입되었고 ~400ms 이상 누적되었을 때만,
      `lufs_eval_interval_frames` 마다 평가.
    - Feedback 룰: `feedback_detectors`가 주입되었으면 매 프레임 채널별로
      detector 업데이트. 지속 검증된 peaks만 Recommendation 발화.
    - Peak 룰: `peak_enabled=True`면 매 프레임 채널별 true peak 평가, 헤드룸
      임계 이상이면 INFO 발화.
    """
    lufs_enabled = lufs_buffer is not None and lufs_targets is not None
    feedback_enabled = feedback_detectors is not None
    frame_count = 0
    try:
        async for signal in audio.stream():
            frame_count += 1
            channels = _split_signal_to_channels(signal, sources_by_id)
            recommendations = evaluate_all_channels(channels, rms_targets)

            if lufs_enabled:
                assert lufs_buffer is not None
                assert lufs_targets is not None
                lufs_buffer.write(signal.samples)
                if (
                    frame_count % lufs_eval_interval_frames == 0
                    and lufs_buffer.fill / signal.format.sample_rate
                    >= MIN_DURATION_SECONDS
                ):
                    buffered_signal = Signal(
                        samples=lufs_buffer.snapshot(),
                        format=signal.format,
                        capture_seq=signal.capture_seq,
                    )
                    lufs_channels = _split_signal_to_channels(
                        buffered_signal, sources_by_id
                    )
                    recommendations.extend(
                        evaluate_all_channels_lufs(lufs_channels, lufs_targets)
                    )

            if feedback_enabled:
                assert feedback_detectors is not None
                peaks_by_source = {}
                for channel in channels:
                    ch_id = int(channel.source.channel)
                    detector = feedback_detectors.get(ch_id)
                    if detector is None:
                        continue
                    peaks = detector.update(channel.samples)
                    if peaks:
                        peaks_by_source[channel.source] = peaks
                if peaks_by_source:
                    recommendations.extend(
                        evaluate_all_feedback(
                            peaks_by_source,
                            pnr_threshold_db=feedback_pnr_threshold_db,
                        )
                    )

            if peak_enabled:
                recommendations.extend(
                    evaluate_all_channels_peak(
                        channels,
                        headroom_threshold_dbfs=peak_headroom_threshold_dbfs,
                        oversample=peak_oversample,
                    )
                )

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
                audit_logger = (
                    AuditLogger(path=cfg.audit_log_path)
                    if cfg.audit_log_path is not None
                    else None
                )
                controller = M32OscController(
                    cfg.m32,
                    audit_logger=audit_logger,
                    action_history=action_history,
                )
                app.state.controller = controller
                channel_map = YamlChannelMetadata(cfg.channel_map_path)
                sources = list(await channel_map.get_all_channels())
                sources_by_id = {int(s.channel): s for s in sources}
                rms_targets = _build_rms_dbfs_targets(cfg)

                lufs_buffer: RollingBuffer | None = None
                lufs_targets: dict[str, float] | None = None
                if cfg.lufs_analysis.enabled:
                    capacity = int(
                        cfg.audio.sample_rate * cfg.lufs_analysis.buffer_seconds
                    )
                    lufs_buffer = RollingBuffer(
                        capacity_frames=capacity,
                        num_channels=cfg.audio.num_channels,
                        dtype=np.float32,
                    )
                    lufs_targets = _build_lufs_targets(cfg)

                feedback_detectors: dict[int, FeedbackDetector] | None = None
                if cfg.feedback_analysis.enabled:
                    feedback_detectors = {
                        ch_id: FeedbackDetector(
                            cfg.audio.sample_rate,
                            persistence_frames=cfg.feedback_analysis.persistence_frames,
                            pnr_threshold_db=cfg.feedback_analysis.pnr_threshold_db,
                            min_frequency_hz=cfg.feedback_analysis.min_frequency_hz,
                            max_frequency_hz=cfg.feedback_analysis.max_frequency_hz,
                        )
                        for ch_id in range(1, cfg.audio.num_channels + 1)
                    }

                task = asyncio.create_task(
                    _processing_loop(
                        audio,
                        controller,
                        broker,
                        sources_by_id,
                        rms_targets,
                        lufs_buffer=lufs_buffer,
                        lufs_targets=lufs_targets,
                        lufs_eval_interval_frames=cfg.lufs_analysis.eval_interval_frames,
                        feedback_detectors=feedback_detectors,
                        feedback_pnr_threshold_db=cfg.feedback_analysis.pnr_threshold_db,
                        peak_enabled=cfg.peak_analysis.enabled,
                        peak_headroom_threshold_dbfs=(
                            cfg.peak_analysis.headroom_threshold_dbfs
                        ),
                        peak_oversample=cfg.peak_analysis.oversample,
                    )
                )
                logger.info(
                    "audio started (mode=%s device=%s lufs=%s feedback=%s peak=%s)",
                    cfg.m32.operating_mode.value,
                    cfg.audio.device_substring,
                    "on" if cfg.lufs_analysis.enabled else "off",
                    "on" if cfg.feedback_analysis.enabled else "off",
                    "on" if cfg.peak_analysis.enabled else "off",
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
            app.state.controller = None

    app = FastAPI(
        title="MixPilot",
        description="실시간 오디오 분석 및 믹싱 어시스턴트 (M32 / 라이브)",
        version="0.1.0",
        lifespan=lifespan,
    )
    action_history = ActionHistory()
    app.state.settings = cfg
    app.state.broker = broker
    app.state.controller = None  # lifespan에서 audio.enabled=True면 채워진다.
    app.state.action_history = action_history

    if cfg.dev_cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """헬스 체크 — 운영 모드·오디오 설정·캡처/분석 활성 여부 반환."""
        return HealthResponse(
            status="ok",
            operating_mode=cfg.m32.operating_mode.value,
            sample_rate=cfg.audio.sample_rate,
            num_channels=cfg.audio.num_channels,
            audio_enabled=cfg.audio.enabled,
            lufs_analysis_enabled=cfg.lufs_analysis.enabled,
            feedback_analysis_enabled=cfg.feedback_analysis.enabled,
            peak_analysis_enabled=cfg.peak_analysis.enabled,
        )

    @app.get("/control/recent-actions", response_model=RecentActionsResponse)
    async def recent_actions(request: Request) -> RecentActionsResponse:
        """최근 자동 적용된 액션 이력 — ADR-0008 §3.6 윈도우 기반 조회.

        실 *역 OSC* 송신(롤백)은 콘솔 상태 reader가 들어와야 가능
        (docs/hardware-dependent.md #4). 지금은 운영자 가시성·디버깅용 조회만.
        """
        history: ActionHistory = request.app.state.action_history
        entries = [
            ActionEntry(
                timestamp=e.timestamp,
                channel=e.channel_id,
                kind=e.kind,
                osc_messages=[
                    OscMessage(address=addr, value=value)
                    for addr, value in e.osc_messages
                ],
                reason=e.reason,
            )
            for e in history.recent()
        ]
        return RecentActionsResponse(
            entries=entries, window_seconds=history.window_seconds
        )

    @app.post("/control/dry-run", response_model=ControlResponse)
    async def force_dry_run(request: Request) -> ControlResponse:
        """ADR-0008 §3 킬 스위치 — 모든 자동 액션 즉시 정지.

        config 변경 없이 controller의 effective_mode를 DRY_RUN으로 강제 다운그레이드.
        한 번 호출되면 프로세스 재시작 전까지 어떤 액션도 송신되지 않는다.

        controller가 없는 경우(audio 비활성)에도 200으로 응답하며 상태 문자열로
        알린다 — 멱등성 + 운영자 혼란 방지.
        """
        controller = request.app.state.controller
        if controller is None:
            return ControlResponse(
                status="no controller (audio disabled)", effective_mode=None
            )
        controller.force_dry_run()
        return ControlResponse(
            status="forced dry-run", effective_mode=controller.effective_mode.value
        )

    @app.get(
        "/recommendations",
        responses={
            200: {
                "model": RecommendationEvent,
                "description": (
                    "Server-Sent Events 스트림. 각 'data:' 라인 본문이 "
                    "RecommendationEvent JSON."
                ),
                "content": {"text/event-stream": {}},
            }
        },
    )
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
