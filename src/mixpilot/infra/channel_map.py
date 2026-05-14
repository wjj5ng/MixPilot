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


def _serialize_entry(s: Source) -> dict[str, Any]:
    """Source → YAML entry dict. stereo_pair_with는 None이면 생략."""
    entry: dict[str, Any] = {
        "id": int(s.channel),
        "category": s.category.value,
        "label": s.label,
    }
    if s.stereo_pair_with is not None:
        entry["stereo_pair_with"] = int(s.stereo_pair_with)
    return entry


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
        explicit_pairs: dict[int, int] = {}
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
            pair_with = item.get("stereo_pair_with")
            if isinstance(pair_with, int) and pair_with != ch_id:
                explicit_pairs[ch_id] = pair_with
            result[ch_id] = Source(
                channel=ChannelId(ch_id),
                category=category,
                label=label,
                stereo_pair_with=None,
            )

        # 자동 reverse — ch3에 pair_with=4만 적어도 ch4의 pair도 ch3로 채움.
        # 양쪽 명시 + 서로 다른 상대를 가리키면 첫 번째 우선(silent conflict 정책).
        pair_table = dict(explicit_pairs)
        for ch_id, partner in explicit_pairs.items():
            pair_table.setdefault(partner, ch_id)
        for ch_id, partner in pair_table.items():
            if ch_id in result:
                src = result[ch_id]
                result[ch_id] = Source(
                    channel=src.channel,
                    category=src.category,
                    label=src.label,
                    stereo_pair_with=partner,
                )
        return result

    def get_source_sync(self, ch_id: int) -> Source | None:
        """채널 ID로 Source 직접 조회 — 동기, 매 frame 핫패스용.

        라이브 처리 루프가 매 frame에서 호출하므로 async가 아닌 sync.
        내부 캐시는 `update_channel`이 mutate하므로 PUT 직후 다음 호출에
        즉시 새 값 반환.
        """
        return self._load().get(int(ch_id))

    async def get_channel_label(self, channel: ChannelId) -> str:
        source = self._load().get(int(channel))
        return source.label if source else ""

    async def get_all_channels(self) -> Iterable[Source]:
        return sorted(self._load().values(), key=lambda s: int(s.channel))

    def update_channel(
        self,
        ch_id: int,
        *,
        category: SourceCategory,
        label: str,
        stereo_pair_with: int | None = None,
    ) -> Source:
        """단일 채널 entry를 갱신 — 메모리 캐시 + YAML 파일 모두 즉시 반영.

        새 채널 ID도 지원 — 매핑에 없던 ID면 추가. 운영자가 service 도중
        매핑을 빠르게 조정할 수 있도록.

        Stereo pair는 양방향으로 동기화 — ch3→ch4 갱신 시 ch4의 pair도 ch3로
        자동 갱신, 기존 ch4의 pair가 ch5였다면 그 관계는 끊어진다(ch5의 pair는
        None으로 클리어).

        내부 캐시 mutate + YAML 영속화. 라이브 처리 루프는 `get_source_sync()`로
        매 frame 캐시를 다시 읽으므로 *다음 frame부터 즉시 반영* — 재시작 불필요.

        Returns:
            갱신된 Source 객체.
        """
        loaded = self._load()
        # 기존 pair 관계 정리 — 본 채널이 이전에 pair 갖고 있었으면 상대 채널의
        # pair도 None으로 클리어 (양쪽 일관성).
        old = loaded.get(ch_id)
        if old is not None and old.stereo_pair_with is not None:
            partner_id = old.stereo_pair_with
            if partner_id in loaded:
                partner = loaded[partner_id]
                loaded[partner_id] = Source(
                    channel=partner.channel,
                    category=partner.category,
                    label=partner.label,
                    stereo_pair_with=None,
                )
        # 새 pair partner의 기존 관계도 정리.
        if stereo_pair_with is not None and stereo_pair_with in loaded:
            partner = loaded[stereo_pair_with]
            if (
                partner.stereo_pair_with is not None
                and partner.stereo_pair_with != ch_id
            ):
                other = partner.stereo_pair_with
                if other in loaded:
                    other_src = loaded[other]
                    loaded[other] = Source(
                        channel=other_src.channel,
                        category=other_src.category,
                        label=other_src.label,
                        stereo_pair_with=None,
                    )
            # partner의 pair를 본 채널로 설정.
            loaded[stereo_pair_with] = Source(
                channel=partner.channel,
                category=partner.category,
                label=partner.label,
                stereo_pair_with=ch_id,
            )
        new_source = Source(
            channel=ChannelId(ch_id),
            category=category,
            label=label,
            stereo_pair_with=stereo_pair_with,
        )
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
                _serialize_entry(s)
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
