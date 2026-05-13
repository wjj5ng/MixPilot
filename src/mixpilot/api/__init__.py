"""MixPilot API 레이어 — FastAPI 라우터·요청·응답 스키마.

ARCHITECTURE.md 규약: 도메인 로직은 직접 구현하지 않는다 — 항상 `rules/`/`dsp/`
또는 `infra/`(어댑터)에 위임. 여기는 HTTP·SSE 표면만.
"""
