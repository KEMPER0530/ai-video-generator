from __future__ import annotations

from pathlib import Path
from typing import Protocol

from domain.models import AppConfig, Story


class ConfigRepository(Protocol):
    def load_config(self, path: Path) -> AppConfig:
        ...  # pragma: no cover


class StoryRepository(Protocol):
    def load_story(self, path: Path) -> Story:
        ...  # pragma: no cover


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
