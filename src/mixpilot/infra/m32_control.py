"""M32 콘솔 OSC 제어 — ADR-0005.

X32 OSC 프로토콜(UDP 10023)로 페이더·뮤트 등을 송신. 운영 모드
(dry-run/assist/auto)에 따라 송신 여부 결정. python-osc는 lazy import.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from mixpilot.config import M32Config, OperatingMode
from mixpilot.domain import Recommendation, RecommendationKind

logger = logging.getLogger(__name__)


class M32OscController:
    """`ConsoleControl` 포트 구현."""

    def __init__(self, config: M32Config, osc_client: Any = None) -> None:
        """
        Args:
            config: M32 설정 (호스트·포트·운영 모드·자동 적용 임계).
            osc_client: send_message(address, value) 메서드를 가진 OSC 클라이언트.
                미지정 시 python-osc SimpleUDPClient를 lazy import해 생성.
        """
        if osc_client is None:
            from pythonosc.udp_client import (
                SimpleUDPClient,
            )

            osc_client = SimpleUDPClient(config.host, config.port)
        self._client = osc_client
        self._config = config

    async def apply(self, recommendation: Recommendation) -> None:
        """추천을 콘솔에 적용. 운영 모드에 따라 실제 송신 여부가 결정된다."""
        if not self._should_apply(recommendation):
            logger.info(
                "skipped (mode=%s, confidence=%.2f): %s",
                self._config.operating_mode.value,
                recommendation.confidence,
                recommendation.reason,
            )
            return
        for address, value in self._translate(recommendation):
            self._client.send_message(address, value)
            logger.info("osc send: %s %r", address, value)

    def _should_apply(self, rec: Recommendation) -> bool:
        mode = self._config.operating_mode
        if mode is OperatingMode.DRY_RUN:
            return False
        if mode is OperatingMode.ASSIST:
            return rec.confidence >= self._config.auto_apply_confidence_threshold
        if mode is OperatingMode.AUTO:
            return True
        return False

    def _translate(self, rec: Recommendation) -> Iterable[tuple[str, float | int]]:
        """Recommendation → (OSC address, value) 시퀀스.

        결정성 보장: 같은 입력 → 같은 시퀀스. 미지원 액션은 경고 로깅 후 빈
        시퀀스 반환(메시지 없음).
        """
        ch = int(rec.target.channel)
        ch_path = f"/ch/{ch:02d}"

        if rec.kind is RecommendationKind.MUTE:
            yield (f"{ch_path}/mix/on", 0)
        elif rec.kind is RecommendationKind.UNMUTE:
            yield (f"{ch_path}/mix/on", 1)
        elif rec.kind is RecommendationKind.GAIN_ADJUST:
            # 절대 fader(0.0-1.0) 적용. delta_db 기반은 현재 fader 읽기 필요 → 추후.
            if "fader" in rec.params:
                fader = max(0.0, min(1.0, float(rec.params["fader"])))
                yield (f"{ch_path}/mix/fader", fader)
            else:
                logger.warning(
                    "GAIN_ADJUST without 'fader' param — delta_db not yet supported"
                )
        elif rec.kind is RecommendationKind.INFO:
            return  # 정보 알림은 OSC 송신 없음
        elif rec.kind in (
            RecommendationKind.FEEDBACK_ALERT,
            RecommendationKind.EQ_ADJUST,
        ):
            logger.warning("%s translation not yet implemented", rec.kind.value)
