# `evals/service-cases/` — service wav 회귀 케이스

실 service 녹음 wav를 입력으로, 추천 패턴을 회귀 자산화. WavReplayAudioSource로
*같은 wav*를 재생해 *같은 추천 패턴*이 나오는지 자동 검증.

## YAML 스키마

```yaml
id: my-service-case
description: 자유 텍스트

# 필수
wav_path: ../fixtures/service-20260514.wav  # 케이스 yaml 상대경로 가능
sample_rate: 48000
num_channels: 32

# 옵션
block_size: 512
channel_map_path: ../../config/channels.yaml   # 미지정 시 디폴트
rules_enabled:
  - loudness
  - peak
  - lufs
  - feedback
  - dynamic_range
  - lra
  - phase

# 기대값 — 비어 있으면 *실행 성공*만 검증.
expected:
  min_recommendation_count: 0
  max_recommendation_count: 500
  kinds_present:    # 최소 1개씩 발화돼야
    - info
    - gain_adjust
  kinds_absent:     # 절대 발화되면 안 됨
    - feedback_alert
```

## 케이스 작성 흐름

1. 운영자가 service wav를 `evals/fixtures/`에 추가 (gitignored).
2. 본 디렉토리에 케이스 yaml 작성. expected는 *처음 실행 결과*를 그대로
   박는 게 가장 단순 — "오늘 본 결과가 미래에도 그대로" 회귀 정의.
3. 실행:
   ```bash
   uv run python -m mixpilot.scripts.run_service_replay \
       evals/service-cases/<case>.yaml
   ```
4. 통과하면 그 결과를 baseline으로 git에 commit.

## 첫 케이스: 합성 baseline

`synthetic-multich-baseline.yaml` — `test-multich-4s.wav`(합성 8ch) 재생.
*러너 동작 검증*이 목적, 실 service 패턴은 아님. 합성 1 kHz 톤이 feedback
임계를 초과해 `feedback_alert`가 발화되는 *의도된* 한계도 확인.

## CI 통합

현재는 service wav가 외부 스토리지·gitignored라 CI에서 실행 안 함. 향후
*공개 가능한 합성 회귀*는 CI baseline 셋에 포함 검토.

## 트러블슈팅

- **WAV not found**: `wav_path`가 yaml 상대경로인지 확인. 절대경로 권장 안 함
  (협업자 환경 차이).
- **sample rate mismatch**: WAV의 sample rate(`wavinfo` 또는 `ffprobe`로
  확인)가 yaml의 `sample_rate`와 일치해야. WavReplayAudioSource는 resample
  지원 안 함.
- **추천 폭주**: 합성 wav는 일정 톤이라 feedback·loudness 룰이 자주 발화.
  실 service에서는 정상 패턴. `rules_enabled`를 좁혀서 노이즈 줄이거나
  `max_recommendation_count`를 현실 값으로.
