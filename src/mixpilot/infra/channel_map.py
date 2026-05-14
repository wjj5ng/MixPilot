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

    def update_channel(
        self, ch_id: int, *, category: SourceCategory, label: str
    ) -> Source:
        """단일 채널 entry를 갱신 — 메모리 캐시 + YAML 파일 모두 즉시 반영.

        새 채널 ID도 지원 — 매핑에 없던 ID면 추가. 운영자가 service 도중
        매핑을 빠르게 조정할 수 있도록.

        ⚠️ 라이브 처리 루프는 시작 시 스냅샷한 `sources_by_id`를 사용하므로
        프로세스 재시작 전까지는 본 변경이 *반영되지 않음*. 호출자는 UI에서
        명시적으로 안내해야 한다.

        Returns:
            갱신된 Source 객체.
        """
        loaded = self._load()
        new_source = Source(channel=ChannelId(ch_id), category=category, label=label)
        loaded[ch_id] = new_source
        self._write_yaml(loaded)
        return new_source

    def _write_yaml(self, sources: dict[int, Source]) -> None:
        """현재 채널맵을 YAML 파일에 쓴다 — atomic rename으로 부분 쓰기 방지.

        파일 첫 줄 header comment를 보존하지만 entry 사이의 운영자 주석은
        손실됨 (수용 가능 — 코멘트는 별도 GitOps 영역).
        """
        header = (
            "# M32 채널 → MixPilot source 카테고리 매핑.\n"
            "# 운영자가 service 단위로 갱신. 코드 수정·재배포 불필요.\n"
            "#\n"
            "# 카테고리: vocal | preacher | choir | instrument | unknown\n"
            "# UI 편집(PUT /channels/{id})으로 수정 시 본 파일이 재작성됨 —\n"
            "# 운영자 주석은 보존되지 않음.\n"
            "\n"
        )
        entries_data = {
            "channels": [
                {
                    "id": int(s.channel),
                    "category": s.category.value,
                    "label": s.label,
                }
                for s in sorted(sources.values(), key=lambda x: int(x.channel))
            ]
        }
        body = yaml.safe_dump(
            entries_data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(header + body, encoding="utf-8")
        tmp_path.replace(self._path)
