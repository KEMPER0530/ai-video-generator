from __future__ import annotations

from pathlib import Path

from domain.errors import AppError
from infrastructure.process_runner import SubprocessRunner


# ffmpeg/ffprobeに関する操作をapplication層から隠すための実装。
class FfmpegMediaGateway:
    def __init__(self, runner: SubprocessRunner):
        self._runner = runner

    def which(self, bin_name: str) -> str:
        return self._runner.which(bin_name)

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self._runner.run(cmd, cwd=cwd)

    def probe_duration(self, path: Path) -> float:
        # 音声ファイルの秒数は、字幕タイミングと画像表示時間の基準になる。
        ffprobe = self.which("ffprobe")
        out = self._runner.check_output(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]
        ).strip()
        try:
            return float(out)
        except ValueError as exc:
            raise AppError(f"Failed to parse duration from ffprobe: {out}") from exc

    def probe_image_size(self, path: Path) -> tuple[int, int]:
        # use_source_size=trueのとき、全画像のサイズ一致を検証するために使う。
        ffprobe = self.which("ffprobe")
        out = self._runner.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(path),
            ]
        ).strip()
        try:
            width_str, height_str = out.split("x", 1)
            return int(width_str), int(height_str)
        except Exception as exc:
            raise AppError(f"Failed to parse image size via ffprobe: {path} ({out})") from exc

    def has_filter(self, ffmpeg_bin: str, name: str) -> bool:
        # 環境によってsubtitlesフィルタが無い場合があるため、実行前に確認する。
        try:
            out = self._runner.check_output([ffmpeg_bin, "-hide_banner", "-filters"], stderr_to_stdout=True)
        except AppError:
            return False
        return any(name in line.split() for line in out.splitlines())
