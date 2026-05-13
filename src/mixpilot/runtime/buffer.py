"""다채널 ring buffer — 라이브 프레임 누적.

LUFS처럼 ~400ms+ 신호가 필요한 분석을 라이브에서 돌리려면 누적이 필수.
이 버퍼는 numpy 2D ring buffer로 `(frames, channels)` 데이터를 효율적으로 보관.

설계 원칙:
- 시간·랜덤 의존 없음 (write 호출자가 결정성을 책임진다).
- 외부 I/O 없음 — 메모리 상태만.
- 같은 write 시퀀스 → 같은 snapshot.
- snapshot은 *시간순* + 항상 복사본 (호출자가 자유롭게 사용).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


class RollingBuffer:
    """다채널 ring buffer — shape `(capacity_frames, num_channels)`.

    write로 새 프레임을 추가하면 가장 오래된 샘플이 자동으로 밀려난다.
    snapshot은 항상 시간순으로 정렬된 *복사본* ndarray를 반환한다.
    """

    def __init__(
        self,
        capacity_frames: int,
        num_channels: int,
        dtype: npt.DTypeLike = np.float32,
    ) -> None:
        if capacity_frames <= 0:
            raise ValueError(f"capacity_frames must be positive, got {capacity_frames}")
        if num_channels <= 0:
            raise ValueError(f"num_channels must be positive, got {num_channels}")

        self._buf: npt.NDArray = np.zeros((capacity_frames, num_channels), dtype=dtype)
        self._capacity = capacity_frames
        self._num_channels = num_channels
        self._write_idx = 0
        self._fill = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def num_channels(self) -> int:
        return self._num_channels

    @property
    def fill(self) -> int:
        """현재 버퍼에 들어 있는 유효 프레임 수 (capacity로 캡)."""
        return self._fill

    @property
    def is_full(self) -> bool:
        return self._fill >= self._capacity

    def write(self, frames: npt.NDArray) -> None:
        """frames를 버퍼에 append.

        Args:
            frames: shape `(n_frames, num_channels)` 또는 1D `(n_frames,)`
                (단일 채널일 때만).

        Raises:
            ValueError: 차원이 1D/2D가 아니거나 채널 수 불일치일 때.
        """
        if frames.ndim == 1:
            frames = frames.reshape(-1, 1)
        if frames.ndim != 2:
            raise ValueError(f"frames must be 1D or 2D, got shape {frames.shape}")
        if frames.shape[1] != self._num_channels:
            raise ValueError(
                f"frames channels mismatch: expected {self._num_channels}, "
                f"got {frames.shape[1]}"
            )
        n = int(frames.shape[0])
        if n == 0:
            return
        if n >= self._capacity:
            # 들어오는 데이터가 버퍼보다 크면 마지막 capacity 프레임만 유지.
            self._buf[:] = frames[-self._capacity :]
            self._write_idx = 0
            self._fill = self._capacity
            return

        first_chunk = min(n, self._capacity - self._write_idx)
        self._buf[self._write_idx : self._write_idx + first_chunk] = frames[
            :first_chunk
        ]
        remaining = n - first_chunk
        if remaining > 0:
            # wrap-around.
            self._buf[:remaining] = frames[first_chunk:]
            self._write_idx = remaining
        else:
            new_idx = self._write_idx + first_chunk
            self._write_idx = 0 if new_idx == self._capacity else new_idx
        self._fill = min(self._capacity, self._fill + n)

    def snapshot(self) -> npt.NDArray:
        """현재 버퍼 내용을 *시간순*으로 반환 (복사본).

        Returns:
            shape `(fill, num_channels)`. 빈 버퍼면 `(0, num_channels)`.
        """
        if self._fill == 0:
            return np.empty((0, self._num_channels), dtype=self._buf.dtype)
        if self._fill < self._capacity:
            # 아직 wrap 안 됨 — 0..fill이 시간순.
            return self._buf[: self._fill].copy()
        # 가득 차고 wrap된 상태: write_idx부터 끝까지 + 0부터 write_idx까지.
        return np.concatenate(
            [self._buf[self._write_idx :], self._buf[: self._write_idx]]
        )

    def reset(self) -> None:
        """버퍼 비우기."""
        self._write_idx = 0
        self._fill = 0
        self._buf.fill(0)
