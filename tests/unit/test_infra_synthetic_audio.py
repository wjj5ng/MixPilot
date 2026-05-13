"""infra.synthetic_audio 단위 테스트 — 합성 사인파 입력."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from mixpilot.config import AudioConfig, AudioSource
from mixpilot.infra import SyntheticAudioSource
from mixpilot.infra.synthetic_audio import default_amplitudes_dbfs


def _cfg(num_channels: int = 4, block_size: int = 128) -> AudioConfig:
    return AudioConfig(
        enabled=True,
        source=AudioSource.SYNTHETIC,
        sample_rate=48000,
        block_size=block_size,
        num_channels=num_channels,
    )


async def _collect(src: SyntheticAudioSource, n: int) -> list:
    out = []
    async for sig in src.stream():
        out.append(sig)
        if len(out) >= n:
            await src.close()
            break
    return out


class TestConstruction:
    def test_format_matches_config(self) -> None:
        src = SyntheticAudioSource(_cfg(num_channels=8))
        assert src.format.sample_rate == 48000
        assert src.format.num_channels == 8

    def test_custom_amplitudes_accepted(self) -> None:
        src = SyntheticAudioSource(
            _cfg(num_channels=3), amplitudes_dbfs=[-20.0, -10.0, 0.0]
        )
        # 사인 amplitude는 10**(dbfs/20).
        np.testing.assert_allclose(
            src._amplitudes,
            np.array([0.1, 0.31622776, 1.0], dtype=np.float32),
            rtol=1e-4,
        )

    def test_rejects_amplitudes_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="amplitudes_dbfs"):
            SyntheticAudioSource(_cfg(num_channels=4), amplitudes_dbfs=[-10.0, -5.0])


class TestDefaultAmplitudes:
    def test_single_channel_default(self) -> None:
        assert default_amplitudes_dbfs(1) == [-15.0]

    def test_two_channels_step(self) -> None:
        assert default_amplitudes_dbfs(2) == [-30.0, -3.0]

    def test_32_channels_monotonic_increasing(self) -> None:
        amps = default_amplitudes_dbfs(32)
        assert len(amps) == 32
        assert amps[0] == pytest.approx(-30.0)
        assert amps[-1] == pytest.approx(-3.0)
        # 단조 증가.
        for i in range(31):
            assert amps[i + 1] > amps[i]


class TestStream:
    def test_yields_signals_with_correct_shape(self) -> None:
        src = SyntheticAudioSource(_cfg(num_channels=4, block_size=64))
        sigs = asyncio.run(_collect(src, 2))
        assert len(sigs) == 2
        for sig in sigs:
            assert sig.samples.shape == (64, 4)
            assert sig.samples.dtype == np.float32

    def test_capture_seq_increments(self) -> None:
        src = SyntheticAudioSource(_cfg(num_channels=2, block_size=64))
        sigs = asyncio.run(_collect(src, 3))
        assert [s.capture_seq for s in sigs] == [1, 2, 3]

    def test_per_channel_amplitude(self) -> None:
        src = SyntheticAudioSource(
            _cfg(num_channels=3, block_size=256),
            amplitudes_dbfs=[-40.0, -20.0, 0.0],
        )
        sigs = asyncio.run(_collect(src, 1))
        # 채널별 sample peak ≈ amplitude.
        peaks = np.abs(sigs[0].samples).max(axis=0)
        np.testing.assert_allclose(
            peaks, [10 ** (-40 / 20), 10 ** (-20 / 20), 1.0], rtol=0.05
        )

    def test_sine_continuity_across_blocks(self) -> None:
        # t_offset이 누적되어 사인이 끊기지 않아야 한다.
        src = SyntheticAudioSource(
            _cfg(num_channels=1, block_size=128),
            amplitudes_dbfs=[0.0],
        )
        sigs = asyncio.run(_collect(src, 2))
        joined = np.concatenate([s.samples[:, 0] for s in sigs])
        # 두 블록 경계에서 phase 불연속 없는지 확인.
        # 사인의 일정 주파수면 1차 차분이 대체로 부드러움.
        diffs = np.diff(joined)
        # 1kHz @ 48k → 샘플당 위상 변화 작음 → max(|diff|) < 0.2 정도.
        assert np.max(np.abs(diffs)) < 0.2

    def test_close_stops_stream(self) -> None:
        # close 호출 후 다음 yield까지만 진행하고 종료.
        src = SyntheticAudioSource(_cfg(num_channels=1, block_size=64))
        sigs = asyncio.run(_collect(src, 1))
        assert len(sigs) == 1
        # close 후 다시 stream을 돌려도 종료된 상태.
        assert src._running is False


class TestDeterminism:
    def test_same_config_same_signals(self) -> None:
        # 같은 설정 + 같은 amplitude로 두 소스 — 같은 sample 시퀀스.
        a = SyntheticAudioSource(
            _cfg(num_channels=2, block_size=64), amplitudes_dbfs=[-10.0, -20.0]
        )
        b = SyntheticAudioSource(
            _cfg(num_channels=2, block_size=64), amplitudes_dbfs=[-10.0, -20.0]
        )
        a_sigs = asyncio.run(_collect(a, 2))
        b_sigs = asyncio.run(_collect(b, 2))
        for sa, sb in zip(a_sigs, b_sigs, strict=True):
            np.testing.assert_array_equal(sa.samples, sb.samples)
