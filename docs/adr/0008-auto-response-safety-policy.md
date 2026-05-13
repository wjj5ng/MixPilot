# ADR-0008: 자동 응답 안전 정책 — Recommendation Kind별 자동 적용 범위와 안전장치

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 오음파(domain-expert), 김설계(architect), 한보안(security)
- 관련: ADR-0005(운영 모드), ADR-0006

## Context

처리 루프가 RMS / LUFS / Peak / Feedback 4종 룰에서 Recommendation을 발화하고,
`M32OscController`가 운영 모드(dry-run / assist / auto)에 따라 OSC로 적용한다.
현재 모든 룰이 INFO를 발화하고 자동 적용 정책은 *confidence + mode*만 본다.

라이브 운영(예배·공연)에서 잘못된 자동 동작은 사고다. 잘못된 MUTE 하나가
설교 도중 발생하면 service 흐름이 무너지고 운영자 신뢰가 깨진다. 반대로,
자동화가 전혀 없으면 MixPilot은 단순 알림 시스템이라 차별 가치가 약하다.

이 ADR은 **어떤 종류의 추천이 어떤 모드에서, 어떤 안전장치와 함께 자동 적용
가능한지의 정책**을 박는다. 구현은 별도 PR (`runtime/auto_guard.py`,
`M32OscController` 확장).

## Decision

### 1. Recommendation Kind별 자동 적용 분류

| Kind | dry-run | assist | auto | 비고 |
|---|---|---|---|---|
| `INFO` | 표시만 | 표시만 | 표시만 | 정보 채널 — 자동 동작 *절대* 없음 |
| `GAIN_ADJUST` | 표시만 | 자동(제한적) | 자동(제한적) | 한 액션 \|Δ\| ≤ 3 dB |
| `UNMUTE` | 표시만 | 자동 | 자동 | 의도된 상태 복원 — 위험 낮음 |
| `MUTE` | 표시만 | 표시만 | 자동(제한적) | 라이브 중 음소거 위험 — auto만 |
| `EQ_ADJUST` | 표시만 | 표시만 | 자동(제한적) | 톤 변화 — 신뢰 누적 후 |
| `FEEDBACK_ALERT` | 표시만 | 자동(한정 액션) | 자동(한정 액션) | 즉응 필요. 응답은 협대역 notch 또는 ≤ 2 dB cut |

### 2. 운영 모드 의미 (ADR-0005 확장)

- **dry-run**: 모든 추천을 표시. 어떤 OSC도 송신 안 함. **디폴트.**
- **assist**: `GAIN_ADJUST` / `UNMUTE` / `FEEDBACK_ALERT`만 자동, 나머지는 표시.
  Confidence ≥ `auto_apply_confidence_threshold`(설정값) 미달이면 표시만.
- **auto**: 위 표의 "자동" 항목 전부 자동. 운영자가 *명시적*으로 진입.

### 3. 보편 안전장치 (모든 자동 액션에 적용)

1. **Confidence 임계**: 각 자동 액션 후보의 confidence ≥ 임계가 아니면 표시만.
2. **변화량 캡**:
   - `GAIN_ADJUST`: 한 액션당 \|Δ\| ≤ **3 dB**.
   - `EQ_ADJUST`: 한 액션당 밴드 \|Δ gain\| ≤ **3 dB**.
   - `FEEDBACK_ALERT` 응답: 협대역 notch 또는 ≤ **2 dB cut**만.
3. **레이트 리미트**:
   - 채널당 **5초 윈도우 안 최대 1회**.
   - 글로벌 **1초 안 최대 3회**.
4. **세션 한도**: service당 자동 액션 **50회**. 초과 시 운영자에게 알리고
   dry-run으로 자동 강등.
5. **초기 부트스트랩**: 캡처 시작 후 처음 **10초**는 자동 액션 금지 — 베이스라인
   정착 시간.
6. **롤백 윈도우**: 최근 **60초** 안의 자동 액션은 UI 한 번에 일괄 되돌리기.
7. **킬 스위치**: UI 정지 버튼으로 즉시 모든 자동 정지 → dry-run 강등. 신규 API:
   `POST /control/dry-run`.
8. **감사 로그**: 모든 자동 *시도*(적용·차단 무관) 기록 — `infra/audit.py`(예정).
   추천 메타·결정·결과를 함께 보관.

### 4. 등급 진입 권장 절차 (강제 아님)

운영자가 처음 자동 모드를 켤 때 권장 순서:

1. **dry-run에서 최소 한 service 분량**(≥ 2시간) 알림 관찰.
2. False positive 비율 자체 점검 — 운영자 직관 ↔ 추천 *일치율 > 80%* 기준 권장.
3. **assist 1회 service** 사용 후 행동 검토.
4. 문제 없으면 **auto** 검토.

이 절차는 코드 강제가 아니라 UI 도움말 + 운영 가이드에 명시.

## Consequences

✅ 좋은 점
- 라이브 환경에서 *안전 우선* 정책이 명시적으로 박힘 — 디폴트가 dry-run이라
  잘못된 액션으로 신뢰가 깨질 위험 최소.
- Kind별 차등 정책으로 *안전 ↔ 유용* 균형 — INFO만 발화하는 단순 알림 시스템 탈피.
- 보편 안전장치(레이트·캡·롤백·킬·감사)가 *모든* 자동 액션에 일관 적용.
- 운영자에게 신뢰 누적 경로(dry-run → assist → auto)가 명확.

⚠️ 트레이드오프
- 정책 복잡도 증가 → 구현·테스트·문서화 부담 ↑.
- 자동 액션의 가치는 *한도 안*에서만 — "큰 문제는 사람이 해결한다"가 명시적 디자인.
- assist는 dry-run보다 *약간만* 더 적극적 — auto에 준하는 자유도는 보장 안 됨.
- 50회/service·5초/채널 같은 수치는 임의 — 운영 경험 누적 후 별도 ADR로 조정.

## Out of scope (재고 시 신규 ADR)

- ML 기반 confidence 보정 (현재는 정적 PNR/delta 매핑)
- 다중 룰 합의 — 여러 룰이 같은 채널에 동시 추천 시 가중치
- 채널 간 상관 분석 — 인접 채널과의 관계로 false positive 줄이기
- 운영자 프로파일 학습 — 각 운영자의 수락/거절 패턴 학습
- 자동 액션 KPI — false positive rate·응답 지연 등 정량 평가 (eval 셋 확장 필요)

## Implementation notes (후속 PR)

- `M32OscController._should_apply(rec)`에 *Kind별 분기* 추가 — Kind dispatch table.
- 보편 안전장치는 `runtime/auto_guard.py`(예정)에 상태로 보관:
  - 채널별 마지막 자동 액션 시각 → 5초 윈도우 체크
  - 전역 카운터 + 1초 슬라이딩 윈도우
  - 세션 누적 카운터 + 초과 시 강등 콜백
  - 부트스트랩 타이머
- 롤백: 최근 60초 자동 액션 이력을 `runtime/auto_guard.py`에 보관 → 일괄 역 OSC 송신.
- 킬 스위치: `POST /control/dry-run` 엔드포인트가 `cfg.m32.operating_mode`를 런타임에
  변경하거나 controller 상태를 강제 갱신.
- 감사 로그: 메트릭 저장소(ADR-0003 미결)와 연계 가능. 우선 로컬 JSONL 파일.

이 정책의 *어떤 한도라도* 코드 미구현 상태로 두는 것은 다음 운영 service 전까지
허용되지 않는다 — auto 모드는 모든 안전장치가 작동할 때만 켜질 수 있다.
