from __future__ import annotations

# ユースケース層が各外部依存を正しい順序で呼ぶことを確認する。
import json
from pathlib import Path

import pytest

from application.dto import CommonArgs, GenerateArgs
from application.use_cases import VideoPipelineUseCases
from domain.errors import AppError
from domain.models import AppConfig, FfmpegConfig, ProjectConfig, Scene, Story, SubtitlesConfig, TtsConfig


def make_config(
    *,
    out_dir: str = "out",
    subtitles_enabled: bool = True,
    use_source_size: bool = True,
    max_duration_sec: float = 0.0,
) -> AppConfig:
    return AppConfig(
        project=ProjectConfig(
            out_dir=out_dir,
            width=1080,
            height=1920,
            fps=24,
            use_source_size=use_source_size,
            max_duration_sec=max_duration_sec,
        ),
        tts=TtsConfig(engine="gtts", voice="ja", rate=170),
        subtitles=SubtitlesConfig(enabled=subtitles_enabled),
        ffmpeg=FfmpegConfig(bin="ffmpeg"),
    )


def make_story(*scenes: Scene) -> Story:
    return Story(title="t", scenes=tuple(scenes))


class StaticConfigRepo:
    def __init__(self, config: AppConfig):
        self.config = config
        self.loaded: list[Path] = []

    def load_config(self, path: Path) -> AppConfig:
        self.loaded.append(path)
        return self.config


class StaticStoryRepo:
    def __init__(self, story: Story):
        self.story = story
        self.loaded: list[Path] = []

    def load_story(self, path: Path) -> Story:
        self.loaded.append(path)
        return self.story


class FakeMedia:
    def __init__(self):
        self.which_map: dict[str, str] = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}
        self.duration_map: dict[Path, float] = {}
        self.image_size_map: dict[Path, tuple[int, int]] = {}
        self.filter_result = True
        self.run_calls: list[list[str]] = []

    def which(self, bin_name: str) -> str:
        return self.which_map.get(bin_name, bin_name)

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self.run_calls.append(cmd)

    def probe_duration(self, path: Path) -> float:
        return self.duration_map[path]

    def probe_image_size(self, path: Path) -> tuple[int, int]:
        return self.image_size_map[path]

    def has_filter(self, ffmpeg_bin: str, name: str) -> bool:
        return self.filter_result


class FakeNarration:
    def __init__(self):
        self.select_calls: list[tuple[str, str]] = []
        self.synthesize_calls: list[tuple[str, Path, str, int, str, str]] = []

    def select_voice(self, voice: str, engine: str) -> str:
        self.select_calls.append((voice, engine))
        return voice

    def synthesize_to_wav(
        self,
        text: str,
        out_wav: Path,
        voice: str,
        rate: int,
        engine: str,
        ffmpeg_bin: str,
    ) -> None:
        self.synthesize_calls.append((text, out_wav, voice, rate, engine, ffmpeg_bin))
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        out_wav.write_text("wav", encoding="utf-8")


class FakeStoryPlanner:
    def __init__(self, story: Story):
        self.story = story
        self.calls: list[tuple[str, str, int, Path, Path]] = []

    def plan_story(self, topic: str, slug: str, scene_count: int, root: Path, tmp_dir: Path) -> Story:
        self.calls.append((topic, slug, scene_count, root, tmp_dir))
        return self.story


class FakeImageGenerator:
    def __init__(self):
        self.calls: list[tuple[str, Scene, int, int, Path, Path]] = []

    def generate_image(self, topic: str, scene: Scene, index: int, total: int, output_path: Path, root: Path) -> None:
        self.calls.append((topic, scene, index, total, output_path, root))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("png", encoding="utf-8")


def make_use_cases(
    tmp_path: Path,
    config: AppConfig,
    story: Story,
    *,
    media: FakeMedia | None = None,
    narration: FakeNarration | None = None,
    story_planner: FakeStoryPlanner | None = None,
    image_generator: FakeImageGenerator | None = None,
    messages: list[str] | None = None,
) -> tuple[VideoPipelineUseCases, FakeMedia, FakeNarration, list[str]]:
    media_obj = media or FakeMedia()
    narration_obj = narration or FakeNarration()
    msgs = messages or []
    use_cases = VideoPipelineUseCases(
        config_repo=StaticConfigRepo(config),
        story_repo=StaticStoryRepo(story),
        media=media_obj,
        narration=narration_obj,
        story_planner=story_planner,
        image_generator=image_generator,
        root=tmp_path,
        emit=msgs.append,
    )
    return use_cases, media_obj, narration_obj, msgs


def default_args(tmp_path: Path, *, no_subtitles: bool = False, with_subtitles: bool = False, max_duration: float | None = None) -> CommonArgs:
    story_path = tmp_path / "stories" / "story.json"
    story_path.parent.mkdir(parents=True, exist_ok=True)
    story_path.write_text("{}", encoding="utf-8")
    return CommonArgs(
        config=tmp_path / "config.json",
        story=story_path,
        images_dir="images",
        no_subtitles=no_subtitles,
        with_subtitles=with_subtitles,
        max_duration_sec=max_duration,
    )


def test_doctor(tmp_path: Path) -> None:
    config = make_config()
    story = make_story(Scene("s1", "img.png", "", "n", ()))
    use_cases, _, narration, messages = make_use_cases(tmp_path, config, story)
    use_cases.doctor(tmp_path / "config.json")
    assert narration.select_calls == [("ja", "gtts")]
    assert messages[0] == "Doctor checks:"


def test_tts_success_and_missing_narration(tmp_path: Path) -> None:
    config = make_config()
    story = make_story(Scene("s1", "img.png", "", "hello", ()), Scene("s2", "img2.png", "", "world", ()))
    args = default_args(tmp_path)
    use_cases, media, narration, messages = make_use_cases(tmp_path, config, story)
    use_cases.tts(args)

    out_audio = tmp_path / "out" / "audio"
    assert (out_audio / "s1.wav").exists()
    assert (out_audio / "s2.wav").exists()
    assert any(cmd[0] == "ffmpeg" and "concat" in cmd for cmd in media.run_calls)
    assert len(narration.synthesize_calls) == 2
    assert any(message.startswith("Wrote ") for message in messages)

    bad_story = make_story(Scene("s1", "img.png", "", "", ()))
    bad_use_cases, _, _, _ = make_use_cases(tmp_path, config, bad_story)
    with pytest.raises(AppError, match=r"scene\[1\] missing narration"):
        bad_use_cases.tts(args)


def test_srt_missing_audio(tmp_path: Path) -> None:
    config = make_config()
    story = make_story(Scene("s1", "img.png", "", "hello", ()))
    use_cases, _, _, _ = make_use_cases(tmp_path, config, story)
    with pytest.raises(AppError, match="Missing per-scene audio"):
        use_cases.srt(default_args(tmp_path))


def test_srt_generates_files(tmp_path: Path) -> None:
    config = make_config(max_duration_sec=10.0)
    story = make_story(Scene("s1", "img.png", "", "短い文章です。", ()))
    media = FakeMedia()
    use_cases, _, _, _ = make_use_cases(tmp_path, config, story, media=media)
    paths_audio = tmp_path / "out" / "audio"
    paths_audio.mkdir(parents=True, exist_ok=True)
    wav = paths_audio / "s1.wav"
    wav.write_text("x", encoding="utf-8")
    media.duration_map[wav] = 2.0

    use_cases.srt(default_args(tmp_path))
    assert (tmp_path / "out" / "subtitles.srt").exists()
    assert (tmp_path / "out" / "subtitles.ass").exists()


def test_srt_handles_empty_cues_and_short_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(max_duration_sec=10.0)
    story = make_story(
        Scene("s1", "img.png", "", "empty", ()),
        Scene("s2", "img.png", "", "short", ()),
        Scene("s3", "img.png", "", "", ()),
    )
    media = FakeMedia()
    use_cases, _, _, _ = make_use_cases(tmp_path, config, story, media=media)
    paths_audio = tmp_path / "out" / "audio"
    paths_audio.mkdir(parents=True, exist_ok=True)
    wav1 = paths_audio / "s1.wav"
    wav2 = paths_audio / "s2.wav"
    wav3 = paths_audio / "s3.wav"
    wav1.write_text("x", encoding="utf-8")
    wav2.write_text("x", encoding="utf-8")
    wav3.write_text("x", encoding="utf-8")
    media.duration_map[wav1] = 1.0
    media.duration_map[wav2] = 0.11
    media.duration_map[wav3] = 1.0

    def fake_split(text: str, width_chars: int = 20, max_lines_per_cue: int = 2) -> list[str]:
        if text == "empty":
            return []
        return ["a", "b"]

    monkeypatch.setattr("application.use_cases.split_subtitle_cues", fake_split)
    use_cases.srt(default_args(tmp_path))
    assert (tmp_path / "out" / "subtitles.srt").exists()


def test_render_errors(tmp_path: Path) -> None:
    config = make_config(subtitles_enabled=True)
    story = make_story(Scene("s1", "img.png", "", "n", ()))
    args = default_args(tmp_path)
    use_cases, media, _, _ = make_use_cases(tmp_path, config, story)

    with pytest.raises(AppError, match="Missing audio"):
        use_cases.render(args)

    out = tmp_path / "out"
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "narration.wav").write_text("x", encoding="utf-8")
    with pytest.raises(AppError, match="Missing subtitles"):
        use_cases.render(args)

    (out / "subtitles.srt").write_text("x", encoding="utf-8")
    (out / "subtitles.ass").write_text("x", encoding="utf-8")
    with pytest.raises(AppError, match="Missing image for scene\\[1\\]"):
        use_cases.render(args)

    images = tmp_path / "stories" / "images"
    images.mkdir(parents=True, exist_ok=True)
    (images / "img.png").write_text("x", encoding="utf-8")
    with pytest.raises(AppError, match="Missing per-scene audio"):
        use_cases.render(args)

    (audio_dir / "s1.wav").write_text("x", encoding="utf-8")
    media.duration_map[audio_dir / "s1.wav"] = 0.01
    with pytest.raises(AppError, match="No scenes to render"):
        use_cases.render(args)


def test_render_mismatched_source_sizes(tmp_path: Path) -> None:
    config = make_config(subtitles_enabled=False, use_source_size=True)
    story = make_story(Scene("s1", "img1.png", "", "n1", ()), Scene("s2", "img2.png", "", "n2", ()))
    args = default_args(tmp_path, no_subtitles=True)
    use_cases, media, _, _ = make_use_cases(tmp_path, config, story)

    out = tmp_path / "out"
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "narration.wav").write_text("x", encoding="utf-8")
    for scene_id in ("s1", "s2"):
        wav = audio_dir / f"{scene_id}.wav"
        wav.write_text("x", encoding="utf-8")
        media.duration_map[wav] = 1.0

    story_dir = tmp_path / "stories"
    (story_dir / "img1.png").write_text("x", encoding="utf-8")
    (story_dir / "img2.png").write_text("x", encoding="utf-8")
    media.image_size_map[(story_dir / "img1.png").resolve()] = (100, 100)
    media.image_size_map[(story_dir / "img2.png").resolve()] = (200, 100)

    with pytest.raises(AppError, match="All scene images must have same size"):
        use_cases.render(args)


def test_render_success_with_subtitles_filter_and_speed(tmp_path: Path) -> None:
    config = make_config(subtitles_enabled=True, use_source_size=True, max_duration_sec=1.0)
    story = make_story(Scene("s1", "img.png", "", "n", ()))
    args = default_args(tmp_path)
    use_cases, media, _, messages = make_use_cases(tmp_path, config, story)
    media.filter_result = True

    out = tmp_path / "out"
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "narration.wav").write_text("x", encoding="utf-8")
    wav = audio_dir / "s1.wav"
    wav.write_text("x", encoding="utf-8")
    media.duration_map[wav] = 2.0
    (out / "subtitles.srt").write_text("x", encoding="utf-8")
    (out / "subtitles.ass").write_text("x", encoding="utf-8")

    story_img = (tmp_path / "stories" / "img.png").resolve()
    story_img.write_text("x", encoding="utf-8")
    media.image_size_map[story_img] = (1080, 1920)

    use_cases.render(args)
    cmd = media.run_calls[-1]
    assert "-filter:a" in cmd
    assert "-vf" in cmd
    assert any("Duration fit: total" in message for message in messages)


def test_render_success_with_drawtext_and_scale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(subtitles_enabled=True, use_source_size=False, max_duration_sec=0.0)
    story = make_story(Scene("s1", "img.png", "", "n", ()))
    args = default_args(tmp_path)
    use_cases, media, _, messages = make_use_cases(tmp_path, config, story)
    media.filter_result = False

    out = tmp_path / "out"
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "narration.wav").write_text("x", encoding="utf-8")
    wav = audio_dir / "s1.wav"
    wav.write_text("x", encoding="utf-8")
    media.duration_map[wav] = 1.0
    (out / "subtitles.srt").write_text("x", encoding="utf-8")
    (out / "subtitles.ass").write_text("x", encoding="utf-8")

    story_img = (tmp_path / "stories" / "img.png").resolve()
    story_img.write_text("x", encoding="utf-8")

    monkeypatch.setattr("application.use_cases.drawtext_filters_from_srt", lambda *args, **kwargs: ["drawtext=test"])
    use_cases.render(args)

    cmd = media.run_calls[-1]
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in vf
    assert "drawtext=test" in vf
    assert any("Fallback to drawtext burn-in from SRT." in message for message in messages)
    assert any("(no speed change)" in message for message in messages)


def test_generate_writes_story_images_and_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(subtitles_enabled=False, out_dir="out")
    planned_story = make_story(
        Scene("raw1", "raw1.png", " First idea ", " First narration. ", ("Lambda",)),
        Scene("raw2", "raw2.png", " Second idea ", " Second narration. ", ()),
    )
    planner = FakeStoryPlanner(planned_story)
    image_generator = FakeImageGenerator()
    use_cases, _, _, messages = make_use_cases(
        tmp_path,
        config,
        planned_story,
        story_planner=planner,
        image_generator=image_generator,
    )
    render_calls: list[CommonArgs] = []
    monkeypatch.setattr(use_cases, "all", lambda a: render_calls.append(a))

    use_cases.generate(
        GenerateArgs(
            config=tmp_path / "config.json",
            topic="AWS Lambda",
            slug="lambda",
            scene_count=2,
            stories_dir="stories",
            images_dir="images",
            render=True,
            with_subtitles=True,
            max_duration_sec=60,
        )
    )

    story_path = tmp_path / "stories" / "story.generated.lambda.json"
    story_data = json.loads(story_path.read_text(encoding="utf-8"))
    assert [scene["id"] for scene in story_data["scenes"]] == ["lambda_01", "lambda_02"]
    assert [scene["image"] for scene in story_data["scenes"]] == ["images/lambda_01.png", "images/lambda_02.png"]
    assert (tmp_path / "images" / "lambda_01.png").exists()
    assert (tmp_path / "images" / "lambda_02.png").exists()
    assert planner.calls == [("AWS Lambda", "lambda", 2, tmp_path.resolve(), tmp_path / "out" / "tmp" / "generate" / "lambda")]
    assert [call[4] for call in image_generator.calls] == [
        tmp_path.resolve() / "images" / "lambda_01.png",
        tmp_path.resolve() / "images" / "lambda_02.png",
    ]
    assert render_calls == [
        CommonArgs(
            config=tmp_path / "config.json",
            story=story_path,
            images_dir="images",
            no_subtitles=False,
            with_subtitles=True,
            max_duration_sec=60,
        )
    ]
    assert any(message.startswith("Wrote ") for message in messages)


def test_generate_skips_existing_images_and_respects_no_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(out_dir="out")
    planned_story = make_story(Scene("raw", "raw.png", "Text", "Narration", ()))
    planner = FakeStoryPlanner(planned_story)
    image_generator = FakeImageGenerator()
    use_cases, _, _, messages = make_use_cases(
        tmp_path,
        config,
        planned_story,
        story_planner=planner,
        image_generator=image_generator,
    )
    monkeypatch.setattr(use_cases, "all", lambda a: pytest.fail("render should not run"))
    existing_image = tmp_path / "custom-images" / "skip_01.png"
    existing_image.parent.mkdir(parents=True, exist_ok=True)
    existing_image.write_text("existing", encoding="utf-8")

    use_cases.generate(
        GenerateArgs(
            config=tmp_path / "config.json",
            topic="Skip images",
            slug="skip",
            scene_count=1,
            images_dir="custom-images",
            render=False,
        )
    )

    story_data = json.loads((tmp_path / "stories" / "story.generated.skip.json").read_text(encoding="utf-8"))
    assert story_data["scenes"][0]["image"] == "custom-images/skip_01.png"
    assert image_generator.calls == []
    assert any("Image exists, skipping" in message for message in messages)


def test_generate_validates_dependencies_and_inputs(tmp_path: Path) -> None:
    config = make_config(out_dir="out")
    story = make_story(Scene("s1", "img.png", "text", "narration", ()))
    planner = FakeStoryPlanner(story)
    image_generator = FakeImageGenerator()

    use_cases, _, _, _ = make_use_cases(tmp_path, config, story, image_generator=image_generator)
    with pytest.raises(AppError, match="Story planner is not configured"):
        use_cases.generate(GenerateArgs(config=tmp_path / "config.json", topic="AWS Lambda"))

    use_cases, _, _, _ = make_use_cases(tmp_path, config, story, story_planner=planner)
    with pytest.raises(AppError, match="Image generator is not configured"):
        use_cases.generate(GenerateArgs(config=tmp_path / "config.json", topic="AWS Lambda"))

    use_cases, _, _, _ = make_use_cases(
        tmp_path,
        config,
        story,
        story_planner=planner,
        image_generator=image_generator,
    )
    with pytest.raises(AppError, match="topic is required"):
        use_cases.generate(GenerateArgs(config=tmp_path / "config.json", topic=" "))
    with pytest.raises(AppError, match="between 1 and 12"):
        use_cases.generate(GenerateArgs(config=tmp_path / "config.json", topic="AWS Lambda", scene_count=0))
    with pytest.raises(AppError, match="ASCII"):
        use_cases.generate(GenerateArgs(config=tmp_path / "config.json", topic="AWS Lambda", slug="!!!"))


def test_all_and_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(subtitles_enabled=True, out_dir="out")
    story = make_story(Scene("s1", "img.png", "", "n", ()))
    use_cases, _, _, _ = make_use_cases(tmp_path, config, story)
    args = default_args(tmp_path)

    order: list[str] = []
    monkeypatch.setattr(use_cases, "tts", lambda a: order.append("tts"))
    monkeypatch.setattr(use_cases, "srt", lambda a: order.append("srt"))
    monkeypatch.setattr(use_cases, "render", lambda a: order.append("render"))

    use_cases.all(args)
    assert order == ["tts", "srt", "render"]

    order.clear()
    use_cases.all(default_args(tmp_path, no_subtitles=True))
    assert order == ["tts", "render"]

    outputs_root = tmp_path / "outputs"
    child_dir = outputs_root / "x"
    child_file = outputs_root / "y.txt"
    child_dir.mkdir(parents=True, exist_ok=True)
    child_file.write_text("x", encoding="utf-8")
    use_cases.clean(tmp_path / "config.json", clean_all=True)
    assert outputs_root.exists()
    assert list(outputs_root.iterdir()) == []

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "file.txt").write_text("x", encoding="utf-8")
    use_cases.clean(tmp_path / "config.json", clean_all=False)
    assert out.exists()
    assert list(out.iterdir()) == []
