# 운영자 가이드

MixPilot를 *실 service*(예배·공연)에서 운영하는 사람을 위한 절차서.
개발자가 아닌 음향 운영자 기준 — 코드 모르고도 따라할 수 있게.

> 처음 사용이라면 [README](../README.md)의 빠른 시작으로 의존성 설치 +
> dry-run 모드 가동을 먼저 확인하세요. 본 문서는 *서버가 뜨고 UI가 보이는*
> 상태에서 시작합니다.

## 1. 시작 전 체크리스트

service 시작 *최소 30분 전*에 모두 확인하세요.

### 하드웨어
- [ ] M32 USB 케이블 노트북에 연결 — `arecord -l` (Linux) / `오디오 MIDI 설정`(macOS)에 M32 보임
- [ ] M32 sample rate **48 kHz** (이외는 미지원)
- [ ] M32와 노트북이 같은 LAN — OSC 제어 시(`MIXPILOT_M32__HOST`) ping 가능

### 노트북 가동
- [ ] 전원 충전기 연결 (배터리만으론 service 도중 위험)
- [ ] 화면 자동 잠금 OFF — `caffeinate -dim` (macOS) 또는 시스템 설정
- [ ] CPU 모니터 한 번 확인 — MixPilot이 정상 가동 시 50% 미만이어야

### 서버 가동

service 종류에 맞는 프리셋으로:

```bash
# 예배
uv run python -m mixpilot.scripts.serve --preset worship

# 공연
uv run python -m mixpilot.scripts.serve --preset performance

# 리허설 (feedback만, 그 외 알림 최소)
uv run python -m mixpilot.scripts.serve --preset rehearsal
```

프론트엔드(다른 터미널):
```bash
npm --prefix frontend run dev
```

브라우저: http://localhost:5173

### 첫 화면 확인
- [ ] **상태 카드**: 운영 모드(예배=`assist`, 공연=`dry-run`), 오디오 캡처 *활성*, 미터 스트림 *활성*
- [ ] **채널 매핑**: M32 채널 라벨이 정확. 다르면 인-라인 편집(저장 즉시 반영)
- [ ] **라이브 미터**: 채널들의 RMS 막대가 움직임 — 신호가 들어옴

신호가 안 들어오면: M32 USB 연결 / 채널 활성 / 시스템 오디오 권한 차례로 확인.

---

## 2. service 흐름

### service 시작 (5분 전)

1. 마이크·소스를 *각자 가벼운 소리로 한 번씩* 체크 — 미터에 신호 들어오는지 시각 확인
2. **채널 시계열 카드**: 첫 채널 자동 선택됨. 30s 윈도우로 두면 최근 변동이 보임
3. **룰 토글 카드**: 디폴트(프리셋이 정한) 그대로 두면 됨. service 중 noise가 많은 룰 끄기 가능

### service 중

운영자는 *기본적으로 화면을 본다*. MixPilot은 *조언자*이지 *대체자*가 아님.

**상시 모니터링**
- **라이브 미터**: 채널이 적색(>-1 dBFS)으로 가면 즉시 페이더 내림
- **추천 스트림** (우상단): 새 알림이 깜박이면 클릭해서 사유 확인
- **채널 시계열**: 의심 채널 선택해두면 트렌드 추적

**알림 종류별 대응**

| 종류 | 의미 | 1차 대응 |
|---|---|---|
| 정보 (정보, RMS/LUFS) | 카테고리 타깃 라우드니스 ±2dB 벗어남 | 페이더로 조정 (assist 모드면 자동 진행) |
| 게인 (gain_adjust) | 시스템이 자동 보정 권장 | assist면 자동 적용됨. auto면 적용 후 알림 |
| 하울링 (feedback_alert) | 특정 주파수 PNR 임계 초과 + 지속 | EQ로 해당 주파수 cut. 즉시 |
| 정보 (DR/LRA/phase) | 압축·다이내믹 폭·stereo phase 이상 | 운영자 판단 — 즉시 대응 필요 없음 |

**의심스러우면 킬 스위치**

추천이 의심스럽거나 시스템이 이상 동작하면 **🛑 자동 응답 정지** 버튼.
- 즉시 dry-run으로 다운그레이드 — 모든 자동 OSC 송신 차단
- 운영자가 직접 콘솔 제어
- 프로세스 재시작 전까지 유지
- 잘못 누르면 손해 없음 (수동 운영으로 회귀일 뿐)

### service 끝 (10~15분 후)

1. **감사 로그 카드** 확인 — service 동안 자동 적용된 액션·차단된 시도
   - "차단" 다수면 임계가 너무 보수적이거나 정책에 문제 있음
   - "적용" 다수면 시스템이 활발히 보정 — 운영자가 사후 검토
2. **추천 스트림 비우기** — 다음 service를 깨끗하게
3. **시계열 캡처** (선택) — 회고용으로 브라우저 스크린샷
4. **서버 종료** — Ctrl+C 두 번 (백엔드 + 프론트엔드)

---

## 3. UI 카드 — 1줄 역할

| 카드 | 역할 | 운영 중 보는 빈도 |
|---|---|---|
| 상태 | 모듈별 활성/비활성 | service 시작 시 1회 |
| 채널 매핑 | M32 채널 → 카테고리·라벨 | service 시작 시 + 변경 시 |
| 룰 토글 | 룰 6+1종 즉시 켜고 끔 | 노이즈 많을 때 |
| 라이브 미터 | RMS·Peak·LRA·옥타브·phase | **항상** |
| 채널 시계열 | 한 채널의 RMS·Peak 시간 흐름 | 의심 채널 추적 시 |
| 킬 스위치 | 자동 액션 즉시 정지 | 비상시 |
| 최근 자동 액션 | 60초 윈도우 메모리 | 알림 발생 직후 |
| 감사 로그 | JSONL 영구 이력(검색·필터) | service 후 회고 |
| 추천 스트림 | 룰 발화 알림 (필터·비우기) | **항상** |

---

## 4. 트러블슈팅

### 미터가 비어있음
- M32 USB 인식 확인
- `MIXPILOT_AUDIO__SOURCE=synthetic`인지 확인 (합성 모드면 sounddevice 안 씀)
- `MIXPILOT_AUDIO__NUM_CHANNELS`가 M32의 실 채널 수와 일치하는지

### 추천이 너무 많이 떠서 노이즈
- **룰 토글**에서 발화 많은 룰 일시 OFF
- 또는 **추천 스트림 비우기** 자주
- service 후 감사 로그에서 패턴 찾기

### 자동 액션이 콘솔에 안 보임
- 운영 모드 확인: `dry-run`이면 *송신 안 함*이 정상
- M32 OSC IP·포트(`MIXPILOT_M32__HOST/PORT`) 확인
- 감사 로그에서 `blocked_policy` 또는 `blocked_guard`로 잡혔는지

### 시스템이 느려짐
- CPU 사용률 확인 — 32채널 + 모든 룰 ON이면 부담 큼
- LRA·DR처럼 부하 큰 룰을 OFF
- 미터 publish 간격 늘리기: `MIXPILOT_METER_STREAM__PUBLISH_INTERVAL_FRAMES=10`

### 채널맵 변경이 안 보임
- "새로고침" 버튼 누름 — yaml 외부 편집했을 때 필요
- UI 인-라인 편집은 즉시 반영 (재시작 불필요)

---

## 5. 자주 쓰는 환경 변수

전체 목록은 [`.env.example`](../.env.example). 운영 중 자주 손대는 것만:

```bash
# 음향 환경별 카테고리 타깃 (LUFS 기준, dB)
MIXPILOT_LUFS__VOCAL=-16.0
MIXPILOT_LUFS__PREACHER=-18.0

# Feedback 민감도 (낮을수록 민감, 12-20 권장)
MIXPILOT_FEEDBACK_ANALYSIS__PNR_THRESHOLD_DB=15.0

# Peak 헤드룸 (0보다 작아야)
MIXPILOT_PEAK_ANALYSIS__HEADROOM_THRESHOLD_DBFS=-1.0

# 감사 로그 파일 위치 (service별 분리 권장)
MIXPILOT_AUDIT_LOG_PATH=./logs/audit-$(date +%Y%m%d).jsonl
```

---

## 6. 사후 회고 절차 (service 끝난 다음 날)

1. `logs/audit-YYYYMMDD.jsonl` 열기 (또는 UI 감사 로그 검색)
2. 다음 질문 답:
   - `applied` 액션 중 *부적절했던 것* 있나? → 임계 조정 검토
   - `blocked_guard` 다수? → rate limit 설정이 너무 빡빡한지
   - `blocked_policy` 다수? → confidence threshold 조정
3. 다음 service 전에 환경 변수 조정 또는 프리셋 yaml 수정
4. 변경이 크면 `evals/fixtures/`에 service 녹음 wav 추가 → 회귀 검증 자산화

> **시계열 자산화** (선택): `MIXPILOT_METRICS_SINK__ENABLED=true` +
> `MIXPILOT_METRICS_SINK__OUTPUT_PATH=./logs/metrics-%Y%m%d-%H%M%S.jsonl`로
> 가동하면 채널별 RMS·Peak·LRA·Phase가 1초마다 JSONL로 누적. service 후
> `jq` / pandas로 트렌드 분석 가능 (ADR-0010).

### 4-1. service wav 회귀 자산화 (선택)
Reaper로 service를 다채널 녹음했다면:

```bash
# 1. wav를 evals/fixtures/에 복사 (gitignore — commit 안 됨)
cp ~/Music/Reaper/service-20260514.wav evals/fixtures/

# 2. 회귀 케이스 yaml 작성 (evals/service-cases/README.md 참조)
# 3. 실행
uv run python -m mixpilot.scripts.run_service_replay \
    evals/service-cases/service-20260514.yaml
```

처음 실행 결과를 expected에 박으면 "오늘 본 결과가 미래에도 그대로"가
회귀 정의가 됩니다. 다음 service 전 코드 변경 후 같은 케이스를 돌려 의도치
않은 변화 즉시 감지.

---

## 7. 비상 시

- **하울링 폭주**: 킬 스위치 → M32에서 직접 페이더 + EQ 컷 → MixPilot 재시작
- **자동 액션 잘못된 채널에 적용**: 킬 스위치 → 콘솔에서 수동 복구 → 채널 매핑 확인 후 재시작
- **노트북 freeze**: M32 USB 분리 → 노트북 재부팅 → 콘솔만으로 service 계속 (MixPilot 없이도 service는 굴러간다 — 어디까지나 보조)

---

## 부록 — 빠른 명령 모음

```bash
# 가동 (프리셋)
uv run python -m mixpilot.scripts.serve --preset worship

# 사용 가능한 프리셋 보기
uv run python -m mixpilot.scripts.serve --list-presets

# 직접 환경 변수로 가동 (개별 제어)
MIXPILOT_AUDIO__ENABLED=true MIXPILOT_AUDIO__SOURCE=sounddevice \
  uv run uvicorn mixpilot.main:app --host 0.0.0.0 --port 8000

# 합성 테스트 (M32 미연결)
MIXPILOT_AUDIO__ENABLED=true MIXPILOT_AUDIO__SOURCE=synthetic \
MIXPILOT_AUDIO__NUM_CHANNELS=8 MIXPILOT_METER_STREAM__ENABLED=true \
  uv run uvicorn mixpilot.main:app --port 8000

# 프론트엔드
npm --prefix frontend run dev
```

문제 발생 시 `/Users/<you>/Documents/workspace/test`의 GitHub Issue로 보고 권장 — 재현 환경 변수와 함께.
