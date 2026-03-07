from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain.errors import AppError
from domain.models import AppConfig, Story, parse_config, parse_story


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid JSON: {path} ({exc})") from exc


class JsonConfigRepository:
    def load_config(self, path: Path) -> AppConfig:
        return parse_config(_load_json(path))


class JsonStoryRepository:
    def load_story(self, path: Path) -> Story:
        return parse_story(_load_json(path))

