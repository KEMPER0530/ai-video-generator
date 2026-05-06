from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from application.dto import CommonArgs, GenerateArgs
from application.pathing import build_paths, resolve_images_dir, resolve_scene_image, subtitles_enabled
from application.ports import ConfigRepository, ImageGenerator, MediaGateway, NarrationGateway, StoryPlanner, StoryRepository
from domain.errors import AppError
from domain.generation import (
    canonicalize_generated_story,
    default_generated_slug,
    generated_story_path,
    normalize_slug,
    normalize_scene_count,
    story_to_json_data,
)
from domain.models import CliOptions
from domain.subtitles import (
    cue_char_weight,
    drawtext_filters_from_srt,
    escape_ass_text,
    format_ass_time,
    format_srt_time,
    split_subtitle_cues,
)
from domain.video import atempo_filter, calc_duration_scale, max_duration_sec


# 動画生成パイプラインの手順をまとめるアプリケーションサービス。
class VideoPipelineUseCases:
    def __init__(
        self,
        config_repo: ConfigRepository,
        story_repo: StoryRepository,
        media: MediaGateway,
        narration: NarrationGateway,
        root: Path,
        emit: Callable[[str], None] = print,
        story_planner: StoryPlanner | None = None,
        image_generator: ImageGenerator | None = None,
    ):
        self._config_repo = config_repo
        self._story_repo = story_repo
        self._media = media
        self._narration = narration
        self._root = root.resolve()
        self._emit = emit
        self._story_planner = story_planner
        self._image_generator = image_generator

    @staticmethod
    def _ensure_dir(path: Path) -> None:
        # 各工程は必要な出力先を自分で作る。
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cli_options(args: CommonArgs) -> CliOptions:
        # CLI引数をドメイン層の字幕/尺判定で使う形へ変換する。
        return CliOptions(
            no_subtitles=args.no_subtitles,
            with_subtitles=args.with_subtitles,
            max_duration_sec=args.max_duration_sec,
        )

    def doctor(self, config_path: Path) -> None:
        # 外部コマンドとTTS設定が実行可能かを軽く確認する。
        config = self._config_repo.load_config(config_path)
        self._emit("Doctor checks:")
        ffmpeg_bin = self._media.which(config.ffmpeg.bin)
        self._media.which("ffprobe")
        self._emit(f"- ffmpeg: OK ({ffmpeg_bin})")
        self._emit("- ffprobe: OK")
        voice = self._narration.select_voice(config.tts.voice, config.tts.engine)
        self._emit(f"- tts: OK (engine={config.tts.engine}, voice={voice})")

    def tts(self, args: CommonArgs) -> None:
        # 各シーンのnarrationから音声を作り、最後に1本のnarration.wavへ連結する。
        config = self._config_repo.load_config(args.config)
        story = self._story_repo.load_story(args.story)
        paths = build_paths(config, self._root)
        self._ensure_dir(paths.audio)

        ffmpeg_bin = self._media.which(config.ffmpeg.bin)
        voice = self._narration.select_voice(config.tts.voice, config.tts.engine)
        scene_files: list[Path] = []
        for idx, scene in enumerate(story.scenes, start=1):
            # 空のナレーションは音声も字幕も作れないため、ここで止める。
            narration = scene.narration.strip()
            if not narration:
                raise AppError(f"scene[{idx}] missing narration")
            wav = paths.audio / f"{scene.id}.wav"
            self._narration.synthesize_to_wav(
                narration,
                wav,
                voice,
                config.tts.rate,
                config.tts.engine,
                ffmpeg_bin,
            )
            scene_files.append(wav)
            self._emit(f"TTS {scene.id}: {wav}")

        self._ensure_dir(paths.tmp)
        concat_list = paths.tmp / "concat_audio.txt"
        # ffmpeg concat demuxer用に、シーン音声の一覧ファイルを作る。
        concat_list.write_text(
            "\n".join(f"file '{wav.as_posix()}'" for wav in scene_files) + "\n",
            encoding="utf-8",
        )
        master_wav = paths.audio / "narration.wav"
        self._media.run(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(master_wav),
            ]
        )
        self._emit(f"Wrote {master_wav}")

    def srt(self, args: CommonArgs) -> None:
        # 音声の実測時間から、SRTとASS字幕の表示タイミングを作る。
        config = self._config_repo.load_config(args.config)
        story = self._story_repo.load_story(args.story)
        paths = build_paths(config, self._root)
        width = config.project.width
        height = config.project.height
        subtitle_font_px = max(38, int(height * 0.034))
        subtitle_margin_lr = max(96, int(width * 0.11))
        # 画面幅とフォントサイズから、1行に収める安全な文字数を概算する。
        safe_line_chars = max(12, int((width - 2 * subtitle_margin_lr) / max(1, subtitle_font_px)))

        durations: list[float] = []
        for idx, scene in enumerate(story.scenes, start=1):
            wav = paths.audio / f"{scene.id}.wav"
            if not wav.exists():
                raise AppError(f"Missing per-scene audio: {wav} (run: tts)")
            durations.append(self._media.probe_duration(wav))

        total_dur = sum(value for value in durations if value > 0.05)
        max_dur = max_duration_sec(args.max_duration_sec, config.project.max_duration_sec)
        dur_scale = calc_duration_scale(total_dur, max_dur)

        srt_lines: list[str] = []
        ass_events: list[str] = []
        cue_index = 1
        current_t = 0.0
        for idx, scene in enumerate(story.scenes):
            duration = durations[idx]
            text = scene.narration.strip()
            if not text or duration <= 0.05:
                continue
            scaled_dur = duration * dur_scale
            cues = split_subtitle_cues(text, width_chars=safe_line_chars, max_lines_per_cue=2)
            if not cues:
                current_t += scaled_dur
                continue
            if len(cues) <= 1:
                gap = 0.0
            else:
                # 複数キューの間に短い隙間を入れつつ、短い音声では隙間を詰める。
                max_gap = max(0.0, (scaled_dur - len(cues) * 0.42) / (len(cues) - 1))
                gap = min(0.05, max_gap)
            usable = max(0.05, scaled_dur - gap * max(0, len(cues) - 1))
            # 長い字幕ほど長く表示し、句読点を含む字幕は少し余裕を持たせる。
            weights = [cue_char_weight(cue) for cue in cues]
            total_weight = float(sum(weights))
            seg_durations = [usable * (weight / total_weight) for weight in weights]

            scene_cursor = current_t
            for cue_text, cue_duration in zip(cues, seg_durations):
                start = scene_cursor
                end = min(current_t + scaled_dur, start + cue_duration)
                if end - start < 0.10:
                    continue
                srt_lines.append(str(cue_index))
                srt_lines.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
                srt_lines.append(cue_text)
                srt_lines.append("")

                ass_events.append(
                    "Dialogue: 0,"
                    f"{format_ass_time(start)},"
                    f"{format_ass_time(end)},"
                    "Narration,,0,0,0,,"
                    r"{\an2\fad(90,110)}"
                    f"{escape_ass_text(cue_text)}"
                )
                cue_index += 1
                scene_cursor = end + gap
            current_t += scaled_dur

        self._ensure_dir(paths.out)
        out_srt = paths.out / "subtitles.srt"
        out_ass = paths.out / "subtitles.ass"
        out_srt.write_text("\n".join(srt_lines), encoding="utf-8")
        # ASSはffmpeg subtitlesフィルタで装飾付き字幕として焼き込む。
        ass_content = "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                "WrapStyle: 2",
                "ScaledBorderAndShadow: yes",
                f"PlayResX: {width}",
                f"PlayResY: {height}",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding",
                (
                    "Style: Narration,Noto Sans CJK JP,"
                    f"{subtitle_font_px},"
                    "&H00FFFFFF,&H000000FF,&H00181818,&H00000000,"
                    "0,0,0,0,100,100,0,0,1,3.2,0.4,2,"
                    f"{subtitle_margin_lr},{subtitle_margin_lr},{max(120, int(height * 0.095))},1"
                ),
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                *ass_events,
                "",
            ]
        )
        out_ass.write_text(ass_content, encoding="utf-8")
        self._emit(f"Wrote {out_srt}")
        self._emit(f"Wrote {out_ass}")

    def render(self, args: CommonArgs) -> None:
        # 画像・音声・字幕をffmpegで結合し、最終MP4を書き出す。
        config = self._config_repo.load_config(args.config)
        story_path = args.story.resolve()
        story = self._story_repo.load_story(story_path)
        paths = build_paths(config, self._root)
        ffmpeg_bin = self._media.which(config.ffmpeg.bin)

        images_dir = resolve_images_dir(args.images_dir, story_path)
        options = self._cli_options(args)
        use_subtitles = subtitles_enabled(options, config)

        # render単体実行時に足りない成果物があれば、先に必要工程を案内する。
        audio = paths.audio / "narration.wav"
        if not audio.exists():
            raise AppError(f"Missing audio: {audio} (run: tts)")

        ass = paths.out / "subtitles.ass"
        srt = paths.out / "subtitles.srt"
        if use_subtitles and (not ass.exists() or not srt.exists()):
            raise AppError(f"Missing subtitles: {ass} / {srt} (run: srt)")

        self._ensure_dir(paths.tmp)
        concat = paths.tmp / "images.txt"
        entries: list[str] = []
        scene_durations: list[float] = []
        scene_images: list[Path] = []
        for idx, scene in enumerate(story.scenes, start=1):
            # story内のimage指定と--images-dirの組み合わせから、実画像パスを解決する。
            image = resolve_scene_image(scene, story_path, idx, images_dir, self._root)
            if not image.exists():
                raise AppError(f"Missing image for scene[{idx}]: {image}")

            wav = paths.audio / f"{scene.id}.wav"
            if not wav.exists():
                raise AppError(f"Missing per-scene audio: {wav} (run: tts)")

            duration = self._media.probe_duration(wav)
            if duration <= 0.05:
                # 短すぎる音声はffmpeg concatの表示時間にできないため除外する。
                continue

            scene_images.append(image)
            scene_durations.append(duration)

        if not scene_images:
            raise AppError("No scenes to render")

        max_dur = max_duration_sec(args.max_duration_sec, config.project.max_duration_sec)
        total_dur = sum(scene_durations)
        dur_scale = calc_duration_scale(total_dur, max_dur)
        for image, duration in zip(scene_images, scene_durations):
            # 画像の表示時間は、対応するシーン音声の長さに合わせる。
            entries.append(f"file '{image.as_posix()}'")
            entries.append(f"duration {duration * dur_scale:.3f}")
        entries.append(entries[-2])
        concat.write_text("\n".join(entries) + "\n", encoding="utf-8")

        out_mp4 = paths.out / "output.mp4"
        width = config.project.width
        height = config.project.height
        use_source_size = config.project.use_source_size
        if use_source_size:
            # 元画像サイズを使う場合は、全シーン画像の解像度が一致している必要がある。
            base_w, base_h = self._media.probe_image_size(scene_images[0])
            for image in scene_images[1:]:
                w, h = self._media.probe_image_size(image)
                if (w, h) != (base_w, base_h):
                    raise AppError(
                        "All scene images must have same size when project.use_source_size=true: "
                        f"{scene_images[0]}={base_w}x{base_h}, {image}={w}x{h}"
                    )
            width, height = base_w, base_h
        fps = config.project.fps

        base_cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-i",
            str(audio),
        ]
        if dur_scale < 0.999:
            # 尺上限に収めるため、映像表示時間と音声速度を同じ倍率で圧縮する。
            speed = 1.0 / dur_scale
            base_cmd.extend(["-filter:a", atempo_filter(speed)])
            self._emit(f"Duration fit: total {total_dur:.2f}s -> target scale {dur_scale:.4f} (audio speed x{speed:.4f})")
        else:
            self._emit(f"Duration fit: total {total_dur:.2f}s (no speed change)")
        base_cmd.extend(
            [
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
            ]
        )
        if max_dur:
            base_cmd.extend(["-t", f"{max_dur:.3f}"])
        base_cmd.append(str(out_mp4))

        vf_parts: list[str] = [f"fps={fps}"]
        if not use_source_size:
            # 縦動画設定の解像度へ、拡大してから中央cropする。
            vf_parts.insert(0, f"crop={width}:{height}")
            vf_parts.insert(0, f"scale={width}:{height}:force_original_aspect_ratio=increase")
        if use_subtitles:
            if self._media.has_filter(ffmpeg_bin, "subtitles"):
                # subtitlesフィルタが使える環境ではASSをそのまま焼き込む。
                ass_path = ass.as_posix().replace("\\", "\\\\").replace(":", "\\:")
                vf_parts.append(f"subtitles=filename={ass_path}:fontsdir=/usr/share/fonts")
            else:
                # Dockerや最小ffmpeg環境ではsubtitlesが無いことがあるためdrawtextへ落とす。
                self._emit("Subtitle filter not available. Fallback to drawtext burn-in from SRT.")
                vf_parts.extend(drawtext_filters_from_srt(srt, paths.tmp / "drawtext", width, height))
        vf = ",".join(vf_parts)
        self._media.run(base_cmd[:10] + ["-vf", vf] + base_cmd[10:])
        self._emit(f"Wrote {out_mp4}")

    def all(self, args: CommonArgs) -> None:
        # 通常利用向けに、音声・字幕・レンダリングを正しい順番で実行する。
        config = self._config_repo.load_config(args.config)
        options = self._cli_options(args)
        self.tts(args)
        if subtitles_enabled(options, config):
            self.srt(args)
        self.render(args)

    def generate(self, args: GenerateArgs) -> None:
        # テーマから台本と画像を作り、そのまま既存のallパイプラインへ渡す。
        if self._story_planner is None:
            raise AppError("Story planner is not configured")
        if self._image_generator is None:
            raise AppError("Image generator is not configured")

        config = self._config_repo.load_config(args.config)
        paths = build_paths(config, self._root)
        scene_count = normalize_scene_count(args.scene_count)
        topic = args.topic.strip()
        if not topic:
            raise AppError("topic is required")
        # slugは台本ファイル名・画像ファイル名・scene idの共通接頭辞として使う。
        # 未指定時は実行時刻を含め、同じテーマの再生成で上書きしないようにする。
        slug = normalize_slug(args.slug.strip()) if args.slug else default_generated_slug(topic)

        tmp_dir = paths.tmp / "generate" / slug
        story = self._story_planner.plan_story(topic, slug, scene_count, self._root, tmp_dir)
        # Codex出力の揺れを、保存前にリポジトリ側の規約へそろえる。
        story = canonicalize_generated_story(story, topic, slug, scene_count, args.images_dir)

        story_path = generated_story_path(self._root, args.stories_dir, slug)
        self._ensure_dir(story_path.parent)
        story_path.write_text(json.dumps(story_to_json_data(story), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._emit(f"Wrote {story_path}")

        total = len(story.scenes)
        for idx, scene in enumerate(story.scenes, start=1):
            image_path = self._root / scene.image
            if image_path.exists() and not args.force_images:
                # 既存画像を残せるようにし、必要時だけ--force-imagesで作り直す。
                self._emit(f"Image exists, skipping: {image_path}")
                continue
            self._image_generator.generate_image(topic, scene, idx, total, image_path, self._root)
            self._emit(f"Wrote {image_path}")

        if args.render:
            # 生成したstory/imagesを入力として、既存の動画生成フローを再利用する。
            self.all(
                CommonArgs(
                    config=args.config,
                    story=story_path,
                    images_dir=args.images_dir,
                    no_subtitles=args.no_subtitles,
                    with_subtitles=args.with_subtitles,
                    max_duration_sec=args.max_duration_sec,
                )
            )

    def clean(self, config_path: Path, clean_all: bool = False) -> None:
        # 出力物だけを削除し、入力のstories/imagesは触らない。
        outputs_root = self._root / "outputs"
        self._ensure_dir(outputs_root)
        if clean_all:
            for child in outputs_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            self._emit(f"Cleaned all outputs under: {outputs_root}")
            return
        config = self._config_repo.load_config(config_path)
        paths = build_paths(config, self._root)
        if paths.out.exists():
            shutil.rmtree(paths.out)
        self._ensure_dir(paths.out)
        self._emit(f"Cleaned output dir: {paths.out}")
