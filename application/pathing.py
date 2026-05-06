from __future__ import annotations

from pathlib import Path

from domain.errors import AppError
from domain.models import AppConfig, CliOptions, OutputPaths, Scene


# configのout_dirを、リポジトリルート基準の絶対パスへそろえる。
def build_paths(config: AppConfig, root: Path) -> OutputPaths:
    out = Path(config.project.out_dir)
    if not out.is_absolute():
        out = root / out
    return OutputPaths(root=root, out=out, audio=out / "audio", tmp=out / "tmp")


# CLI指定があればそれを優先し、未指定ならconfigの字幕設定を使う。
def subtitles_enabled(options: CliOptions, config: AppConfig) -> bool:
    if options.no_subtitles:
        return False
    if options.with_subtitles:
        return True
    return config.subtitles.enabled


# images_dirはstoryファイルの場所からの相対指定として扱う。
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
        # story内のimage指定は、互換性のため複数の候補から実在パスを探す。
        candidates: list[Path] = []
        if images_dir is not None:
            candidates.append((images_dir / p).resolve())
            if len(p.parts) >= 2 and p.parts[0].lower() == "images":
                # imageがimages/foo.pngなら、--images-dir配下のfoo.pngも候補にする。
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
