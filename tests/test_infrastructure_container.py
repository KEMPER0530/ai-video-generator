from __future__ import annotations

from pathlib import Path

from application.use_cases import VideoPipelineUseCases
from infrastructure.container import build_use_cases


def test_build_use_cases_returns_service(tmp_path: Path) -> None:
    use_cases = build_use_cases(root=Path(tmp_path), emit=lambda msg: None)
    assert isinstance(use_cases, VideoPipelineUseCases)

