from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommonArgs:
    config: Path
    story: Path
    images_dir: str
    no_subtitles: bool = False
    with_subtitles: bool = False
    max_duration_sec: float | None = None

