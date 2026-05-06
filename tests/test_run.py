from __future__ import annotations

# CLI引数のパースとユースケースへの振り分けを確認する。
import argparse
from pathlib import Path

import pytest

import run
from domain.errors import AppError


class DummyUseCases:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.raise_error = False

    def doctor(self, config: Path) -> None:
        self.calls.append(("doctor", config))
        if self.raise_error:
            raise AppError("boom")

    def tts(self, args) -> None:
        self.calls.append(("tts", args))

    def srt(self, args) -> None:
        self.calls.append(("srt", args))

    def render(self, args) -> None:
        self.calls.append(("render", args))

    def all(self, args) -> None:
        self.calls.append(("all", args))

    def generate(self, args) -> None:
        self.calls.append(("generate", args))

    def clean(self, config: Path, clean_all: bool = False) -> None:
        self.calls.append(("clean", (config, clean_all)))


def test_build_parser_and_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = DummyUseCases()
    monkeypatch.setattr(run, "build_use_cases", lambda root, emit=print: dummy)

    assert run.main(["doctor", "--config", "c.json"]) == 0
    assert run.main(["tts", "--config", "c.json", "--story", "s.json", "--images-dir", "img"]) == 0
    assert run.main(["srt", "--config", "c.json", "--story", "s.json", "--images-dir", "img"]) == 0
    assert run.main(["render", "--config", "c.json", "--story", "s.json", "--images-dir", "img"]) == 0
    assert run.main(["all", "--config", "c.json", "--story", "s.json", "--images-dir", "img"]) == 0
    assert run.main(["generate", "AWS Lambda", "--slug", "lambda", "--scenes", "3", "--no-render"]) == 0
    assert run.main(["clean", "--config", "c.json", "--all"]) == 0

    called_names = [name for name, _ in dummy.calls]
    assert called_names == ["doctor", "tts", "srt", "render", "all", "generate", "clean"]
    generate_args = dummy.calls[-2][1]
    assert generate_args.topic == "AWS Lambda"
    assert generate_args.slug == "lambda"
    assert generate_args.scene_count == 3
    assert generate_args.render is False


def test_subtitle_flags_are_mutually_exclusive() -> None:
    parser = run.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "all",
                "--config",
                "c.json",
                "--story",
                "s.json",
                "--images-dir",
                "img",
                "--no-subtitles",
                "--with-subtitles",
            ]
        )
    assert exc.value.code == 2


def test_generate_prompts_for_topic_and_supports_subtitle_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = DummyUseCases()
    monkeypatch.setattr(run, "build_use_cases", lambda root, emit=print: dummy)
    monkeypatch.setattr("builtins.input", lambda prompt: "EC2 autoscaling")

    assert run.main(["generate", "--no-render", "--no-subtitles"]) == 0

    generate_args = dummy.calls[0][1]
    assert generate_args.topic == "EC2 autoscaling"
    assert generate_args.no_subtitles is True
    assert generate_args.with_subtitles is False


def test_generate_subtitle_flags_are_mutually_exclusive() -> None:
    parser = run.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["generate", "AWS Lambda", "--no-subtitles", "--with-subtitles"])
    assert exc.value.code == 2


def test_main_handles_app_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    dummy = DummyUseCases()
    dummy.raise_error = True
    monkeypatch.setattr(run, "build_use_cases", lambda root, emit=print: dummy)
    code = run.main(["doctor", "--config", "c.json"])
    assert code == 2
    assert "ERROR: boom" in capsys.readouterr().err


def test_main_unsupported_command_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyParser:
        def parse_args(self, argv):
            return argparse.Namespace(cmd="unsupported")

        def error(self, msg: str):
            raise RuntimeError(msg)

    monkeypatch.setattr(run, "build_parser", lambda: DummyParser())  # type: ignore[return-value]
    monkeypatch.setattr(run, "build_use_cases", lambda root, emit=print: DummyUseCases())
    with pytest.raises(RuntimeError, match="unsupported command"):
        run.main([])
