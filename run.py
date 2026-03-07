#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from application.dto import CommonArgs
from domain.errors import AppError
from infrastructure.container import build_use_cases


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True)
    parser.add_argument("--story", required=True)
    parser.add_argument("--images-dir", required=True, help="Base directory for scene images.")
    parser.add_argument("--no-subtitles", action="store_true", help="Disable subtitle burn-in for this run.")
    parser.add_argument("--with-subtitles", action="store_true", help="Enable subtitle burn-in for this run.")
    parser.add_argument("--max-duration-sec", type=float, default=None, help="Target max output duration in seconds.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-video-generator/run.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doc = sub.add_parser("doctor", help="check local dependencies")
    p_doc.add_argument("--config", required=True)

    p_tts = sub.add_parser("tts", help="generate per-scene TTS + narration.wav")
    _add_common(p_tts)

    p_srt = sub.add_parser("srt", help="create subtitles.srt from scene timings")
    _add_common(p_srt)

    p_render = sub.add_parser("render", help="render output.mp4 via ffmpeg")
    _add_common(p_render)

    p_all = sub.add_parser("all", help="run tts -> srt -> render")
    _add_common(p_all)

    p_clean = sub.add_parser("clean", help="clean generated output directories")
    p_clean.add_argument("--config", default="configs/config.docker.cpu.json")
    p_clean.add_argument("--all", action="store_true", help="clean all subdirectories under outputs/")

    return parser


def _to_common_args(args: argparse.Namespace) -> CommonArgs:
    return CommonArgs(
        config=Path(args.config),
        story=Path(args.story),
        images_dir=args.images_dir,
        no_subtitles=bool(args.no_subtitles),
        with_subtitles=bool(args.with_subtitles),
        max_duration_sec=args.max_duration_sec,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    use_cases = build_use_cases(root=root, emit=print)

    try:
        if args.cmd == "doctor":
            use_cases.doctor(Path(args.config))
        elif args.cmd == "tts":
            use_cases.tts(_to_common_args(args))
        elif args.cmd == "srt":
            use_cases.srt(_to_common_args(args))
        elif args.cmd == "render":
            use_cases.render(_to_common_args(args))
        elif args.cmd == "all":
            use_cases.all(_to_common_args(args))
        elif args.cmd == "clean":
            use_cases.clean(Path(args.config), clean_all=bool(args.all))
        else:
            parser.error(f"unsupported command: {args.cmd}")
    except AppError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
