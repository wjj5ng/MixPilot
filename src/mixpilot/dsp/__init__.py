"""MixPilot DSP layer — 순수 분석 함수.

ARCHITECTURE.md 규약: `dsp`는 numpy/scipy/pyloudnorm/domain 타입에만 의존.
모든 함수는 순수 — 같은 입력에 같은 출력, 부수효과 없음.
"""

from .dynamic_range import dynamic_range_channels, dynamic_range_db
from .feedback import (
    DEFAULT_NEIGHBOR_BAND_HZ,
    DEFAULT_PNR_THRESHOLD_DB,
    FeedbackPeak,
    detect_peak_bins,
)
from .lra import NO_LRA, lra
from .lufs import (
    MIN_DURATION_SECONDS,
    SILENCE_FLOOR_LUFS,
    lufs_channels,
    lufs_integrated,
)
from .peak import (
    DEFAULT_TRUE_PEAK_OVERSAMPLE,
    peak,
    peak_channels,
    true_peak,
    true_peak_channels,
)
from .rms import SILENCE_FLOOR_DBFS, rms, rms_channels, to_dbfs
from .spectrum import OCTAVE_CENTERS_HZ, octave_band_levels_dbfs

__all__ = [
    "DEFAULT_NEIGHBOR_BAND_HZ",
    "DEFAULT_PNR_THRESHOLD_DB",
    "DEFAULT_TRUE_PEAK_OVERSAMPLE",
    "MIN_DURATION_SECONDS",
    "NO_LRA",
    "OCTAVE_CENTERS_HZ",
    "SILENCE_FLOOR_DBFS",
    "SILENCE_FLOOR_LUFS",
    "FeedbackPeak",
    "detect_peak_bins",
    "dynamic_range_channels",
    "dynamic_range_db",
    "lra",
    "lufs_channels",
    "lufs_integrated",
    "octave_band_levels_dbfs",
    "peak",
    "peak_channels",
    "rms",
    "rms_channels",
    "to_dbfs",
    "true_peak",
    "true_peak_channels",
]
