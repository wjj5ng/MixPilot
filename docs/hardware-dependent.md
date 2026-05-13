# 하드웨어 종속 작업 인벤토리

실 **Behringer/Midas M32** 콘솔이 연결되어야 의미 있게 구현·검증되는 작업들의
목록. 오프라인 환경(노트북만)에서는 *골격·테스트·문서*만 가능하고, 실제 동작은
하드웨어 도착 이후로 미룬다.

각 항목은 다음을 명시:
- **블로커**: 왜 하드웨어가 필요한가
- **임시 상태**: 지금 코드에 무엇이 있는가
- **하드웨어 도착 후 작업**: 실 동작을 위해 무엇을 더 해야 하는가

## 1. M32 상태 reader (`infra/m32_meta.py`)

ADR-0005 implementation note에서 언급. 현재 콘솔 상태(페이더 위치, 뮤트, 라벨,
게인 등)를 OSC로 *조회*하는 양방향 통신 어댑터.

- **블로커**: X32 OSC는 send + receive 둘 다 필요. UDP 응답 수신을 위해
  `python-osc`의 `dispatcher.Dispatcher` + `osc_server` 패턴이 필요한데,
  실제 M32가 응답을 줘야 응답 형식·타이밍·재전송 정책을 검증할 수 있다.
- **임시 상태**: `infra/channel_map.py::YamlChannelMetadata`가 정적 YAML로
  대체. 채널 → 카테고리 매핑은 동작하지만 *현재* 콘솔 상태와는 무관.
- **하드웨어 도착 후**:
  - `infra/m32_meta.py::M32OscMetadata` 구현 — `domain.ports.ConsoleMetadata`
  - request/response 매칭 (OSC ID 또는 주소 기반)
  - 채널 라벨 자동 인식 → category 추론
  - 현재 페이더 캐시 + 변경 시 콜백

## 2. GAIN_ADJUST의 delta_db 경로

ADR-0008 §3.2 변화량 캡(±3 dB)은 *delta* 기반. 현재 `M32OscController._translate`
는 GAIN_ADJUST를 `params["fader"]` 절대값으로만 처리.

- **블로커**: delta를 적용하려면 *현재* 페이더 값을 알아야 한다 → 위 #1 reader 필요.
- **임시 상태**: 
  - 룰 측은 INFO만 발화. 자동 적용 안 됨.
  - 컨트롤러는 `delta_db`가 params에 있어도 클램프 후 *경고 로깅·미송신*.
  - `MAX_DELTA_DB = 3.0` 상수와 `_clamp_delta_db` 헬퍼가 캡 정책을 코드에 박아둠.
- **하드웨어 도착 후**:
  - reader로 현재 fader 조회
  - `new_fader = clamp(fader_to_db(current) + clamp(delta) → db_to_fader)`
  - OSC 송신
  - 단위 테스트로 클램프 동작 검증

## 3. FEEDBACK_ALERT / EQ_ADJUST 변환

ADR-0008 §3.2 응답 한도(feedback ≤ 2 dB cut 또는 협대역 notch, EQ ±3 dB).
현재 둘 다 placeholder — `_translate`가 경고 로깅만.

- **블로커**: 
  - Feedback notch는 채널별 EQ 밴드를 *프로그래밍 가능*하게 설정해야 한다 →
    M32 EQ 밴드 OSC 주소·파라미터 매핑이 실 콘솔에서 확정 필요.
  - EQ_ADJUST도 동일.
- **임시 상태**: `MAX_FEEDBACK_CUT_DB = 2.0` 상수만 정의.
- **하드웨어 도착 후**:
  - X32 OSC 사양(`/ch/XX/eq/{band}/g`, `/ch/XX/eq/{band}/f` 등) 검증
  - 캡 적용한 변환 로직 + 테스트

## 4. 롤백 (`POST /control/rollback`)

ADR-0008 §3.6 60초 롤백 윈도우. 최근 자동 액션을 *역으로* 송신.

- **블로커**: 역 OSC는 *이전 상태*를 알아야 만들 수 있다. MUTE↔UNMUTE는 self-inverse
  지만 fader 변경의 역은 "직전 fader 값"이 필요 → 위 #1 reader 필요.
- **임시 상태**: 
  - `runtime/action_history.py::ActionHistory`가 적용된 액션을 60초 윈도우에 보관.
  - `GET /control/recent-actions`로 *조회*만 가능. *실행 취소*는 아직.
- **하드웨어 도착 후**:
  - 액션 적용 직전에 reader로 현재 값을 캡처해 `HistoryEntry`에 저장.
  - 롤백 시 그 값으로 역 OSC 송신.
  - `POST /control/rollback` 엔드포인트 구현.

## 5. 실 audio source 기반 SSE 라운드트립 점검

ADR-0007 frontend 검증의 한 축. 가짜 audio source(시뮬레이션)로도 가능하지만,
현장 운영 시나리오(라이브 service 전체)의 안정성은 실 M32에서만 확인 가능.

- **블로커**: M32 USB 캡처 + 라이브 환경 노이즈·역동성.
- **임시 상태**: 
  - 단위 테스트로 broker·serializer 흐름 검증.
  - 가짜 audio source 시뮬레이션 미구현 (별도 작업으로 가능).
- **하드웨어 도착 후**:
  - 실 service 한 번 가동 후 false positive 비율, 지연, 메모리 사용량 측정.
  - 결과로 ADR-0008의 임의값(50회/service, 5초/채널 등) 재검토.

## 6. ADR-0008 등급 진입 절차의 *실행*

ADR-0008 §4는 dry-run → assist → auto 단계 권장. 실 진입은 service에서 검증해야
함.

- **블로커**: 운영 service.
- **임시 상태**: 정책은 코드에 박혀 있고 모드 전환은 가능. 절차 자체는 운영자가
  수동으로 진행.
- **하드웨어 도착 후**:
  - 1차 service: dry-run 관찰. 알림 vs 운영자 직관 일치율 기록.
  - 결과 정리 → ADR-0008 임의값 보정 또는 신규 ADR 작성.

---

## 진행 원칙 (오프라인 동안)

- ✅ 정책·인프라·테스트는 미리 코드에 박는다.
- ✅ 모든 미적용 경로는 명시적 경고 로깅 + 이 문서 참조.
- ✅ 자동 적용은 *물리적으로* 무력화 — auto 모드라도 delta 경로 미구현이면 무송신.
- ❌ 하드웨어 없이는 검증 불가능한 동작을 임의로 "동작한다"고 표기하지 않는다.
