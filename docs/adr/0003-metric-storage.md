# ADR-0003: 메트릭 저장소 — 현 단계는 JSONL 감사로 충분, 시계열 저장 보류

- 상태: Superseded by [ADR-0010](0010-metric-timeseries-persistence.md) (2026-05-14) — 시계열 UI·운영자 가이드 도입으로 영속화 필요성 확정
- 날짜: 2026-05-14
- 결정자: 차운영(sre), 김설계(architect), 윤분석(data-analyst)
- 관련: ADR-0008(자동 응답 안전 정책)

## Context

MixPilot 처리 루프는 매 프레임 다수의 측정(RMS·LUFS·Peak·Feedback)을 계산하고
규칙으로 추천을 생성한다. 이 데이터를 어떻게 보관할지 결정 필요.

후보:

1. **Prometheus** 시계열 — 운영용 표준. 외부 인프라 필요.
2. **InfluxDB / TimescaleDB** — 시계열 전용 DB. 운영 부담 큼.
3. **로컬 SQLite** — 임베디드, 외부 인프라 없음.
4. **JSONL 감사 로그** (ADR-0008 §3) — 자동 액션 *시도*만 기록.
5. **메모리 + ActionHistory** — 최근 60초 윈도우만 (롤백용).

## Decision

**현 단계는 JSONL 감사 로그 + 메모리 ActionHistory로 충분.** 별도 시계열
저장소는 도입하지 않는다.

근거:
- 1차 운영 단계의 핵심 데이터는 *자동 액션 시도*이며 이는 ADR-0008 §3의 감사
  로그가 모두 캡처한다.
- *측정값 자체*(예: 매 프레임 LUFS)는 양이 막대하며(32ch × ~100 fps = 3200/sec)
  저장 가치는 현재 운영 시나리오에서 명확하지 않다.
- 사후 분석은 audit JSONL을 `jq`·`pandas`로 충분히 가능.
- 실 service 후 *어떤 분석을 원하는지*가 명확해진 뒤 도입이 합리.

## Consequences

✅ 좋은 점
- **외부 인프라 0**: 솔로 운영자의 노트북 한 대로 모든 데이터 자급.
- **운영 부담 최소**: 데이터베이스 백업·튜닝·스키마 마이그레이션 없음.
- **검토 용이**: JSONL은 line-oriented라 `grep`/`jq`/스프레드시트 import 모두 즉시 가능.

⚠️ 트레이드오프
- 시계열 *집계 쿼리*(예: "이번 service 평균 LUFS per category")는 별도 스크립트
  필요. 한 번에 가능하지만 SQL 같은 즉답성 없음.
- 측정값 *원본*(매 프레임 RMS/LUFS)은 보관 안 함. 사후 정밀 분석에는 evals
  fixtures로 재생을 통해 재현.
- audit JSONL은 자동 액션 시도 외 정보는 없음. 운영자 *수동* 조작은 별도로
  기록하지 않음.

## When to revisit

다음 중 하나가 발생하면 본 ADR 재검토:

1. **service 후 회고에서 "OO 메트릭 추이를 보고 싶다"** 같은 구체 요구가 *반복적*으로 등장.
2. **여러 service 비교 분석** 요구 (예: 매월 추세 비교).
3. **운영자가 직접 메트릭 대시보드(Grafana 등)를 통해 모니터링하고 싶어 함**.
4. **자동화의 *효과 측정* 필요** — false positive rate·응답 지연 등 정량 KPI를
   계산해야 정책 튜닝 가능 (ADR-0008 임의값 보정).

위 시점에 후보 재평가. 첫 진입은 **SQLite + JSONL → CSV/Parquet 변환 스크립트**가
유력 — 외부 인프라 없이 분석 가능.

## Implementation notes

- 현재 코드:
  - `infra/audit.py::AuditLogger` — JSONL 자동 액션 감사.
  - `runtime/action_history.py::ActionHistory` — 메모리 60초 윈도우.
  - 둘 다 *자동 액션* 중심. *측정값 시계열*은 미수집.
- 시계열이 필요해지면 추가 옵션:
  - `infra/metrics_sink.py::SQLiteMetricsSink` (예정) — 단순 schema, append-only.
  - 또는 `infra/metrics_sink.py::JsonlMetricsSink` — 측정 자체도 JSONL로.
- ADR-0008 §3.8 감사 로그 위치(`audit_log_path`)와 향후 메트릭 저장소 위치는
  서로 다른 설정으로 분리한다 — 한쪽 비활성·다른쪽 활성 가능하도록.
