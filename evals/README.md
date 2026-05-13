# Evals

이 디렉토리는 프로젝트의 **평가 셋(eval set)** 을 담습니다. LLM/에이전트가 포함된 흐름이 예상대로 동작하는지 검증하는 결정적 회귀 테스트 모음입니다.

## 구조

- `cases/` — 평가 케이스. 각 케이스 = `{input, expected, metadata}`.
- `fixtures/` — 케이스가 참조하는 공유 데이터(샘플 문서, 픽스처).
- `results/` — 실행 결과. git에서 추적하지 않습니다(`.gitkeep`만).

## Generator-Evaluator 패턴

평가는 두 부분으로 나뉩니다:

1. **Generator** — 어떤 입력을 모델/시스템에 줄지 정의.
2. **Evaluator** — 출력이 좋은지 판정하는 기준 (정확 일치 / 임베딩 유사 / LLM-as-judge / 규칙 기반 등).

케이스 = `(Generator 입력, Evaluator 기준, 합격 임계)`

## 실행

```bash
/run-eval                    # 모든 케이스
/run-eval --case='auth/*'    # 특정 케이스
```

## 케이스 작성 예시 (YAML)

```yaml
id: auth-001
description: "로그인 실패 시 안전한 에러 메시지 반환"
input:
  endpoint: POST /auth/login
  body:
    email: nonexistent@example.com
    password: wrong
expected:
  status: 401
  body_matches:
    error: "Invalid credentials"
  must_not_contain:
    - "user not found"   # 이메일 존재 여부 누설 금지
metadata:
  category: security
  added: 2026-05-13
```

## 회귀 추적

- 매 실행마다 `results/<timestamp>/`에 결과 저장.
- CI에서 main 브랜치 대비 회귀를 감지하도록 연결 권장.

## 비용·지연 추적

- 각 케이스 실행 후 토큰·지연을 메타로 기록.
- 임계 초과 시 경고(예: p95 > 2s, 케이스당 토큰 > 5000).

<!-- TODO: 실제 평가 러너 구현 후 이 섹션 갱신 -->
