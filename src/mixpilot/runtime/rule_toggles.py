"""룰별 활성 상태 — service 도중 운영자가 재시작 없이 켜고 끔.

라이브 처리 루프는 매 프레임 `snapshot()`을 호출해 그 시점의 enabled 셋을
읽는다 — race condition 없이 일관된 frame.

config의 초기값을 `from_config()`로 복사한 뒤 mutable. 변경은 API endpoint나
테스트에서 `set_enabled()`로 수행.

지원 룰 이름 (사용자 노출 식별자):

- `loudness` — RMS dBFS 카테고리 타깃 비교
- `lufs` — 누적 LUFS 평가
- `peak` — true peak 헤드룸
- `feedback` — 하울링 감지
- `dynamic_range` — crest factor 임계
- `lra` — Loudness Range
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# 변경 시 endpoint·UI도 함께 업데이트해야 함.
RULE_NAMES: tuple[str, ...] = (
    "loudness",
    "lufs",
    "peak",
    "feedback",
    "dynamic_range",
    "lra",
    "phase",
)


@dataclass
class RuleToggles:
    """Per-rule enabled 상태의 mutable 컨테이너."""

    _enabled: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 알려진 룰 외 entry는 무시 — defensive.
        normalized: dict[str, bool] = {}
        for name in RULE_NAMES:
            normalized[name] = bool(self._enabled.get(name, False))
        self._enabled = normalized

    @classmethod
    def from_config_flags(
        cls,
        *,
        loudness: bool = True,
        lufs: bool = False,
        peak: bool = False,
        feedback: bool = False,
        dynamic_range: bool = False,
        lra: bool = False,
        phase: bool = False,
    ) -> RuleToggles:
        """config의 enabled 플래그를 명시 인자로 받아 인스턴스 생성.

        `loudness`는 historical하게 항상 활성이지만 운영자가 토글로 끌 수
        있도록 별도 키. 기본 True.
        """
        return cls(
            {
                "loudness": loudness,
                "lufs": lufs,
                "peak": peak,
                "feedback": feedback,
                "dynamic_range": dynamic_range,
                "lra": lra,
                "phase": phase,
            }
        )

    def is_enabled(self, rule: str) -> bool:
        return self._enabled.get(rule, False)

    def set_enabled(self, rule: str, enabled: bool) -> None:
        """단일 룰의 상태 변경. 알 수 없는 이름이면 `ValueError`."""
        if rule not in self._enabled:
            raise ValueError(f"unknown rule {rule!r}; valid: {', '.join(RULE_NAMES)}")
        self._enabled[rule] = bool(enabled)

    def snapshot(self) -> Mapping[str, bool]:
        """현재 상태의 immutable view — 처리 루프가 frame당 1회 호출."""
        return dict(self._enabled)
