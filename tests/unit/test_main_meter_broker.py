"""MeterBroker와 미터 페이로드 직렬화 단위 테스트."""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from mixpilot.domain import (
    AudioFormat,
    Channel,
    Source,
    SourceCategory,
)
from mixpilot.main import MeterBroker, _compute_meter_payload

_FMT = AudioFormat(sample_rate=48000, num_channels=1, sample_dtype="float64")


def _ch(
    samples: np.ndarray,
    *,
    channel_id: int = 1,
    label: str = "",
    category: SourceCategory = SourceCategory.UNKNOWN,
) -> Channel:
    source = Source(channel=channel_id, category=category, label=label)
    return Channel(source=source, samples=samples, format=_FMT)


class TestComputeMeterPayload:
    def test_empty_channels_returns_empty_list(self) -> None:
        payload = _compute_meter_payload([], capture_seq=7)
        assert payload == {"capture_seq": 7, "channels": []}

    def test_single_channel_silence(self) -> None:
        samples = np.zeros(1024, dtype=np.float64)
        vocal_ch = _ch(
            samples,
            channel_id=1,
            label="메인 보컬",
            category=SourceCategory.VOCAL,
        )
        payload = _compute_meter_payload([vocal_ch], capture_seq=42)
        assert payload["capture_seq"] == 42
        assert len(payload["channels"]) == 1
        ch = payload["channels"][0]
        assert ch["channel"] == 1
        assert ch["label"] == "메인 보컬"
        assert ch["category"] == "vocal"
        assert ch["rms_dbfs"] == -120.0
        assert ch["peak_dbfs"] == -120.0

    def test_multi_channel_independent(self) -> None:
        sr = 48000
        t = np.arange(sr // 100) / sr  # 10 ms
        ch1_samples = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
        ch2_samples = np.zeros_like(t, dtype=np.float64)
        ch3_samples = np.full_like(t, 0.1, dtype=np.float64)
        channels = [
            _ch(ch1_samples, channel_id=1, label="vox", category=SourceCategory.VOCAL),
            _ch(ch2_samples, channel_id=2, label="", category=SourceCategory.UNKNOWN),
            _ch(
                ch3_samples,
                channel_id=3,
                label="dc",
                category=SourceCategory.INSTRUMENT,
            ),
        ]
        payload = _compute_meter_payload(channels, capture_seq=1)
        assert len(payload["channels"]) == 3

        assert payload["channels"][0]["channel"] == 1
        assert payload["channels"][0]["label"] == "vox"
        assert payload["channels"][0]["category"] == "vocal"
        assert payload["channels"][0]["peak_dbfs"] == pytest.approx(-6.02, abs=0.1)
        assert payload["channels"][0]["rms_dbfs"] == pytest.approx(-9.03, abs=0.1)

        assert payload["channels"][1]["channel"] == 2
        assert payload["channels"][1]["label"] == ""
        assert payload["channels"][1]["category"] == "unknown"
        assert payload["channels"][1]["rms_dbfs"] == -120.0

        assert payload["channels"][2]["channel"] == 3
        assert payload["channels"][2]["label"] == "dc"
        assert payload["channels"][2]["category"] == "instrument"
        assert payload["channels"][2]["peak_dbfs"] == pytest.approx(-20.0, abs=0.01)
        assert payload["channels"][2]["rms_dbfs"] == pytest.approx(-20.0, abs=0.01)

    def test_preserves_input_channel_id(self) -> None:
        # M32 1-based 채널 ID — _compute_meter_payload는 입력 source.channel을
        # 그대로 사용해야 함 (인덱스+1이 아님).
        payload = _compute_meter_payload(
            [_ch(np.zeros(100), channel_id=12)], capture_seq=0
        )
        assert payload["channels"][0]["channel"] == 12

    def test_dbfs_values_are_finite(self) -> None:
        channels = [
            _ch(np.zeros(100), channel_id=i) for i in range(1, 5)
        ]
        payload = _compute_meter_payload(channels, capture_seq=0)
        for ch in payload["channels"]:
            assert math.isfinite(ch["rms_dbfs"])
            assert math.isfinite(ch["peak_dbfs"])


class TestMeterBroker:
    def test_subscribe_returns_unique_queues(self) -> None:
        async def run() -> None:
            broker = MeterBroker(max_queue_size=2)
            q1 = broker.subscribe()
            q2 = broker.subscribe()
            assert q1 is not q2
            assert broker.subscriber_count == 2

        asyncio.run(run())

    def test_publish_fan_outs_to_all_subscribers(self) -> None:
        async def run() -> None:
            broker = MeterBroker(max_queue_size=2)
            q1 = broker.subscribe()
            q2 = broker.subscribe()
            broker.publish({"capture_seq": 1, "channels": []})
            v1 = await asyncio.wait_for(q1.get(), timeout=0.1)
            v2 = await asyncio.wait_for(q2.get(), timeout=0.1)
            assert v1 == {"capture_seq": 1, "channels": []}
            assert v2 == {"capture_seq": 1, "channels": []}

        asyncio.run(run())

    def test_unsubscribe_removes_queue(self) -> None:
        async def run() -> None:
            broker = MeterBroker(max_queue_size=2)
            q = broker.subscribe()
            broker.unsubscribe(q)
            assert broker.subscriber_count == 0
            broker.publish({"capture_seq": 1, "channels": []})
            assert q.empty()

        asyncio.run(run())

    def test_full_queue_drops_oldest(self) -> None:
        async def run() -> None:
            broker = MeterBroker(max_queue_size=2)
            q = broker.subscribe()
            broker.publish({"capture_seq": 1, "channels": []})
            broker.publish({"capture_seq": 2, "channels": []})
            broker.publish({"capture_seq": 3, "channels": []})
            first = await asyncio.wait_for(q.get(), timeout=0.1)
            second = await asyncio.wait_for(q.get(), timeout=0.1)
            seqs = {first["capture_seq"], second["capture_seq"]}
            # 최신 2개만 남음.
            assert seqs == {2, 3}

        asyncio.run(run())

    def test_publish_with_no_subscribers_is_noop(self) -> None:
        broker = MeterBroker()
        broker.publish({"capture_seq": 0, "channels": []})
        assert broker.subscriber_count == 0
