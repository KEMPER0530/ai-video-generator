from __future__ import annotations

from pathlib import Path
from typing import Callable

from application.use_cases import VideoPipelineUseCases
from infrastructure.codex_gateway import CodexCliImageGenerator, CodexCliStoryPlanner
from infrastructure.media_gateway import FfmpegMediaGateway
from infrastructure.narration_gateway import MultiEngineNarrationGateway
from infrastructure.process_runner import SubprocessRunner
from infrastructure.repositories import JsonConfigRepository, JsonStoryRepository


def build_use_cases(root: Path, emit: Callable[[str], None] = print) -> VideoPipelineUseCases:
    # 実行時に使う具体実装をここで組み立て、application層には抽象として渡す。
    runner = SubprocessRunner(root)
    return VideoPipelineUseCases(
        config_repo=JsonConfigRepository(),
        story_repo=JsonStoryRepository(),
        media=FfmpegMediaGateway(runner),
        narration=MultiEngineNarrationGateway(runner),
        story_planner=CodexCliStoryPlanner(runner),
        image_generator=CodexCliImageGenerator(runner),
        root=root,
        emit=emit,
    )
