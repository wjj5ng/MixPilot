"""Service wav 회귀 러너 — 실 service 녹음 wav를 끝까지 재생해 추천을 캡처.

운영자가 `evals/fixtures/`에 service wav를 추가하고 회귀 case YAML을 작성하면
다음 변경부터 *같은 wav*에 *같은 추천 패턴*이 나오는지 자동 검증된다.

본 러너는 main 앱을 띄우지 않고 `_processing_loop`을 *직접* 호출 — minimal
wiring으로 통합 회귀를 빠르게(메모리 안에서) 실행.

사용:
    uv run python -m mixpilot.scripts.run_service_replay evals/service-cases/case.yaml

YAML 스키마(요약):
    id: my-case
    wav_path: evals/fixtures/service-2026-05-14.wav
    sample_rate: 48000
    num_channels: 8
    block_size: 512
    channel_map_path: config/channels.yaml  # 옵션
    rules_enabled: [loudness, peak, lufs, feedback, dynamic_range, lra, phase]
    expected:
        min_recommendation_count: 0  # 옵션
        max_recommendation_count: 200  # 옵션
        kinds_present: ["info"]  # 옵션 — 최소 1개씩 발화돼야
        kinds_absent: ["feedback_alert"]  # 옵션 — 발화되지 않아야

회귀 정확도가 *케이스 작성자*의 expected 정의에 달려 있음. 첫 service wav를
테스트한 결과를 expected로 박는 게 가장 단순한 회귀 정의 — "오늘 본 결과가
미래에도 그대로" 보장.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from mixpilot.config import (
    AudioConfig,
    AudioSource,
    DynamicRangeAnalysisConfig,
    FeedbackAnalysisConfig,
    LraAnalysisConfig,
    LufsAnalysisConfig,
    LufsTargets,
    M32Config,
    PeakAnalysisConfig,
    PhaseAnalysisConfig,
    RmsDbfsTargets,
    Settings,
)
from mixpilot.domain import Recommendation
from mixpilot.infra.channel_map import YamlChannelMetadata
from mixpilot.infra.m32_control import M32OscController
from mixpilot.infra.wav_replay import WavReplayAudioSource
from mixpilot.runtime import FeedbackDetector, RollingBuffer, RuleToggles


class _NullOscClient:
    """`send_message`만 no-op으로 받는 stub — OSC 송신 silent."""

    def send_message(self, *_args: Any, **_kwargs: Any) -> None:
        pass


@dataclass
class ReplayResult:
    """회귀 실행 결과 — pass/fail 판정 + 캡처된 추천 통계."""

    case_id: str
    passed: bool
    recommendation_count: int
    kinds_seen: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    duration_frames: int = 0


async def _replay_async(case: dict[str, Any], case_path: Path) -> ReplayResult:
    """실제 비동기 실행 — `WavReplayAudioSource` + processing loop."""
    from mixpilot.main import (
        RecommendationBroker,
        _build_live_thresholds,
        _processing_loop,
    )

    case_id = str(case.get("id", "<unnamed>"))
    wav_path = Path(case["wav_path"])
    # 케이스 yaml 상대경로 처리.
    if not wav_path.is_absolute():
        wav_path = (case_path.parent / wav_path).resolve()
    sample_rate = int(case.get("sample_rate", 48000))
    num_channels = int(case.get("num_channels", 8))
    block_size = int(case.get("block_size", 512))
    rules_enabled = set(case.get("rules_enabled", ["loudness"]))

    audio_cfg = AudioConfig(
        enabled=True,
        source=AudioSource.WAV,
        sample_rate=sample_rate,
        block_size=block_size,
        num_channels=num_channels,
        replay_path=wav_path,
        replay_loop=False,  # 자연 종료 → processing loop 빠져나옴
    )
    audio = WavReplayAudioSource(audio_cfg)

    # 빠른 settings — 디폴트만 사용.
    settings = Settings(
        audio=audio_cfg,
        rms_dbfs=RmsDbfsTargets(),
        lufs=LufsTargets(),
        peak_analysis=PeakAnalysisConfig(),
        lufs_analysis=LufsAnalysisConfig(),
        feedback_analysis=FeedbackAnalysisConfig(),
        dynamic_range_analysis=DynamicRangeAnalysisConfig(),
        lra_analysis=LraAnalysisConfig(),
        phase_analysis=PhaseAnalysisConfig(),
    )

    channel_map_path = case.get("channel_map_path")
    if channel_map_path:
        cm_path = Path(channel_map_path)
        if not cm_path.is_absolute():
            cm_path = (case_path.parent / cm_path).resolve()
        channel_map = YamlChannelMetadata(cm_path)
    else:
        # 디폴트 채널맵 (UNKNOWN 카테고리 폴백).
        channel_map = YamlChannelMetadata(Path("config/channels.yaml"))

    controller = M32OscController(M32Config(), osc_client=_NullOscClient())
    broker = RecommendationBroker(max_queue_size=10_000)
    captured: list[Recommendation] = []
    queue = broker.subscribe()

    # 버퍼·detector 모두 사전 생성 (main.py와 동일 패턴).
    lufs_buffer = RollingBuffer(
        capacity_frames=int(sample_rate * settings.lufs_analysis.buffer_seconds),
        num_channels=num_channels,
        dtype=np.float32,
    )
    lra_buffer = RollingBuffer(
        capacity_frames=int(sample_rate * settings.lra_analysis.buffer_seconds),
        num_channels=num_channels,
        dtype=np.float32,
    )
    feedback_detectors = {
        ch_id: FeedbackDetector(
            sample_rate,
            persistence_frames=settings.feedback_analysis.persistence_frames,
            pnr_threshold_db=settings.feedback_analysis.pnr_threshold_db,
            min_frequency_hz=settings.feedback_analysis.min_frequency_hz,
            max_frequency_hz=settings.feedback_analysis.max_frequency_hz,
        )
        for ch_id in range(1, num_channels + 1)
    }
    rule_toggles = RuleToggles.from_config_flags(
        loudness="loudness" in rules_enabled,
        lufs="lufs" in rules_enabled,
        peak="peak" in rules_enabled,
        feedback="feedback" in rules_enabled,
        dynamic_range="dynamic_range" in rules_enabled,
        lra="lra" in rules_enabled,
        phase="phase" in rules_enabled,
    )

    # 처리 루프 직접 실행. WAV 끝나면 async for가 자연 종료.
    duration_frames = [0]

    async def consume() -> None:
        while True:
            try:
                rec = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                # 처리 루프 끝났는지 확인 — 끝났으면 더 들어올 추천 없음.
                if processing_task.done():
                    break
                continue
            captured.append(rec)
            duration_frames[0] = max(duration_frames[0], 1)

    processing_task = asyncio.create_task(
        _processing_loop(
            audio,
            controller,
            broker,
            channel_map,
            rule_toggles,
            _build_live_thresholds(settings),
            lufs_buffer=lufs_buffer,
            lufs_eval_interval_frames=settings.lufs_analysis.eval_interval_frames,
            feedback_detectors=feedback_detectors,
            lra_buffer=lra_buffer,
            lra_eval_interval_frames=settings.lra_analysis.eval_interval_frames,
            meter_broker=None,  # 미터 SSE는 회귀에서 불필요
        )
    )
    consume_task = asyncio.create_task(consume())
    try:
        await processing_task
    finally:
        await audio.close()
        await consume_task
        broker.unsubscribe(queue)

    # 캡처된 추천 통계.
    kinds_seen: dict[str, int] = {}
    for rec in captured:
        kinds_seen[rec.kind.value] = kinds_seen.get(rec.kind.value, 0) + 1

    # expected 검증.
    expected = case.get("expected", {}) or {}
    failures: list[str] = []

    min_count = expected.get("min_recommendation_count")
    if min_count is not None and len(captured) < int(min_count):
        failures.append(f"min_recommendation_count={min_count}, got {len(captured)}")

    max_count = expected.get("max_recommendation_count")
    if max_count is not None and len(captured) > int(max_count):
        failures.append(f"max_recommendation_count={max_count}, got {len(captured)}")

    for kind in expected.get("kinds_present", []) or []:
        if kinds_seen.get(kind, 0) == 0:
            failures.append(f"kind {kind!r} expected present, never fired")

    for kind in expected.get("kinds_absent", []) or []:
        if kinds_seen.get(kind, 0) > 0:
            failures.append(
                f"kind {kind!r} expected absent, fired {kinds_seen[kind]} times"
            )

    return ReplayResult(
        case_id=case_id,
        passed=not failures,
        recommendation_count=len(captured),
        kinds_seen=kinds_seen,
        failures=failures,
        duration_frames=duration_frames[0],
    )


def run_case_file(path: Path) -> ReplayResult:
    """YAML 한 케이스를 실행 → ReplayResult."""
    case = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(case, dict):
        raise ValueError(f"{path}: YAML root must be a mapping")
    return asyncio.run(_replay_async(case, path))


def _format_report(result: ReplayResult) -> str:
    mark = "✅" if result.passed else "❌"
    lines = [
        f"{mark} {result.case_id}",
        f"  추천 {result.recommendation_count}건, 종류: {result.kinds_seen}",
    ]
    if result.failures:
        for f in result.failures:
            lines.append(f"  ❗ {f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MixPilot service wav 회귀 러너.")
    parser.add_argument("paths", nargs="+", type=Path, help="case YAML 파일들")
    parser.add_argument(
        "--json",
        action="store_true",
        help="결과를 JSON으로 stdout 출력 (인간 친화 보고서 대신).",
    )
    args = parser.parse_args(argv)

    any_failed = False
    results: list[ReplayResult] = []
    for p in args.paths:
        try:
            result = run_case_file(p)
        except FileNotFoundError as e:
            print(f"❌ {p}: {e}", file=sys.stderr)
            any_failed = True
            continue
        results.append(result)
        if not args.json:
            print(_format_report(result))
        if not result.passed:
            any_failed = True

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
