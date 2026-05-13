"""Feedback 지속성 검출기 — 프레임 시퀀스에 걸쳐 같은 bin이 살아남는지 추적.

`dsp.detect_peak_bins`는 단일 프레임만 본다. 음악의 짧은 톤(어택·멜로디)도
한 프레임에서는 높은 PNR을 낼 수 있어 그것만으로는 false positive가 잦다.
이 detector가 *연속 N 프레임* 같은 bin이 candidate로 잡힐 때만 결과로 승격해
진짜 feedback(지속 공진)만 통과시킨다.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from mixpilot.dsp.feedback import (
    DEFAULT_NEIGHBOR_BAND_HZ,
    DEFAULT_PNR_THRESHOLD_DB,
    FeedbackPeak,
    detect_peak_bins,
)


class FeedbackDetector:
    """프레임 시퀀스에서 지속 검증된 feedback peaks를 추적.

    같은 FFT bin이 `persistence_frames` 이상 *연속* candidate일 때만 `update`가
    그 peak를 반환한다. 음악적 단발성 톤은 자동 필터링됨.

    상태는 `bin_index → 연속 프레임 카운트` 매핑. 프레임에서 빠진 bin은 즉시
    리셋 (히스테리시스 없음 — 단순/예측 가능).
    """

    def __init__(
        self,
        sample_rate: int,
        *,
        persistence_frames: int = 3,
        pnr_threshold_db: float = DEFAULT_PNR_THRESHOLD_DB,
        min_frequency_hz: float = 100.0,
        max_frequency_hz: float | None = None,
        neighbor_band_hz: float = DEFAULT_NEIGHBOR_BAND_HZ,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if persistence_frames < 1:
            raise ValueError(
                f"persistence_frames must be >= 1, got {persistence_frames}"
            )
        self._sample_rate = sample_rate
        self._persistence_frames = persistence_frames
        self._pnr_threshold_db = pnr_threshold_db
        self._min_frequency_hz = min_frequency_hz
        self._max_frequency_hz = max_frequency_hz
        self._neighbor_band_hz = neighbor_band_hz
        # bin_index → 연속 candidate 프레임 수.
        self._streaks: dict[int, int] = {}

    @property
    def persistence_frames(self) -> int:
        return self._persistence_frames

    @property
    def active_bins(self) -> int:
        """현재 추적 중인 candidate bin 수 (지속 검증 여부 무관)."""
        return len(self._streaks)

    def update(self, samples: npt.NDArray[np.floating]) -> list[FeedbackPeak]:
        """프레임 분석 + 지속 검증.

        Args:
            samples: 1D 신호 프레임.

        Returns:
            `persistence_frames` 이상 연속 candidate였던 peaks (bin_index 오름차순).
            처음 N 프레임 동안은 비어 있음. 한 번 sustained되면 매 프레임마다
            계속 반환된다 — consumer가 dedupe 정책을 결정.
        """
        peaks = detect_peak_bins(
            samples,
            self._sample_rate,
            pnr_threshold_db=self._pnr_threshold_db,
            min_frequency_hz=self._min_frequency_hz,
            max_frequency_hz=self._max_frequency_hz,
            neighbor_band_hz=self._neighbor_band_hz,
        )
        current_by_bin = {p.bin_index: p for p in peaks}

        new_streaks: dict[int, int] = {}
        for bin_idx in current_by_bin:
            new_streaks[bin_idx] = self._streaks.get(bin_idx, 0) + 1
        # 이번 프레임에 빠진 bin은 streak 리셋 (new_streaks에 없음).
        self._streaks = new_streaks

        return [
            current_by_bin[bin_idx]
            for bin_idx in sorted(current_by_bin.keys())
            if new_streaks[bin_idx] >= self._persistence_frames
        ]

    def reset(self) -> None:
        """추적 상태 초기화."""
        self._streaks = {}
