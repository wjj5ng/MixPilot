"""YAML 기반 채널 매핑 — `config/channels.yaml`에서 채널 → 카테고리 로드.

`ConsoleMetadata` 포트의 초기 구현. M32 OSC 라벨 자동 인식(infra/m32_meta.py)이
들어오기 전까지의 1차 진입점. 운영자가 service 단위로 yaml을 갱신한다.

파일 포맷:
    channels:
      - id: 1
        category: preacher
        label: "설교자 메인"
      - id: 5
        category: choir
        label: "성가대 SOP"
      ...
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from mixpilot.domain import ChannelId, Source, SourceCategory


class YamlChannelMetadata:
    """`ConsoleMetadata` 포트의 YAML 구현."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: dict[int, Source] | None = None

    def reload(self) -> None:
        """캐시 무효화 — service 도중 yaml 수정 후 재로드."""
        self._cache = None

    def _load(self) -> dict[int, Source]:
        if self._cache is None:
            self._cache = self._read_yaml()
        return self._cache

    def _read_yaml(self) -> dict[int, Source]:
        with self._path.open(encoding="utf-8") as f:
            data: Any = yaml.safe_load(f) or {}

        if not isinstance(data, dict):
            raise ValueError(
                f"channels.yaml root must be a mapping, got {type(data).__name__}"
            )
        raw_channels = data.get("channels", [])
        if not isinstance(raw_channels, list):
            raise ValueError("channels.yaml 'channels' must be a list")

        result: dict[int, Source] = {}
        for item in raw_channels:
            if not isinstance(item, dict):
                continue
            ch_id = item.get("id")
            if not isinstance(ch_id, int):
                continue
            category_str = str(item.get("category", "unknown")).lower()
            try:
                category = SourceCategory(category_str)
            except ValueError:
                category = SourceCategory.UNKNOWN
            label = str(item.get("label", ""))
            result[ch_id] = Source(
                channel=ChannelId(ch_id),
                category=category,
                label=label,
            )
        return result

    async def get_channel_label(self, channel: ChannelId) -> str:
        source = self._load().get(int(channel))
        return source.label if source else ""

    async def get_all_channels(self) -> Iterable[Source]:
        return sorted(self._load().values(), key=lambda s: int(s.channel))
