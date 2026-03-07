from __future__ import annotations

from pathlib import Path

import pytest

from domain.errors import AppError
from infrastructure.repositories import JsonConfigRepository, JsonStoryRepository


def test_json_repositories_load(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"project":{"out_dir":"x","width":100,"height":200,"fps":30,"use_source_size":true,"max_duration_sec":0},'
        '"tts":{"engine":"gtts","voice":"ja","rate":170},"subtitles":{"enabled":true},"ffmpeg":{"bin":"ffmpeg"}}',
        encoding="utf-8",
    )
    story_path = tmp_path / "story.json"
    story_path.write_text('{"title":"t","scenes":[{"id":"s1","narration":"n","image":"img.png"}]}', encoding="utf-8")

    config = JsonConfigRepository().load_config(config_path)
    story = JsonStoryRepository().load_story(story_path)
    assert config.project.width == 100
    assert story.scenes[0].id == "s1"


def test_json_repositories_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(AppError, match="Missing file"):
        JsonConfigRepository().load_config(missing)

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(AppError, match="Invalid JSON"):
        JsonStoryRepository().load_story(broken)

