"""MixPilot FastAPI 앱의 OpenAPI JSON 출력 — CI/오프라인 codegen용.

서버를 띄우지 않고 `app.openapi()`를 호출해 스키마를 표준출력 또는 파일로 쓴다.
프론트엔드 `npm run gen:api:offline`이 이를 활용해 백엔드 서버 없이 타입 재생성.

사용:
    uv run python -m mixpilot.scripts.export_openapi             # stdout
    uv run python -m mixpilot.scripts.export_openapi -o api.json  # 파일
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from mixpilot.config import Settings
from mixpilot.main import create_app


def export_openapi() -> dict[str, Any]:
    """`/openapi.json` 본문을 dict로 반환.

    환경 변수 의존성을 피하기 위해 디폴트 `Settings()`로 앱을 만든다.
    스키마는 환경 변수에 영향받지 않으므로 결과는 결정적.
    """
    # 디폴트 Settings로 격리 — 실행 환경의 MIXPILOT_* 영향 배제.
    for key in [k for k in os.environ if k.startswith("MIXPILOT_")]:
        os.environ.pop(key, None)
    app = create_app(settings=Settings())
    return app.openapi()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export MixPilot OpenAPI JSON without running the server.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file path. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    schema = export_openapi()
    text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"

    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
