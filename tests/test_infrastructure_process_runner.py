from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from domain.errors import AppError
from infrastructure.process_runner import SubprocessRunner


def test_which_prefers_existing_relative_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local_bin = tmp_path / "bin" / "tool"
    local_bin.parent.mkdir(parents=True)
    local_bin.write_text("", encoding="utf-8")

    runner = SubprocessRunner(tmp_path)
    assert runner.which("bin/tool") == str(local_bin.resolve())

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    assert runner.which("tool") == "/usr/bin/tool"


def test_which_raises_if_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(AppError, match="Command not found"):
        SubprocessRunner(tmp_path).which("missing")


def test_run_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called: list[tuple[list[str], str | None]] = []

    def fake_run(cmd: list[str], cwd: str | None = None, check: bool = True) -> None:
        called.append((cmd, cwd))

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SubprocessRunner(tmp_path)
    runner.run(["echo", "ok"], cwd=tmp_path)
    assert called == [(["echo", "ok"], str(tmp_path))]

    def fail_run(cmd: list[str], cwd: str | None = None, check: bool = True) -> None:
        raise subprocess.CalledProcessError(9, cmd)

    monkeypatch.setattr(subprocess, "run", fail_run)
    with pytest.raises(AppError, match="Command failed \\(9\\): echo ng"):
        runner.run(["echo", "ng"])


def test_check_output_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    received: list[dict[str, object]] = []

    def fake_check_output(cmd: list[str], **kwargs: object) -> str:
        received.append(kwargs)
        return "ok"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    runner = SubprocessRunner(tmp_path)
    assert runner.check_output(["cmd"]) == "ok"
    assert runner.check_output(["cmd"], stderr_to_stdout=True) == "ok"
    assert received[0] == {"text": True}
    assert received[1]["stderr"] == subprocess.STDOUT

    def fail_check_output(cmd: list[str], **kwargs: object) -> str:
        raise subprocess.CalledProcessError(3, cmd)

    monkeypatch.setattr(subprocess, "check_output", fail_check_output)
    with pytest.raises(AppError, match="Command failed \\(3\\): x"):
        runner.check_output(["x"])

