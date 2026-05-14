/**
 * MixPilot 백엔드 API 클라이언트 (얇은 fetch / EventSource 래퍼).
 *
 * 응답 타입은 백엔드 OpenAPI에서 자동 생성 — `api-types.ts`. 수정 금지.
 * 갱신: 백엔드 띄운 상태에서 `npm run gen:api`.
 *
 * 백엔드는 dev 시 별도 포트(http://localhost:8000), 빌드 후에는 같은 origin.
 * VITE_API_BASE_URL을 .env에 설정해 override 가능.
 */

import type { components } from "./api-types";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type RecommendationPayload = components["schemas"]["RecommendationEvent"];
export type ControlResponse = components["schemas"]["ControlResponse"];
export type ActionEntry = components["schemas"]["ActionEntry"];
export type RecentActionsResponse = components["schemas"]["RecentActionsResponse"];
export type MeterSnapshot = components["schemas"]["MeterSnapshotEvent"];
export type ChannelMeter = components["schemas"]["ChannelMeter"];
export type AuditEntry = components["schemas"]["AuditEntry"];
export type AuditLogResponse = components["schemas"]["AuditLogResponse"];
export type ChannelMapEntry = components["schemas"]["ChannelMapEntry"];
export type ChannelMapResponse = components["schemas"]["ChannelMapResponse"];
export type RuleState = components["schemas"]["RuleState"];
export type RulesResponse = components["schemas"]["RulesResponse"];
export type OperatingModeState = components["schemas"]["OperatingModeState"];
export type ReloadResponse = components["schemas"]["ReloadResponse"];

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`/health failed: ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

/** 현재 운영 모드 + 킬 스위치 active 여부. */
export async function fetchOperatingMode(): Promise<OperatingModeState> {
  const response = await fetch(`${API_BASE_URL}/control/operating-mode`);
  if (!response.ok) {
    throw new Error(`/control/operating-mode failed: ${response.status}`);
  }
  return (await response.json()) as OperatingModeState;
}

/** 평상시 운영 모드 토글 — dry-run / assist / auto. */
export async function setOperatingMode(
  mode: string,
): Promise<OperatingModeState> {
  const response = await fetch(`${API_BASE_URL}/control/operating-mode`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(
      `/control/operating-mode failed: ${response.status} ${detail}`,
    );
  }
  return (await response.json()) as OperatingModeState;
}

/** graceful 임계 reload — 새 Settings()를 평가해 라이브 임계·타깃 갱신. */
export async function reloadThresholds(): Promise<ReloadResponse> {
  const response = await fetch(`${API_BASE_URL}/control/reload`, {
    method: "POST",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`/control/reload failed: ${response.status} ${detail}`);
  }
  return (await response.json()) as ReloadResponse;
}

/** ADR-0008 §3 킬 스위치 — controller를 즉시 dry-run으로 다운그레이드. */
export async function forceDryRun(): Promise<ControlResponse> {
  const response = await fetch(`${API_BASE_URL}/control/dry-run`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`/control/dry-run failed: ${response.status}`);
  }
  return (await response.json()) as ControlResponse;
}

/** 최근 적용된 자동 액션 이력 — ADR-0008 §3.6. */
export async function fetchRecentActions(): Promise<RecentActionsResponse> {
  const response = await fetch(`${API_BASE_URL}/control/recent-actions`);
  if (!response.ok) {
    throw new Error(`/control/recent-actions failed: ${response.status}`);
  }
  return (await response.json()) as RecentActionsResponse;
}

/** 룰 토글 상태 — service 도중 운영자가 즉시 켜고 끔. */
export async function fetchRules(): Promise<RulesResponse> {
  const response = await fetch(`${API_BASE_URL}/control/rules`);
  if (!response.ok) {
    throw new Error(`/control/rules failed: ${response.status}`);
  }
  return (await response.json()) as RulesResponse;
}

/** 단일 룰 켜기/끄기 — 다음 frame부터 즉시 반영. */
export async function setRuleEnabled(
  rule: string,
  enabled: boolean,
): Promise<RuleState> {
  const response = await fetch(`${API_BASE_URL}/control/rules/${rule}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(
      `/control/rules/${rule} failed: ${response.status} ${detail}`,
    );
  }
  return (await response.json()) as RuleState;
}

/** 현재 채널맵 — config/channels.yaml의 현재 내용. */
export async function fetchChannelMap(): Promise<ChannelMapResponse> {
  const response = await fetch(`${API_BASE_URL}/channels`);
  if (!response.ok) {
    throw new Error(`/channels failed: ${response.status}`);
  }
  return (await response.json()) as ChannelMapResponse;
}

/** 단일 채널 매핑 갱신 — YAML 영속 + 라이브 처리 루프 다음 frame부터 즉시 반영. */
export async function updateChannel(
  channel: number,
  category: string,
  label: string,
  stereoPairWith: number | null = null,
): Promise<ChannelMapEntry> {
  const response = await fetch(`${API_BASE_URL}/channels/${channel}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      category,
      label,
      stereo_pair_with: stereoPairWith,
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`/channels/${channel} failed: ${response.status} ${detail}`);
  }
  return (await response.json()) as ChannelMapEntry;
}

/** 감사 로그 JSONL의 최근 레코드 — ADR-0008 §3 영구 이력. */
export async function fetchAuditLog(
  limit: number = 50,
): Promise<AuditLogResponse> {
  const response = await fetch(
    `${API_BASE_URL}/control/audit-log/recent?limit=${limit}`,
  );
  if (!response.ok) {
    throw new Error(`/control/audit-log/recent failed: ${response.status}`);
  }
  return (await response.json()) as AuditLogResponse;
}

/**
 * /recommendations SSE 구독.
 * onMessage: 추천 페이로드를 받았을 때.
 * onError: 연결 오류 / 끊김.
 * 반환값: 정리 함수(연결 종료).
 */
export function subscribeRecommendations(
  onMessage: (rec: RecommendationPayload) => void,
  onError?: (err: Event) => void,
): () => void {
  const source = new EventSource(`${API_BASE_URL}/recommendations`);
  source.addEventListener("message", (event) => {
    try {
      const data = JSON.parse(event.data) as RecommendationPayload;
      onMessage(data);
    } catch (e) {
      console.warn("invalid recommendation payload", event.data, e);
    }
  });
  if (onError) {
    source.addEventListener("error", onError);
  }
  return () => source.close();
}

/** /meters SSE 구독 — 채널별 RMS·peak dBFS 스냅샷. */
export function subscribeMeters(
  onMessage: (snapshot: MeterSnapshot) => void,
  onError?: (err: Event) => void,
): () => void {
  const source = new EventSource(`${API_BASE_URL}/meters`);
  source.addEventListener("message", (event) => {
    try {
      const data = JSON.parse(event.data) as MeterSnapshot;
      onMessage(data);
    } catch (e) {
      console.warn("invalid meter payload", event.data, e);
    }
  });
  if (onError) {
    source.addEventListener("error", onError);
  }
  return () => source.close();
}
