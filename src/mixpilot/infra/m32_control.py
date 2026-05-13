"""M32 콘솔 OSC 제어 — ADR-0005, ADR-0008.

X32 OSC 프로토콜(UDP 10023)로 페이더·뮤트 등을 송신. 운영 모드
(dry-run/assist/auto)와 Recommendation Kind 매트릭스(ADR-0008 §1)에 따라
적용 여부 결정. 보편 안전장치(레이트·세션 한도)는 선택적 `AutoGuard`로 위임.
python-osc는 lazy import.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from mixpilot.config import M32Config, OperatingMode
from mixpilot.domain import Recommendation, RecommendationKind
from mixpilot.runtime import AutoGuard

logger = logging.getLogger(__name__)


# ADR-0008 §1 Kind x Mode 자동 적용 매트릭스.
# INFO는 어떤 모드에서도 자동 적용 안 됨 — 정보 채널 전용.
_AUTO_KINDS_BY_MODE: dict[OperatingMode, frozenset[RecommendationKind]] = {
    OperatingMode.DRY_RUN: frozenset(),
    OperatingMode.ASSIST: frozenset(
        {
            RecommendationKind.GAIN_ADJUST,
            RecommendationKind.UNMUTE,
            RecommendationKind.FEEDBACK_ALERT,
        }
    ),
    OperatingMode.AUTO: frozenset(
        {
            RecommendationKind.GAIN_ADJUST,
            RecommendationKind.UNMUTE,
            RecommendationKind.FEEDBACK_ALERT,
            RecommendationKind.MUTE,
            RecommendationKind.EQ_ADJUST,
        }
    ),
}


class M32OscController:
    """`ConsoleControl` 포트 구현."""

    def __init__(
        self,
        config: M32Config,
        osc_client: Any = None,
        *,
        auto_guard: AutoGuard | None = None,
    ) -> None:
        """
        Args:
            config: M32 설정 (호스트·포트·운영 모드·자동 적용 임계).
            osc_client: send_message(address, value) 메서드를 가진 OSC 클라이언트.
                미지정 시 python-osc SimpleUDPClient를 lazy import해 생성.
            auto_guard: ADR-0008 §3 보편 안전장치(레이트·세션 한도) — 선택적.
                None이면 가드 검사를 건너뛴다(테스트·하위호환). 프로덕션은 항상
                전달해야 한다.
        """
        if osc_client is None:
            from pythonosc.udp_client import (
                SimpleUDPClient,
            )

            osc_client = SimpleUDPClient(config.host, config.port)
        self._client = osc_client
        self._config = config
        self._auto_guard = auto_guard

    async def apply(self, recommendation: Recommendation) -> None:
        """추천을 콘솔에 적용.

        운영 모드·Kind·confidence·AutoGuard 검사를 모두 통과해야 OSC가 송신된다.
        """
        if not self._should_apply(recommendation):
            logger.info(
                "skipped policy (mode=%s, kind=%s, confidence=%.2f): %s",
                self._config.operating_mode.value,
                recommendation.kind.value,
                recommendation.confidence,
                recommendation.reason,
            )
            return
        if self._auto_guard is not None:
            decision = self._auto_guard.try_register(int(recommendation.target.channel))
            if not decision.allowed:
                logger.info(
                    "skipped guard (%s): %s",
                    decision.reason,
                    recommendation.reason,
                )
                return
        for address, value in self._translate(recommendation):
            self._client.send_message(address, value)
            logger.info("osc send: %s %r", address, value)

    def _should_apply(self, rec: Recommendation) -> bool:
        """ADR-0008 §1 Kind dispatch + §3 confidence 임계.

        INFO는 어떤 모드에서도 자동 적용 안 됨. confidence 임계는 모든 모드에 적용.
        """
        mode = self._config.operating_mode
        if rec.kind not in _AUTO_KINDS_BY_MODE[mode]:
            return False
        if rec.confidence < self._config.auto_apply_confidence_threshold:
            return False
        return True

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
