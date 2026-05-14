# ADR-0009: LRA (Loudness Range) — 직접 구현, 48 kHz 한정

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 오음파(domain-expert), 김설계(architect), 신속도(performance)
- 관련: ADR-0001(librosa 미도입), ADR-0004(M32 USB 48 kHz)

## Context

EBU R128 / EBU Tech 3342의 **Loudness Range(LRA)** 메트릭은 곡 전체의 단기
LUFS 분포를 LU 단위로 요약한다. 라이브 운영에서는 다음을 가시화하는 데 사용:

- 압축된 소스(LRA < 5 LU) — 라우드니스 워 의심.
- 무압축 소스(LRA > 15 LU) — 페이더 추격이 필요한 dynamic 콘텐츠.

알고리즘 (EBU Tech 3342):

1. K-weighting(고역 강조 + 저역 통과)을 신호 전체에 적용.
2. **3 초** 블록을 **1 초** 간격으로 슬라이드 — short-term loudness 추출.
3. 절대 게이팅: blocks with `L_s < −70 LUFS` 제거.
4. 상대 게이팅: 잔존 blocks의 *power-mean* − 20 LU 미만 추가 제거.
5. LRA = `P_95 − P_10` (LU 단위).

## Decision

**LRA를 직접 구현한다.** `pyloudnorm`의 내부 필터·게이팅 함수에 의존하지
않고, K-weighting과 게이팅 모두 `src/mixpilot/dsp/lra.py`에 명시적으로 작성.

세부 결정:

### 1. K-weighting — 48 kHz 전용 하드코드

BS.1770-4 참조 계수(48 kHz)를 코드에 직접 박는다. 다른 sample rate에서는
`ValueError`를 raise (M32가 48 kHz 고정이므로 운영 경로에서 발생 불가).

```python
# 2-section SOS for scipy.signal.sosfilt
_K_FILTER_SOS_48000 = np.array([
    # Pre-filter (high-shelf ~1.5 kHz, +4 dB)
    [1.53512485958697, -2.69169618940638, 1.19839281085285,
     1.0, -1.69065929318241, 0.73248077421585],
    # RLB (high-pass ~38 Hz)
    [1.0, -2.0, 1.0,
     1.0, -1.99004745483398, 0.99007225036621],
])
```

이유:
- M32 USB는 48 kHz 고정([ADR-0004](0004-audio-input-m32-usb.md)) — 운영 환경에선 다른 rate가 안 들어옴.
- `scipy.signal.bilinear`로 다른 rate 동적 생성 가능하지만 복잡도·테스트 비용 증가.
- 향후 다른 rate 필요해지면 `_design_k_weighting(sample_rate)` 추가 + 본 ADR 갱신.

### 2. 상대 게이트는 power-mean 사용 (EBU Tech 3342 §3.3 정확 준수)

```python
energies = [10 ** (L / 10) for L in above_abs]
power_mean_db = 10 * log10(mean(energies))
relative_gate = power_mean_db - 20
```

단순 산술 평균을 쓰는 구현도 흔하지만, 본 프로젝트는 *측정 정확성* 우선이라
EBU 표준 그대로.

### 3. 백분위는 `numpy.percentile` (linear interpolation)

```python
p10 = np.percentile(survivors, 10)
p95 = np.percentile(survivors, 95)
return p95 - p10
```

표본이 적을 때(예: 6 초 신호 → 4 블록)는 보간 결과가 불안정하지만 표준이
그렇게 정의 — *어느 정도 신호 길이가 필요*하다는 자체가 LRA의 본질.

### 4. 입력 길이 < 3 초이면 `ValueError`

3 초 미만은 단일 블록도 만들 수 없으므로 LRA를 계산할 수 없다. `lufs_integrated`와
동일 정책 — 호출자가 명시적으로 충분한 버퍼를 확보해야.

### 5. 모든 블록이 게이팅으로 제거되면 `0.0` 반환

엄밀하게는 "정의되지 않음"이지만, INFO 알림 룰에서 사용할 수 있게 0.0(=
다이내믹 없음)으로 약속. 호출자가 "신호 너무 조용/단조롭다" 판단 가능.

## Consequences

✅ 좋은 점
- `pyloudnorm` 내부 변경에 영향 받지 않음 — 독립 구현.
- 알고리즘 각 단계를 코드에 명시 → 회귀 추적·교육적 가치 큼.
- BS.1770-4 reference signal로 정확도 검증 가능 (향후 추가).
- 48 kHz만 지원하므로 코드·테스트가 단순.

⚠️ 트레이드오프
- 다른 sample rate 신호를 LRA에 통과시킬 수 없음 — 명시적 raise로 호출자
  실수를 일찍 잡지만, 다른 rate가 들어올 가능성이 있는 시스템에선 사전 resample 필요.
- 정확도 검증은 ITU-R BS.1770-4 / EBU Tech 3341 conformance signals 도입 시점까지
  속성 검증(steady = 0, two-level = level difference) 위주.
- LRA는 *누적 메트릭*이라 라이브 처리 루프에 통합 시 별도 RollingBuffer(>=3s)
  필요. LUFS의 buffer와 공유 가능 여부는 추후 결정.

## When to revisit

다음 중 하나가 발생하면 본 ADR 재검토:

1. **다른 sample rate 입력 필요** — Reaper 프로젝트가 44.1 kHz를 사용하거나
   외부 녹음 import.
2. **conformance test 도입** — ITU-R BS.1770-4 EBU Tech 3341 test signals 회귀 추가.
3. **pyloudnorm IIRfilter 재사용 이득 명확** — 동일 K-weighting을 LUFS·LRA·향후
   다른 메트릭에서 공유 가능해질 때.
4. **정확도 이슈** — 사람의 청취 인상과 LRA 값이 일관 어긋나면 (10 %+ 편차).

## Implementation notes

- `src/mixpilot/dsp/lra.py`:
  - `lra(samples, sample_rate) -> float`
  - 상수: `BLOCK_SECONDS = 3.0`, `HOP_SECONDS = 1.0`, `ABSOLUTE_GATE_LUFS = -70.0`,
    `RELATIVE_GATE_LU = -20.0`, `MIN_DURATION_SECONDS = 3.0`.
- `dsp/__init__.py`에 재노출.
- `evals/cases/lra-baseline.yaml` — steady sine(=0), two-level(≈ level diff),
  silence(=0), too short(raises) 케이스.
- 러너 dispatch + CI 잡 baseline 셋에 추가.
- 라이브 처리 루프 통합은 *별도 커밋* — DSP 함수가 안정된 뒤.
