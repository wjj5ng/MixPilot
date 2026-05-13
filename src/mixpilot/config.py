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

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    """오디오 입력 설정 (ADR-0004 — M32 USB 직접 캡처)."""

    enabled: bool = False
    """오디오 캡처 활성화 여부. False면 main.py 라이프스팬이 인프라를
    초기화하지 않아 M32 미연결 환경에서도 서버가 뜬다. 라이브 운영 시 True."""

    device_substring: str = "M32"  # sounddevice 디바이스명 substring 매칭
    sample_rate: int = Field(default=48000, gt=0)
    block_size: int = Field(default=512, gt=0)  # 256-1024 권장 (ADR-0004)
    num_channels: int = Field(default=32, gt=0)


class M32Config(BaseModel):
    """M32 콘솔 제어 설정 (ADR-0005 — X32 OSC over UDP)."""

    host: str = "192.168.1.100"
    port: int = Field(default=10023, gt=0, le=65535)
    operating_mode: OperatingMode = OperatingMode.DRY_RUN
    auto_apply_confidence_threshold: float = Field(default=0.95, ge=0.0, le=1.0)


class LufsTargets(BaseModel):
    """카테고리별 LUFS 목표 (EBU R128 integrated).

    값은 dBFS와 다른 단위 — LUFS는 인지 라우드니스 기준.
    카테고리 이름은 도메인 `SourceCategory` 값과 정렬되되, 결합은 피한다
    (config는 다른 mixpilot 모듈을 import하지 않음).
    """

    vocal: float = -16.0
    preacher: float = -18.0
    choir: float = -20.0
    instrument: float = -22.0
    unknown: float = -23.0  # 보수적 폴백

    def for_category(self, category: str) -> float:
        """카테고리 string → LUFS 목표값.

        유효 카테고리: 'vocal' | 'preacher' | 'choir' | 'instrument' | 'unknown'.
        매칭되지 않으면 `unknown` 목표값으로 폴백.
        """
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

    # M32 채널 → 카테고리 매핑 파일 (외부 자료, service 단위로 갱신).
    channel_map_path: Path = Path("config/channels.yaml")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 라이프타임 동안 캐시된 단일 Settings 인스턴스.

    프로덕션 진입점(`main.py`)과 의존성 주입에 사용. 테스트에서는
    `Settings()`를 직접 생성하거나 `get_settings.cache_clear()` 호출.
    """
    return Settings()
