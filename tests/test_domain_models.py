from __future__ import annotations

# config/story JSONをドメインモデルへ変換する検証をまとめる。
import pytest

from domain.errors import AppError
from domain.models import parse_config, parse_story


def test_parse_config_defaults_and_conversions() -> None:
    config = parse_config(
        {
            "project": {
                "out_dir": "out",
                "width": "720",
                "height": 1280,
                "fps": "30",
                "use_source_size": "false",
                "max_duration_sec": "60",
            },
            "tts": {"engine": "GTTS", "voice": "ja", "rate": "170"},
            "subtitles": {"enabled": 1},
            "ffmpeg": {"bin": "ffmpeg-custom"},
        }
    )
    assert config.project.out_dir == "out"
    assert config.project.width == 720
    assert config.project.height == 1280
    assert config.project.fps == 30
    assert config.project.use_source_size is False
    assert config.project.max_duration_sec == 60.0
    assert config.tts.engine == "gtts"
    assert config.tts.rate == 170
    assert config.subtitles.enabled is True
    assert config.ffmpeg.bin == "ffmpeg-custom"


def test_parse_config_defaults() -> None:
    config = parse_config({})
    assert config.project.out_dir == "outputs/docker-all"
    assert config.project.width == 1080
    assert config.project.height == 1920
    assert config.project.fps == 24
    assert config.project.use_source_size is True
    assert config.project.max_duration_sec == 0.0
    assert config.tts.engine == "gtts"
    assert config.tts.voice == "ja"
    assert config.tts.rate == 170
    assert config.subtitles.enabled is True
    assert config.ffmpeg.bin == "ffmpeg"


def test_parse_config_string_true_boolean() -> None:
    config = parse_config({"project": {"use_source_size": "true"}})
    assert config.project.use_source_size is True


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"tts": {"engine": "bad"}}, "tts.engine must be one of"),
        ({"project": {"width": "x"}}, "project.width must be an integer"),
        ({"project": {"max_duration_sec": "x"}}, "project.max_duration_sec must be a number"),
        ({"project": {"use_source_size": "maybe"}}, "project.use_source_size must be a boolean"),
        ({"tts": {"rate": "x"}}, "tts.rate must be an integer"),
        ({"subtitles": {"enabled": "maybe"}}, "subtitles.enabled must be a boolean"),
    ],
)
def test_parse_config_validation_errors(data: dict, message: str) -> None:
    with pytest.raises(AppError, match=message):
        parse_config(data)


def test_parse_story_parses_keywords_and_defaults() -> None:
    story = parse_story(
        {
            "title": "title",
            "scenes": [
                {
                    "id": "scene1",
                    "image": "image1.png",
                    "on_screen_text": "on screen",
                    "narration": "narration",
                    "keywords": [" AWS ", "", "ECS"],
                },
                {
                    "image": "image2.png",
                    "keywords": "S3， Lambda／API・ Gateway",
                },
                {},
            ],
        }
    )
    assert story.title == "title"
    assert story.scenes[0].id == "scene1"
    assert story.scenes[0].keywords == ("AWS", "ECS")
    assert story.scenes[1].id == "s2"
    assert story.scenes[1].keywords == ("S3", "Lambda/API", "Gateway")
    assert story.scenes[2].id == "s3"
    assert story.scenes[2].keywords == ()


def test_parse_story_validation_errors() -> None:
    with pytest.raises(AppError, match="story.scenes must be a list"):
        parse_story({"scenes": "x"})  # type: ignore[arg-type]

    with pytest.raises(AppError, match=r"scene\[1\] must be an object"):
        parse_story({"scenes": ["x"]})  # type: ignore[list-item]
