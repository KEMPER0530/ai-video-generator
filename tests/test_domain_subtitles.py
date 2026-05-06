from __future__ import annotations

# 字幕の時刻変換、分割、drawtextフォールバックを確認する。
from pathlib import Path

import pytest

from domain.errors import AppError
from domain import subtitles as mod


def test_time_format_and_parse() -> None:
    assert mod.format_srt_time(-1.0) == "00:00:00,000"
    assert mod.format_srt_time(3661.234) == "01:01:01,234"
    assert mod.format_ass_time(-1.0) == "0:00:00.00"
    assert mod.format_ass_time(3661.23) == "1:01:01.23"
    assert mod.srt_time_to_sec("00:00:01,500") == 1.5
    with pytest.raises(AppError, match="Invalid SRT time"):
        mod.srt_time_to_sec("00:00:01.500")


def test_parse_srt(tmp_path: Path) -> None:
    srt = tmp_path / "sub.srt"
    srt.write_text(
        "\n".join(
            [
                "only index",
                "",
                "1",
                "00:00:00,000 --> 00:00:01,000",
                "hello",
                "",
                "2",
                "invalid",
                "skip",
                "",
                "3",
                "00:00:02,000 --> 00:00:01,000",
                "skip",
                "",
            ]
        ),
        encoding="utf-8",
    )
    cues = mod.parse_srt(srt)
    assert cues == [(0.0, 1.0, "hello")]


def test_parse_srt_raises_for_invalid_time(tmp_path: Path) -> None:
    srt = tmp_path / "sub.srt"
    srt.write_text("1\n00:00:00,000 --> x\nhello\n", encoding="utf-8")
    with pytest.raises(AppError, match="Invalid SRT time"):
        mod.parse_srt(srt)


def test_escape_and_caption_wrapping() -> None:
    assert mod.escape_ass_text(r"a\b{c}" + "\n" + "x") == r"a\\b\{c\}\Nx"
    text = "これはとても長い文章です。\n。\nあ"
    wrapped = mod.caption_from_narration(text, width_chars=8)
    assert "。" in wrapped
    assert "\n。\n" not in wrapped
    assert mod.caption_from_narration("abc\n\n。", width_chars=20) == "abc。"


def test_split_subtitle_cues_and_weight() -> None:
    cues = mod.split_subtitle_cues("短い。次の文。", width_chars=10, max_lines_per_cue=1)
    assert len(cues) >= 1
    assert mod.split_subtitle_cues("   ") == []
    assert mod.split_subtitle_cues("。。", width_chars=10, max_lines_per_cue=1)
    assert mod.cue_char_weight("a、b。c!?") > len("a、b。c!?")


def test_split_subtitle_cues_skips_empty_wrapped_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "caption_from_narration", lambda text, width_chars=22: "   ")
    assert mod.split_subtitle_cues("有効なテキスト", width_chars=10, max_lines_per_cue=1) == []


def test_find_fontfile_and_drawtext_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_font = mod.find_fontfile(candidates=("missing1", "missing2"))
    assert no_font is None

    existing = tmp_path / "font.ttf"
    existing.write_text("x", encoding="utf-8")
    assert mod.find_fontfile(candidates=(str(existing),)) == existing

    srt = tmp_path / "sub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

    monkeypatch.setattr(mod, "find_fontfile", lambda candidates=None: existing)
    filters = mod.drawtext_filters_from_srt(srt, tmp_path / "tmp", 1080, 1920)
    assert filters
    assert "fontfile=" in filters[0]

    monkeypatch.setattr(mod, "find_fontfile", lambda candidates=None: None)
    filters_no_font = mod.drawtext_filters_from_srt(srt, tmp_path / "tmp2", 1080, 1920)
    assert filters_no_font
    assert "fontfile=" not in filters_no_font[0]
