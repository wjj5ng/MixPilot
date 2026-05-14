"""WAV 재생 오디오 소스 — Virtual Soundcheck·회귀 검증용.

녹화된 다채널 WAV 파일을 실시간 cadence(block_size / sample_rate)로 송출.
M32 없이 *실 신호*로 처리 루프(룰·미터·OSC)를 검증한다(ADR-0006 보조 경로).

설계:
- 메모리 1회 로드 — 라이브 운영자 노트북에서 수~수십 분 길이까지 안정.
- `replay_loop=True`면 끝점에 도달 시 처음부터 다시 재생 (Soundcheck 반복).
- 채널 수 매칭:
  * WAV 채널 수 == config.num_channels: 그대로 사용.
  * WAV 단일 채널: 모든 config 채널에 broadcast.
  * 그 외: 명시적 에러 — 운영자가 의도하지 않은 매핑을 사전 차단.
- sample_rate 매칭은 *엄격* — resample은 의도적으로 지원하지 않음(품질·복잡도).
  WAV가 다르면 미리 변환해두라고 명시적 에러.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from mixpilot.config import AudioConfig
from mixpilot.domain import AudioFormat, Signal

logger = logging.getLogger(__name__)


def _load_wav_as_float32(path: Path) -> tuple[int, np.ndarray]:
    """WAV를 (sample_rate, samples[frames, channels] float32) 형태로 로드.

    PCM int16/int32/float32 모두 지원. int 타입은 -1.0~1.0 float32로 정규화.
    """
    sr, raw = wavfile.read(str(path))
    if raw.ndim == 1:
        raw = raw[:, np.newaxis]
    if raw.dtype == np.int16:
        data = raw.astype(np.float32) / np.float32(32768.0)
    elif raw.dtype == np.int32:
        data = raw.astype(np.float32) / np.float32(2147483648.0)
    elif raw.dtype == np.float32:
        data = raw
    elif raw.dtype == np.float64:
        data = raw.astype(np.float32)
    else:
        raise ValueError(
            f"unsupported WAV sample dtype {raw.dtype} (expected int16/int32/float)"
        )
    return int(sr), data


class WavReplayAudioSource:
    """`AudioSource` 포트의 WAV 재생 구현."""

    def __init__(self, config: AudioConfig) -> None:
        if config.replay_path is None:
            raise ValueError(
                "AudioConfig.replay_path must be set when source=wav"
            )
        if not config.replay_path.exists():
            raise FileNotFoundError(f"WAV not found: {config.replay_path}")

        sr, data = _load_wav_as_float32(config.replay_path)
        if sr != config.sample_rate:
            raise ValueError(
                f"WAV sample rate {sr} != config.sample_rate "
                f"{config.sample_rate}; resample WAV first"
            )

        # 채널 수 매핑.
        n_wav = data.shape[1]
        if n_wav == config.num_channels:
            self._data = data
        elif n_wav == 1:
            # broadcast 1 → num_channels.
            self._data = np.broadcast_to(
                data, (data.shape[0], config.num_channels)
            ).copy()
        else:
            raise ValueError(
                f"WAV has {n_wav} channels but config.num_channels="
                f"{config.num_channels} (only equal or mono-broadcast supported)"
            )

        self._config = config
        self._format = AudioFormat(
            sample_rate=config.sample_rate,
            num_channels=config.num_channels,
            sample_dtype="float32",
        )
        self._cursor = 0
        self._seq = 0
        self._running = True

    @property
    def format(self) -> AudioFormat:
        return self._format

    async def stream(self) -> AsyncIterator[Signal]:
        sr = self._config.sample_rate
        block = self._config.block_size
        block_duration = block / sr
        total_frames = self._data.shape[0]
        loop = self._config.replay_loop
        logger.info(
            "wav replay started (path=%s, frames=%d, channels=%d, loop=%s)",
            self._config.replay_path,
            total_frames,
            self._config.num_channels,
            loop,
        )
        try:
            while self._running:
                # 다음 block 추출 — 경계를 넘으면 wrap 또는 종료.
                end = self._cursor + block
                if end <= total_frames:
                    chunk = self._data[self._cursor:end]
                    self._cursor = end
                else:
                    head = self._data[self._cursor:total_frames]
                    if not loop:
                        # 마지막 부분 패딩 후 송출 후 종료.
                        if head.size > 0:
                            padded = np.zeros(
                                (block, self._config.num_channels),
                                dtype=np.float32,
                            )
                            padded[: head.shape[0]] = head
                            chunk = padded
                            self._seq += 1
                            yield Signal(
                                samples=chunk,
                                format=self._format,
                                capture_seq=self._seq,
                            )
                        logger.info("wav replay finished (no loop)")
                        return
                    # 끝까지 가서 처음으로 wrap.
                    remainder = block - head.shape[0]
                    tail = self._data[:remainder]
                    chunk = np.concatenate([head, tail], axis=0)
                    self._cursor = remainder
                self._seq += 1
                yield Signal(
                    samples=chunk,
                    format=self._format,
                    capture_seq=self._seq,
                )
                await asyncio.sleep(block_duration)
        finally:
            logger.info("wav replay stopped (seq=%d)", self._seq)

    async def close(self) -> None:
        """루프 중단 요청 — 다음 yield 후 종료."""
        self._running = False
