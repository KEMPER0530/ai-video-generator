from __future__ import annotations

from pathlib import Path

from domain.errors import AppError
from infrastructure.process_runner import SubprocessRunner


class FfmpegMediaGateway:
    def __init__(self, runner: SubprocessRunner):
        self._runner = runner

    def which(self, bin_name: str) -> str:
        return self._runner.which(bin_name)

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self._runner.run(cmd, cwd=cwd)

    def probe_duration(self, path: Path) -> float:
        ffprobe = self.which("ffprobe")
        out = self._runner.check_output(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]
        ).strip()
        try:
            return float(out)
        except ValueError as exc:
            raise AppError(f"Failed to parse duration from ffprobe: {out}") from exc

    def probe_image_size(self, path: Path) -> tuple[int, int]:
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
        try:
            out = self._runner.check_output([ffmpeg_bin, "-hide_banner", "-filters"], stderr_to_stdout=True)
        except AppError:
            return False
        return any(name in line.split() for line in out.splitlines())

