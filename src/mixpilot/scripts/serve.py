"""MixPilot 서버 런처 — service 프리셋 적용 후 uvicorn 가동.

YAML 프리셋(`config/presets/*.yaml`)을 읽어 환경 변수로 변환한 뒤 본 프로세스
환경에 *덮어쓰지 않고* 추가(`setdefault`) — 운영자가 CLI에서 명시한 env는
항상 우선. 그 뒤 uvicorn을 `mixpilot.main:app`로 가동.

사용:
    uv run python -m mixpilot.scripts.serve --preset worship
    uv run python -m mixpilot.scripts.serve --preset performance --port 9000
    uv run python -m mixpilot.scripts.serve --preset rehearsal --reload

프리셋이 *세팅하는* 키와 운영자가 CLI에서 *override하는* 키:
- 프리셋 키만 적용 → 운영자가 명시하지 않은 항목에 대해서만 디폴트 변경.
- 운영자가 `MIXPILOT_AUDIO__ENABLED=false` 등 env로 명시했으면 그대로 둠.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import uvicorn
import yaml

logger = logging.getLogger("mixpilot.serve")

# 프로젝트 루트 기준의 프리셋 디렉토리. 본 모듈 위치(src/mixpilot/scripts) →
# parents[3]가 프로젝트 루트.
_PRESET_DIR = Path(__file__).resolve().parents[3] / "config" / "presets"

# 평탄화된 dict의 키 구분자 — pydantic-settings의 `env_nested_delimiter`와 일치.
_ENV_NESTED_DELIMITER = "__"
_ENV_PREFIX = "MIXPILOT_"


def list_presets() -> list[str]:
    """`config/presets/*.yaml`의 stem 이름 목록."""
    if not _PRESET_DIR.exists():
        return []
    return sorted(p.stem for p in _PRESET_DIR.glob("*.yaml"))


def load_preset(name: str) -> dict[str, Any]:
    """프리셋 YAML을 읽어 dict 반환. 없으면 `FileNotFoundError`."""
    path = _PRESET_DIR / f"{name}.yaml"
    if not path.exists():
        available = ", ".join(list_presets()) or "(none)"
        raise FileNotFoundError(
            f"preset '{name}' not found at {path}. Available: {available}"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"preset {path} must be a YAML mapping at the top level")
    return data


def flatten_to_env(
    data: Mapping[str, Any],
    *,
    prefix: str = _ENV_PREFIX,
    delim: str = _ENV_NESTED_DELIMITER,
) -> dict[str, str]:
    """중첩 dict → env-var 평탄화.

    예: `audio.enabled = true` → `MIXPILOT_AUDIO__ENABLED=true`.

    `description`처럼 Settings 모델에 매핑되지 않는 메타 키도 평탄화하지만
    pydantic-settings의 `extra="ignore"` 정책으로 무시됨 — 안전.

    Boolean·숫자는 str로 변환. 리스트·None은 보존하기 어려우므로 JSON 직렬화.
    """
    flat: dict[str, str] = {}

    def _walk(d: Mapping[str, Any], path: tuple[str, ...]) -> None:
        for key, value in d.items():
            new_path = (*path, key.upper())
            if isinstance(value, Mapping):
                _walk(value, new_path)
            else:
                env_key = prefix + delim.join(new_path)
                flat[env_key] = _coerce_to_str(value)

    _walk(data, ())
    return flat


def _coerce_to_str(value: Any) -> str:
    if isinstance(value, bool):
        # pydantic-settings는 "true"/"false" 문자열을 bool로 파싱.
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def apply_preset_to_env(preset_env: Mapping[str, str]) -> dict[str, str]:
    """프리셋 env를 process env에 *덮어쓰지 않고* setdefault. 추가된 키 반환."""
    applied: dict[str, str] = {}
    for k, v in preset_env.items():
        if k not in os.environ:
            os.environ[k] = v
            applied[k] = v
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MixPilot 서버 런처 — service 프리셋 적용 후 uvicorn 가동."
    )
    parser.add_argument(
        "--preset",
        type=str,
        default=None,
        help="적용할 프리셋 이름 (config/presets/<name>.yaml). 미지정이면 디폴트만.",
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="바인드 host. 기본 127.0.0.1."
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="바인드 port. 기본 8000."
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="dev 모드 — 코드 변경 자동 reload.",
    )
    parser.add_argument(
        "--log-level", type=str, default="info", help="uvicorn 로그 레벨."
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="사용 가능한 프리셋 목록만 출력하고 종료.",
    )
    args = parser.parse_args(argv)

    if args.list_presets:
        names = list_presets()
        if not names:
            print(f"no presets found in {_PRESET_DIR}")
            return 0
        print("사용 가능한 프리셋:")
        for name in names:
            try:
                data = load_preset(name)
                desc = data.get("description", "")
            except Exception as e:  # pragma: no cover
                desc = f"<로드 실패: {e}>"
            print(f"  {name:14} — {desc}")
        return 0

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    if args.preset:
        try:
            data = load_preset(args.preset)
        except FileNotFoundError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 2
        env_dict = flatten_to_env(data)
        applied = apply_preset_to_env(env_dict)
        skipped = sorted(set(env_dict) - set(applied))
        logger.info("preset %s applied (%d keys)", args.preset, len(applied))
        if skipped:
            logger.info(
                "preset에서 %d개 키는 이미 환경에 있어 보존: %s",
                len(skipped),
                ", ".join(skipped),
            )

    uvicorn.run(
        "mixpilot.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
