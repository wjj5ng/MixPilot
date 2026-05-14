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
    dynamic_range_analysis_enabled: bool
    lra_analysis_enabled: bool
    meter_stream_enabled: bool


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


class AuditEntry(BaseModel):
    """ADR-0008 §3 감사 JSONL의 한 레코드 — applied/blocked 모두 포함."""

    timestamp: float
    outcome: str
    effective_mode: str
    reason: str
    channel: int
    category: str
    label: str
    kind: str
    confidence: float
    rec_reason: str
    osc_messages: list[OscMessage]


class AuditLogResponse(BaseModel):
    """`GET /control/audit-log/recent` 응답.

    `entries`는 최신 → 과거 순. `enabled=false`면 감사 로그 미설정(서버 운영
    환경에서 `audit_log_path`가 None).
    """

    enabled: bool
    entries: list[AuditEntry]


class ChannelMapEntry(BaseModel):
    """채널맵 한 항목 — `config/channels.yaml`의 한 채널 entry."""

    channel: int
    category: str
    label: str


class ChannelMapResponse(BaseModel):
    """`GET /channels` 응답 — 현재 채널맵 전체."""

    entries: list[ChannelMapEntry]


class ChannelMapUpdateRequest(BaseModel):
    """`PUT /channels/{id}` 요청 body — 카테고리·라벨 갱신."""

    category: str
    label: str = ""


class ChannelMeter(BaseModel):
    """단일 채널 미터 — 라벨·카테고리·RMS·peak·LRA·옥타브 스펙트럼."""

    channel: int
    label: str
    category: str
    rms_dbfs: float
    peak_dbfs: float
    lra_lu: float | None = None
    """가장 최근 평가된 LRA(LU). 미평가/비활성이면 null."""

    octave_bands_dbfs: list[float] = []
    """현재 프레임의 옥타브 밴드 레벨 (8개: 125·250·500·1k·2k·4k·8k·16k Hz)."""


class MeterSnapshotEvent(BaseModel):
    """`/meters` SSE 스트림의 단일 이벤트 페이로드.

    한 프레임의 채널별 미터값 묶음. 클라이언트는 capture_seq를 보고 누락
    여부를 추적 가능 (단조 증가).
    """

    capture_seq: int
    channels: list[ChannelMeter]


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
