---
description: evals/cases/의 YAML 케이스를 실행하여 DSP 회귀 검증. 결과를 표준 출력으로 보고.
argument-hint: [<yaml-path>...]
---

`evals/cases/`의 평가 케이스를 실제로 실행하는 슬래시 명령. 내부적으로
`mixpilot.scripts.run_eval` CLI를 호출합니다.

## 사용

```bash
# 단일 케이스 파일
uv run python -m mixpilot.scripts.run_eval evals/cases/rms-baseline.yaml

# 여러 개 (glob)
uv run python -m mixpilot.scripts.run_eval evals/cases/*.yaml
```

## 동작

1. YAML 파일의 `function_under_test`(dotted path)를 dispatch 테이블에서 조회.
2. 각 `cases[*]`에 대해:
   - `input.kind`(sine/dc/silence/impulse)로 신호 합성
   - DSP 함수 호출
   - `expected.value` ± `tolerance_abs` / `tolerance_rel`로 통과 판정
3. 케이스별 ✅/❌ 출력 + 어느 하나라도 실패하면 exit 1.

## 지원 범위 (점진 확장)

| YAML 케이스 | 상태 |
|---|---|
| `rms-baseline.yaml` | ✅ 통과 (4/4) |
| `lufs-baseline.yaml` | ✅ 통과 (4/4) |
| `peak-baseline.yaml` | ✅ 통과 (10/10 assertion) |
| `feedback-baseline.yaml` | ✅ 통과 (7/7 assertion) |

미지원 케이스는 보고서에서 `unsupported function`로 표시. 새 DSP 지원 추가는
`src/mixpilot/scripts/run_eval.py`의 `_DSP_DISPATCH`·`_SIGNAL_GENERATORS`에 항목 추가.

## 평가 셋 설계

자세한 가이드는 [`evals/README.md`](../../evals/README.md) 참조 (Generator-Evaluator 패턴).
