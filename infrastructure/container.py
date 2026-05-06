from __future__ import annotations

import os
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
    codex_sandbox = os.environ.get("AI_VIDEO_CODEX_SANDBOX", "workspace-write")
    return VideoPipelineUseCases(
        config_repo=JsonConfigRepository(),
        story_repo=JsonStoryRepository(),
        media=FfmpegMediaGateway(runner),
        narration=MultiEngineNarrationGateway(runner),
        story_planner=CodexCliStoryPlanner(runner, sandbox=codex_sandbox),
        image_generator=CodexCliImageGenerator(runner, sandbox=codex_sandbox),
        root=root,
        emit=emit,
    )
