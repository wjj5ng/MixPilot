"""FastAPI 진입점 — 의존성 와이어링과 라이프스팬 관리.

ARCHITECTURE.md 규약: `main`만 조립자 권한 — 모든 모듈 import 가능하고
DI·라이프스팬을 담당. 도메인 로직·DSP 로직은 여기서 직접 구현하지 않는다.

실행:
    uv run fastapi dev src/mixpilot/main.py
    uv run uvicorn mixpilot.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mixpilot.config import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """애플리케이션 라이프스팬.

    인프라 어댑터(AudioSource, ConsoleControl 등) 시작·종료 자리.
    현재는 placeholder — 5순위에서 채움.
    """
    # TODO(5순위): SoundDeviceAudioSource·M32OscController 초기화 + 시작
    yield
    # TODO(5순위): 어댑터 close


def create_app(settings: Settings | None = None) -> FastAPI:
    """FastAPI 앱 팩토리.

    settings를 명시적으로 주입할 수 있어 테스트 격리에 사용한다.
    프로덕션은 인자 없이 호출 → `get_settings()`로 캐시된 인스턴스 사용.
    """
    cfg = settings or get_settings()

    app = FastAPI(
        title="MixPilot",
        description="실시간 오디오 분석 및 믹싱 어시스턴트 (M32 / 라이브)",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = cfg

    @app.get("/health")
    async def health() -> dict[str, str | int]:
        """헬스 체크 — 운영 모드와 핵심 오디오 설정을 함께 반환.

        시크릿이나 내부 식별자는 노출하지 않는다.
        """
        return {
            "status": "ok",
            "operating_mode": cfg.m32.operating_mode.value,
            "sample_rate": cfg.audio.sample_rate,
            "num_channels": cfg.audio.num_channels,
        }

    return app


# uvicorn / fastapi CLI가 import할 모듈 레벨 인스턴스.
app = create_app()
