from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from domain.errors import AppError


# 外部コマンド実行を1か所に集約し、CalledProcessErrorをAppErrorへ変換する。
class SubprocessRunner:
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir.resolve()

    def which(self, bin_name: str) -> str:
        # 相対/絶対パスで渡されたコマンドは、PATH検索より先に実ファイルを確認する。
        if "/" in bin_name or bin_name.startswith("."):
            candidate = Path(bin_name)
            if not candidate.is_absolute():
                candidate = (self._base_dir / candidate).resolve()
            if candidate.exists():
                return str(candidate)
        found = shutil.which(bin_name)
        if not found:
            raise AppError(f"Command not found: {bin_name}")
        return found

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        # check=Trueで失敗を拾い、上位層には終了コード付きで返す。
        try:
            subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)
        except subprocess.CalledProcessError as exc:
            raise AppError(f"Command failed ({exc.returncode}): {' '.join(cmd)}") from exc

    def check_output(self, cmd: list[str], *, stderr_to_stdout: bool = False) -> str:
        # ffprobeなど、標準出力をパースするコマンド用の薄いラッパー。
        kwargs: dict[str, object] = {"text": True}
        if stderr_to_stdout:
            kwargs["stderr"] = subprocess.STDOUT
        try:
            out = subprocess.check_output(cmd, **kwargs)
        except subprocess.CalledProcessError as exc:
            raise AppError(f"Command failed ({exc.returncode}): {' '.join(cmd)}") from exc
        return out
