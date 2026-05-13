# Architecture

<!-- TODO: 채워야 의미가 있는 문서입니다. 각 섹션의 TODO 마커를 채워주세요. -->

## 모듈 경계

| 모듈 | 책임 | 의존 허용 | 의존 금지 |
|---|---|---|---|
| <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

## 의존성 방향

권장 시작점 (Clean / Hexagonal):

```
interface  →  application  →  domain
infra      →  application  →  domain
```

- 외곽(interface/infra) → 내부(domain) 방향만 허용.
- **도메인은 프레임워크에 의존하지 않는다.**
- 같은 레이어 안에서의 순환 의존도 금지.

<!-- TODO: 프로젝트에 맞게 수정 -->

## 수정 금지 디렉토리

AI 에이전트도 사람도 직접 수정하지 않습니다(자동 생성·외부 코드):

- <!-- TODO: 예) `src/generated/`, `vendor/`, `*.proto`에서 생성된 *_pb2.py 등 -->

## 외부 시스템 경계

각 외부 시스템에 대해 어댑터를 두고, 도메인은 추상 인터페이스만 알게 합니다.

| 외부 시스템 | 어댑터 위치 | 비고 |
|---|---|---|
| <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

## 결정 기록 (ADR)

주요 아키텍처 결정은 `docs/adr/NNNN-<title>.md` 또는 이 파일 하단에 기록합니다.

<!-- TODO: ADR 추가 -->
