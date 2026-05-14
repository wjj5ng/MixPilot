"""infra.channel_map 단위 테스트 — YAML 로드·카테고리 파싱·캐시 무효화."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mixpilot.domain import ChannelId, SourceCategory
from mixpilot.infra.channel_map import YamlChannelMetadata


@pytest.fixture
def sample_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "channels.yaml"
    p.write_text(
        """\
channels:
  - id: 1
    category: preacher
    label: "설교자 메인"
  - id: 5
    category: choir
    label: "성가대 SOP"
  - id: 17
    category: bogus_value
    label: ""
""",
        encoding="utf-8",
    )
    return p


class TestGetChannelLabel:
    def test_known_channel_returns_label(self, sample_yaml: Path) -> None:
        meta = YamlChannelMetadata(sample_yaml)
        assert asyncio.run(meta.get_channel_label(ChannelId(1))) == "설교자 메인"

    def test_unknown_channel_returns_empty(self, sample_yaml: Path) -> None:
        meta = YamlChannelMetadata(sample_yaml)
        assert asyncio.run(meta.get_channel_label(ChannelId(999))) == ""


class TestGetAllChannels:
    def test_sorted_by_channel_id(self, sample_yaml: Path) -> None:
        meta = YamlChannelMetadata(sample_yaml)
        sources = list(asyncio.run(meta.get_all_channels()))
        assert [int(s.channel) for s in sources] == [1, 5, 17]

    def test_invalid_category_falls_back_to_unknown(self, sample_yaml: Path) -> None:
        meta = YamlChannelMetadata(sample_yaml)
        sources = list(asyncio.run(meta.get_all_channels()))
        by_id = {int(s.channel): s for s in sources}
        assert by_id[17].category is SourceCategory.UNKNOWN

    def test_known_categories_parsed(self, sample_yaml: Path) -> None:
        meta = YamlChannelMetadata(sample_yaml)
        sources = list(asyncio.run(meta.get_all_channels()))
        by_id = {int(s.channel): s for s in sources}
        assert by_id[1].category is SourceCategory.PREACHER
        assert by_id[5].category is SourceCategory.CHOIR


class TestCache:
    def test_reload_picks_up_file_changes(self, tmp_path: Path) -> None:
        p = tmp_path / "channels.yaml"
        p.write_text("channels:\n  - id: 1\n    category: vocal\n    label: A\n")
        meta = YamlChannelMetadata(p)
        assert asyncio.run(meta.get_channel_label(ChannelId(1))) == "A"

        p.write_text("channels:\n  - id: 1\n    category: vocal\n    label: B\n")
        # 캐시 무효화 전에는 옛값.
        assert asyncio.run(meta.get_channel_label(ChannelId(1))) == "A"
        meta.reload()
        assert asyncio.run(meta.get_channel_label(ChannelId(1))) == "B"


class TestMalformedYaml:
    def test_non_mapping_root_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "channels.yaml"
        p.write_text("- just\n- a\n- list\n")
        meta = YamlChannelMetadata(p)
        with pytest.raises(ValueError, match="mapping"):
            asyncio.run(meta.get_all_channels())

    def test_channels_not_list_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "channels.yaml"
        p.write_text("channels: not_a_list\n")
        meta = YamlChannelMetadata(p)
        with pytest.raises(ValueError, match="list"):
            asyncio.run(meta.get_all_channels())

    def test_empty_file_yields_no_channels(self, tmp_path: Path) -> None:
        p = tmp_path / "channels.yaml"
        p.write_text("")
        meta = YamlChannelMetadata(p)
        assert list(asyncio.run(meta.get_all_channels())) == []

    def test_update_channel_persists_to_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "channels.yaml"
        p.write_text(
            """\
channels:
  - id: 1
    category: vocal
    label: 원본 라벨
""",
            encoding="utf-8",
        )
        meta = YamlChannelMetadata(p)
        asyncio.run(meta.get_all_channels())  # 캐시 로드.
        updated = meta.update_channel(
            1, category=SourceCategory.PREACHER, label="설교자 메인"
        )
        assert int(updated.channel) == 1
        assert updated.category is SourceCategory.PREACHER
        assert updated.label == "설교자 메인"
        # YAML에 영속화됐는지 새 인스턴스로 재로드.
        meta2 = YamlChannelMetadata(p)
        sources = list(asyncio.run(meta2.get_all_channels()))
        assert len(sources) == 1
        assert sources[0].category is SourceCategory.PREACHER
        assert sources[0].label == "설교자 메인"

    def test_update_channel_adds_new_id(self, tmp_path: Path) -> None:
        p = tmp_path / "channels.yaml"
        p.write_text(
            "channels:\n  - id: 1\n    category: vocal\n",
            encoding="utf-8",
        )
        meta = YamlChannelMetadata(p)
        asyncio.run(meta.get_all_channels())
        meta.update_channel(5, category=SourceCategory.CHOIR, label="성가대 SOP")
        meta2 = YamlChannelMetadata(p)
        sources = list(asyncio.run(meta2.get_all_channels()))
        assert {int(s.channel) for s in sources} == {1, 5}

    def test_update_channel_atomic_no_tmp_leak(self, tmp_path: Path) -> None:
        # .tmp 파일이 정상 처리 후 남지 않아야 함.
        p = tmp_path / "channels.yaml"
        p.write_text("channels: []\n", encoding="utf-8")
        meta = YamlChannelMetadata(p)
        meta.update_channel(3, category=SourceCategory.INSTRUMENT, label="기타")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_skips_malformed_entries(self, tmp_path: Path) -> None:
        p = tmp_path / "channels.yaml"
        p.write_text(
            """\
channels:
  - id: 1
    category: vocal
    label: OK
  - id: "not an int"
    category: vocal
  - "string entry"
""",
            encoding="utf-8",
        )
        meta = YamlChannelMetadata(p)
        sources = list(asyncio.run(meta.get_all_channels()))
        assert [int(s.channel) for s in sources] == [1]
