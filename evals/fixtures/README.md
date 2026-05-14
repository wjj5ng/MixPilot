# `evals/fixtures/` — 표준 신호 및 service 녹음 wav

## 자동 생성 신호

`generate_test_wavs.py`로 재생성 가능 (작은 합성 신호, git ignored):

```bash
uv run python evals/fixtures/generate_test_wavs.py
```

생성물:
- `test-1khz-mono-2s.wav` — 1 kHz 모노 2초, amp 0.3
- `test-multich-4s.wav` — 8채널 4초, 반음 계단 amp 0.05~0.4

이건 *러너 동작 검증*용. 실 service 신호와 다름.

## 실 service 녹음 (운영자 제공)

운영자가 service를 Reaper로 녹음한 다채널 wav를 본 디렉토리에 추가하면
회귀 검증 자산이 된다.

**제출 절차**:

1. **녹음**: Reaper에서 M32 USB 입력 32ch를 *각 채널별 분리 트랙*으로 녹화
   (단일 multichannel wav가 가장 사용하기 쉬움 — Reaper 메뉴: File → Render
   → "Multichannel" 옵션).
2. **파일명**: `service-YYYYMMDD-<짧은 설명>.wav` 형식 권장
   (예: `service-20260514-sunday-morning.wav`).
3. **포맷**: 48 kHz, float32 또는 int24. M32 sample rate와 일치해야 함.
4. **크기**: 30분 이상이면 git에 직접 commit하지 말고 외부 스토리지
   (S3·Dropbox·git-lfs) 분리. `.gitignore`에 `evals/fixtures/*.wav`가
   포함되어 있어 commit되지 않음.
5. **회귀 케이스 작성**: `evals/service-cases/<file>.yaml` 작성
   ([스키마는 service-cases/README.md](../service-cases/README.md) 참조).

**라이센스·프라이버시**:

- 운영자가 직접 녹음한 service 신호 — 교회·공연장 사전 동의 확인.
- 발성·노래는 인물 식별 가능. 공개 저장소에 *commit하지 말 것* (gitignore 됨).
- 음향 분석 자산화 외 다른 용도 사용 금지.

## 회귀 실행

```bash
# 단일 케이스
uv run python -m mixpilot.scripts.run_service_replay \
    evals/service-cases/service-20260514.yaml

# 여러 개
uv run python -m mixpilot.scripts.run_service_replay \
    evals/service-cases/*.yaml

# JSON 출력 (CI 친화)
uv run python -m mixpilot.scripts.run_service_replay \
    --json evals/service-cases/case.yaml | jq .
```
