"""sounddevice 기반 다채널 오디오 캡처 — ADR-0004.

M32 USB 인터페이스를 32-in 멀티채널 디바이스로 받는다. PortAudio 콜백을
asyncio.Queue로 브릿지해 `AudioSource` 포트를 구현.

sounddevice 모듈은 lazy import — 인스턴스화 시점에만 필요해서, 임포트
실패해도 다른 인프라 모듈은 영향 없음. 테스트는 `sd_module`을 주입.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from mixpilot.config import AudioConfig
from mixpilot.domain import AudioFormat, Signal

logger = logging.getLogger(__name__)


class SoundDeviceAudioSource:
    """`AudioSource` 포트 구현 (sounddevice 기반)."""

    def __init__(
        self,
        config: AudioConfig,
        sd_module: Any = None,
    ) -> None:
        """
        Args:
            config: 오디오 설정 (디바이스 substring·sample rate·block size 등).
            sd_module: sounddevice 모듈 또는 동등 인터페이스. 미지정 시 lazy import.
        """
        if sd_module is None:
            import sounddevice

            sd_module = sounddevice
        self._sd = sd_module
        self._config = config
        self._format = AudioFormat(
            sample_rate=config.sample_rate,
            num_channels=config.num_channels,
            sample_dtype="float32",
        )
        self._stream: Any = None
        self._queue: asyncio.Queue[Signal] | None = None
        self._seq = 0

    @property
    def format(self) -> AudioFormat:
        return self._format

    def _resolve_device_index(self) -> int | None:
        """`device_substring` 매칭 입력 디바이스 인덱스.

        빈 substring이면 None(OS 디폴트 입력). 매칭 디바이스가 없으면 RuntimeError.
        """
        substring = self._config.device_substring.strip()
        if not substring:
            return None
        devices = list(self._sd.query_devices())
        for i, dev in enumerate(devices):
            name = str(dev.get("name", ""))
            max_in = int(dev.get("max_input_channels", 0))
            if substring.lower() in name.lower() and max_in > 0:
                return i
        available = [d.get("name") for d in devices]
        raise RuntimeError(
            f"No input device matching '{substring}'. Available: {available}"
        )

    async def stream(self) -> AsyncIterator[Signal]:
        """입력 스트림 시작 + 프레임을 비동기로 yield.

        sounddevice 콜백은 별도 스레드에서 호출되므로 loop.call_soon_threadsafe로
        asyncio.Queue에 넣는다. 큐가 가득 차면 프레임을 드롭(라이브 우선).
        """
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=64)
        device = self._resolve_device_index()
        queue = self._queue  # local capture for callback

        def callback(
            indata: np.ndarray,
            frames: int,
            time_info: Any,
            status: Any,
        ) -> None:
            if status:
                logger.warning("audio capture status: %s", status)
            self._seq += 1
            signal = Signal(
                samples=indata.copy(),
                format=self._format,
                capture_seq=self._seq,
            )

            def _enqueue() -> None:
                try:
                    queue.put_nowait(signal)
                except asyncio.QueueFull:
                    logger.warning("audio queue full; dropping frame %d", self._seq)

            loop.call_soon_threadsafe(_enqueue)

        self._stream = self._sd.InputStream(
            samplerate=self._config.sample_rate,
            blocksize=self._config.block_size,
            channels=self._config.num_channels,
            dtype="float32",
            device=device,
            callback=callback,
        )
        self._stream.start()

        try:
            while True:
                yield await queue.get()
        finally:
            await self.close()

    async def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
