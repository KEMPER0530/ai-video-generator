from __future__ import annotations

from pathlib import Path
from typing import Callable

from application.use_cases import VideoPipelineUseCases
from infrastructure.media_gateway import FfmpegMediaGateway
from infrastructure.narration_gateway import MultiEngineNarrationGateway
from infrastructure.process_runner import SubprocessRunner
from infrastructure.repositories import JsonConfigRepository, JsonStoryRepository


def build_use_cases(root: Path, emit: Callable[[str], None] = print) -> VideoPipelineUseCases:
    runner = SubprocessRunner(root)
    return VideoPipelineUseCases(
        config_repo=JsonConfigRepository(),
        story_repo=JsonStoryRepository(),
        media=FfmpegMediaGateway(runner),
        narration=MultiEngineNarrationGateway(runner),
        root=root,
        emit=emit,
    )

