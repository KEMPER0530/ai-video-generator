from __future__ import annotations

from typing import Optional

from .errors import AppError


def max_duration_sec(cli_value: Optional[float], config_value: float) -> Optional[float]:
    # CLI指定をconfigより優先し、0以下は「上限なし」として扱う。
    value = cli_value if cli_value is not None else config_value
    if value <= 0:
        return None
    return float(value)


def calc_duration_scale(total_duration: float, max_duration: Optional[float]) -> float:
    # 音声と画像表示時間を同じ倍率で縮めるための係数を計算する。
    if not max_duration or total_duration <= 0:
        return 1.0
    if total_duration <= max_duration:
        return 1.0
    return max_duration / total_duration


def atempo_filter(speed: float) -> str:
    # ffmpegのatempoは0.5〜2.0倍しか扱えないため、必要なら複数段に分解する。
    if speed <= 0:
        raise AppError(f"Invalid speed for atempo: {speed}")
    parts: list[str] = []
    remain = speed
    while remain > 2.0:
        parts.append("atempo=2.0")
        remain /= 2.0
    while remain < 0.5:
        parts.append("atempo=0.5")
        remain /= 0.5
    parts.append(f"atempo={remain:.6f}")
    return ",".join(parts)
