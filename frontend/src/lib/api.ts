/**
 * MixPilot 백엔드 API 클라이언트 (얇은 fetch / EventSource 래퍼).
 *
 * 백엔드는 dev 시 별도 포트(http://localhost:8000), 빌드 후에는 같은 origin.
 * VITE_API_BASE_URL을 .env에 설정해 override 가능.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  operating_mode: string;
  sample_rate: number;
  num_channels: number;
  audio_enabled: boolean;
  lufs_analysis_enabled: boolean;
  feedback_analysis_enabled: boolean;
}

export interface RecommendationPayload {
  channel: number;
  category: string;
  label: string;
  kind: string;
  params: Record<string, number>;
  confidence: number;
  reason: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`/health failed: ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
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
