"""합성 오디오 소스 — `AudioSource` 포트의 데모/테스트용 구현.

M32 같은 실 하드웨어 없이 처리 루프를 가동할 수 있게 한다. 각 채널은 시간에
따라 연속하는 1 kHz 사인파를 amplitude만 다르게 송출. 실시간 클럭 흐름을
흉내내기 위해 매 block_size 샘플 뒤 `block_size / sample_rate` 만큼 sleep.

용도:
- 개발자 데모: 브라우저 UI에서 `/recommendations` 스트림 실제로 보기.
- 통합 테스트: 라이브 입력 시뮬레이션.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence

import numpy as np

from mixpilot.config import AudioConfig
from mixpilot.domain import AudioFormat, Signal

logger = logging.getLogger(__name__)


def _default_amplitudes_dbfs(num_channels: int) -> list[float]:
    """채널별 디폴트 amplitude — -30 dBFS(낮음) ~ -3 dBFS(높음) 선형 step."""
    if num_channels == 1:
        return [-15.0]
    return [-30.0 + (n / (num_channels - 1)) * 27.0 for n in range(num_channels)]


class SyntheticAudioSource:
    """`AudioSource` 포트의 합성 1 kHz 사인 구현."""

    def __init__(
        self,
        config: AudioConfig,
        *,
        amplitudes_dbfs: Sequence[float] | None = None,
        freq_hz: float = 1000.0,
    ) -> None:
        self._config = config
        self._format = AudioFormat(
            sample_rate=config.sample_rate,
            num_channels=config.num_channels,
            sample_dtype="float32",
        )
        self._freq = freq_hz
        amps = (
            list(amplitudes_dbfs)
            if amplitudes_dbfs is not None
            else _default_amplitudes_dbfs(config.num_channels)
        )
        if len(amps) != config.num_channels:
            raise ValueError(
                f"amplitudes_dbfs length {len(amps)} != "
                f"num_channels {config.num_channels}"
            )
        self._amplitudes = np.array(
            [10.0 ** (db / 20.0) for db in amps], dtype=np.float32
        )
        self._t_offset = 0  # 누적 샘플 인덱스 — 사인파 연속성 보장.
        self._seq = 0
        self._running = True

    @property
    def format(self) -> AudioFormat:
        return self._format

    async def stream(self) -> AsyncIterator[Signal]:
        sr = self._config.sample_rate
        block = self._config.block_size
        block_duration = block / sr
        logger.info(
            "synthetic audio started (sr=%d, channels=%d, block=%d)",
            sr,
            self._config.num_channels,
            block,
        )
        try:
            while self._running:
                t = (np.arange(block, dtype=np.float64) + self._t_offset) / sr
                base = np.sin(2 * np.pi * self._freq * t).astype(np.float32)
                # shape (block, num_channels) — base를 채널별 amp로 스케일.
                samples = base[:, np.newaxis] * self._amplitudes[np.newaxis, :]
                self._t_offset += block
                self._seq += 1
                yield Signal(
                    samples=samples,
                    format=self._format,
                    capture_seq=self._seq,
                )
                await asyncio.sleep(block_duration)
        finally:
            logger.info("synthetic audio stopped (seq=%d)", self._seq)

    async def close(self) -> None:
        """루프 중단 요청 — 다음 yield 후 종료."""
        self._running = False


# 모듈 레벨 헬퍼 — 테스트가 amplitudes 디폴트를 재사용할 수 있도록.
default_amplitudes_dbfs = _default_amplitudes_dbfs
