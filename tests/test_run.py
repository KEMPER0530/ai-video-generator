from __future__ import annotations

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
    assert run.main(["clean", "--config", "c.json", "--all"]) == 0

    called_names = [name for name, _ in dummy.calls]
    assert called_names == ["doctor", "tts", "srt", "render", "all", "clean"]


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

