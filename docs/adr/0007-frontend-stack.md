# ADR-0007: 프론트엔드 — Svelte + Vite (vanilla SPA), 같은 레포 monorepo

- 상태: Accepted
- 날짜: 2026-05-14
- 결정자: 최도안(designer), 이선두(frontend), 김설계(architect)
- 관련: ADR-0004, ADR-0005

## Context

MixPilot 운영 대시보드가 필요하다. 라이브 환경에서 운영자가:
- 채널별 라우드니스(RMS / LUFS) 미터
- 추천(Recommendation) 스트림 — 특히 FEEDBACK_ALERT
- M32 운영 모드와 헬스 상태

를 시각적으로 확인할 수 있어야 한다. 백엔드는 이미 `/health`와
`/recommendations` (SSE)를 노출 중.

## Decision

1. **레포 구성**: 별도 레포가 아니라 **같은 레포 안에 `frontend/` 디렉토리**
   (monorepo 스타일). API 변경과 UI 갱신을 한 PR로 묶을 수 있어 솔로 개발
   단계에 적합. 팀이 커지면 분리 가능 — 합치는 것보다 쉬움.

2. **프레임워크**: **Svelte 5 + Vite** (vanilla SPA, **SvelteKit 미사용**).
   - SSR 불필요 (로컬 라이브 콘솔 옆 노트북에서만 띄움).
   - 라이브 미터·SSE 스트림 같은 *fine-grained reactivity*에 Svelte가 강함.
   - 번들 작고 빌드 빠름 — 의존성 미니멈.

3. **언어**: TypeScript. OpenAPI 자동 타입 생성과 결합 예정.

4. **API 클라이언트**: 표준 `fetch` + `EventSource`. 별도 라이브러리 회피.

5. **상태 관리**: Svelte의 store ($state runes / writable). 별도 상태 라이브러리 없음.

6. **스타일링**: 첫 단계는 vanilla CSS. 페이지가 늘면 TailwindCSS 도입 검토.

## Consequences

✅ 좋은 점
- 백엔드/프론트가 한 곳 — API 스키마 변경이 동시에 추적됨.
- AGENTS.md / ARCHITECTURE.md를 단일 소스로 유지.
- Svelte의 적은 보일러플레이트 → 솔로 개발 부담 적음.
- Vite 빌드 산출물을 프로덕션에서 FastAPI가 직접 서빙 가능 (CORS 불필요).

⚠️ 트레이드오프
- Python + Node 두 생태계가 한 레포에 공존 — 신규 기여자 진입 비용.
- Svelte 5 runes는 비교적 새 문법 — 학습 곡선 (다만 짧음).
- SvelteKit 생태계의 라우터·SSR·Adapter 등은 못 씀 — 필요하면 추후 마이그레이션.

## Alternatives considered

- **React + Vite**: 가장 대중적이지만 라이브 미터링에는 useState/useEffect의
  렌더링 모델이 무거움. 컴포넌트 수 늘면 보일러플레이트 부담.
- **SvelteKit**: SSR·라우팅 기능이 풍부하지만 우리 시나리오(로컬 SPA)에는 과함.
- **별도 레포**: 솔로 단계에서 동기화 비용이 큼. 팀 커지면 재고.
- **htmx + Jinja**: FastAPI 서버 사이드 렌더 — 라이브 SSE 다중 미터에는 reactivity
  부족.

## Implementation notes

- 위치: `frontend/` (레포 루트 직속).
- 패키지 매니저: pnpm/npm 중 npm 디폴트(전역 설치 부담 회피).
- 백엔드 dev: `MIXPILOT_DEV_CORS_ENABLED=true` 설정 시 `http://localhost:5173`
  허용.
- 빌드: `npm --prefix frontend run build` → `frontend/dist/`.
- 프로덕션: FastAPI `StaticFiles`로 `frontend/dist/` 서빙 — 향후 ADR.
