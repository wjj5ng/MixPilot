"""채널별 시계열 메트릭 JSONL 영속화 — ADR-0010.

UI의 채널 시계열 카드는 브라우저 메모리 2분 윈도우만 보관. 본 sink는 처리
루프가 매 frame 산출하는 메트릭 스냅샷을 정해진 cadence(기본 1 Hz)로 JSONL에
append → service 단위 영구 자산.

설계:
- append-only JSONL. 한 라인 = 한 timestamp의 모든 채널 스냅샷.
- AuditLogger와 동일한 strftime path expansion 패턴 (서버 가동 시점에 expand).
- *cadence* throttling: 처리 루프가 매 frame 호출해도 마지막 기록으로부터
  `interval_seconds` 경과 시에만 실제 write. 그 외엔 no-op.
- enabled=False면 모든 호출이 no-op.

JSONL 라인 스키마:
    {
      "timestamp": 1747200000.5,
      "capture_seq": 12345,
      "channels": [
        {"channel": 1, "rms_dbfs": -23.5, "peak_dbfs": -18.2,
         "lra_lu": null, "phase_with_pair": null},
        ...
      ]
    }
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JsonlMetricsSink:
    """채널별 메트릭 시계열 JSONL append."""

    def __init__(
        self,
        path: Path | None,
        interval_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Args:
            path: JSONL 출력 경로. None이면 모든 호출 no-op.
            interval_seconds: 기록 cadence. 마지막 기록 후 이 시간 경과 시에만 write.
            clock: 시계 — 테스트에서 결정적 cadence 제어용.
        """
        self._path = path
        self._interval = float(interval_seconds)
        self._clock = clock
        self._last_write: float = 0.0  # 첫 호출은 즉시 기록.

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def maybe_write(
        self,
        channel_payloads: Sequence[dict[str, Any]],
        *,
        capture_seq: int,
        wall_timestamp: float | None = None,
    ) -> bool:
        """interval이 경과했으면 한 라인 기록. 그 외엔 no-op.

        Args:
            channel_payloads: 미터 페이로드의 `channels` 부분. 각 dict는 channel
                / rms_dbfs / peak_dbfs / lra_lu / phase_with_pair 등을 가짐.
                octave_bands_dbfs 같은 큰 필드는 영속화에서 제외 권장.
            capture_seq: 원천 Signal의 단조 시퀀스.
            wall_timestamp: 기록할 wall clock(epoch). None이면 time.time() 사용.

        Returns:
            실제 write가 일어났으면 True, throttle로 스킵됐으면 False.
        """
        if self._path is None:
            return False
        now = self._clock()
        if now - self._last_write < self._interval:
            return False
        self._last_write = now

        ts = wall_timestamp if wall_timestamp is not None else time.time()
        slim_channels = [_slim_channel(c) for c in channel_payloads]
        record = {
            "timestamp": ts,
            "capture_seq": int(capture_seq),
            "channels": slim_channels,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            # 디스크 가득 참 / 권한 등 — 운영을 막지 않고 경고만.
            logger.warning("metrics sink write failed: %s", e)
            return False
        return True


def _slim_channel(payload: dict[str, Any]) -> dict[str, Any]:
    """미터 페이로드에서 시계열에 의미 있는 필드만 추출.

    octave_bands_dbfs는 8개 float 배열로 부피 큼 — 영속화에서 제외. 향후
    별도 sink로 분리 가능.
    """
    return {
        "channel": payload["channel"],
        "rms_dbfs": payload["rms_dbfs"],
        "peak_dbfs": payload["peak_dbfs"],
        "lra_lu": payload.get("lra_lu"),
        "phase_with_pair": payload.get("phase_with_pair"),
    }
