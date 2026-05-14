# Changelog

MixPilot의 모든 주목할 만한 변경 사항을 기록합니다.

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)을 따르며,
버전은 [SemVer](https://semver.org/lang/ko/)를 따릅니다.

## [Unreleased]

### Added (Unreleased)

- Stereo phase correlation 룰 + 미터 표시 + 채널맵 stereo pair 편집.
  - 채널맵 yaml에 `stereo_pair_with` 필드 — 한쪽만 명시해도 자동 reverse.
  - `rules.phase`: 페어 채널의 correlation이 임계(기본 -0.3) 이하면 INFO.
  - 미터 페이로드에 `phase_with_pair`, `stereo_pair_with` 포함 → 미터 row 옆에
    `↔ chXX  φ+0.97` 형식으로 표시. < -0.3 적/정상 녹/> 0.5 황 색상.
  - 룰 토글에 phase 항목 자동 포함.
  - PhaseAnalysisConfig — enabled / warn_threshold.

### Changed (Unreleased)

- **채널맵 PUT의 라이브 처리 루프 즉시 반영** — 운영자가 service 도중 매핑
  편집 시 재시작 없이 다음 frame부터 새 매핑이 적용된다. 처리 루프가 사전
  스냅샷 dict 대신 `channel_map.get_source_sync()`를 매 frame 호출하도록 변경.
  UI 안내 문구도 "재시작 후 반영" → "다음 frame부터 즉시 반영"으로 갱신.

### 향후 후보

- 프로덕션 배포 아티팩트 (Dockerfile + systemd unit)
- ITU-R BS.1770-4 conformance signals로 LUFS·LRA 정확값 검증

---

## [0.1.0] - 2026-05-14

라이브 음향 환경(예배·공연)을 위한 실시간 오디오 분석·믹싱 어시스턴트
플랫폼의 초기 릴리스. M32 USB 32ch 캡처를 전제로 한 단일 노트북 운영 환경.

### Added

#### DSP 분석 (7종)
- **RMS** — 프레임 단위 평균 에너지, 다채널 벡터 변형.
- **LUFS** — pyloudnorm 기반 EBU R128 integrated loudness. 400 ms 이상 신호 요구.
- **LRA** — EBU R128 / Tech 3342 Loudness Range. K-weighting + 3s 블록 +
  power-mean 게이팅 직접 구현. 48 kHz 한정 (ADR-0009).
- **Peak / True Peak** — BS.1770-4 4x 오버샘플링으로 inter-sample peak.
- **Feedback Detection** — Hann + rFFT의 PNR(Peak-to-Neighbor Ratio) +
  지속 검증(persistence).
- **Dynamic Range** — `20·log10(peak/RMS)` crest factor. 압축 강도 가시화.
- **Octave-band Spectrum** — 8개 옥타브(125 Hz~16 kHz) dBFS. 미터 옆 시각화용.

#### 규칙 엔진
- `rules.loudness` — RMS dBFS 카테고리 타깃 비교.
- `rules.lufs` — 누적 LUFS 카테고리 타깃 비교.
- `rules.lra` — LRA 임계 외(< 5 / > 15 LU)에서 INFO 알림.
- `rules.peak` — true peak 헤드룸 위반 시 INFO.
- `rules.feedback` — feedback peak → FEEDBACK_ALERT.
- `rules.dynamic_range` — 압축 강함·트랜션트 폭 큼 INFO.

#### 자동 응답 안전 정책 (ADR-0008)
- `dry-run` / `assist` / `auto` 3 단계 운영 모드.
- `AutoGuard`: 채널별·전역 rate limit + service bootstrap silence + 세션 한도.
- 킬 스위치(`POST /control/dry-run`) — 모든 자동 송신 즉시 차단.
- 감사 로그 JSONL (`AuditLogger`) — applied/blocked_policy/blocked_guard 전부 기록.
- 메모리 ActionHistory 슬라이딩 윈도우(60 초) — 운영자 즉시 가시.

#### API (FastAPI + SSE)
- `GET /health` — 모듈별 활성 상태.
- `GET /channels` / `PUT /channels/{id}` — 채널맵 조회·편집.
- `GET /control/recent-actions` — 메모리 60 초 윈도우.
- `GET /control/audit-log/recent?limit=` — JSONL 영구 이력.
- `POST /control/dry-run` — 킬 스위치.
- `GET /recommendations` (SSE) — 룰 발화 추천 스트림.
- `GET /meters` (SSE) — 채널별 RMS·Peak·LRA·옥타브 스펙트럼 ~9 Hz 스트림.

#### 인프라
- `SoundDeviceAudioSource` — M32 USB 캡처 (ADR-0004).
- `SyntheticAudioSource` — 합성 사인파, 데모·테스트용.
- `WavReplayAudioSource` — WAV 재생, Virtual Soundcheck (ADR-0006).
- `M32OscController` — X32 OSC over UDP 10023 (ADR-0005).
- `YamlChannelMetadata` — `config/channels.yaml` 기반 채널 매핑, 런타임 편집.
- `RollingBuffer` — 다채널 누적 버퍼 (LUFS·LRA용).
- `FeedbackDetector` — 채널별 persistence 추적 래퍼.

#### 프론트엔드 (Svelte 5 + Vite + TS — ADR-0007)
- 상태 카드 — 모듈별 활성/비활성.
- 채널맵 카드 — 인-라인 편집(category select + label input).
- 라이브 미터 카드 — 채널별 RMS·Peak·Peak hold·LRA·8밴드 spectrum 시각화.
- 킬 스위치 버튼.
- 최근 자동 액션 패널 — 메모리 60 초.
- 감사 로그 카드 — 검색·outcome 필터.
- 추천 스트림 — 종류 필터(전체/경고/정보) + 비우기.

#### service 프리셋 + 런처
- `config/presets/`: worship·performance·rehearsal.
- `mixpilot.scripts.serve --preset <name>` — env 번들 적용 + uvicorn 가동.
- 운영자가 env로 명시한 값은 항상 우선(setdefault 패턴).

#### 평가 시스템
- `mixpilot.scripts.run_eval` — YAML 케이스 러너.
- 어설션 스키마: value+tolerance, value_range, delta_from, raises,
  peak 다중 함수, feedback peak-list, 옥타브 밴드.
- 6 baseline: `rms-baseline`, `lufs-baseline`, `peak-baseline`,
  `feedback-baseline`, `dynamic-range-baseline`, `lra-baseline`.
- `--output-dir`로 결과 JSON 영속화.

#### CI · 결정성
- GitHub Actions 3 잡: backend (ruff format/lint + pytest + eval 6종),
  frontend (svelte-check + vite build), OpenAPI schema drift.
- ruff 버전 정확 핀(`==0.15.12`) + pre-commit 커밋 게이트로 format drift 차단.

#### 기타
- DSP 벤치마크 CLI(`mixpilot.scripts.bench_dsp`) — 로컬 latency 회귀, CI 제외.
- WAV fixture 생성기(`evals/fixtures/generate_test_wavs.py`).

### Architecture Decisions

| ADR | 결정 |
|---|---|
| [0001](docs/adr/0001-dsp-helper-libraries.md) | librosa 미도입 — numpy + scipy + pyloudnorm 충분 |
| [0002](docs/adr/0002-dashboard-realtime-push.md) | 대시보드 push — SSE 채택 |
| [0003](docs/adr/0003-metric-storage.md) | 메트릭 시계열 저장 보류, JSONL audit로 충분 |
| [0004](docs/adr/0004-audio-input-m32-usb.md) | 오디오 입력 — sounddevice로 M32 USB 직접 캡처 |
| [0005](docs/adr/0005-control-output-x32-osc.md) | 콘솔 제어 — X32 OSC over UDP |
| [0006](docs/adr/0006-reaper-scope.md) | Reaper — 녹음·Soundcheck 보조 한정 |
| [0007](docs/adr/0007-frontend-stack.md) | 프론트엔드 — Svelte 5 + Vite |
| [0008](docs/adr/0008-auto-response-safety-policy.md) | 자동 응답 안전 정책 |
| [0009](docs/adr/0009-lra-implementation.md) | LRA 직접 구현, 48 kHz 한정 |

### 검증

- 660+ pytest 케이스 (단위·통합) 통과.
- ruff format / lint clean.
- 6 baseline eval 30+ 어설션 CI 자동.
- 프론트엔드 svelte-check 0 errors, vite build clean.

[Unreleased]: https://github.com/wjj5ng/MixPilot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wjj5ng/MixPilot/releases/tag/v0.1.0
