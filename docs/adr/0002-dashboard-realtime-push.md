# ADR-0002: 대시보드 실시간 push — Server-Sent Events (SSE) 채택

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 김설계(architect), 이선두(frontend), 박후방(backend)
- 관련: ADR-0007(프론트엔드 스택)

## Context

MixPilot 운영 대시보드는 백엔드에서 *추천(Recommendation) 이벤트*를 실시간으로
받아 표시해야 한다. 후보:

1. **Server-Sent Events (SSE)** — HTTP `text/event-stream`. 서버 → 클라이언트 단방향.
2. **WebSocket** — 양방향 전이중. 프레임 기반.
3. **Long polling** — 클라이언트 반복 요청. 레거시 대안.

## Decision

**SSE 채택.** 백엔드는 `/recommendations` 엔드포인트에서 `StreamingResponse`로
이벤트를 송출하고, 프론트엔드는 `EventSource` API로 구독.

```
백엔드: FastAPI StreamingResponse + text/event-stream
프론트:  EventSource("/recommendations") → onMessage
```

## Consequences

✅ 좋은 점
- **단방향에 충분**: 추천 이벤트는 서버 → 클라이언트 단방향. 양방향 불필요.
- **HTTP 위에서 동작**: 별도 upgrade·핸드셰이크·프로토콜 협상 없음. CORS·인증
  헤더·캐싱 정책이 일반 HTTP와 동일.
- **자동 재연결**: 브라우저 `EventSource`가 끊기면 자동 재연결 + `Last-Event-ID`
  지원. 클라이언트 코드 부담 없음.
- **HTTP/2 친화**: HTTP/2 다중화로 한 connection에서 다른 요청과 공존.
- **OpenAPI 명세**: 응답 타입을 `text/event-stream`으로 등록 → 프론트 타입
  자동 생성 (codegen이 정상 처리).
- **FastAPI 네이티브**: `StreamingResponse` + 비동기 generator로 자연스럽게 구현.
- **운영자 디버깅**: `curl -N`으로 손쉽게 이벤트 확인 가능 (실제로 본 프로젝트
  스모크 테스트에 사용 중).

⚠️ 트레이드오프
- **단방향**: 클라이언트 → 서버 *제어*는 별도 REST 엔드포인트(`POST /control/*`)로
  처리. 양방향이 필요해지면 마이그레이션 필요.
- **텍스트 전용**: 바이너리 페이로드 불가능 — JSON 직렬화 필요. 우리 페이로드는
  텍스트라 무관.
- **proxy/방화벽 버퍼링**: 일부 reverse proxy가 응답을 버퍼링할 수 있어 이벤트
  지연 가능. 운영 시 nginx의 `proxy_buffering off` 등 설정 필요.

## Alternatives considered

- **WebSocket**: 양방향이 필요할 때 매력적. 우리는 단방향만 필요해 오버헤드만
  추가됨. 또한 자동 재연결 라이브러리 추가 필요. 채택 안 함.
- **Long polling**: HTTP 요청 누적, 지연 큼, 운영자 디버깅 어려움. 최신 대안 있는
  데 굳이 선택할 이유 없음.
- **WebTransport / WebRTC**: 미래지향이지만 브라우저 지원·운영 도구 미성숙. 우리
  스케일에 과함.

## When to revisit

- 클라이언트 → 서버 *실시간* 명령 흐름이 필요해지면 (예: 라이브 채널 핫키 매핑).
  현재는 `POST /control/*` REST로 충분.
- 페이로드가 *바이너리* 또는 *매우 큰 텍스트*가 되면 (오디오 파형 직접 push 등).
- 단일 서버가 *수만 동시 구독자*를 다뤄야 하면 (현재 솔로 운영자 1~수명 수준).

## Implementation notes

- `/recommendations` 엔드포인트: `responses={200: {"model": RecommendationEvent,
  "content": {"text/event-stream": {}}}}` 로 OpenAPI 등록 (ADR-0007 codegen 호환).
- 이벤트 포맷: `data: <json>\n\n` 표준 SSE.
- 첫 이벤트는 `event: subscribed\ndata: {}\n\n` 마커 — 클라이언트 구독 성립 확인용.
- 15초마다 `: keep-alive\n\n` 코멘트 송신 — proxy idle timeout 방지.
- 백엔드 측은 `RecommendationBroker`가 in-memory pub/sub로 fan-out.
