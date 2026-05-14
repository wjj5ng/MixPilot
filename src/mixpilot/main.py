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
    AuditEntry,
    AuditLogResponse,
    ChannelMapEntry,
    ChannelMapResponse,
    ChannelMapUpdateRequest,
    ControlResponse,
    HealthResponse,
    MeterSnapshotEvent,
    OscMessage,
    RecentActionsResponse,
    RecommendationEvent,
    RulesResponse,
    RuleState,
    RuleToggleRequest,
)
from mixpilot.config import AudioSource, Settings, get_settings
from mixpilot.domain import (
    Channel,
    ChannelId,
    Recommendation,
    Signal,
    Source,
    SourceCategory,
)
from mixpilot.dsp import (
    MIN_DURATION_SECONDS,
    octave_band_levels_dbfs,
    peak_channels,
    rms_channels,
    to_dbfs,
)
from mixpilot.dsp.lra import MIN_DURATION_SECONDS as LRA_MIN_DURATION_SECONDS
from mixpilot.dsp.lra import lra as compute_lra
from mixpilot.dsp.phase import phase_correlation
from mixpilot.infra.audio_capture import SoundDeviceAudioSource
from mixpilot.infra.audit import AuditLogger
from mixpilot.infra.channel_map import YamlChannelMetadata
from mixpilot.infra.m32_control import M32OscController
from mixpilot.infra.synthetic_audio import SyntheticAudioSource
from mixpilot.infra.wav_replay import WavReplayAudioSource
from mixpilot.rules import (
    evaluate_all_channels,
    evaluate_all_channels_dynamic_range,
    evaluate_all_channels_lufs,
    evaluate_all_channels_peak,
    evaluate_all_feedback,
    evaluate_all_phase_pairs,
    evaluate_lra_value,
)
from mixpilot.runtime import (
    ActionHistory,
    FeedbackDetector,
    RollingBuffer,
    RuleToggles,
)
from mixpilot.runtime.rule_toggles import RULE_NAMES

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


class MeterBroker:
    """채널별 미터 스냅샷을 SSE 구독자에 fan-out 하는 in-memory pub/sub.

    미터는 *최신만이 가치 있음* — 큐가 가득 차면 옛 스냅샷을 드롭하고 새 것을
    넣는다(`drop_oldest=True`). 큐 크기가 작아도(기본 2) 끊김 없는 표시 가능.
    """

    def __init__(self, max_queue_size: int = 2) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._max_queue_size
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            # 옛 스냅샷보다 최신이 우선 — 가득 차면 가장 오래된 것 제거 후 푸시.
            while queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # 동시성 코너: 다른 코루틴이 가득 채움. 다음 사이클에 캐치업.

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def _compute_meter_payload(
    channels: list[Channel],
    capture_seq: int,
    *,
    lra_by_channel: dict[int, float] | None = None,
    phase_by_pair: dict[tuple[int, int], float] | None = None,
) -> dict[str, Any]:
    """채널별 RMS·peak dBFS + 라벨/카테고리 + (옵션) LRA를 SSE 페이로드로 직렬화.

    LRA는 long-window 메트릭이라 매 publish마다 다시 계산하지 않음 — 호출자가
    가장 최근에 계산한 값을 `lra_by_channel`로 주입. 키는 1-based 채널 ID.
    아직 평가가 안 된 채널은 None(=`lra_lu: null`)으로 전송.

    Args:
        channels: `_split_signal_to_channels` 결과 — source 정보 포함.
        capture_seq: 원천 Signal의 단조 시퀀스.
        lra_by_channel: 채널 ID → LRA(LU) 캐시. None이면 모든 채널 lra_lu=null.
    """
    if not channels:
        return {"capture_seq": int(capture_seq), "channels": []}

    # 2D ndarray로 모아서 벡터화 계산 — 채널 수 많을수록 이득.
    stacked = np.stack([ch.samples for ch in channels], axis=1)
    rms_lin = rms_channels(stacked)
    peak_lin = peak_channels(stacked)

    payload_channels: list[dict[str, Any]] = []
    for idx, ch in enumerate(channels):
        ch_id = int(ch.source.channel)
        partner_id = ch.source.stereo_pair_with
        phase_value: float | None = None
        if partner_id is not None and phase_by_pair is not None:
            key = (min(ch_id, partner_id), max(ch_id, partner_id))
            phase_value = phase_by_pair.get(key)
        payload_channels.append(
            {
                "channel": ch_id,
                "label": ch.source.label,
                "category": ch.source.category.value,
                "stereo_pair_with": partner_id,
                "rms_dbfs": to_dbfs(float(rms_lin[idx])),
                "peak_dbfs": to_dbfs(float(peak_lin[idx])),
                "lra_lu": (lra_by_channel.get(ch_id) if lra_by_channel else None),
                "phase_with_pair": phase_value,
                "octave_bands_dbfs": octave_band_levels_dbfs(
                    ch.samples, ch.format.sample_rate
                ),
            }
        )
    return {"capture_seq": int(capture_seq), "channels": payload_channels}


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
    audio: SoundDeviceAudioSource | SyntheticAudioSource | WavReplayAudioSource,
    controller: M32OscController,
    broker: RecommendationBroker,
    sources_by_id: dict[int, Source],
    rms_targets: dict[str, float],
    rule_toggles: RuleToggles,
    *,
    lufs_buffer: RollingBuffer,
    lufs_targets: dict[str, float],
    lufs_eval_interval_frames: int = 50,
    feedback_detectors: dict[int, FeedbackDetector],
    feedback_pnr_threshold_db: float = 15.0,
    peak_headroom_threshold_dbfs: float = -1.0,
    peak_oversample: int = 4,
    dynamic_range_low_threshold_db: float = 6.0,
    dynamic_range_high_threshold_db: float = 20.0,
    dynamic_range_silence_threshold_db: float = 0.5,
    lra_buffer: RollingBuffer,
    lra_eval_interval_frames: int = 300,
    lra_low_threshold_lu: float = 5.0,
    lra_high_threshold_lu: float = 15.0,
    lra_silence_threshold_lu: float = 0.1,
    phase_warn_threshold: float = -0.3,
    meter_broker: MeterBroker | None = None,
    meter_publish_interval_frames: int = 5,
) -> None:
    """오디오 프레임 → 룰 평가 → 제어 송신 + 브로커 푸시.

    각 룰의 활성 여부는 `rule_toggles.snapshot()`을 매 프레임 시작 시 캐시해
    그 frame 안에서는 일관된 상태로 평가. 운영자가 service 도중 토글해도 다음
    프레임부터 즉시 반영 — 재시작 불필요.

    버퍼·detector는 *항상* 사전 생성. enabled 토글 OFF 시에도 누적은 계속됨
    (다시 ON 했을 때 즉시 의미 있는 결과 얻을 수 있도록).
    """
    meter_enabled = meter_broker is not None
    # 채널 → 최신 LRA 값 캐시. publish cadence(~9 Hz) > LRA eval cadence(~0.3 Hz)이므로
    # 매 publish에 최신 LRA를 포함하려면 이전 평가값을 보관해야 한다.
    latest_lra: dict[int, float] = {}
    frame_count = 0
    try:
        async for signal in audio.stream():
            frame_count += 1
            # 토글 상태를 frame 단위로 캐시 — 같은 frame 내 일관성 보장.
            tg = rule_toggles.snapshot()
            channels = _split_signal_to_channels(signal, sources_by_id)
            recommendations = (
                evaluate_all_channels(channels, rms_targets) if tg["loudness"] else []
            )

            # LUFS buffer는 항상 누적 — 토글 OFF여도 신호는 쌓아둠 → 다음 ON 시
            # 즉시 의미 있는 평가 가능.
            lufs_buffer.write(signal.samples)
            if (
                tg["lufs"]
                and frame_count % lufs_eval_interval_frames == 0
                and lufs_buffer.fill / signal.format.sample_rate >= MIN_DURATION_SECONDS
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

            # Feedback detector도 항상 update — persistence 추적은 *지속적으로*
            # 일어나야 의미 있음. 토글 OFF면 발화만 안 함.
            peaks_by_source = {}
            for channel in channels:
                ch_id = int(channel.source.channel)
                detector = feedback_detectors.get(ch_id)
                if detector is None:
                    continue
                peaks = detector.update(channel.samples)
                if peaks:
                    peaks_by_source[channel.source] = peaks
            if tg["feedback"] and peaks_by_source:
                recommendations.extend(
                    evaluate_all_feedback(
                        peaks_by_source,
                        pnr_threshold_db=feedback_pnr_threshold_db,
                    )
                )

            if tg["peak"]:
                recommendations.extend(
                    evaluate_all_channels_peak(
                        channels,
                        headroom_threshold_dbfs=peak_headroom_threshold_dbfs,
                        oversample=peak_oversample,
                    )
                )

            if tg["dynamic_range"]:
                recommendations.extend(
                    evaluate_all_channels_dynamic_range(
                        channels,
                        low_threshold_db=dynamic_range_low_threshold_db,
                        high_threshold_db=dynamic_range_high_threshold_db,
                        silence_threshold_db=dynamic_range_silence_threshold_db,
                    )
                )

            # Stereo phase는 항상 계산 — meter 캐시 갱신용. 룰 발화만 토글.
            phase_by_pair: dict[tuple[int, int], float] = {}
            seen_pairs: set[tuple[int, int]] = set()
            for ch in channels:
                partner_id = ch.source.stereo_pair_with
                if partner_id is None:
                    continue
                a_id = int(ch.source.channel)
                pair_key = (min(a_id, partner_id), max(a_id, partner_id))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                left_ch = next(
                    (c for c in channels if int(c.source.channel) == pair_key[0]),
                    None,
                )
                right_ch = next(
                    (c for c in channels if int(c.source.channel) == pair_key[1]),
                    None,
                )
                if left_ch is None or right_ch is None:
                    continue
                phase_by_pair[pair_key] = phase_correlation(
                    left_ch.samples, right_ch.samples
                )
            if tg["phase"]:
                recommendations.extend(
                    evaluate_all_phase_pairs(
                        channels, warn_threshold=phase_warn_threshold
                    )
                )

            # LRA buffer도 항상 누적. 토글 + interval 조건 일치 시 평가.
            lra_buffer.write(signal.samples)
            if (
                tg["lra"]
                and frame_count % lra_eval_interval_frames == 0
                and lra_buffer.fill / signal.format.sample_rate
                >= LRA_MIN_DURATION_SECONDS
            ):
                buffered_signal = Signal(
                    samples=lra_buffer.snapshot(),
                    format=signal.format,
                    capture_seq=signal.capture_seq,
                )
                lra_channels = _split_signal_to_channels(buffered_signal, sources_by_id)
                # LRA를 한 번만 계산 — meter 캐시·룰 평가 모두 같은 값 사용.
                for lra_ch in lra_channels:
                    try:
                        value = compute_lra(lra_ch.samples, lra_ch.format.sample_rate)
                    except ValueError:
                        # 채널 신호가 충분하지 않거나 무효 — 캐시 미반영.
                        continue
                    ch_id = int(lra_ch.source.channel)
                    latest_lra[ch_id] = value
                    rec = evaluate_lra_value(
                        lra_ch.source,
                        value,
                        low_threshold_lu=lra_low_threshold_lu,
                        high_threshold_lu=lra_high_threshold_lu,
                        silence_threshold_lu=lra_silence_threshold_lu,
                    )
                    if rec is not None:
                        recommendations.append(rec)

            if meter_enabled and frame_count % meter_publish_interval_frames == 0:
                assert meter_broker is not None
                meter_broker.publish(
                    _compute_meter_payload(
                        channels,
                        signal.capture_seq,
                        lra_by_channel=latest_lra if tg["lra"] else None,
                        phase_by_pair=phase_by_pair if phase_by_pair else None,
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
    meter_broker = MeterBroker()
    # audit_log_path가 None이면 record()/read_recent()가 모두 no-op.
    audit_logger = AuditLogger(path=cfg.audit_log_path)
    # channel_map은 audio 비활성 상태에서도 endpoint가 읽을 수 있어야 하므로
    # 라이프스팬 외부에서 1회 생성.
    channel_map = YamlChannelMetadata(cfg.channel_map_path)
    # rule_toggles는 audio 비활성 상태에서도 endpoint가 응답하도록 외부 생성.
    # audio enabled 시 lifespan이 *덮어쓸* 수도 있지만 동일 인스턴스 패턴은
    # 단순. 처리 루프는 본 인스턴스를 직접 받음 → 동기.
    rule_toggles_default = RuleToggles.from_config_flags(
        loudness=True,
        lufs=cfg.lufs_analysis.enabled,
        peak=cfg.peak_analysis.enabled,
        feedback=cfg.feedback_analysis.enabled,
        dynamic_range=cfg.dynamic_range_analysis.enabled,
        lra=cfg.lra_analysis.enabled,
        phase=cfg.phase_analysis.enabled,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        audio: (
            SoundDeviceAudioSource | SyntheticAudioSource | WavReplayAudioSource | None
        ) = None

        if cfg.audio.enabled:
            try:
                if cfg.audio.source is AudioSource.SYNTHETIC:
                    audio = SyntheticAudioSource(
                        cfg.audio,
                        amplitudes_dbfs=cfg.audio.synthetic_amplitudes_dbfs,
                    )
                elif cfg.audio.source is AudioSource.WAV:
                    audio = WavReplayAudioSource(cfg.audio)
                else:
                    audio = SoundDeviceAudioSource(cfg.audio)
                controller = M32OscController(
                    cfg.m32,
                    audit_logger=audit_logger,
                    action_history=action_history,
                )
                app.state.controller = controller
                sources = list(await channel_map.get_all_channels())
                sources_by_id = {int(s.channel): s for s in sources}
                rms_targets = _build_rms_dbfs_targets(cfg)

                # 버퍼·detector는 *항상* 생성 — 토글 OFF여도 누적은 진행되어
                # 다시 ON 시 즉시 의미 있는 평가가 가능. config에 값이 없으면
                # 합리적 디폴트 사용.
                lufs_capacity = int(
                    cfg.audio.sample_rate * cfg.lufs_analysis.buffer_seconds
                )
                lufs_buffer = RollingBuffer(
                    capacity_frames=lufs_capacity,
                    num_channels=cfg.audio.num_channels,
                    dtype=np.float32,
                )
                lufs_targets = _build_lufs_targets(cfg)

                lra_capacity = int(
                    cfg.audio.sample_rate * cfg.lra_analysis.buffer_seconds
                )
                lra_buffer = RollingBuffer(
                    capacity_frames=lra_capacity,
                    num_channels=cfg.audio.num_channels,
                    dtype=np.float32,
                )

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

                # rule_toggles는 create_app에서 만든 인스턴스를 그대로 사용.
                # endpoint가 mutate → 처리 루프가 다음 frame부터 반영.
                rule_toggles = rule_toggles_default

                task = asyncio.create_task(
                    _processing_loop(
                        audio,
                        controller,
                        broker,
                        sources_by_id,
                        rms_targets,
                        rule_toggles,
                        lufs_buffer=lufs_buffer,
                        lufs_targets=lufs_targets,
                        lufs_eval_interval_frames=cfg.lufs_analysis.eval_interval_frames,
                        feedback_detectors=feedback_detectors,
                        feedback_pnr_threshold_db=cfg.feedback_analysis.pnr_threshold_db,
                        peak_headroom_threshold_dbfs=(
                            cfg.peak_analysis.headroom_threshold_dbfs
                        ),
                        peak_oversample=cfg.peak_analysis.oversample,
                        dynamic_range_low_threshold_db=(
                            cfg.dynamic_range_analysis.low_threshold_db
                        ),
                        dynamic_range_high_threshold_db=(
                            cfg.dynamic_range_analysis.high_threshold_db
                        ),
                        dynamic_range_silence_threshold_db=(
                            cfg.dynamic_range_analysis.silence_threshold_db
                        ),
                        lra_buffer=lra_buffer,
                        lra_eval_interval_frames=(
                            cfg.lra_analysis.eval_interval_frames
                        ),
                        lra_low_threshold_lu=cfg.lra_analysis.low_threshold_lu,
                        lra_high_threshold_lu=cfg.lra_analysis.high_threshold_lu,
                        lra_silence_threshold_lu=(
                            cfg.lra_analysis.silence_threshold_lu
                        ),
                        phase_warn_threshold=cfg.phase_analysis.warn_threshold,
                        meter_broker=(
                            meter_broker if cfg.meter_stream.enabled else None
                        ),
                        meter_publish_interval_frames=(
                            cfg.meter_stream.publish_interval_frames
                        ),
                    )
                )
                logger.info(
                    "audio started (mode=%s device=%s lufs=%s "
                    "feedback=%s peak=%s dr=%s lra=%s meters=%s)",
                    cfg.m32.operating_mode.value,
                    cfg.audio.device_substring,
                    "on" if cfg.lufs_analysis.enabled else "off",
                    "on" if cfg.feedback_analysis.enabled else "off",
                    "on" if cfg.peak_analysis.enabled else "off",
                    "on" if cfg.dynamic_range_analysis.enabled else "off",
                    "on" if cfg.lra_analysis.enabled else "off",
                    "on" if cfg.meter_stream.enabled else "off",
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
    app.state.audit_logger = audit_logger
    app.state.channel_map = channel_map
    app.state.rule_toggles = rule_toggles_default

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
            dynamic_range_analysis_enabled=cfg.dynamic_range_analysis.enabled,
            lra_analysis_enabled=cfg.lra_analysis.enabled,
            phase_analysis_enabled=cfg.phase_analysis.enabled,
            meter_stream_enabled=cfg.meter_stream.enabled,
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

    @app.get("/channels", response_model=ChannelMapResponse)
    async def get_channels(request: Request) -> ChannelMapResponse:
        """현재 채널맵 — `config/channels.yaml`을 그대로 반영.

        운영자가 매핑을 외부 편집 후 새로고침해 즉시 확인할 수 있도록 매 요청마다
        파일을 다시 읽는다(`reload()` 후 read). 매우 자주 호출되는 경로가 아니라 OK.
        """
        cm: YamlChannelMetadata = request.app.state.channel_map
        cm.reload()
        sources = list(await cm.get_all_channels())
        entries = [
            ChannelMapEntry(
                channel=int(s.channel),
                category=s.category.value,
                label=s.label,
                stereo_pair_with=s.stereo_pair_with,
            )
            for s in sources
        ]
        return ChannelMapResponse(entries=entries)

    @app.put("/channels/{channel_id}", response_model=ChannelMapEntry)
    async def update_channel(
        channel_id: int,
        body: ChannelMapUpdateRequest,
        request: Request,
    ) -> ChannelMapEntry:
        """채널 카테고리·라벨 갱신 — YAML에 즉시 영속, 라이브 루프는 재시작 후 반영.

        Body:
            category: 'vocal' | 'preacher' | 'choir' | 'instrument' | 'unknown'
            label: 자유 문자열 (빈 문자열 허용).

        Returns:
            갱신 직후의 ChannelMapEntry.

        Raises:
            HTTP 400: category가 유효하지 않을 때.
            HTTP 422: channel_id가 1 이상이 아닐 때 (FastAPI 기본 검증).
        """
        from fastapi import HTTPException

        from mixpilot.domain import SourceCategory

        if channel_id < 1:
            raise HTTPException(
                status_code=422, detail=f"channel_id must be >= 1, got {channel_id}"
            )
        try:
            category = SourceCategory(body.category.lower())
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"invalid category: {body.category}"
            ) from e
        cm: YamlChannelMetadata = request.app.state.channel_map
        # stereo_pair_with 가드: 자기 자신을 페어로 설정 불가, 1 이상이거나 None.
        pair = body.stereo_pair_with
        if pair is not None:
            if pair == channel_id:
                raise HTTPException(
                    status_code=400,
                    detail="stereo_pair_with cannot equal channel_id",
                )
            if pair < 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"stereo_pair_with must be >= 1, got {pair}",
                )
        updated = cm.update_channel(
            channel_id,
            category=category,
            label=body.label,
            stereo_pair_with=pair,
        )
        return ChannelMapEntry(
            channel=int(updated.channel),
            category=updated.category.value,
            label=updated.label,
            stereo_pair_with=updated.stereo_pair_with,
        )

    @app.get("/control/rules", response_model=RulesResponse)
    async def get_rules(request: Request) -> RulesResponse:
        """모든 룰의 현재 토글 상태 — service 도중 운영자 가시용."""
        toggles: RuleToggles = request.app.state.rule_toggles
        snap = toggles.snapshot()
        rules = [RuleState(name=name, enabled=snap[name]) for name in RULE_NAMES]
        return RulesResponse(rules=rules)

    @app.put("/control/rules/{rule_name}", response_model=RuleState)
    async def update_rule(
        rule_name: str,
        body: RuleToggleRequest,
        request: Request,
    ) -> RuleState:
        """단일 룰 토글 — 처리 루프는 다음 frame부터 반영(재시작 불필요).

        Raises:
            HTTP 400: 알 수 없는 룰 이름.
        """
        from fastapi import HTTPException

        toggles: RuleToggles = request.app.state.rule_toggles
        try:
            toggles.set_enabled(rule_name, body.enabled)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RuleState(name=rule_name, enabled=toggles.is_enabled(rule_name))

    @app.get("/control/audit-log/recent", response_model=AuditLogResponse)
    async def audit_log_recent(request: Request, limit: int = 50) -> AuditLogResponse:
        """ADR-0008 §3 감사 JSONL의 최근 레코드 — 영구 이력 조회.

        `recent-actions`는 메모리 60초 윈도우(applied만), 이 엔드포인트는
        디스크 JSONL을 읽어 *모든* 자동 액션 시도(applied·blocked_policy·
        blocked_guard)를 최신 순으로 반환.

        `audit_log_path`가 None이면 `enabled=false` + 빈 리스트.
        """
        if limit < 1 or limit > 500:
            limit = 50
        audit: AuditLogger = request.app.state.audit_logger
        enabled = audit.path is not None
        raw = audit.read_recent(limit=limit) if enabled else []
        entries = [
            AuditEntry(
                timestamp=r["timestamp"],
                outcome=r["outcome"],
                effective_mode=r["effective_mode"],
                reason=r.get("reason", ""),
                channel=int(r["channel"]),
                category=r["category"],
                label=r.get("label", ""),
                kind=r["kind"],
                confidence=float(r["confidence"]),
                rec_reason=r.get("rec_reason", ""),
                osc_messages=[
                    OscMessage(address=addr, value=value)
                    for addr, value in r.get("osc_messages", [])
                ],
            )
            for r in raw
        ]
        return AuditLogResponse(enabled=enabled, entries=entries)

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

    @app.get(
        "/meters",
        responses={
            200: {
                "model": MeterSnapshotEvent,
                "description": (
                    "Server-Sent Events 스트림. 각 'data:' 라인 본문이 "
                    "MeterSnapshotEvent JSON. 미터는 throttled "
                    "(`meter_stream.publish_interval_frames`)."
                ),
                "content": {"text/event-stream": {}},
            }
        },
    )
    async def stream_meters(request: Request) -> StreamingResponse:
        """채널별 RMS·peak dBFS 스트림.

        `meter_stream.enabled`가 false면 연결은 성립하되 데이터 이벤트가
        생기지 않는다(keep-alive만 송신).
        """
        queue = meter_broker.subscribe()

        async def event_generator() -> AsyncIterator[str]:
            try:
                yield "event: subscribed\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            finally:
                meter_broker.unsubscribe(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app


# uvicorn / fastapi CLI가 import할 모듈 레벨 인스턴스.
app = create_app()
