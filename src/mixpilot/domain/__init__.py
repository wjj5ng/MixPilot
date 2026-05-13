"""MixPilot domain layer — pure data types and ports.

Per ARCHITECTURE.md: `domain` is the dependency root. No framework
dependencies, no I/O, no time/random side effects.
"""

from .models import (
    AudioFormat,
    Channel,
    ChannelId,
    Recommendation,
    RecommendationKind,
    Signal,
    Source,
    SourceCategory,
)
from .ports import (
    AudioSource,
    ConsoleControl,
    ConsoleMetadata,
    MetricsSink,
    Notifier,
)

__all__ = [
    "AudioFormat",
    "AudioSource",
    "Channel",
    "ChannelId",
    "ConsoleControl",
    "ConsoleMetadata",
    "MetricsSink",
    "Notifier",
    "Recommendation",
    "RecommendationKind",
    "Signal",
    "Source",
    "SourceCategory",
]
