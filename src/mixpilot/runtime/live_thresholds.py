"""런타임 변경 가능한 룰 임계·타깃 — `/control/reload`로 service 도중 갱신.

처리 루프는 매 frame 본 객체의 속성을 직접 읽는다(스냅샷 캐시 없음). 운영자가
`POST /control/reload`를 호출하면 `.env` 또는 환경 변수가 재평가되어 본 객체의
필드가 *그 자리에서* 갱신 → 다음 frame부터 새 임계로 평가.

긴 재시작 없이 service 중 임계를 미세 조정하기 위함. 본 객체로 처리할 수
없는 변경(audio 디바이스·sample rate·LUFS/LRA buffer 크기·feedback detector
persistence 등)은 reload에서 ignored로 보고하고 운영자에게 명시적 재시작을
요구한다.

ARCHITECTURE 규약: `runtime`만 — 외부 I/O 없음. `Settings`로부터 *복사*해
받는다(domain 의존성을 만들지 않기 위해).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LiveThresholds:
    """라이브 갱신 가능한 룰 임계·타깃 집합.

    rms_targets·lufs_targets는 dict로 두어 처리 루프가 동일 참조를 매 frame
    조회하는 패턴 유지(기존 `evaluate_all_channels(channels, rms_targets)`에
    그대로 주입 가능). 스칼라 임계는 직접 속성으로 읽힌다.
    """

    # 카테고리별 RMS dBFS 타깃 — 키 'vocal'|'preacher'|'choir'|'instrument'|'unknown'.
    rms_targets: dict[str, float] = field(default_factory=dict)

    # 카테고리별 LUFS 타깃.
    lufs_targets: dict[str, float] = field(default_factory=dict)

    peak_headroom_threshold_dbfs: float = -1.0
    peak_oversample: int = 4

    dynamic_range_low_threshold_db: float = 6.0
    dynamic_range_high_threshold_db: float = 20.0
    dynamic_range_silence_threshold_db: float = 0.5

    peak_persistence_frames: int = 1
    dynamic_range_persistence_frames: int = 1

    lra_low_threshold_lu: float = 5.0
    lra_high_threshold_lu: float = 15.0
    lra_silence_threshold_lu: float = 0.1

    phase_warn_threshold: float = -0.3

    feedback_pnr_threshold_db: float = 15.0

    def apply_threshold_settings(
        self,
        *,
        rms_targets: dict[str, float],
        lufs_targets: dict[str, float],
        peak_headroom_threshold_dbfs: float,
        peak_oversample: int,
        peak_persistence_frames: int,
        dynamic_range_low_threshold_db: float,
        dynamic_range_high_threshold_db: float,
        dynamic_range_silence_threshold_db: float,
        dynamic_range_persistence_frames: int,
        lra_low_threshold_lu: float,
        lra_high_threshold_lu: float,
        lra_silence_threshold_lu: float,
        phase_warn_threshold: float,
        feedback_pnr_threshold_db: float,
    ) -> None:
        """주어진 값으로 모든 임계를 *원자적으로* 갱신.

        rms_targets·lufs_targets는 동일 dict 객체를 유지해야 처리 루프가 갖고
        있는 참조와 호환되므로 in-place 갱신(`.clear() + .update()`).
        """
        self.rms_targets.clear()
        self.rms_targets.update(rms_targets)
        self.lufs_targets.clear()
        self.lufs_targets.update(lufs_targets)
        self.peak_headroom_threshold_dbfs = peak_headroom_threshold_dbfs
        self.peak_oversample = peak_oversample
        self.peak_persistence_frames = peak_persistence_frames
        self.dynamic_range_low_threshold_db = dynamic_range_low_threshold_db
        self.dynamic_range_high_threshold_db = dynamic_range_high_threshold_db
        self.dynamic_range_silence_threshold_db = dynamic_range_silence_threshold_db
        self.dynamic_range_persistence_frames = dynamic_range_persistence_frames
        self.lra_low_threshold_lu = lra_low_threshold_lu
        self.lra_high_threshold_lu = lra_high_threshold_lu
        self.lra_silence_threshold_lu = lra_silence_threshold_lu
        self.phase_warn_threshold = phase_warn_threshold
        self.feedback_pnr_threshold_db = feedback_pnr_threshold_db

    def snapshot(self) -> dict[str, float | int | dict[str, float]]:
        """현재 임계 + 타깃 dict — 진단·`/control/reload` 응답용."""
        return {
            "rms_targets": dict(self.rms_targets),
            "lufs_targets": dict(self.lufs_targets),
            "peak_headroom_threshold_dbfs": self.peak_headroom_threshold_dbfs,
            "peak_oversample": self.peak_oversample,
            "peak_persistence_frames": self.peak_persistence_frames,
            "dynamic_range_low_threshold_db": self.dynamic_range_low_threshold_db,
            "dynamic_range_high_threshold_db": self.dynamic_range_high_threshold_db,
            "dynamic_range_silence_threshold_db": (
                self.dynamic_range_silence_threshold_db
            ),
            "dynamic_range_persistence_frames": self.dynamic_range_persistence_frames,
            "lra_low_threshold_lu": self.lra_low_threshold_lu,
            "lra_high_threshold_lu": self.lra_high_threshold_lu,
            "lra_silence_threshold_lu": self.lra_silence_threshold_lu,
            "phase_warn_threshold": self.phase_warn_threshold,
            "feedback_pnr_threshold_db": self.feedback_pnr_threshold_db,
        }
