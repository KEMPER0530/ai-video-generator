#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from application.dto import CommonArgs, GenerateArgs
from domain.errors import AppError
from infrastructure.container import build_use_cases


# tts/srt/render/allで共通して使う引数を1か所にまとめる。
def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True)
    parser.add_argument("--story", required=True)
    parser.add_argument("--images-dir", required=True, help="Base directory for scene images.")
    subtitle_group = parser.add_mutually_exclusive_group()
    subtitle_group.add_argument("--no-subtitles", action="store_true", help="Disable subtitle burn-in for this run.")
    subtitle_group.add_argument("--with-subtitles", action="store_true", help="Enable subtitle burn-in for this run.")
    parser.add_argument("--max-duration-sec", type=float, default=None, help="Target max output duration in seconds.")


def build_parser() -> argparse.ArgumentParser:
    # CLIは薄く保ち、実処理はapplication層のユースケースへ委譲する。
    parser = argparse.ArgumentParser(prog="ai-video-generator")
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

    p_generate = sub.add_parser("generate", help="generate story/images, then render output.mp4")
    p_generate.add_argument("topic", nargs="?", help="Video topic. If omitted, prompt interactively.")
    p_generate.add_argument("--config", default="configs/config.docker.cpu.json")
    p_generate.add_argument("--slug", default=None, help="Fixed output prefix. Defaults to topic plus timestamp.")
    p_generate.add_argument("--scenes", type=int, default=6, help="Number of scenes/images to generate.")
    p_generate.add_argument("--stories-dir", default="stories")
    p_generate.add_argument("--images-dir", default="images")
    p_generate.add_argument("--no-render", action="store_true", help="Only generate story/images; skip mp4 rendering.")
    p_generate.add_argument("--force-images", action="store_true", help="Regenerate images even if files already exist.")
    p_generate.add_argument("--max-duration-sec", type=float, default=None, help="Target max output duration in seconds.")
    # generateは「字幕付きMP4まで」が主用途なので、字幕焼き込みを既定で有効にする。
    p_generate.set_defaults(burn_subtitles=True)
    gen_subtitles = p_generate.add_mutually_exclusive_group()
    gen_subtitles.add_argument("--with-subtitles", dest="burn_subtitles", action="store_true", help="Burn subtitles into the generated mp4.")
    gen_subtitles.add_argument("--no-subtitles", dest="burn_subtitles", action="store_false", help="Render without subtitle burn-in.")

    p_clean = sub.add_parser("clean", help="clean generated output directories")
    p_clean.add_argument("--config", default="configs/config.docker.cpu.json")
    p_clean.add_argument("--all", action="store_true", help="clean all subdirectories under outputs/")

    return parser


def _to_common_args(args: argparse.Namespace) -> CommonArgs:
    # argparseのNamespaceを、アプリケーション層が受け取りやすいDTOへ変換する。
    return CommonArgs(
        config=Path(args.config),
        story=Path(args.story),
        images_dir=args.images_dir,
        no_subtitles=bool(args.no_subtitles),
        with_subtitles=bool(args.with_subtitles),
        max_duration_sec=args.max_duration_sec,
    )


def _to_generate_args(args: argparse.Namespace) -> GenerateArgs:
    topic = args.topic
    if topic is None:
        # トピック未指定なら、ユーザーが自然に入力できる対話モードにする。
        topic = input("何について動画を生成しますか？ ").strip()
    return GenerateArgs(
        config=Path(args.config),
        topic=topic,
        slug=args.slug,
        scene_count=args.scenes,
        stories_dir=args.stories_dir,
        images_dir=args.images_dir,
        render=not bool(args.no_render),
        force_images=bool(args.force_images),
        no_subtitles=not bool(args.burn_subtitles),
        with_subtitles=bool(args.burn_subtitles),
        max_duration_sec=args.max_duration_sec,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    use_cases = build_use_cases(root=root, emit=print)

    try:
        # コマンド名ごとに対応するユースケースへ振り分ける。
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
        elif args.cmd == "generate":
            use_cases.generate(_to_generate_args(args))
        elif args.cmd == "clean":
            use_cases.clean(Path(args.config), clean_all=bool(args.all))
        else:
            parser.error(f"unsupported command: {args.cmd}")
    except AppError as exc:
        # 想定内のエラーはスタックトレースではなく、短いメッセージとして表示する。
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
