"""MixPilot 런타임 지원 모듈 — 라이브 처리 인프라.

`domain`/`dsp`/`rules`는 순수 함수·값 타입이지만, 라이브 처리에는 *상태*가
필요한 컴포넌트(버퍼·스로틀러·스케줄러 등)도 있다. 그런 것들이 이 모듈에 모인다.

ARCHITECTURE 규약: `runtime`은 `domain`(타입)과 표준 라이브러리만 import.
외부 I/O 없음. 단, 메모리 상태는 보유한다.
"""

from .buffer import RollingBuffer
from .feedback_detector import FeedbackDetector

__all__ = ["FeedbackDetector", "RollingBuffer"]
