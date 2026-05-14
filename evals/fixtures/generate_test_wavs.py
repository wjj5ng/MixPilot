"""테스트용 WAV fixture 생성기 — 한 번 실행해 evals/fixtures/ 디렉토리 채움.

git에 들어가는 작은 표준 신호 파일들을 결정적으로 생성. 외부 녹음에 의존
하지 않아 CI에서도 검증 가능. 실제 service 회귀 신호(예배 전체)는 git-lfs
또는 외부 스토리지로 분리해야 함 (file size).

생성 후 결과:
- test-1khz-mono-2s.wav: 1 kHz 사인파 모노 2초, 48 kHz, float32, amp 0.3
- test-multich-4s.wav: 8채널 4초, 48 kHz, 각 채널 다른 amplitude로 사인파

실행: `uv run python evals/fixtures/generate_test_wavs.py`
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import wavfile


def _sine(freq_hz: float, duration_s: float, amp: float, sr: int) -> np.ndarray:
    t = np.arange(int(duration_s * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def main() -> None:
    out_dir = Path(__file__).parent
    sr = 48000

    # 1. 1 kHz 모노 2초
    mono = _sine(1000.0, 2.0, 0.3, sr)
    wavfile.write(out_dir / "test-1khz-mono-2s.wav", sr, mono)
    print(f"wrote {out_dir / 'test-1khz-mono-2s.wav'} ({mono.size} samples)")

    # 2. 8채널 4초 — 각 채널 amplitude 단계 + 약간 다른 주파수
    channels = []
    for i in range(8):
        amp = 0.05 + i * 0.05  # 0.05 ~ 0.4
        freq = 440.0 * (2 ** (i / 12.0))  # 반음씩 — 도/도샵/레 ...
        channels.append(_sine(freq, 4.0, amp, sr))
    multi = np.stack(channels, axis=1)  # (frames, channels)
    wavfile.write(out_dir / "test-multich-4s.wav", sr, multi)
    print(f"wrote {out_dir / 'test-multich-4s.wav'} ({multi.shape})")


if __name__ == "__main__":
    main()
