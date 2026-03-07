from __future__ import annotations

from pathlib import Path

from domain.errors import AppError
from domain.models import AppConfig, CliOptions, OutputPaths, Scene


def build_paths(config: AppConfig, root: Path) -> OutputPaths:
    out = Path(config.project.out_dir)
    if not out.is_absolute():
        out = root / out
    return OutputPaths(root=root, out=out, audio=out / "audio", tmp=out / "tmp")


def subtitles_enabled(options: CliOptions, config: AppConfig) -> bool:
    if options.no_subtitles:
        return False
    if options.with_subtitles:
        return True
    return config.subtitles.enabled


def resolve_images_dir(images_dir_arg: str, story_path: Path) -> Path:
    path = Path(images_dir_arg)
    if path.is_absolute():
        return path
    return (story_path.parent / path).resolve()


def resolve_scene_image(
    scene: Scene,
    story_path: Path,
    index: int,
    images_dir: Path | None,
    root: Path,
) -> Path:
    image = scene.image.strip()
    sid = scene.id or f"s{index}"
    if image:
        p = Path(image)
        if p.is_absolute():
            return p
        candidates: list[Path] = []
        if images_dir is not None:
            candidates.append((images_dir / p).resolve())
            if len(p.parts) >= 2 and p.parts[0].lower() == "images":
                candidates.append((images_dir / Path(*p.parts[1:])).resolve())
        candidates.append((story_path.parent / p).resolve())
        candidates.append((root / p).resolve())
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    if images_dir is not None:
        return (images_dir / f"{sid}.png").resolve()
    raise AppError(f"scene[{index}] missing required field: image (or pass --images-dir)")

