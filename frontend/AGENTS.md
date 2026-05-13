# frontend/ — MixPilot 운영 대시보드

Svelte 5 + Vite + TypeScript SPA. 백엔드(`/health`, `/recommendations`)를 소비.

루트 [`AGENTS.md`](../AGENTS.md)의 컨텍스트(도메인, M32, 카테고리, 추천 종류,
한국어 컨벤션 등)를 모두 상속한다. 이 문서는 *프론트엔드 특화*만 정리.

## Stack (ADR-0007)

- **언어**: TypeScript (strict).
- **프레임워크**: Svelte 5 (runes). SvelteKit 미사용.
- **빌드**: Vite.
- **API**: 표준 `fetch` + `EventSource`. 별도 클라이언트 라이브러리 없음.
- **상태**: `$state` runes만 사용. 별도 store 라이브러리 없음.
- **스타일**: vanilla CSS (Svelte single-file).

## Commands

| 목적 | 명령 |
|---|---|
| 의존성 설치 | `npm --prefix frontend install` |
| dev 서버 | `npm --prefix frontend run dev` (http://localhost:5173) |
| 빌드 | `npm --prefix frontend run build` → `frontend/dist/` |
| 타입 체크 | `npm --prefix frontend run check` |

## 백엔드 연동

- 디폴트 base URL: `http://localhost:8000` (`src/lib/api.ts`).
- override: 프로젝트 `.env`에 `VITE_API_BASE_URL=...`.
- dev 환경에서는 백엔드 측 `MIXPILOT_DEV_CORS_ENABLED=true` 필요 — 다른 origin이므로.

## Conventions

- **컴포넌트 단위**: `src/{Component}.svelte`. 도메인별 폴더 구조는 컴포넌트가
  10개를 넘기면 도입.
- **타입**: API 응답·요청 타입은 `src/lib/api.ts`에 모아 둔다. 백엔드 도메인
  변경 시 같은 PR에서 함께 갱신.
- **수치 표시 단위**: dBFS / LUFS / Hz 단위는 화면에 반드시 명시. 라이브 운영자는
  단위 혼동이 사고로 직결.
- **한국어 UI**: 운영자가 한국어 사용자.
- **커밋 메시지**: 루트 컨벤션 준수 — type prefix는 영문, 본문은 한국어.

## 향후 도입 검토

- TailwindCSS — 화면 수 10개 이상이면.
- OpenAPI codegen — 타입을 백엔드 `/openapi.json`에서 자동 생성.
- 프로덕션 서빙: FastAPI `StaticFiles`로 `frontend/dist/` 서빙 (별도 ADR).
- 채널별 라이브 미터 (캔버스/SVG 기반) — 현재는 추천 리스트만.

## Notes for AI assistants

- Svelte 5의 **runes**(`$state`, `$derived`, `$effect`)를 사용. 이전 Svelte 4의
  `let`/reactive `$:` 문법과 혼용하지 말 것.
- DOM 직접 조작보다 Svelte의 reactivity를 우선.
- 라이브 데이터 스트림(SSE)은 컴포넌트 `onDestroy`에서 반드시 close — 누수 방지.
