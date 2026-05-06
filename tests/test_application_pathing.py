from __future__ import annotations

# パス解決と字幕ON/OFF判定の境界条件を確認する。
from pathlib import Path

import pytest

from application.pathing import build_paths, resolve_images_dir, resolve_scene_image, subtitles_enabled
from domain.errors import AppError
from domain.models import AppConfig, CliOptions, FfmpegConfig, ProjectConfig, Scene, SubtitlesConfig, TtsConfig


def _config(out_dir: str = "out") -> AppConfig:
    return AppConfig(
        project=ProjectConfig(
            out_dir=out_dir,
            width=1080,
            height=1920,
            fps=24,
            use_source_size=True,
            max_duration_sec=0.0,
        ),
        tts=TtsConfig(engine="gtts", voice="ja", rate=170),
        subtitles=SubtitlesConfig(enabled=True),
        ffmpeg=FfmpegConfig(bin="ffmpeg"),
    )


def test_build_paths_relative_and_absolute(tmp_path: Path) -> None:
    rel = build_paths(_config("outputs/x"), tmp_path)
    assert rel.out == tmp_path / "outputs/x"

    abs_out = tmp_path / "abs"
    abs_paths = build_paths(_config(str(abs_out)), tmp_path)
    assert abs_paths.out == abs_out


def test_subtitles_enabled_precedence() -> None:
    cfg = _config()
    assert subtitles_enabled(CliOptions(no_subtitles=True), cfg) is False
    assert subtitles_enabled(CliOptions(with_subtitles=True), cfg) is True
    assert subtitles_enabled(CliOptions(), cfg) is True


def test_resolve_images_dir(tmp_path: Path) -> None:
    story = tmp_path / "stories" / "story.json"
    story.parent.mkdir(parents=True, exist_ok=True)
    story.write_text("{}", encoding="utf-8")

    assert resolve_images_dir(str(tmp_path / "images"), story) == tmp_path / "images"
    assert resolve_images_dir("../images", story) == (story.parent / "../images").resolve()


def test_resolve_scene_image_with_image_candidates(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    story_dir = root / "stories"
    images_dir = root / "images_base"
    story_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)
    story_path = story_dir / "story.json"
    story_path.write_text("{}", encoding="utf-8")

    scene_abs = Scene("s1", str(root / "abs.png"), "", "", ())
    assert resolve_scene_image(scene_abs, story_path, 1, images_dir, root) == root / "abs.png"

    scene_image_dir = Scene("s2", "images/img.png", "", "", ())
    expected = (images_dir / "img.png").resolve()
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_text("x", encoding="utf-8")
    assert resolve_scene_image(scene_image_dir, story_path, 2, images_dir, root) == expected

    scene_story_rel = Scene("s3", "story_rel.png", "", "", ())
    story_rel = (story_dir / "story_rel.png").resolve()
    story_rel.write_text("x", encoding="utf-8")
    assert resolve_scene_image(scene_story_rel, story_path, 3, images_dir, root) == story_rel

    scene_root_rel = Scene("s4", "root_rel.png", "", "", ())
    root_rel = (root / "root_rel.png").resolve()
    root_rel.write_text("x", encoding="utf-8")
    assert resolve_scene_image(scene_root_rel, story_path, 4, images_dir, root) == root_rel

    scene_missing = Scene("s5", "missing.png", "", "", ())
    fallback = resolve_scene_image(scene_missing, story_path, 5, images_dir, root)
    assert fallback == (images_dir / "missing.png").resolve()


def test_resolve_scene_image_without_image_uses_id_or_raises(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    story_path = root / "stories" / "story.json"
    story_path.parent.mkdir(parents=True)
    story_path.write_text("{}", encoding="utf-8")
    images_dir = root / "images"
    images_dir.mkdir(parents=True)

    scene = Scene("scene-id", "", "", "", ())
    assert resolve_scene_image(scene, story_path, 1, images_dir, root) == (images_dir / "scene-id.png").resolve()

    with pytest.raises(AppError, match="missing required field: image"):
        resolve_scene_image(scene, story_path, 1, None, root)
