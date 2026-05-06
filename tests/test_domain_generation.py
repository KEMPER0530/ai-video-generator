from __future__ import annotations

# Codex生成結果を保存可能な台本/画像パスへ正規化する処理を確認する。
from datetime import datetime
from pathlib import Path

import pytest

from domain.errors import AppError
from domain.generation import (
    canonicalize_generated_story,
    default_generated_slug,
    extract_json_payload,
    generated_story_path,
    normalize_scene_count,
    normalize_slug,
    scene_id,
    scene_image_ref,
    slugify_topic,
    story_to_json_data,
)
from domain.models import Scene, Story


def test_scene_count_and_slug_helpers() -> None:
    assert normalize_scene_count(1) == 1
    assert normalize_scene_count(12) == 12
    assert slugify_topic("AWS Lambda for beginners") == "aws_lambda_for_beginners"
    assert slugify_topic("!!!") == "generated"
    assert normalize_slug("AWS Lambda!") == "aws_lambda"
    assert default_generated_slug("AWS Lambda", datetime(2026, 5, 6, 12, 34, 56)) == "aws_lambda_20260506_123456"
    assert default_generated_slug("日本語だけ", datetime(2026, 5, 6, 12, 34, 56)) == "generated_20260506_123456"
    assert scene_id("lambda", 2) == "lambda_02"
    assert scene_image_ref("lambda", 2) == "images/lambda_02.png"
    assert scene_image_ref("lambda", 2, "assets/generated") == "assets/generated/lambda_02.png"


@pytest.mark.parametrize("value", [0, 13])
def test_normalize_scene_count_rejects_out_of_range(value: int) -> None:
    with pytest.raises(AppError, match="between 1 and 12"):
        normalize_scene_count(value)


def test_normalize_slug_rejects_non_ascii_slugs() -> None:
    with pytest.raises(AppError, match="ASCII"):
        normalize_slug("!!!")


def test_generated_story_path_supports_relative_and_absolute_dirs(tmp_path: Path) -> None:
    assert generated_story_path(tmp_path, "stories", "lambda") == tmp_path / "stories" / "story.generated.lambda.json"
    assert generated_story_path(tmp_path, str(tmp_path / "custom"), "lambda") == tmp_path / "custom" / "story.generated.lambda.json"


def test_extract_json_payload_accepts_plain_fenced_and_prefixed_json() -> None:
    assert extract_json_payload('{"title": "x"}') == {"title": "x"}
    assert extract_json_payload('```json\n{"title": "x"}\n```') == {"title": "x"}
    assert extract_json_payload('Result:\n{"title": "x"}\nDone.') == {"title": "x"}


@pytest.mark.parametrize("text", ["", "not json", "{"])
def test_extract_json_payload_rejects_invalid_output(text: str) -> None:
    with pytest.raises(AppError):
        extract_json_payload(text)


def test_extract_json_payload_rejects_non_object_json() -> None:
    with pytest.raises(AppError, match="must be an object"):
        extract_json_payload("[]")


def test_canonicalize_generated_story_rewrites_ids_images_and_trims_text() -> None:
    story = Story(
        title=" ",
        scenes=(
            Scene("old", "old.png", " On screen ", " Narration ", ("Lambda",)),
            Scene("old2", "old2.png", " Second ", " More narration ", ()),
        ),
    )

    result = canonicalize_generated_story(story, "AWS Lambda", "lambda", 2, "assets")

    assert result.title.startswith("AWS Lambda")
    assert result.scenes[0] == Scene("lambda_01", "assets/lambda_01.png", "On screen", "Narration", ("Lambda",))
    assert result.scenes[1] == Scene("lambda_02", "assets/lambda_02.png", "Second", "More narration", ())


def test_canonicalize_generated_story_rejects_bad_scene_counts_and_empty_text() -> None:
    story = Story(title="x", scenes=(Scene("s1", "x.png", "text", "narration", ()),))
    with pytest.raises(AppError, match="exactly 2 scenes"):
        canonicalize_generated_story(story, "Topic", "topic", 2)

    with pytest.raises(AppError, match=r"scene\[1\] missing on_screen_text"):
        canonicalize_generated_story(Story("x", (Scene("s1", "x.png", "", "n", ()),)), "Topic", "topic", 1)

    with pytest.raises(AppError, match=r"scene\[1\] missing narration"):
        canonicalize_generated_story(Story("x", (Scene("s1", "x.png", "text", "", ()),)), "Topic", "topic", 1)


def test_story_to_json_data_omits_empty_keywords() -> None:
    story = Story(
        title="Title",
        scenes=(
            Scene("s1", "images/s1.png", "text", "narration", ("k1", "k2")),
            Scene("s2", "images/s2.png", "text2", "narration2", ()),
        ),
    )

    assert story_to_json_data(story) == {
        "title": "Title",
        "scenes": [
            {
                "id": "s1",
                "image": "images/s1.png",
                "on_screen_text": "text",
                "narration": "narration",
                "keywords": ["k1", "k2"],
            },
            {
                "id": "s2",
                "image": "images/s2.png",
                "on_screen_text": "text2",
                "narration": "narration2",
            },
        ],
    }
