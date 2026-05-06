from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# 既存ファイルから動画を作るコマンド群で共有する入力値。
@dataclass(frozen=True)
class CommonArgs:
    config: Path
    story: Path
    images_dir: str
    no_subtitles: bool = False
    with_subtitles: bool = False
    max_duration_sec: float | None = None


# テーマから台本・画像・動画まで生成するgenerate専用の入力値。
@dataclass(frozen=True)
class GenerateArgs:
    config: Path
    topic: str
    slug: str | None = None
    scene_count: int = 6
    stories_dir: str = "stories"
    images_dir: str = "images"
    render: bool = True
    force_images: bool = False
    no_subtitles: bool = False
    with_subtitles: bool = True
    max_duration_sec: float | None = None
