# Architecture

MixPilot의 모듈 경계·의존성 방향·외부 시스템 어댑터 규칙. 이 문서는 **강제 규약**이며, AI 에이전트도 사람도 위반하지 않습니다. 위반이 필요하면 코드보다 먼저 이 문서를 갱신하세요.

## 의존성 방향

```
        main.py  (조립자 · 진입점)
            │
   ┌────────┼────────┐
   ▼        ▼        ▼
  api     infra    config
   │        │
   └────┬───┘
        ▼
      rules
     ┌──┴──┐
     ▼     ▼
    dsp ─▶ domain   (dsp는 domain의 타입만 사용)
```

핵심 규칙:

- **`domain`은 프레임워크·외부 I/O 라이브러리에 의존하지 않는다.** numpy는 *타입·연산용*으로만 허용.
- **`dsp`는 순수 함수 모듈.** 부수효과(파일·소켓·전역 상태) 금지. `api`/`infra`/`rules`를 import하지 않는다.
- **`rules`는 결정 로직만.** `domain` + `dsp`를 조합해 추천을 *결정*. I/O 없음.
- **`api`/`infra`는 외곽.** 도메인 로직을 직접 구현하지 않고 항상 `rules`/`dsp`에 위임.
- **`main.py`만 조립자.** 의존성 와이어링·라이프스팬 관리·DI 컨테이너 역할.
- **같은 레이어 안 순환 의존 금지** (예: `dsp/*` 모듈끼리 순환, `rules/*` 모듈끼리 순환).

## 모듈 경계

| 모듈 | 책임 | 의존 허용 | 의존 금지 |
|---|---|---|---|
| `domain/` | 도메인 모델: `Signal`, `Channel`, `Source`, `Recommendation`, `AudioFormat`, 포트(Protocol) 정의. 순수 데이터·불변 타입 우선. | `numpy`(타입), 표준 라이브러리 | 그 외 모든 외부 라이브러리, 모든 형제 모듈 |
| `dsp/` | DSP 분석: FFT, LUFS, Peak/True Peak, RMS, Dynamic Range, Feedback Detection. 순수 함수 `(ndarray, params) → metrics`. | `numpy`, `scipy`, `pyloudnorm`, `domain/`(타입) | `api/`, `infra/`, `rules/`, 모든 부수효과 |
| `rules/` | 규칙 기반 추천 엔진. 분석 결과 → 추천 액션 매핑. 결정성 보장. | `domain/`, `dsp/`, 표준 라이브러리 | `api/`, `infra/`, 외부 I/O, 시간·랜덤 |
| `api/` | FastAPI 라우터, 요청·응답 스키마, WebSocket 핸들러. | `fastapi`, `pydantic`, `domain/`, `rules/`, `infra/`(추상 포트 통해) | `dsp/` 직접 호출 (→ `rules/` 통해서), 도메인 로직 직접 구현 |
| `infra/` | 외부 I/O 어댑터 — 오디오 캡처·결과 저장·메트릭·외부 알림. `domain/`의 포트를 *구현*. | `domain/`(포트), 외부 라이브러리(`sounddevice`, `pyaudio`, HTTP 클라이언트 등) | `api/`, `rules/`, `dsp/`, 도메인 로직 |
| `runtime/` | 라이브 처리에 필요한 *상태가 있는* 지원 컴포넌트 — 링 버퍼, 스로틀러, 지속성 검출기 등. 외부 I/O는 없지만 메모리 상태 보유. `dsp/`의 순수 함수를 *상태와 함께 래핑*하는 자리. | `numpy`, 표준 라이브러리, `domain/`(타입), `dsp/`(순수 분석 함수) | `api/`, `infra/`, `rules/`, 외부 I/O |
| `main.py` | FastAPI 인스턴스, 의존성 주입 와이어링, 라이프스팬(startup/shutdown) 이벤트. | 모든 모듈(조립자 권한) | 도메인 로직·DSP 로직 직접 작성 |
| `config.py` | 환경 변수, 카테고리별 임계값, 튜닝 파라미터. | `pydantic-settings`, 표준 라이브러리 | 다른 `src/mixpilot/*` 모듈 import 금지 (역의존만 허용) |

## 수정 금지 디렉토리·파일

AI 에이전트도 사람도 직접 편집하지 않습니다. 변경이 필요하면 *생성 도구를 통해서*만.

- **`.venv/`** — uv가 관리. `uv sync` / `uv add` / `uv remove`로만 갱신.
- **`uv.lock`** — `uv lock` 또는 `uv add` 부수 효과로만 갱신. 직접 편집 금지.
- **`evals/results/`** — 평가 실행 결과 (auto-generated, gitignored).
- **`src/mixpilot/_generated/`** *(코드 생성 도구 도입 시 신설)* — 생성 산출물.

## 외부 시스템 경계

각 외부 시스템은 `infra/` 안에 어댑터를 두고, `domain/`에 추상 포트(Protocol / ABC)만 노출합니다. 도메인·rules·dsp는 어댑터 구현체를 알지 못합니다.

| 외부 시스템 | 어댑터 위치(예정) | 추상 포트(예정) | 비고 |
|---|---|---|---|
| M32 오디오 캡처 | `infra/audio_capture.py::SoundDeviceAudioSource` | `domain/ports.py::AudioSource` | `sounddevice` 기반 USB 32ch 캡처 (ADR-0004) |
| M32 제어 | `infra/m32_control.py::M32OscController` | `domain/ports.py::ConsoleControl` | X32 OSC over UDP 10023 (ADR-0005) |
| M32 메타데이터 | `infra/m32_meta.py` | `domain/ports.py::ConsoleMetadata` | 채널 라벨·게인·라우팅 등을 OSC로 조회 (ADR-0005에 포함) |
| 메트릭 저장 | `infra/metrics_sink.py` | `domain/ports.py::MetricsSink` | 로컬 JSONL / Prometheus / InfluxDB 등 (ADR-0003 미결) |
| 대시보드 push | `api/realtime.py` | (FastAPI 내장) | WebSocket 또는 SSE (ADR-0002 미결) |
| 설정 로드 | `config.py` | (직접 사용) | `.env` + 카테고리별 임계값 + 채널 매핑 파일 |
| Reaper | *없음* | *없음* | 운영 경로 제외, 보조 도구로만 사용 (ADR-0006) |

<!-- 어댑터 구현·교체 시 위 표를 함께 갱신 -->

## 카테고리별 임계값

입력 소스 카테고리(보컬·설교자·성가대·악기)마다 정상 임계값이 다릅니다. 임계값은 **반드시** `config.py` 또는 외부 설정 파일에 분리:

```python
# 좋은 예
threshold = settings.lufs_target[source_category]

# 나쁜 예 (하드코딩 — 어디서 온 값인지 모름)
if lufs > -14.0: ...
```

새 임계값을 추가할 때:
1. `config.py`(또는 `config/thresholds.yaml`)에 기본값 등록.
2. 카테고리별 오버라이드 가능하게 구조화.
3. `rules/`에서 `settings`로 주입받아 사용. 모듈 상단 상수로 박지 않는다.

## M32 채널 매핑

M32 32채널을 입력 소스 카테고리(보컬·설교자·성가대·악기)로 매핑하는 정보는 **외부 설정**에 둡니다 — 코드에 박지 않습니다:

- 기본: `config/channels.yaml` — 채널 번호 → 카테고리 + 라벨 + 라우팅.
- 자동 추천: M32 OSC `/ch/XX/config/name`으로 콘솔의 스크리블 스트립 라벨을 읽어 매핑 후보를 생성 (`infra/m32_meta.py`).
- 운영자가 service 단위로 매핑을 갱신할 수 있어야 함 — 코드 수정·재배포 불필요.

`domain/`에는 *카테고리*만 존재하고, "ch01=설교자" 같은 구체 매핑은 외부 자료. `domain/`은 카테고리를 *인자로* 받는다 — `Source(category=SourceCategory.PREACHER, ...)`.

## 결정성 보장

`rules/`와 `dsp/`는 *같은 입력에 같은 출력*을 보장합니다. 다음을 금지:

- **시간 함수**: `datetime.now()`, `time.time()`, `time.monotonic()` — 시간이 필요하면 **인수로 받기**.
- **랜덤**: `random`, `numpy.random` — 테스트 픽스처·시드 고정 외 금지.
- **환경 변수 직접 읽기** — `os.environ`/`os.getenv` 호출 금지. 항상 `config.py`를 통해.
- **정렬 없는 dict/set 순회** — 결정성이 필요한 출력에서는 항상 명시적 정렬 또는 정렬된 자료구조(예: `tuple`, 정렬된 `list`) 사용.
- **부동소수 비교**: `==` 대신 `np.isclose`/`math.isclose` + 명시적 허용 오차.

## 실시간성 예산

라이브 환경 타깃이므로 *처리 지연*은 기능 추가의 1차 제약입니다. **M32에서 32채널 동시 캡처가 기본 시나리오**.

- DSP 핫패스 1프레임 처리(채널 1개): **목표 ≤ 1.5ms** — 32채널 병렬 처리 전제로 종단 예산을 채널 수로 분할.
- 단일 채널 단독 분석(디버깅·검증): **목표 ≤ 10ms**.
- 분석→추천 파이프라인 종단 지연(32채널 합산): **목표 ≤ 50ms**.
- 32채널 처리는 numpy 벡터화 우선, 필요 시 asyncio·멀티프로세스로 확장. GIL 영향이 큰 부분은 `numba`/`cython`/`numpy` C 루프 검토.
- 새 분석/규칙 추가 시 `evals/`에 **1채널·32채널** 지연 케이스 모두 회귀 측정. 임계 초과 시 PR 머지 보류.

## 결정 기록 (ADR)

주요 아키텍처 결정은 `docs/adr/NNNN-<title>.md` 또는 이 파일 하단에 기록.

| 번호 | 제목 | 상태 |
|---|---|---|
| ADR-0001 | DSP 분석 보조 라이브러리 선정 (librosa 도입 여부) | Open |
| ADR-0002 | 대시보드 실시간 push 방식 (WebSocket vs SSE) | Open |
| ADR-0003 | 메트릭 저장소 선정 | Open |
| [ADR-0004](docs/adr/0004-audio-input-m32-usb.md) | 오디오 입력 — M32 USB 직접 캡처 (sounddevice) | Accepted |
| [ADR-0005](docs/adr/0005-control-output-x32-osc.md) | 제어 출력 — X32 OSC over UDP로 M32 직결 | Accepted |
| [ADR-0006](docs/adr/0006-reaper-scope.md) | Reaper의 역할 범위 — 운영 경로 제외 | Accepted |

<!-- 새 결정 추가 시 행 추가 + `docs/adr/NNNN-<title>.md`에 본문 -->
