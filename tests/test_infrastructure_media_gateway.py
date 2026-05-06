from __future__ import annotations

# ffmpeg/ffprobeゲートウェイのコマンド呼び出しとパースを確認する。
from pathlib import Path

import pytest

from domain.errors import AppError
from infrastructure.media_gateway import FfmpegMediaGateway


class DummyRunner:
    def __init__(self) -> None:
        self.which_map: dict[str, str] = {"ffprobe": "ffprobe-path"}
        self.outputs: dict[tuple[str, ...], str] = {}
        self.raise_error: set[tuple[str, ...]] = set()
        self.run_calls: list[list[str]] = []

    def which(self, name: str) -> str:
        if name in self.which_map:
            return self.which_map[name]
        raise AppError(f"Command not found: {name}")

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self.run_calls.append(cmd)

    def check_output(self, cmd: list[str], *, stderr_to_stdout: bool = False) -> str:
        key = tuple(cmd)
        if key in self.raise_error:
            raise AppError("boom")
        return self.outputs[key]


def test_gateway_delegates_which_and_run() -> None:
    runner = DummyRunner()
    gateway = FfmpegMediaGateway(runner)  # type: ignore[arg-type]
    assert gateway.which("ffprobe") == "ffprobe-path"
    gateway.run(["ffmpeg", "-version"])
    assert runner.run_calls == [["ffmpeg", "-version"]]


def test_probe_duration_success_and_parse_error(tmp_path: Path) -> None:
    runner = DummyRunner()
    target = tmp_path / "a.wav"
    key = ("ffprobe-path", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(target))
    runner.outputs[key] = "1.23\n"

    gateway = FfmpegMediaGateway(runner)  # type: ignore[arg-type]
    assert gateway.probe_duration(target) == 1.23

    runner.outputs[key] = "x"
    with pytest.raises(AppError, match="Failed to parse duration"):
        gateway.probe_duration(target)


def test_probe_image_size_success_and_error(tmp_path: Path) -> None:
    runner = DummyRunner()
    target = tmp_path / "a.png"
    key = (
        "ffprobe-path",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        str(target),
    )
    runner.outputs[key] = "1080x1920"

    gateway = FfmpegMediaGateway(runner)  # type: ignore[arg-type]
    assert gateway.probe_image_size(target) == (1080, 1920)

    runner.outputs[key] = "broken"
    with pytest.raises(AppError, match="Failed to parse image size"):
        gateway.probe_image_size(target)


def test_has_filter_true_false_and_error() -> None:
    runner = DummyRunner()
    key = ("ffmpeg", "-hide_banner", "-filters")
    runner.outputs[key] = " ... subtitles ... \n"

    gateway = FfmpegMediaGateway(runner)  # type: ignore[arg-type]
    assert gateway.has_filter("ffmpeg", "subtitles") is True
    assert gateway.has_filter("ffmpeg", "drawtext") is False

    runner.raise_error.add(key)
    assert gateway.has_filter("ffmpeg", "subtitles") is False
