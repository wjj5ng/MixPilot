# MixPilot

라이브 음향 환경(예배·공연)을 위한 실시간 오디오 분석 및 믹싱 어시스턴트.
FFT / LUFS / Peak / Feedback Detection 등 DSP 분석을 기반으로 오디오 상태를
실시간으로 측정하고, 규칙 기반 추천·자동화로 믹싱 품질 향상을 지원합니다.

운영 콘솔: **Behringer/Midas M32** (32-in USB).
보조 DAW: **Reaper** — 녹음·Virtual Soundcheck·평가 셋 생성 한정 ([ADR-0006](docs/adr/0006-reaper-scope.md)).

## 빠른 시작

### 의존성 설치

```bash
# Python (백엔드)
uv sync

# Node (프론트엔드)
npm --prefix frontend install
```

### 가동 (M32 없이도 가능)

#### 프리셋 사용 (권장)

service별 환경 변수 번들 — `config/presets/*.yaml`:

```bash
# 터미널 1 — 백엔드 (예배 / 공연 / 리허설)
uv run python -m mixpilot.scripts.serve --preset worship
uv run python -m mixpilot.scripts.serve --preset performance
uv run python -m mixpilot.scripts.serve --preset rehearsal

# 사용 가능한 프리셋 보기
uv run python -m mixpilot.scripts.serve --list-presets

# 터미널 2 — 프론트엔드
npm --prefix frontend run dev
```

운영자가 `MIXPILOT_*` env로 명시한 값은 프리셋이 덮지 않음 (사용자 우선).

#### 직접 env (개별 키 제어)

`MIXPILOT_AUDIO__SOURCE=synthetic` 으로 합성 오디오로 처리 루프를 검증할 수 있습니다.

```bash
# 터미널 1 — 백엔드
MIXPILOT_AUDIO__ENABLED=true \
MIXPILOT_AUDIO__SOURCE=synthetic \
MIXPILOT_AUDIO__NUM_CHANNELS=4 \
MIXPILOT_PEAK_ANALYSIS__ENABLED=true \
MIXPILOT_DEV_CORS_ENABLED=true \
  uv run fastapi dev src/mixpilot/main.py

# 터미널 2 — 프론트엔드
npm --prefix frontend run dev
```

브라우저 `http://localhost:5173` 접속 — 상태·추천 스트림·최근 자동 액션·킬 스위치
모두 사용 가능. M32 연결 시 `MIXPILOT_AUDIO__SOURCE=sounddevice`로 전환.

### 테스트

```bash
uv run pytest                 # 백엔드 (486+ 케이스)
uv run ruff check src tests   # 린트
npm --prefix frontend run check  # 프론트 타입체크
```

## 문서

| 문서 | 내용 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | 단일 컨텍스트 인덱스 (스택·도메인·관례·실행 명령). AI 어시스턴트도 같이 읽는다 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 모듈 경계·의존성 방향·실시간 예산·ADR 인덱스 |
| [`CHANGELOG.md`](CHANGELOG.md) | 릴리스별 변경 기록 (Keep a Changelog / SemVer) |
| [`docs/adr/`](docs/adr/) | 아키텍처 결정 기록 (0001~0009) |
| [`docs/hardware-dependent.md`](docs/hardware-dependent.md) | 실 M32가 있어야 진행/검증 가능한 작업 인벤토리 |
| [`evals/`](evals/) | DSP 회귀 케이스 (사인·DC·무음·임펄스 표준 신호) |

## 핵심 결정 한 줄 요약

- **운영 콘솔**: M32 USB 직접 캡처 ([ADR-0004](docs/adr/0004-audio-input-m32-usb.md))
- **제어 경로**: X32 OSC over UDP 10023 ([ADR-0005](docs/adr/0005-control-output-x32-osc.md))
- **자동 응답 안전 정책**: dry-run / assist / auto 3단계 + 8가지 안전장치 ([ADR-0008](docs/adr/0008-auto-response-safety-policy.md))
- **프론트엔드**: Svelte + Vite vanilla SPA, monorepo ([ADR-0007](docs/adr/0007-frontend-stack.md))

## 상태

초기 개발 단계. 처리 파이프라인(DSP 4종 + Rules + Infra)과 안전 정책(킬 스위치·
감사 로그·레이트 리미트·세션 한도) 모두 구현됨. 실 M32 연결 후 진행할 작업은
[`docs/hardware-dependent.md`](docs/hardware-dependent.md) 참조.
