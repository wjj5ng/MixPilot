# ADR-0005: 제어 출력 — X32 OSC over UDP로 M32 직결

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 오음파(domain-expert), 김설계(architect)
- 관련: ADR-0004, ADR-0006

## Context

규칙 엔진(`rules/`)이 생성한 추천을 *실제 콘솔에 적용*해야 한다. 후보:

1. **M32 OSC 직결** (UDP 10023, X32 호환 프로토콜)
2. **DAW(Reaper) 경유 OSC** — Reaper가 M32에 제어 신호 중계
3. **사람이 수동 적용** (대시보드 표시만, 자동 제어 없음)

## Decision

**MixPilot은 M32에 직접 OSC를 송신한다.** 라이브러리는 `python-osc` 또는 동급. UDP 포트 10023. 명령은 X32/M32 표준 주소(`/ch/XX/mix/fader`, `/ch/XX/mix/on`, `/ch/XX/eq/*`, `/ch/XX/dyn/*` 등).

자동 적용 여부는 **운영 모드 설정**으로 분기:

- `dry-run`: 추천을 대시보드에만 표시. **디폴트.**
- `assist`: 신뢰도가 임계 이상인 추천만 자동 적용, 나머지는 표시.
- `auto`: 정책에 따라 자동 적용. 운영자가 명시적으로 활성화해야 진입.

## Consequences

✅ 좋은 점
- 단일 홉 — 지연·고장점 최소
- Reaper 의존 없음 (ADR-0006)
- M32 표준 프로토콜 → Behringer X32와도 즉시 호환
- 양방향 가능 — 현재 페이더 위치·라벨 읽기로 상태 동기화

⚠️ 트레이드오프
- 운영 중 잘못된 자동 제어는 사고 → 기본은 `dry-run`/`assist`이어야 함
- 비신뢰 UDP(응답 보장 없음) → 로컬 상태 미러 + 재전송으로 안전 회로 필요
- 외부 컨트롤러(태블릿 X32-Edit 등)와 동시 변경 시 경쟁 가능성

## Alternatives considered

- **Reaper OSC 경유**: 한 단계 더 있어 지연·복잡도 증가. 운영 중 Reaper가 죽으면 제어 단절. ADR-0006로 명시적 거부.
- **수동 적용만**: 가장 안전하지만 MixPilot 차별점 약화. 기본 운영 모드는 `dry-run`이지만 *시스템 능력*은 자동 제어를 지원해야 함.

## Implementation notes

- 어댑터: `infra/m32_control.py::M32OscController`
- 추상 포트: `domain/ports.py::ConsoleControl`
- 설정: `config.py`에 호스트 IP·포트, 운영 모드(`dry-run|assist|auto`)
- 명령 송신 전 *로컬 상태 미러*와 차이 검증 — 외부 컨트롤러 동시 변경 감지
- 모든 OSC 송신은 결정 로그로 기록 (감사·롤백)
- 결정성: 같은 추천 입력에 같은 OSC 메시지 발생 (`rules/` 결정성 원칙과 일치)
- 채널 메타데이터(스크리블 스트립 라벨 등)는 OSC `/ch/XX/config/name` 등으로 조회 — `infra/m32_meta.py`에 분리
