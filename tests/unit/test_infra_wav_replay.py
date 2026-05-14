"""WavReplayAudioSource 단위 테스트 — 로드·broadcast·loop·종료."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from mixpilot.config import AudioConfig, AudioSource
from mixpilot.infra.wav_replay import WavReplayAudioSource


def _write_wav(
    path: Path,
    *,
    samples: np.ndarray,
    sample_rate: int = 48000,
) -> None:
    wavfile.write(str(path), sample_rate, samples)


def _config(
    path: Path,
    *,
    num_channels: int = 1,
    block_size: int = 512,
    sample_rate: int = 48000,
    loop: bool = True,
) -> AudioConfig:
    return AudioConfig(
        enabled=True,
        source=AudioSource.WAV,
        num_channels=num_channels,
        block_size=block_size,
        sample_rate=sample_rate,
        replay_path=path,
        replay_loop=loop,
    )


class TestInputValidation:
    def test_missing_path_raises(self) -> None:
        cfg = AudioConfig(
            enabled=True,
            source=AudioSource.WAV,
            replay_path=None,
        )
        with pytest.raises(ValueError, match="replay_path must be set"):
            WavReplayAudioSource(cfg)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        cfg = AudioConfig(
            enabled=True,
            source=AudioSource.WAV,
            replay_path=tmp_path / "no.wav",
        )
        with pytest.raises(FileNotFoundError, match="WAV not found"):
            WavReplayAudioSource(cfg)

    def test_sample_rate_mismatch_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "a.wav"
        # 44.1 kHz wav를 48 kHz config로 로드 → 거부.
        _write_wav(path, samples=np.zeros(100, dtype=np.float32), sample_rate=44100)
        cfg = _config(path, sample_rate=48000)
        with pytest.raises(ValueError, match="sample rate"):
            WavReplayAudioSource(cfg)

    def test_channel_count_mismatch_raises(self, tmp_path: Path) -> None:
        # 4채널 wav를 8채널 config로 로드 → 거부 (broadcast 안 함).
        path = tmp_path / "a.wav"
        data = np.zeros((100, 4), dtype=np.float32)
        _write_wav(path, samples=data)
        cfg = _config(path, num_channels=8)
        with pytest.raises(ValueError, match="channels"):
            WavReplayAudioSource(cfg)


class TestLoadAndStream:
    def test_mono_broadcasts_to_all_channels(self, tmp_path: Path) -> None:
        path = tmp_path / "mono.wav"
        n = 2048
        t = np.arange(n) / 48000
        mono = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        _write_wav(path, samples=mono)
        cfg = _config(path, num_channels=4, block_size=512)
        src = WavReplayAudioSource(cfg)
        assert src.format.num_channels == 4

        async def collect_one() -> None:
            async for signal in src.stream():
                assert signal.samples.shape == (512, 4)
                # 모든 채널이 같은 값(broadcast 결과).
                for ch in range(1, 4):
                    np.testing.assert_array_equal(
                        signal.samples[:, 0], signal.samples[:, ch]
                    )
                await src.close()
                break

        asyncio.run(collect_one())

    def test_multichannel_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / "multi.wav"
        n = 2048
        # 4채널, 채널마다 다른 amplitude.
        data = np.zeros((n, 4), dtype=np.float32)
        for ch in range(4):
            data[:, ch] = (ch + 1) * 0.1
        _write_wav(path, samples=data)
        cfg = _config(path, num_channels=4, block_size=512)
        src = WavReplayAudioSource(cfg)

        async def collect_one() -> None:
            async for signal in src.stream():
                # 채널별 다른 값 보존.
                for ch in range(4):
                    expected = (ch + 1) * 0.1
                    np.testing.assert_allclose(
                        signal.samples[:, ch], expected, atol=1e-6
                    )
                await src.close()
                break

        asyncio.run(collect_one())

    def test_int16_wav_normalized_to_float32(self, tmp_path: Path) -> None:
        path = tmp_path / "int16.wav"
        # int16 풀-스케일 = 32767 → float32 ~1.0.
        data = np.full(2048, 32767, dtype=np.int16)
        _write_wav(path, samples=data)
        cfg = _config(path, num_channels=1, block_size=512)
        src = WavReplayAudioSource(cfg)

        async def collect_one() -> None:
            async for signal in src.stream():
                assert signal.samples.dtype == np.float32
                # 정규화 검증 — 0.9990 ~ 1.0 사이.
                assert np.all(signal.samples >= 0.99)
                assert np.all(signal.samples <= 1.0)
                await src.close()
                break

        asyncio.run(collect_one())

    def test_capture_seq_monotonic(self, tmp_path: Path) -> None:
        path = tmp_path / "x.wav"
        _write_wav(path, samples=np.zeros(2048, dtype=np.float32))
        cfg = _config(path, num_channels=1, block_size=512)
        src = WavReplayAudioSource(cfg)

        async def collect_three() -> list[int]:
            seqs: list[int] = []
            async for signal in src.stream():
                seqs.append(signal.capture_seq)
                if len(seqs) >= 3:
                    await src.close()
                    break
            return seqs

        seqs = asyncio.run(collect_three())
        assert seqs == [1, 2, 3]


class TestLoopBehavior:
    def test_loop_wraps_at_end(self, tmp_path: Path) -> None:
        # 1024 샘플 신호를 block_size=512로 → 2 블록 + 그 다음은 처음으로 wrap.
        path = tmp_path / "short.wav"
        data = np.linspace(0.0, 0.9, 1024, dtype=np.float32)
        _write_wav(path, samples=data)
        cfg = _config(path, num_channels=1, block_size=512, loop=True)
        src = WavReplayAudioSource(cfg)

        async def collect_blocks() -> list[np.ndarray]:
            chunks: list[np.ndarray] = []
            async for signal in src.stream():
                chunks.append(signal.samples[:, 0].copy())
                if len(chunks) >= 3:
                    await src.close()
                    break
            return chunks

        chunks = asyncio.run(collect_blocks())
        # 3번째 블록은 처음 블록(0~511 인덱스)과 동일해야 함.
        np.testing.assert_allclose(chunks[0], chunks[2], atol=1e-6)

    def test_no_loop_terminates_at_end(self, tmp_path: Path) -> None:
        # 800 샘플 신호, block 512, loop=False → 1st block + 2nd padded block + stop.
        path = tmp_path / "short.wav"
        data = np.full(800, 0.5, dtype=np.float32)
        _write_wav(path, samples=data)
        cfg = _config(path, num_channels=1, block_size=512, loop=False)
        src = WavReplayAudioSource(cfg)

        async def collect_all() -> list[np.ndarray]:
            chunks: list[np.ndarray] = []
            async for signal in src.stream():
                chunks.append(signal.samples[:, 0].copy())
            return chunks

        chunks = asyncio.run(collect_all())
        # 2 블록 (첫 512 + 패딩된 288+0)
        assert len(chunks) == 2
        # 두 번째 블록은 끝부분(288 샘플) + 0 패딩(224 샘플).
        assert chunks[1][0] == pytest.approx(0.5)
        assert chunks[1][287] == pytest.approx(0.5)
        assert chunks[1][288] == 0.0
        assert chunks[1][-1] == 0.0
