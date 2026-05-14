# Evals

DSP 결정적 회귀 케이스 모음. 각 케이스는 표준 신호를 합성해 DSP 함수에 통과시킨 뒤
결과를 기대값 또는 속성과 비교합니다. **DSP 코드 변경 후 이 회귀가 깨지면 의도적
변경이라면 ADR + 케이스 파일 갱신, 그렇지 않으면 버그**.

## 구조

- `cases/` — `*.yaml` 회귀 케이스. 함수 1종 또는 함수군 1개당 파일 1개 권장.
- `fixtures/` — 합성으로 만들 수 없는 실신호(녹음·픽스처). 용량 크면 git-lfs 권장.
- `results/` — 사후 분석을 위한 실행 결과(미구현). `.gitkeep`만 추적.

## 실행

```bash
# 단일 파일
uv run python -m mixpilot.scripts.run_eval evals/cases/rms-baseline.yaml

# 여러 파일 (CI 기본 셋)
uv run python -m mixpilot.scripts.run_eval evals/cases/*.yaml
```

슬래시 명령 `/run-eval`도 동일 CLI를 호출합니다. CI(`.github/workflows/ci.yml`)에서
4종 baseline을 자동 실행 — 회귀가 메인에 들어오지 못합니다.

## YAML 스키마

### 최상위 키

| 키 | 설명 |
|---|---|
| `id` | 케이스 셋 식별자. 파일명과 같게 권장. |
| `description` | 자유 텍스트. |
| `function_under_test` | DSP 함수의 도트 경로 (단수). |
| `functions_under_test` | 한 케이스가 *여러 함수*를 동시에 검증할 때 (예: peak·true_peak). 배열. |
| `cases` | 케이스 배열. 각 원소는 `{id, input, expected, params?}`. |

`function_under_test`(단수)·`functions_under_test`(복수)는 상호 배타.

### 신호 종류 (`input.kind`)

| kind | 필수 파라미터 | 비고 |
|---|---|---|
| `sine` | `sample_rate`, `frequency_hz`, `amplitude`, `(duration_seconds \| num_samples)` | 순수 사인파. |
| `sum_of_sines` | `sample_rate`, `frequencies_hz: [...]`, `amplitudes: [...]`, `(duration_seconds \| num_samples)` | 길이 동일한 두 배열. |
| `dc` | `sample_rate`, `value`, `duration_seconds` | 상수 신호. |
| `silence` | `(duration_seconds \| num_samples)` | 모두 0. |
| `impulse` | `length`, `position`(기본 0), `amplitude`(기본 1.0) | 단일 비-제로 샘플. |
| `white_noise` | `amplitude`, `seed`(기본 0), `num_samples`(또는 duration) | gaussian, seed 고정 → 결정적. |

### 어설션 스키마 (`expected.*`)

**스칼라 값(rms·lufs)**

```yaml
expected:
  value: 0.3535      # 정확한 기대값
  tolerance_abs: 1e-12   # 둘 중 하나 또는 둘 다
  tolerance_rel: 1e-4    # OR 조합 (어느 한쪽이라도 만족하면 통과)
```

**범위(lufs sine-amp 등 K-weighting 의존)**

```yaml
expected:
  value_range: [-25.0, -21.0]
```

**직전 케이스 대비 차분(lufs amplitude 스케일링)**

```yaml
expected:
  delta_from: lufs-sine-1khz-amp0.1   # 같은 파일 내 이전 케이스 id
  delta_value: 6.0                     # 기대 delta
  tolerance_abs: 0.1
```

**예외 발생(가드 검증)**

```yaml
expected:
  raises: ValueError
  match: "too short"   # str(exc) substring (선택)
```

**Peak/True Peak 어설션(복수 함수 case)**

`functions_under_test: [mixpilot.dsp.peak.peak, mixpilot.dsp.peak.true_peak]`인 YAML에서
case별로 다음 키 조합 가능:

```yaml
expected:
  peak: 0.5                # peak() 정확 비교 (tolerance와 함께)
  true_peak: 0.5           # true_peak() 정확 비교
  true_peak_at_least: 0.5  # true_peak() >= 값
  true_peak_at_most: 0.55  # true_peak() <= 값
  tolerance_abs: 1e-9      # peak/true_peak equal에 공통 적용
  tolerance_rel: 1e-3      # (tolerance_abs와 OR)
```

**Feedback Detection 어설션**

`function_under_test: mixpilot.dsp.feedback.detect_peak_bins`. 결과가
`list[FeedbackPeak]`이므로 카운트·주파수 기반 어설션:

```yaml
expected:
  result_count: 0                              # 정확 count
  min_result_count: 1                          # >= N
  max_result_count: 5                          # <= N
  strongest_frequency_hz: 1000.0               # 최대 magnitude peak의 주파수
  strongest_frequency_tolerance_hz: 50.0       # ± tol (기본 50)
  frequencies_hz: [500, 3000]                  # 각 주파수마다 매칭 peak 1개 필요
  frequency_tolerance_hz: 50.0                 # 위에 적용
  assert: "no peak near 80 Hz"                 # 자유 문구 — 현재 지원 패턴:
                                               # "no peak near {freq} Hz [(± {tol} Hz)]"
```

한 case에 여러 어설션 키가 있으면 각각 별도 `CaseResult`로 보고 (모두 통과해야 패스).

### params 블록 (DSP 함수 kwargs)

Feedback case는 `params:`로 함수에 추가 kwargs 전달 가능:

```yaml
cases:
  - id: feedback-below-min-freq-rejected
    input: {...}
    params:
      min_frequency_hz: 100.0
      pnr_threshold_db: 20.0
    expected: {...}
```

지원 키(`detect_peak_bins`): `min_frequency_hz`, `max_frequency_hz`,
`pnr_threshold_db`, `neighbor_band_hz`.

## 새 DSP 함수 지원 추가

1. `src/mixpilot/scripts/run_eval.py`의 `_DSP_DISPATCH`에 entry 추가:
   ```python
   "mixpilot.dsp.newdsp.fn": lambda samples, input_spec: newdsp_fn(samples, ...),
   ```
2. 스칼라 반환이면 기존 어설션 스키마(`value`/`value_range`/`delta_from`/`raises`) 사용 가능.
3. 비스칼라 반환(리스트·구조체)이면 feedback처럼 전용 분기 추가.
4. `evals/cases/*.yaml` 작성 후 `uv run python -m mixpilot.scripts.run_eval ...`로 검증.

## 현재 baseline 셋

| 파일 | 함수 | 케이스/어설션 |
|---|---|---|
| `rms-baseline.yaml` | `rms` | 4/4 |
| `lufs-baseline.yaml` | `lufs_integrated` | 4/4 (raises 포함) |
| `peak-baseline.yaml` | `peak`+`true_peak` | 10/10 (4 cases × 다중 어설션) |
| `feedback-baseline.yaml` | `detect_peak_bins` | 7/7 (5 cases × 다중 어설션) |

## DSP 정확도 임계 기준

- RMS: rel_tol 1e-4 — 본질적으로 산술 합. 거의 정확.
- LUFS: ± 0.1 LUFS (delta_from 검증) — pyloudnorm K-weighting 정밀.
- Peak: abs_tol 1e-9 (silence), rel_tol 1e-3 (sine).
- True Peak: 사인파 0~10% 초과(resample 보간 transient 영향).
- Feedback frequency: ± 50 Hz (1024-pt FFT의 bin resolution ≈ 47 Hz).

임계를 *완화*하려면 ADR 작성 필요.

## 향후 계획

- Latency budget 케이스 — DSP 함수당 입력 길이별 실행 시간 상한 검증.
- 실신호 fixture 도입 시 `evals/fixtures/`에 git-lfs 또는 외부 URL.
- ITU-R BS.1770-4 conformance test signals로 LUFS 정확값 검증 (현재는 속성/범위만).
