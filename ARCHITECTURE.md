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
| 오디오 캡처 | `infra/audio_capture.py` | `domain/ports.py::AudioSource` | `sounddevice` / `pyaudio` / 외부 RTP 스트림 중 결정 (AGENTS.md TODO) |
| 메트릭 저장 | `infra/metrics_sink.py` | `domain/ports.py::MetricsSink` | 로컬 JSONL / Prometheus / InfluxDB 등 |
| 추천 알림 | `infra/notifier.py` | `domain/ports.py::Notifier` | WebSocket 푸시 / 로깅 / 외부 알림 |
| 설정 로드 | `config.py` | (직접 사용) | `.env` + 환경 변수 + 카테고리별 임계값 파일 |

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

## 결정성 보장

`rules/`와 `dsp/`는 *같은 입력에 같은 출력*을 보장합니다. 다음을 금지:

- **시간 함수**: `datetime.now()`, `time.time()`, `time.monotonic()` — 시간이 필요하면 **인수로 받기**.
- **랜덤**: `random`, `numpy.random` — 테스트 픽스처·시드 고정 외 금지.
- **환경 변수 직접 읽기** — `os.environ`/`os.getenv` 호출 금지. 항상 `config.py`를 통해.
- **정렬 없는 dict/set 순회** — 결정성이 필요한 출력에서는 항상 명시적 정렬 또는 정렬된 자료구조(예: `tuple`, 정렬된 `list`) 사용.
- **부동소수 비교**: `==` 대신 `np.isclose`/`math.isclose` + 명시적 허용 오차.

## 실시간성 예산

라이브 환경 타깃이므로 *처리 지연*은 기능 추가의 1차 제약입니다.

- DSP 핫패스 1프레임 처리: **목표 ≤ 10ms** (예산. 실제 측정값을 `evals/`로 회귀 추적).
- 분석→추천 파이프라인 종단 지연: **목표 ≤ 50ms**.
- 새 분석/규칙 추가 시 `evals/` 지연 케이스로 회귀 측정 필수. 임계 초과 시 PR 머지 보류.

## 결정 기록 (ADR)

주요 아키텍처 결정은 `docs/adr/NNNN-<title>.md` 또는 이 파일 하단에 기록.

| 번호 | 제목 | 상태 |
|---|---|---|
| ADR-0001 | DSP 라이브러리 선정 (librosa vs scipy-only vs 자체 구현) | <!-- TODO --> |
| ADR-0002 | 실시간 전송 방식 (WebSocket vs SSE vs gRPC streaming) | <!-- TODO --> |
| ADR-0003 | 메트릭 저장소 선정 | <!-- TODO --> |

<!-- 새 결정 추가 시 행 추가 + 별도 ADR 파일 또는 이 문서 하단에 본문 -->
