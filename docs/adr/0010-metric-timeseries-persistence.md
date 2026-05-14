# ADR-0010: 메트릭 시계열 영속화 — JsonlMetricsSink 도입

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 차운영(sre), 김설계(architect), 윤분석(data-analyst)
- 관련: [ADR-0003](0003-metric-storage.md) — 본 ADR이 supersede.

## Context

ADR-0003에서는 *그 시점*의 운영 시나리오로 보아 시계열 저장이 불필요하다고
판단해 JSONL audit log + 메모리 ActionHistory로 충분하다고 결정했음.

그 후 다음 변경이 누적되며 환경이 달라졌다:

- 채널 시계열 UI 도입 (Timeseries.svelte) — 브라우저 메모리 2분 윈도우만 보관.
- 운영자 가이드(`docs/operator-guide.md`)의 *사후 회고 절차*가 명시적 데이터
  자산을 전제.
- 사용자가 "service 후 회고에 시계열이 필요" 명시 — ADR-0003의 재방문 조건
  (§"When to revisit" #1, #3) 충족.

## Decision

**메트릭 시계열을 JSONL로 영속화한다.** `infra/metrics_sink.py::JsonlMetricsSink`
도입.

세부:

- **포맷**: JSONL append. 한 라인 = 한 timestamp의 *모든 채널 스냅샷*. 채널
  별 분리 라인 대비 service 1시간 라인 수가 1/N로 작음(N=채널 수).
- **저장 cadence**: 미터 publish(~9 Hz)와 *별도*. `interval_seconds`로 throttle.
  디폴트 1.0초 → service 1시간 ≈ 3600줄. service 1회 ~수 MB.
- **필드**: channel, rms_dbfs, peak_dbfs, lra_lu, phase_with_pair. `octave_bands_dbfs`
  는 부피 큼(8 float × N ch × 매 라인)이라 *제외*. 향후 별도 sink로 분리 가능.
- **경로 expansion**: AuditLogger와 동일한 strftime — `./logs/metrics-%Y%m%d.jsonl`
  → service 가동 시점에 expand. 운영자가 매 service env 손볼 필요 없음.
- **비활성 시**: `MetricsSinkConfig.enabled=False`(디폴트)면 path=None, 모든
  호출이 no-op. 운영자가 *명시적*으로 켜야 동작 — bandwidth·디스크 안전 디폴트.

## Consequences

✅ 좋은 점
- service 후 회고에서 시계열 추세를 *데이터로* 확인 가능. jq/pandas로 즉시 분석.
- audit log와 *별도 파일* — 두 자산의 lifecycle 분리(audit는 보관, metrics는
  service별 회전).
- write throttle로 디스크 부담 제한 (1 Hz × 32 ch × 1시간 ≈ 7 MB JSONL).
- 같은 strftime 패턴으로 audit/metrics 둘 다 자동 분리 — 운영자 경험 일관.

⚠️ 트레이드오프
- 디스크 사용량 — service 1회 ~수 MB. 장기 누적 시 외부 회전(logrotate) 필요.
- 시계열 *집계 쿼리*(예: "지난 1년 평균 LUFS")는 별도 ingest 필요. 초기엔
  jq/awk로 충분, 규모 커지면 SQLite/Parquet 변환 스크립트.
- octave_bands_dbfs 제외 결정 — 8 float이 30% 이상 부피 차지. 회고 시점에
  필요하면 후속 ADR로 별도 sink.

## When to revisit

- 시계열 분석이 *고빈도*로 필요해지면(매주 trend 비교, 자동 알림 등) DB 검토.
- 운영자가 1초 cadence가 부족하다고 보면 (예: transient 추적용 100 ms) interval 조정.
- 외부 SaaS(Grafana, Datadog) 도입 시 이 sink가 *동시 출력*하는 게 합리적인지.

## Implementation notes

- `infra/metrics_sink.py::JsonlMetricsSink`:
  - `maybe_write(channel_payloads, capture_seq, wall_timestamp=None)` 호출.
    interval 미경과면 no-op, 경과면 한 라인 append.
  - `clock` 의존성 주입으로 결정적 테스트.
- `config.MetricsSinkConfig`: enabled / output_path / interval_seconds.
- `main.py` `_processing_loop` meter publish 위치에서 `metrics_sink.maybe_write()` 동반 호출.
- 호출자(예: service_replay 러너)는 None으로 패스해 영속화 skip 가능.
- HealthResponse.metrics_sink_enabled로 UI에서 노출.
