---
description: evals/cases/를 순회하여 평가를 실행하고 결과를 evals/results/<timestamp>/에 기록.
argument-hint: [--case=<glob>] [--out=<path>]
---

`evals/cases/`의 평가 케이스를 실행하고, 결과를 `evals/results/<timestamp>/`에 기록합니다.

## 동작 골격 (TODO: 프로젝트 결정에 맞춰 구현)

1. `evals/cases/`에서 `*.json` 또는 `*.yaml` 케이스 파일 수집.
2. 각 케이스에 대해:
   - 입력을 모델/엔드포인트에 전달
   - 출력을 기대값과 비교 (정확 일치 / 의미 유사 / LLM-as-judge 등)
   - 결과를 `evals/results/<timestamp>/<case-id>.json`에 기록
3. 요약 출력:
   - 통과/실패/스킵 수
   - 회귀(이전 결과 대비) 항목
   - 비용·지연 메트릭

## 골격 코드 위치

<!-- TODO: 평가 러너 경로 채우기. 예: `evals/runner.py` 또는 `uv run python -m evals` -->

## 평가 셋 설계

자세한 가이드는 [`evals/README.md`](../../evals/README.md) 참조 (Generator-Evaluator 패턴).
