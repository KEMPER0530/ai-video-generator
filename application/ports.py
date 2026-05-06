from __future__ import annotations

from pathlib import Path
from typing import Protocol

from domain.models import AppConfig, Scene, Story


# application層から見た設定JSONの読み込み口。
class ConfigRepository(Protocol):
    def load_config(self, path: Path) -> AppConfig:
        ...  # pragma: no cover


# application層から見た台本JSONの読み込み口。
class StoryRepository(Protocol):
    def load_story(self, path: Path) -> Story:
        ...  # pragma: no cover


# ffmpeg/ffprobeなど、動画処理に必要な外部コマンドの境界。
class MediaGateway(Protocol):
    def which(self, bin_name: str) -> str:
        ...  # pragma: no cover

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        ...  # pragma: no cover

    def probe_duration(self, path: Path) -> float:
        ...  # pragma: no cover

    def probe_image_size(self, path: Path) -> tuple[int, int]:
        ...  # pragma: no cover

    def has_filter(self, ffmpeg_bin: str, name: str) -> bool:
        ...  # pragma: no cover


# TTSエンジンを差し替えられるようにするための境界。
class NarrationGateway(Protocol):
    def select_voice(self, voice: str, engine: str) -> str:
        ...  # pragma: no cover

    def synthesize_to_wav(
        self,
        text: str,
        out_wav: Path,
        voice: str,
        rate: int,
        engine: str,
        ffmpeg_bin: str,
    ) -> None:
        ...  # pragma: no cover


# Codex CLIなどを使って、テーマからStoryを作る境界。
class StoryPlanner(Protocol):
    def plan_story(self, topic: str, slug: str, scene_count: int, root: Path, tmp_dir: Path) -> Story:
        ...  # pragma: no cover


# Codex CLIの$imagegenなどを使って、1シーン分の画像を作る境界。
class ImageGenerator(Protocol):
    def generate_image(self, topic: str, scene: Scene, index: int, total: int, output_path: Path, root: Path) -> None:
        ...  # pragma: no cover
