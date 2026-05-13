# ADR-0004: 오디오 입력 — M32 USB 직접 캡처 (sounddevice)

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 오음파(domain-expert), 김설계(architect)
- 관련: ADR-0005, ADR-0006

## Context

MixPilot은 라이브 음향 운영(예배·공연) 환경의 다채널 입력을 실시간 분석한다. 운영 현장 콘솔은 **Behringer/Midas M32**로 확정되었으며, 표준 32-in / 32-out USB 오디오 인터페이스를 내장한다.

비교한 경로:
1. **가상 오디오 디바이스 경유** (BlackHole/ReaRoute → MixPilot) — Reaper나 다른 DAW를 통해 라우팅
2. **M32 USB 직접 캡처** (M32 → sounddevice → MixPilot)
3. **AES50/Dante 네트워크 캡처** (전용 카드 + 별도 캡처 소프트웨어)

## Decision

**M32 USB를 `sounddevice` 라이브러리로 직접 캡처한다.** 32채널이 단일 multichannel 디바이스로 노출되며, OS의 표준 오디오 API(CoreAudio/ASIO)로 접근.

## Consequences

✅ 좋은 점
- 추가 라우팅 소프트웨어 불필요 — 운영 환경 변수 감소
- 가장 짧은 신호 경로 → 지연 최소화 (M32 내부 0.8ms + USB 버퍼)
- DAW가 죽어도 분석 경로 무관
- Reaper가 보조 도구로 분리됨 (ADR-0006)

⚠️ 트레이드오프
- USB 1개 점유 — Reaper와 동시 사용은 OS 드라이버에 종속될 수 있음(macOS Aggregate Device, Windows 다중 어플리케이션 점유 정책)
- 32채널 처리량을 클라이언트(MixPilot 호스트)가 전부 부담
- USB 버스 안정성에 종속 (드롭아웃 방지 위해 USB 허브 회피·전용 포트 권장)

## Alternatives considered

- **BlackHole/ReaRoute 경유**: 추가 컴포넌트가 끼어 디버깅 면이 늘고 지연 증가. 향후 다른 시나리오에서 필요해지면 옵션으로 남기되 기본 경로는 아니다.
- **AES50/Dante**: 전용 카드 비용 + 별도 캡처 도구. 단일 노트북 운영을 가정한 초기 단계에는 과한 투자. 트래픽이 늘어나면 재검토.

## Implementation notes

- 어댑터: `infra/audio_capture.py::SoundDeviceAudioSource`
- 추상 포트: `domain/ports.py::AudioSource`
- 디바이스 선택은 `config.py`(또는 `config/audio.yaml`)에서 디바이스명 substring 매칭(예: `"M32"` / `"X32"`)
- 버퍼·블록 크기는 측정 후 조정(초기 권장: 256–512 samples @ 48 kHz)
- 회귀 검증: `evals/fixtures/`의 알려진 신호를 M32 입력으로 재생 후 동일 출력 확인 (Virtual Soundcheck로 가능 — ADR-0006)
