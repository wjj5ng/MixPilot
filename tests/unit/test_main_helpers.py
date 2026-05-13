"""main.py 헬퍼 단위 테스트 — RecommendationBroker, 신호 분리, 직렬화."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from mixpilot.config import LufsTargets, Settings
from mixpilot.domain import (
    AudioFormat,
    ChannelId,
    Recommendation,
    RecommendationKind,
    Signal,
    Source,
    SourceCategory,
)
from mixpilot.main import (
    RecommendationBroker,
    _build_targets,
    _serialize_recommendation,
    _split_signal_to_channels,
)


def _rec(
    channel: int = 1,
    kind: RecommendationKind = RecommendationKind.INFO,
    *,
    category: SourceCategory = SourceCategory.VOCAL,
    label: str = "",
    confidence: float = 0.5,
    params: dict[str, float] | None = None,
    reason: str = "t",
) -> Recommendation:
    return Recommendation(
        target=Source(ChannelId(channel), category, label),
        kind=kind,
        params=params or {},
        confidence=confidence,
        reason=reason,
    )


class TestRecommendationBroker:
    def test_publish_without_subscribers_is_safe(self) -> None:
        broker = RecommendationBroker()
        broker.publish(_rec())  # 예외 없이 끝나야 함.
        assert broker.subscriber_count == 0

    def test_subscribe_increments_count(self) -> None:
        broker = RecommendationBroker()
        broker.subscribe()
        assert broker.subscriber_count == 1

    def test_unsubscribe_decrements_count(self) -> None:
        broker = RecommendationBroker()
        queue = broker.subscribe()
        broker.unsubscribe(queue)
        assert broker.subscriber_count == 0

    def test_publish_delivers_to_subscriber(self) -> None:
        broker = RecommendationBroker()

        async def run() -> Recommendation:
            queue = broker.subscribe()
            broker.publish(_rec(channel=3, reason="hello"))
            return await queue.get()

        received = asyncio.run(run())
        assert int(received.target.channel) == 3
        assert received.reason == "hello"

    def test_publish_fans_out_to_all_subscribers(self) -> None:
        broker = RecommendationBroker()

        async def run() -> tuple[Recommendation, Recommendation]:
            q1 = broker.subscribe()
            q2 = broker.subscribe()
            broker.publish(_rec(channel=5))
            return await q1.get(), await q2.get()

        a, b = asyncio.run(run())
        assert int(a.target.channel) == 5
        assert int(b.target.channel) == 5

    def test_full_queue_drops_message(self) -> None:
        broker = RecommendationBroker(max_queue_size=1)
        queue = broker.subscribe()
        broker.publish(_rec(channel=1))
        broker.publish(_rec(channel=2))  # 둘째는 드롭.
        assert queue.qsize() == 1


class TestSplitSignalToChannels:
    def _format(self, channels: int = 4) -> AudioFormat:
        return AudioFormat(
            sample_rate=48000, num_channels=channels, sample_dtype="float32"
        )

    def _signal_2d(self, frames: int = 64, channels: int = 4, seq: int = 7) -> Signal:
        samples = np.arange(frames * channels, dtype=np.float32).reshape(
            frames, channels
        )
        return Signal(samples=samples, format=self._format(channels), capture_seq=seq)

    def test_2d_signal_splits_per_channel(self) -> None:
        sig = self._signal_2d(channels=4)
        result = _split_signal_to_channels(sig, sources_by_id={})
        assert len(result) == 4
        for idx, ch in enumerate(result):
            assert ch.samples.shape == (64,)
            np.testing.assert_array_equal(ch.samples, sig.samples[:, idx])

    def test_1d_signal_becomes_single_channel(self) -> None:
        samples = np.zeros(128, dtype=np.float32)
        sig = Signal(samples=samples, format=self._format(1), capture_seq=1)
        result = _split_signal_to_channels(sig, sources_by_id={})
        assert len(result) == 1
        assert result[0].samples.shape == (128,)

    def test_channel_ids_are_one_based(self) -> None:
        sig = self._signal_2d(channels=3)
        result = _split_signal_to_channels(sig, sources_by_id={})
        assert [int(ch.source.channel) for ch in result] == [1, 2, 3]

    def test_unmapped_channels_get_unknown_category(self) -> None:
        sig = self._signal_2d(channels=2)
        result = _split_signal_to_channels(sig, sources_by_id={})
        for ch in result:
            assert ch.source.category is SourceCategory.UNKNOWN

    def test_mapped_channels_use_provided_source(self) -> None:
        sig = self._signal_2d(channels=2)
        mapped = Source(ChannelId(1), SourceCategory.PREACHER, "설교자")
        result = _split_signal_to_channels(sig, sources_by_id={1: mapped})
        assert result[0].source is mapped
        assert result[1].source.category is SourceCategory.UNKNOWN

    def test_preserves_capture_seq_and_format(self) -> None:
        sig = self._signal_2d(channels=2, seq=99)
        result = _split_signal_to_channels(sig, sources_by_id={})
        for ch in result:
            assert ch.capture_seq == 99
            assert ch.format == sig.format


class TestSerializeRecommendation:
    def test_basic_fields_serialized(self) -> None:
        rec = _rec(
            channel=4,
            kind=RecommendationKind.GAIN_ADJUST,
            category=SourceCategory.CHOIR,
            label="성가대",
            confidence=0.77,
            params={"fader": 0.6},
            reason="이유",
        )
        payload = _serialize_recommendation(rec)
        assert payload == {
            "channel": 4,
            "category": "choir",
            "label": "성가대",
            "kind": "gain_adjust",
            "params": {"fader": 0.6},
            "confidence": 0.77,
            "reason": "이유",
        }

    def test_empty_label_is_empty_string(self) -> None:
        rec = _rec(label="")
        assert _serialize_recommendation(rec)["label"] == ""

    def test_params_dict_is_copied(self) -> None:
        original = {"x": 1.0}
        rec = _rec(params=original)
        payload = _serialize_recommendation(rec)
        payload["params"]["x"] = 999.0  # type: ignore[index]
        assert original == {"x": 1.0}


class TestBuildTargets:
    def test_returns_all_five_categories(self) -> None:
        settings = Settings()
        targets = _build_targets(settings)
        assert set(targets.keys()) == {
            "vocal",
            "preacher",
            "choir",
            "instrument",
            "unknown",
        }

    def test_values_come_from_lufs_block(self) -> None:
        settings = Settings()
        settings.lufs = LufsTargets(
            vocal=-1.0,
            preacher=-2.0,
            choir=-3.0,
            instrument=-4.0,
            unknown=-5.0,
        )
        targets = _build_targets(settings)
        assert targets == {
            "vocal": -1.0,
            "preacher": -2.0,
            "choir": -3.0,
            "instrument": -4.0,
            "unknown": -5.0,
        }


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """MIXPILOT_* 환경 변수 제거 — Settings()가 디폴트로 떨어지게."""
    import os

    for k in [k for k in os.environ if k.startswith("MIXPILOT_")]:
        monkeypatch.delenv(k, raising=False)
