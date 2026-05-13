"""infra.audio_capture 단위 테스트 — device 해석 + format/lifecycle.

stream() 자체는 PortAudio 콜백 + asyncio 통합이라 실 하드웨어/통합 환경에서
검증. 여기서는 sd_module을 mock으로 주입해 결정 로직만 검증한다.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from mixpilot.config import AudioConfig
from mixpilot.infra.audio_capture import SoundDeviceAudioSource


def _fake_sd(devices: list[dict[str, Any]]) -> MagicMock:
    mock = MagicMock()
    mock.query_devices.return_value = devices
    mock.InputStream = MagicMock()
    return mock


class TestResolveDeviceIndex:
    def test_finds_device_by_substring(self) -> None:
        sd = _fake_sd(
            [
                {"name": "Built-in Microphone", "max_input_channels": 1},
                {"name": "X32 USB ASIO Driver", "max_input_channels": 32},
                {"name": "Headphones", "max_input_channels": 0},
            ]
        )
        src = SoundDeviceAudioSource(AudioConfig(device_substring="X32"), sd_module=sd)
        assert src._resolve_device_index() == 1

    def test_case_insensitive_match(self) -> None:
        sd = _fake_sd(
            [
                {"name": "m32 Audio", "max_input_channels": 32},
            ]
        )
        src = SoundDeviceAudioSource(AudioConfig(device_substring="M32"), sd_module=sd)
        assert src._resolve_device_index() == 0

    def test_empty_substring_returns_none(self) -> None:
        sd = _fake_sd(
            [{"name": "Anything", "max_input_channels": 2}],
        )
        src = SoundDeviceAudioSource(AudioConfig(device_substring=""), sd_module=sd)
        assert src._resolve_device_index() is None

    def test_whitespace_only_substring_returns_none(self) -> None:
        sd = _fake_sd([{"name": "x", "max_input_channels": 2}])
        src = SoundDeviceAudioSource(AudioConfig(device_substring="   "), sd_module=sd)
        assert src._resolve_device_index() is None

    def test_skips_devices_without_input_channels(self) -> None:
        sd = _fake_sd(
            [
                {"name": "M32 Output Only", "max_input_channels": 0},
                {"name": "M32 USB", "max_input_channels": 32},
            ]
        )
        src = SoundDeviceAudioSource(AudioConfig(device_substring="M32"), sd_module=sd)
        assert src._resolve_device_index() == 1

    def test_raises_when_no_match(self) -> None:
        sd = _fake_sd(
            [
                {"name": "Built-in", "max_input_channels": 1},
            ]
        )
        src = SoundDeviceAudioSource(AudioConfig(device_substring="M32"), sd_module=sd)
        with pytest.raises(RuntimeError, match="M32"):
            src._resolve_device_index()


class TestFormat:
    def test_format_reflects_config(self) -> None:
        sd = _fake_sd([])
        cfg = AudioConfig(sample_rate=44100, num_channels=16, device_substring="")
        src = SoundDeviceAudioSource(cfg, sd_module=sd)
        fmt = src.format
        assert fmt.sample_rate == 44100
        assert fmt.num_channels == 16
        assert fmt.sample_dtype == "float32"


class TestCloseLifecycle:
    def test_close_before_start_is_noop(self) -> None:
        sd = _fake_sd([])
        src = SoundDeviceAudioSource(AudioConfig(device_substring=""), sd_module=sd)
        # close() 가 stream 없이도 예외 없이 끝나야 함.
        asyncio.run(src.close())

    def test_close_stops_and_clears_stream(self) -> None:
        sd = _fake_sd([])
        src = SoundDeviceAudioSource(AudioConfig(device_substring=""), sd_module=sd)
        fake_stream = MagicMock()
        src._stream = fake_stream
        asyncio.run(src.close())
        fake_stream.stop.assert_called_once()
        fake_stream.close.assert_called_once()
        assert src._stream is None
