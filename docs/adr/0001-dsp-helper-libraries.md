# ADR-0001: DSP 보조 라이브러리 — librosa 미도입, numpy + scipy + pyloudnorm로 충분

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 오음파(domain-expert), 김설계(architect), 신속도(performance)
- 관련: ADR-0004(오디오 입력)

## Context

MixPilot의 DSP 계층은 RMS / LUFS / Peak / Feedback 4종을 지원한다. 각 함수가
현재 사용 중인 보조 라이브러리:

| DSP | 의존 라이브러리 |
|---|---|
| `dsp.rms` | numpy |
| `dsp.peak` (true peak) | numpy, scipy.signal.resample_poly |
| `dsp.lufs` | pyloudnorm (numpy/scipy 기반) |
| `dsp.feedback` | numpy (rFFT) |

별도로 [librosa](https://librosa.org)를 도입할지 검토했다. librosa는 음악 정보
검색(MIR) 영역의 고수준 라이브러리로 다음과 같은 기능 제공:

- 비트 트래킹·템포 추정
- MFCC·스펙트럴 피처
- 피치 검출(yin, pYIN)
- 소스 분리 보조(HPSS)
- 멀로그래프(mel-spectrogram)

## Decision

**librosa는 도입하지 않는다.** 현재 4종 DSP는 모두 `numpy` + `scipy.signal`
+ `pyloudnorm` 조합으로 충분히 구현 가능하며, 결과적으로 의존성 트리가 작아
설치 시간·디스크 사용량·배포 이미지 크기 모두에서 유리하다.

## Consequences

✅ 좋은 점
- **의존성 최소화**: librosa는 numpy/scipy/scikit-learn/audioread/lazy_loader 등
  다수 트랜시티브를 끌고 온다. 우리 패키지의 `uv.lock`이 단순.
- **빌드·배포 가벼움**: 도커 이미지 또는 임베디드 배포에서 ~100 MB 절감.
- **결정성·테스트성**: 우리가 직접 numpy로 짠 함수는 동작이 명시적이고, 단위 테스트로 모든 경계 검증 가능 (`dsp.rms` 등). librosa는 내부 휴리스틱이 많아 회귀 추적이 어렵다.
- **실시간 적합성**: librosa의 일부 함수는 batch/오프라인 가정. MixPilot의
  *라이브 프레임 단위* 분석에는 별로 맞지 않는다.

⚠️ 트레이드오프
- 음악 분석(피치·MFCC·소스 분리) 기능이 필요해지면 직접 구현하거나 librosa를
  다시 검토해야 한다. 그러나 *현재 도메인*(라이브 운영 알림·자동화)에는 그런
  기능이 없다.
- 자체 구현 = 우리 책임. 학술 알고리즘 변경에 즉시 따라가기 어려움.

## When to revisit

다음 중 하나가 발생하면 본 ADR을 재검토한다:

1. **피치 기반 룰 필요** — 예: 보컬 음정 안정성 모니터, 악기 튜닝 검증.
2. **소스 분리** — 한 채널에 여러 소스가 섞여 있을 때 분리해서 분석.
3. **음악적 컨텍스트 인식** — 곡 구조(verse/chorus) 자동 감지로 카테고리별
   임계 동적 조정.
4. **MFCC/임베딩 기반 분류** — ML 모델로 카테고리 자동 인식.

이 중 하나라도 *실제 운영 요구로* 등장하면 librosa 또는 다른 후보(예:
`torchaudio`, `essentia`)를 다시 평가한다. 그 시점에서 import 비용·라이브러리
선택을 ADR-0009 이후로 새 ADR 작성.

## Alternatives considered

- **librosa 부분 도입**: librosa의 *일부* 함수만 사용. 의존성을 줄이지 못해
  실익 없음 (librosa는 모듈 import 시 트랜시티브를 모두 끌어옴).
- **essentia**: C++ 백엔드 + Python 바인딩으로 성능은 좋지만 macOS 빌드 휴대성
  떨어짐. 우리 운영 환경(개인 노트북)에는 과한 부담.
- **자체 알고리즘 패키지화**: 우리 함수들을 별도 라이브러리로 분리. 솔로 개발
  단계에서 분리 비용 > 이득. 후일 재고.

## Implementation notes

- `pyproject.toml`에 librosa 의존성 추가 *금지*.
- 새 DSP 추가 시 numpy/scipy 우선. 그것으로 안 되면 본 ADR 재검토 후 결정.
- `dsp/__init__.py` 의 재노출 심볼 목록은 librosa 의존이 없음을 보장.
