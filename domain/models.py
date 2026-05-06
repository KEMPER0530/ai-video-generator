from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AppError


# 1シーン分の入力データ。imageは台本JSON上の相対/絶対パス文字列。
@dataclass(frozen=True)
class Scene:
    id: str
    image: str
    on_screen_text: str
    narration: str
    keywords: tuple[str, ...]


# 動画全体の台本。各処理はこのStoryを中心に進む。
@dataclass(frozen=True)
class Story:
    title: str
    scenes: tuple[Scene, ...]


# 出力解像度、fps、尺調整など動画生成全体の設定。
@dataclass(frozen=True)
class ProjectConfig:
    out_dir: str
    width: int
    height: int
    fps: int
    use_source_size: bool
    max_duration_sec: float


# TTSエンジンごとの声・速度設定。
@dataclass(frozen=True)
class TtsConfig:
    engine: str
    voice: str
    rate: int


# 字幕焼き込みの既定値。
@dataclass(frozen=True)
class SubtitlesConfig:
    enabled: bool


# ffmpegコマンド名を環境に合わせて差し替えるための設定。
@dataclass(frozen=True)
class FfmpegConfig:
    bin: str


# config JSONをパースした後にアプリ全体で使う設定。
@dataclass(frozen=True)
class AppConfig:
    project: ProjectConfig
    tts: TtsConfig
    subtitles: SubtitlesConfig
    ffmpeg: FfmpegConfig


# out_dirから派生する成果物ディレクトリ群。
@dataclass(frozen=True)
class OutputPaths:
    root: Path
    out: Path
    audio: Path
    tmp: Path


# CLIで一時的に上書きできる実行オプション。
@dataclass(frozen=True)
class CliOptions:
    no_subtitles: bool = False
    with_subtitles: bool = False
    max_duration_sec: float | None = None


def _as_int(value: Any, label: str) -> int:
    # JSON由来の値を明示的にintへ寄せ、失敗時はユーザー向けエラーにする。
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{label} must be an integer") from exc


def _as_float(value: Any, label: str) -> float:
    # JSONでは数値/文字列どちらで来ても扱えるようにする。
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{label} must be a number") from exc


def _as_bool(value: Any, label: str) -> bool:
    # configではtrue/falseだけでなく、"yes"や"1"のような表記も許容する。
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise AppError(f"{label} must be a boolean")


def parse_config(data: dict[str, Any]) -> AppConfig:
    # 欠けている設定は既定値で補い、危険な値だけ明示的に弾く。
    project_raw = data.get("project", {}) or {}
    tts_raw = data.get("tts", {}) or {}
    subtitles_raw = data.get("subtitles", {}) or {}
    ffmpeg_raw = data.get("ffmpeg", {}) or {}

    engine = str(tts_raw.get("engine", "gtts")).strip().lower()
    if engine not in {"gtts", "say", "espeak-ng"}:
        raise AppError("tts.engine must be one of: gtts, say, espeak-ng")

    return AppConfig(
        project=ProjectConfig(
            out_dir=str(project_raw.get("out_dir", "outputs/docker-all")),
            width=_as_int(project_raw.get("width", 1080), "project.width"),
            height=_as_int(project_raw.get("height", 1920), "project.height"),
            fps=_as_int(project_raw.get("fps", 24), "project.fps"),
            use_source_size=_as_bool(project_raw.get("use_source_size", True), "project.use_source_size"),
            max_duration_sec=_as_float(project_raw.get("max_duration_sec", 0), "project.max_duration_sec"),
        ),
        tts=TtsConfig(
            engine=engine,
            voice=str(tts_raw.get("voice", "ja")),
            rate=_as_int(tts_raw.get("rate", 170), "tts.rate"),
        ),
        subtitles=SubtitlesConfig(enabled=_as_bool(subtitles_raw.get("enabled", True), "subtitles.enabled")),
        ffmpeg=FfmpegConfig(bin=str(ffmpeg_raw.get("bin", "ffmpeg"))),
    )


def _parse_keywords(raw: Any) -> tuple[str, ...]:
    # keywordsは配列でも文字列でも受け取り、字幕強調に使いやすい形へ正規化する。
    if isinstance(raw, list):
        return tuple(str(x).strip() for x in raw if str(x).strip())
    if isinstance(raw, str):
        tokens = [x.strip() for x in raw.replace("，", ",").replace("／", "/").replace("・", " ").split(",")]
        out: list[str] = []
        for token in tokens:
            out.extend([piece for piece in token.split() if piece])
        return tuple(out)
    return tuple()


def parse_story(data: dict[str, Any]) -> Story:
    # 台本JSONは最低限scenes配列を要求し、各シーンはSceneへ変換する。
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        raise AppError("story.scenes must be a list")

    scenes: list[Scene] = []
    for idx, item in enumerate(scenes_raw, start=1):
        if not isinstance(item, dict):
            raise AppError(f"scene[{idx}] must be an object")
        sid = str(item.get("id") or f"s{idx}")
        scenes.append(
            Scene(
                id=sid,
                image=str(item.get("image", "")).strip(),
                on_screen_text=str(item.get("on_screen_text", "")).strip(),
                narration=str(item.get("narration", "")).strip(),
                keywords=_parse_keywords(item.get("keywords")),
            )
        )

    return Story(title=str(data.get("title", "")).strip(), scenes=tuple(scenes))
