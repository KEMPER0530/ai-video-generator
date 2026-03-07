from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest

from domain.errors import AppError
from infrastructure.narration_gateway import MultiEngineNarrationGateway


class DummyRunner:
    def __init__(self) -> None:
        self.outputs: dict[tuple[str, ...], str] = {}
        self.raise_check = False
        self.which_map: dict[str, str] = {"espeak-ng": "/usr/bin/espeak-ng"}
        self.run_calls: list[list[str]] = []

    def check_output(self, cmd: list[str], *, stderr_to_stdout: bool = False) -> str:
        if self.raise_check:
            raise AppError("boom")
        return self.outputs.get(tuple(cmd), "")

    def which(self, bin_name: str) -> str:
        if bin_name not in self.which_map:
            raise AppError(f"Command not found: {bin_name}")
        return self.which_map[bin_name]

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self.run_calls.append(cmd)


def _install_fake_gtts(monkeypatch: pytest.MonkeyPatch, *, save_error: Exception | None = None) -> None:
    gtts_mod = types.ModuleType("gtts")
    lang_mod = types.ModuleType("gtts.lang")
    lang_mod.tts_langs = lambda: {"ja": "Japanese", "en": "English"}  # type: ignore[attr-defined]

    class FakeGTTS:
        def __init__(self, text: str, lang: str):
            self.text = text
            self.lang = lang

        def save(self, path: str) -> None:
            if save_error is not None:
                raise save_error
            Path(path).write_text("mp3", encoding="utf-8")

    gtts_mod.gTTS = FakeGTTS  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gtts", gtts_mod)
    monkeypatch.setitem(sys.modules, "gtts.lang", lang_mod)


def test_select_voice_gtts_success_and_invalid_language(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_gtts(monkeypatch)
    gateway = MultiEngineNarrationGateway(DummyRunner())  # type: ignore[arg-type]
    assert gateway.select_voice("ja", "gtts") == "ja"
    with pytest.raises(AppError, match="Language not available for gTTS"):
        gateway.select_voice("zz", "gtts")


def test_select_voice_gtts_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fake_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if name == "gtts.lang":
            raise ImportError("missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    gateway = MultiEngineNarrationGateway(DummyRunner())  # type: ignore[arg-type]
    with pytest.raises(AppError, match="gTTS is not installed"):
        gateway.select_voice("ja", "gtts")


def test_select_voice_say_and_espeak_branches() -> None:
    runner = DummyRunner()
    gateway = MultiEngineNarrationGateway(runner)  # type: ignore[arg-type]

    runner.raise_check = True
    with pytest.raises(AppError, match="macOS `say` is not available"):
        gateway.select_voice("Kyoko", "say")
    runner.raise_check = False

    runner.outputs[("say", "-v", "?")] = "Kyoko ja_JP\nAlex en_US\n"
    assert gateway.select_voice("Kyoko", "say") == "Kyoko"
    with pytest.raises(AppError, match="Voice not available for say"):
        gateway.select_voice("Nope", "say")

    runner.raise_check = True
    with pytest.raises(AppError, match="Failed to list voices via `espeak-ng --voices`"):
        gateway.select_voice("ja", "espeak-ng")
    runner.raise_check = False

    runner.outputs[("/usr/bin/espeak-ng", "--voices")] = "ja\n"
    assert gateway.select_voice("ja", "espeak-ng") == "ja"
    with pytest.raises(AppError, match="Voice not available for espeak-ng"):
        gateway.select_voice("en", "espeak-ng")

    with pytest.raises(AppError, match="Unsupported tts.engine"):
        gateway.select_voice("ja", "unsupported")


def test_synthesize_gtts_success_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = DummyRunner()
    gateway = MultiEngineNarrationGateway(runner)  # type: ignore[arg-type]
    out_wav = tmp_path / "out.wav"

    _install_fake_gtts(monkeypatch)
    gateway.synthesize_to_wav("hello", out_wav, "ja", 170, "gtts", "ffmpeg")
    assert len(runner.run_calls) == 1
    assert runner.run_calls[0][0] == "ffmpeg"
    assert runner.run_calls[0][-1] == str(out_wav)

    original_import = builtins.__import__

    def fake_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if name == "gtts":
            raise ImportError("missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(AppError, match="gTTS is not installed"):
        gateway.synthesize_to_wav("hello", out_wav, "ja", 170, "gtts", "ffmpeg")

    monkeypatch.setattr(builtins, "__import__", original_import)
    _install_fake_gtts(monkeypatch, save_error=RuntimeError("network error"))
    with pytest.raises(AppError, match="gTTS request failed"):
        gateway.synthesize_to_wav("hello", out_wav, "ja", 170, "gtts", "ffmpeg")


def test_synthesize_say_espeak_and_unsupported(tmp_path: Path) -> None:
    runner = DummyRunner()
    gateway = MultiEngineNarrationGateway(runner)  # type: ignore[arg-type]
    out_wav = tmp_path / "out.wav"

    gateway.synthesize_to_wav("hello", out_wav, "Kyoko", 170, "say", "ffmpeg")
    assert runner.run_calls[0][0] == "say"
    assert runner.run_calls[1][0] == "ffmpeg"

    runner.run_calls.clear()
    gateway.synthesize_to_wav("hello", out_wav, "ja", 170, "espeak-ng", "ffmpeg")
    assert runner.run_calls[0][0] == "espeak-ng"
    assert runner.run_calls[1][0] == "ffmpeg"

    with pytest.raises(AppError, match="Unsupported tts.engine"):
        gateway.synthesize_to_wav("hello", out_wav, "ja", 170, "bad", "ffmpeg")

