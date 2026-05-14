"""애플리케이션 설정 — 환경 변수와 .env 파일에서 로드.

ARCHITECTURE.md 규약: 다른 `src/mixpilot/*` 모듈을 import하지 않는다
(역의존만 허용). 카테고리 키는 string으로 표현 — 소비자(`rules/` 등)가
필요 시 도메인 enum으로 변환.

환경 변수 형식:
    MIXPILOT_<SECTION>__<FIELD>=value
    예) MIXPILOT_M32__HOST=192.168.1.50
        MIXPILOT_LUFS__VOCAL=-17.0
        MIXPILOT_AUDIO__SAMPLE_RATE=44100
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AudioSource(StrEnum):
    """`AudioConfig.source` 선택지.

    - `sounddevice`: 실 M32 USB 캡처 (ADR-0004 기본 경로).
    - `synthetic`: 합성 사인파 — 하드웨어 없이 처리 루프를 가동·데모할 때.
    """

    SOUNDDEVICE = "sounddevice"
    SYNTHETIC = "synthetic"


class OperatingMode(StrEnum):
    """추천 적용 모드 — ADR-0005.

    - `dry-run`: 표시만, 실제 콘솔 변경 없음 (기본).
    - `assist`: 신뢰도가 임계 이상인 추천만 자동 적용.
    - `auto`: 정책 따라 자동 적용 (운영자가 명시적으로 활성화해야 함).
    """

    DRY_RUN = "dry-run"
    ASSIST = "assist"
    AUTO = "auto"


class AudioConfig(BaseModel):
    """오디오 입력 설정 (ADR-0004 — M32 USB 직접 캡처 + 합성 옵션)."""

    enabled: bool = False
    """오디오 캡처 활성화 여부. False면 main.py 라이프스팬이 인프라를
    초기화하지 않아 M32 미연결 환경에서도 서버가 뜬다. 라이브 운영 시 True."""

    source: AudioSource = AudioSource.SOUNDDEVICE
    """입력 소스 선택. 디폴트 sounddevice(실 M32). 데모·테스트는 synthetic."""

    device_substring: str = "M32"  # sounddevice 디바이스명 substring 매칭
    sample_rate: int = Field(default=48000, gt=0)
    block_size: int = Field(default=512, gt=0)  # 256-1024 권장 (ADR-0004)
    num_channels: int = Field(default=32, gt=0)

    synthetic_amplitudes_dbfs: Sequence[float] | None = None
    """`source=synthetic` 일 때 채널별 사인파 amplitude (dBFS).
    None이면 채널 1=-30 dBFS, 채널 N=-3 dBFS의 선형 step. 길이는 `num_channels`."""


class M32Config(BaseModel):
    """M32 콘솔 제어 설정 (ADR-0005 — X32 OSC over UDP)."""

    host: str = "192.168.1.100"
    port: int = Field(default=10023, gt=0, le=65535)
    operating_mode: OperatingMode = OperatingMode.DRY_RUN
    auto_apply_confidence_threshold: float = Field(default=0.95, ge=0.0, le=1.0)


class LufsTargets(BaseModel):
    """카테고리별 LUFS 목표 (EBU R128 integrated).

    LUFS는 K-weighting + 게이팅 기반 인지 라우드니스. 측정에 최소 ~400ms
    신호 필요 — 라이브 프레임 단위로는 못 쓰고 누적 버퍼/오프라인에서만 적용.
    카테고리 이름은 도메인 `SourceCategory` 값과 정렬하되 import 결합은 피한다.
    """

    vocal: float = -16.0
    preacher: float = -18.0
    choir: float = -20.0
    instrument: float = -22.0
    unknown: float = -23.0  # 보수적 폴백 / EBU R128 broadcast target.

    def for_category(self, category: str) -> float:
        """카테고리 string → LUFS 목표값.

        유효 카테고리: 'vocal' | 'preacher' | 'choir' | 'instrument' | 'unknown'.
        매칭되지 않으면 `unknown` 목표값으로 폴백.
        """
        return getattr(self, category, self.unknown)


class PeakAnalysisConfig(BaseModel):
    """라이브 true peak 클리핑·헤드룸 감시 설정.

    매 프레임 채널별 true peak를 계산해 임계 이상이면 INFO Recommendation을
    발화. RMS처럼 짧은 프레임에서도 측정 가능해 라이브 루프에 직접 통합.
    """

    enabled: bool = False
    """라이브 peak 감시 활성화 여부. 디폴트 off."""

    headroom_threshold_dbfs: float = Field(default=-1.0, le=0.0)
    """이 이상의 true peak는 알림. 0보다 클 수 없음 (디지털 풀-스케일이 한계)."""

    oversample: int = Field(default=4, gt=0)
    """True peak 오버샘플링 배수. ITU-R BS.1770-4 권고는 4."""


class DynamicRangeAnalysisConfig(BaseModel):
    """라이브 dynamic range (crest factor) 감시 설정.

    매 프레임 채널별 DR(=20·log10(peak/RMS))을 계산해 정상 범위 밖이면 INFO
    Recommendation 발화. 자동 액션은 없음(운영자 판단 영역).
    """

    enabled: bool = False
    """라이브 DR 감시 활성화 여부. 디폴트 off."""

    low_threshold_db: float = Field(default=6.0, ge=0.0)
    """이 미만이면 "압축 강함" 알림."""

    high_threshold_db: float = Field(default=20.0, gt=0.0)
    """이 초과면 "트랜션트 폭 큼" 알림. low_threshold_db보다 커야 함."""

    silence_threshold_db: float = Field(default=0.5, ge=0.0)
    """DR이 이 미만이면 무음으로 간주 — 평가 스킵."""


class FeedbackAnalysisConfig(BaseModel):
    """라이브 feedback (하울링) 감지 설정.

    채널마다 별도의 `FeedbackDetector` 인스턴스를 두고 매 프레임 업데이트한다.
    PNR 임계와 지속성(persistence)을 함께 만족할 때만 alert 발화.
    """

    enabled: bool = False
    """라이브 feedback 감지 활성화 여부. 디폴트 off."""

    pnr_threshold_db: float = Field(default=15.0, ge=0.0)
    """Peak-to-Neighbor Ratio 임계(dB). 12~20 권장."""

    persistence_frames: int = Field(default=3, gt=0)
    """N 연속 프레임 candidate일 때만 alert. 1~5 권장."""

    min_frequency_hz: float = Field(default=100.0, gt=0.0)
    """이 미만 주파수는 분석에서 제외 (베이스 노이즈)."""

    max_frequency_hz: float = Field(default=8000.0, gt=0.0)
    """이 초과 주파수는 분석에서 제외. 보컬·라이브 악기 영역 기준."""


class LufsAnalysisConfig(BaseModel):
    """라이브 LUFS 분석 설정.

    LUFS는 K-weighting + 게이팅이라 ~400ms+ 신호가 필요. 라이브 프레임 단위로는
    못 쓰므로 채널별 ring buffer에 누적했다가 주기적으로 평가한다. 비활성이면
    RMS 룰만 사용.
    """

    enabled: bool = False
    """라이브 LUFS 평가 활성화 여부. 디폴트 off — RMS만 사용."""

    buffer_seconds: float = Field(default=1.0, gt=0.0, le=10.0)
    """LUFS 계산용 누적 버퍼 길이(초). 1.0~3.0 권장."""

    eval_interval_frames: int = Field(default=50, gt=0)
    """N 프레임마다 LUFS 평가. block=512@48k면 50프레임 ≈ 533ms 주기."""


class RmsDbfsTargets(BaseModel):
    """카테고리별 RMS dBFS 목표 — 라이브 프레임 단위 분석용.

    LUFS와 의도적으로 분리. LUFS는 K-weighted 인지 라우드니스, RMS dBFS는
    단순 평균 에너지. RMS는 짧은 프레임(수~수십 ms)에서도 즉시 측정 가능.

    값은 일반적으로 같은 카테고리의 LUFS 목표보다 2~3 dB 더 낮다 — K-weighting이
    중주파에서 평균 +2~3 dB 부스트하기 때문.
    """

    vocal: float = -18.0
    preacher: float = -20.0
    choir: float = -22.0
    instrument: float = -24.0
    unknown: float = -26.0

    def for_category(self, category: str) -> float:
        return getattr(self, category, self.unknown)


class Settings(BaseSettings):
    """전역 애플리케이션 설정.

    환경 변수가 .env 파일을 덮어쓰고, .env가 코드 디폴트를 덮어쓴다.
    """

    model_config = SettingsConfigDict(
        env_prefix="MIXPILOT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    audio: AudioConfig = Field(default_factory=AudioConfig)
    m32: M32Config = Field(default_factory=M32Config)
    lufs: LufsTargets = Field(default_factory=LufsTargets)
    rms_dbfs: RmsDbfsTargets = Field(default_factory=RmsDbfsTargets)
    lufs_analysis: LufsAnalysisConfig = Field(default_factory=LufsAnalysisConfig)
    feedback_analysis: FeedbackAnalysisConfig = Field(
        default_factory=FeedbackAnalysisConfig
    )
    peak_analysis: PeakAnalysisConfig = Field(default_factory=PeakAnalysisConfig)
    dynamic_range_analysis: DynamicRangeAnalysisConfig = Field(
        default_factory=DynamicRangeAnalysisConfig
    )

    dev_cors_enabled: bool = False
    """프론트엔드 dev 서버(http://localhost:5173)에서의 CORS 요청을 허용한다.
    프로덕션은 FastAPI가 빌드 산출물을 같은 origin에서 서빙하므로 비활성 유지."""

    audit_log_path: Path | None = None
    """ADR-0008 §3 감사 로그 JSONL 경로. None이면 감사 로깅 비활성.
    프로덕션은 운영자가 사후 검토할 수 있게 설정 권장."""

    # M32 채널 → 카테고리 매핑 파일 (외부 자료, service 단위로 갱신).
    channel_map_path: Path = Path("config/channels.yaml")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 라이프타임 동안 캐시된 단일 Settings 인스턴스.

    프로덕션 진입점(`main.py`)과 의존성 주입에 사용. 테스트에서는
    `Settings()`를 직접 생성하거나 `get_settings.cache_clear()` 호출.
    """
    return Settings()
