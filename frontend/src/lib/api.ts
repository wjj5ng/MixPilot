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

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`/health failed: ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
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
