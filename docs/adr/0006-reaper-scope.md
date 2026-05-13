# ADR-0006: Reaper의 역할 범위 — 운영 경로 제외, 보조 도구 한정

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 오음파(domain-expert), 김설계(architect)
- 관련: ADR-0004, ADR-0005

## Context

Reaper는 라이브 음향 환경에서 흔하고, 본 운영자도 이미 설치되어 있다. MixPilot 운영 경로(라이브 분석·제어)에 어떻게 통합할지 결정 필요.

## Decision

**Reaper는 MixPilot의 런타임 의존성이 아니다.** 보조·개발 도구로만 사용한다. 코드 어디에도 Reaper를 import하거나 어댑터를 두지 않는다.

허용되는 Reaper 사용처:

1. **멀티트랙 녹음** — 라이브 세션을 사후 분석용으로 보관 (M32 → USB → Reaper)
2. **Virtual Soundcheck** — Reaper 재생을 M32의 USB 입력으로 되돌려 시스템·신호 체크
3. **`evals/fixtures/` 생성** — 표준 신호·실세션 발췌를 평가 셋 입력으로 가공
4. **개발자 회귀 재생** — DSP·규칙 변경 후 같은 음원으로 회귀 검증

## Consequences

✅ 좋은 점
- 운영 경로의 의존 컴포넌트 수 감소 → 라이브 중 고장점 감소
- 다른 DAW(Logic, Pro Tools, Ardour) 사용자도 동일하게 운용 가능
- 어댑터·테스트·문서 부담 없음

⚠️ 트레이드오프
- Reaper가 가진 풍부한 OSC·ReaScript 기능을 운영에 못 씀
- 향후 "Reaper 인덕션 자동화" 같은 요구가 들어오면 ADR 갱신 필요

## Out of scope (재고 시 ADR 갱신)

- Reaper ReaScript로 MixPilot UI 통합
- Reaper VST3/JSFX로 MixPilot DSP 패키징
- Reaper OSC를 M32 제어의 *대안 경로*로 사용 (현재는 직결만)

위 사용처가 실제로 필요해지면 본 ADR을 `Superseded` 처리하고 신규 ADR 작성.

## Operational notes

- 운영자는 Reaper 사용 여부와 무관하게 MixPilot을 가동할 수 있어야 한다.
- 개발 문서에는 Reaper 사용 *방법*을 적되, 필수 의존으로 표기하지 않는다.
