"""Domain models.

Pure data types. Frozen dataclasses preferred. No I/O, no datetime.now(),
no random. See ARCHITECTURE.md "결정성 보장" for the full rule set.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

import numpy as np
import numpy.typing as npt

ChannelId = NewType("ChannelId", int)


class SourceCategory(StrEnum):
    """입력 소스 카테고리.

    카테고리별 정상 임계값과 적용 규칙이 다르므로, 규칙 엔진은 항상
    카테고리를 명시적으로 받아 처리한다. config/channels.yaml에서
    채널 번호 → 카테고리 매핑이 부여된다.
    """

    VOCAL = "vocal"
    PREACHER = "preacher"
    CHOIR = "choir"
    INSTRUMENT = "instrument"
    UNKNOWN = "unknown"


class RecommendationKind(StrEnum):
    """추천 액션의 종류."""

    GAIN_ADJUST = "gain_adjust"
    EQ_ADJUST = "eq_adjust"
    MUTE = "mute"
    UNMUTE = "unmute"
    FEEDBACK_ALERT = "feedback_alert"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """오디오 신호의 포맷 메타데이터."""

    sample_rate: int
    num_channels: int
    sample_dtype: str

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")
        if self.num_channels <= 0:
            raise ValueError(f"num_channels must be positive, got {self.num_channels}")


@dataclass(frozen=True, slots=True)
class Signal:
    """다채널 오디오 프레임.

    samples shape: (frames,) 단일 채널, 또는 (frames, channels) 다채널.
    capture_seq는 외부 로깅용 단조 증가 시퀀스 — DSP 함수는 이 값을 사용하지
    않는다(결정성 보장).
    """

    samples: npt.NDArray[np.floating]
    format: AudioFormat
    capture_seq: int = 0

    @property
    def num_frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration_seconds(self) -> float:
        return self.num_frames / self.format.sample_rate


@dataclass(frozen=True, slots=True)
class Source:
    """단일 입력 소스 (콘솔의 한 채널).

    채널 번호와 카테고리는 외부 매핑(config/channels.yaml)에서 부여된다.
    label은 M32 스크리블 스트립 라벨 — 정보 용도.

    `stereo_pair_with`는 스테레오 페어의 *상대* 채널 번호. None이면 mono.
    Phase correlation 룰·미터가 이 정보를 사용해 모노 다운믹스 안전성을 평가.
    """

    channel: ChannelId
    category: SourceCategory
    label: str = ""
    stereo_pair_with: int | None = None


@dataclass(frozen=True, slots=True)
class Channel:
    """캡처된 단일 채널의 신호 + 소스 매핑.

    `Signal`이 다채널 텐서인 반면, `Channel`은 특정 한 채널의 1D 신호 +
    그 채널이 매핑된 Source.
    """

    source: Source
    samples: npt.NDArray[np.floating]
    format: AudioFormat
    capture_seq: int = 0


@dataclass(frozen=True, slots=True)
class Recommendation:
    """규칙 엔진이 생성한 추천.

    실제 적용은 `ConsoleControl` 포트의 구현체가 담당. 같은 입력에 같은
    Recommendation이 결정적으로 나와야 한다.
    """

    target: Source
    kind: RecommendationKind
    params: dict[str, float]
    confidence: float
    reason: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
