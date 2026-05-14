# MixPilot

MixPilot는 라이브 음향 환경을 위한 **실시간 오디오 분석 및 믹싱 어시스턴트** 플랫폼입니다.

FFT, LUFS, Peak, RMS, Dynamic Range, Feedback Detection 등의 DSP 분석을 기반으로 오디오 상태를 실시간으로 분석하고, 규칙 기반 추천 및 자동화 기능을 통해 믹싱 품질 향상을 지원합니다.

메인 보컬, 설교자, 성가대, 라이브 악기 등 다양한 입력 소스를 분석하여 라이브 예배 및 공연 환경에서 안정적이고 일관된 음향 운영을 목표로 합니다.

## Domain

- **분석 지표 (DSP)**: FFT(주파수 분포), LUFS(라우드니스), LRA(라우드니스 레인지, ADR-0009), Peak, RMS, Dynamic Range, Feedback Detection, Phase Correlation(L/R 모노 다운믹스 안전성).
- **입력 소스**: 메인 보컬, 설교자, 성가대, 라이브 악기 등 다중 채널.
- **출력**: 규칙 기반 믹싱 추천 + 자동화 액션.
- **타깃 환경**: 라이브 예배, 공연. 안정성·일관성이 새로운 기능보다 우선.

## Stack

- **Language**: Python 3.12+
- **Package manager**: uv
- **Framework**: FastAPI
- **Tests**: pytest
- **CI**: GitHub Actions
- **DSP**: `numpy` + `scipy` 기본, `pyloudnorm`(LUFS). 추가 분석 라이브러리(`librosa` 등) 도입은 필요 시 ADR로 결정 (ADR-0001 미결).
- **오디오 I/O**: `sounddevice` — M32 USB 32ch 직접 캡처 ([ADR-0004](docs/adr/0004-audio-input-m32-usb.md)).
- **콘솔 제어**: `python-osc` — X32 OSC over UDP로 M32 직결 ([ADR-0005](docs/adr/0005-control-output-x32-osc.md)).
- **대시보드 push**: WebSocket / SSE 미결 (ADR-0002).
- **운영 콘솔**: Behringer/Midas **M32** (32 input / USB 32-in·32-out 내장).
- **DAW (보조)**: **Reaper** — 녹음·Virtual Soundcheck·`evals/fixtures/` 생성 한정. 운영 경로 제외 ([ADR-0006](docs/adr/0006-reaper-scope.md)).

## Commands

| 목적 | 명령 |
|---|---|
| 백엔드 의존성 설치 | `uv sync` |
| 백엔드 의존성 추가 | `uv add <package>` |
| 백엔드 개발 의존성 | `uv add --dev <package>` |
| 백엔드 테스트 | `uv run pytest` |
| 백엔드 테스트+커버리지 | `uv run pytest --cov=src/mixpilot --cov-report=term-missing` |
| 백엔드 포맷 | `uv run ruff format .` |
| 백엔드 린트 | `uv run ruff check --fix .` |
| pre-commit 훅 설치(1회) | `uv run pre-commit install` |
| pre-commit 전체 실행 | `uv run pre-commit run --all-files` |
| 백엔드 개발 서버 | `uv run fastapi dev src/mixpilot/main.py` |
| 백엔드 프로덕션 | `uv run uvicorn mixpilot.main:app --host 0.0.0.0 --port 8000` |
| 프론트 의존성 설치 | `npm --prefix frontend install` |
| 프론트 dev 서버 | `npm --prefix frontend run dev` (http://localhost:5173) |
| 프론트 빌드 | `npm --prefix frontend run build` |
| 프론트 타입 체크 | `npm --prefix frontend run check` |

## Project structure (src 레이아웃 + monorepo)

```
src/mixpilot/                  # Python 백엔드 (FastAPI)
  __init__.py
  main.py                      # 진입점 (app = FastAPI())
  api/                         # HTTP/WS 라우터, 요청·응답 스키마
  dsp/                         # DSP 분석 모듈 (RMS, LUFS, Feedback 등)
  rules/                       # 규칙 기반 추천 엔진
  domain/                      # 도메인 모델·포트
  infra/                       # 외부 I/O 어댑터
  runtime/                     # 상태 보유 런타임 컴포넌트 (RollingBuffer 등)
  config.py                    # pydantic-settings 기반 설정
frontend/                      # Svelte + Vite 운영 대시보드 (ADR-0007)
  src/
    App.svelte
    lib/api.ts                 # 백엔드 API 클라이언트
  package.json
  vite.config.ts
tests/                         # pytest. src/mixpilot/<x> ↔ tests/<x>로 미러
  unit/
  integration/
evals/                         # 평가 셋
  cases/
  fixtures/
  results/                     # gitignore
docs/adr/                      # 아키텍처 결정 기록
ARCHITECTURE.md                # 모듈 경계·의존성 방향
```

> `tests/`는 첫 모듈 만들 때 동시에. `evals/fixtures/`의 오디오 샘플은 용량에
> 따라 git-lfs 또는 외부 스토리지 분리.

## Conventions

- **언어**: 도메인 용어는 한국어 원어 유지(예: "하울링", "피드백"), 코드 식별자는 영문 snake_case.
- **타입 힌트 의무**: 공개 함수·메서드는 타입 힌트 필수. `from __future__ import annotations` 권장.
- **함수형 우선**: DSP 분석 함수는 *순수 함수* 우선 — `(np.ndarray, params) → metrics`. 부수효과(파일·소켓·DB)는 `infra/`에만.
- **에러 처리**: 외부 입력(API 바디·오디오 스트림)만 검증. 내부 호출은 신뢰. 보안·신호 무결성 경계에서만 raise.
- **실시간 코드 주의**: DSP 핫패스에서는 메모리 할당 최소화(`np.empty`·재사용), GIL 영향 줄이려 `numpy`·`scipy` 벡터화 우선, 필요 시 `numba`/`cython` 검토.
- **포맷·린트**: ruff. 버전은 `pyproject.toml` dev-dep에 정확 핀(`==0.15.12`)
  — pre-commit·CI·로컬 모두 동일 버전. 편집 시 Claude Code 훅이 자동
  실행(`.claude/settings.json`)되고, 커밋 시점에 `pre-commit` 훅이 *최종
  게이트*. ruff bump은 의도적 PR로만 (의도하지 않은 format drift 차단).
- **커밋 메시지**: 한국어로 작성. 타입 prefix(`feat:` / `fix:` / `chore:` / `docs:` / `refactor:` / `test:` 등)는 영문 컨벤션 유지하되, subject 설명·body·footer는 한국어로. 예: `feat(domain): 도메인 모델·포트 정의 추가`.

## Architecture

자세한 모듈 경계·의존성 방향·수정 금지 디렉토리는 [`ARCHITECTURE.md`](./ARCHITECTURE.md) 참조. 권장 의존성 방향:

```
api ─┐
     ├─→ rules ─→ domain
infra ┘            ↑
         dsp ──────┘
```

- `domain`은 어떤 외부 라이브러리(numpy 제외)에도 의존하지 않음.
- `dsp`는 `numpy`/`scipy`만 의존. `infra`/`api`를 import 금지.
- `rules`는 `domain` + `dsp`를 사용해 추천을 *결정*만 함. I/O 없음.
- `api`/`infra`가 외곽.

## Tooling

- 코드 편집 후 `ruff format` + `ruff check --fix`가 자동 실행됩니다 (`.claude/settings.json` PostToolUse 훅, ruff가 PATH에 있을 때만).
- 평가 셋: `evals/cases/`에 케이스 추가 후 `/run-eval` 슬래시 명령 실행.
- DSP 회귀 테스트는 표준 오디오 픽스처(`evals/fixtures/`)로 결정적 출력 검증 — 정확도 임계(예: LUFS ±0.1) 기준.

## Notes for AI assistants

- **Claude Code 사용자**: 글로벌 14인 에이전트(`~/.claude/agents/`)가 일반 직무를 담당합니다. MixPilot 도메인(DSP·라이브 음향·예배 환경 운영) 전문가는 `.claude/agents/domain-expert.md`에서 정의 — 채울 때 위 Domain 섹션을 시드로 사용.
- **Cursor/Codex/Copilot 사용자**: 이 파일이 메인 컨텍스트 인덱스입니다.
- **DSP 변경 시 주의**: 분석 함수의 출력 단위·범위가 바뀌면 `rules/`와 `evals/`가 함께 깨집니다. 항상 평가 셋 회귀 확인.
- **실시간성 회귀**: 라이브 환경 타깃이므로 새 기능 추가 시 *지연(latency)* 회귀를 측정하세요. 평가 셋에 지연 케이스 포함.
- **운영자 관점**: UI/명령/명세 변경 시 [`docs/operator-guide.md`](docs/operator-guide.md)도 같이 갱신. 음향 운영자가 코드 모르고 따라할 수 있어야 함.
