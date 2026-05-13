"""API 응답 스키마 — pydantic 모델.

FastAPI가 이 모델들을 사용해 `/openapi.json`을 생성하고, 프론트엔드는
`openapi-typescript`로 TS 타입을 자동 생성한다. 도메인 모델(`Recommendation`)을
직접 노출하지 않고 *API 표면용 별도 모델*을 두는 이유:
- API 호환성은 도메인 변경과 독립적으로 관리
- 도메인 모델은 frozen dataclass + numpy 의존 → 직접 직렬화 부적합
"""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """`/health` 응답."""

    status: str
    operating_mode: str
    sample_rate: int
    num_channels: int
    audio_enabled: bool
    lufs_analysis_enabled: bool
    feedback_analysis_enabled: bool
    peak_analysis_enabled: bool


class ControlResponse(BaseModel):
    """제어 엔드포인트(`/control/*`) 공통 응답."""

    status: str
    """동작 결과 요약. 예: 'forced dry-run', 'no controller (audio disabled)'."""

    effective_mode: str | None = None
    """오버라이드 후의 effective_mode. controller가 없을 땐 None."""


class OscMessage(BaseModel):
    """단일 OSC 메시지 — `(address, value)` 한 쌍."""

    address: str
    value: float


class ActionEntry(BaseModel):
    """`ActionHistory.HistoryEntry`의 API 표면 형태."""

    timestamp: float
    channel: int
    kind: str
    osc_messages: list[OscMessage]
    reason: str


class RecentActionsResponse(BaseModel):
    """`GET /control/recent-actions` 응답."""

    entries: list[ActionEntry]
    window_seconds: float


class RecommendationEvent(BaseModel):
    """`/recommendations` SSE 스트림의 단일 이벤트 페이로드.

    각 `data:` 라인 본문에 직렬화되는 JSON. 도메인 `Recommendation`을
    JSON 친화 형태로 변환한 결과.
    """

    channel: int
    category: str
    label: str
    kind: str
    params: dict[str, float]
    confidence: float
    reason: str
