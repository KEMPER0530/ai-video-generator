from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from application.dto import CommonArgs
from application.pathing import build_paths, resolve_images_dir, resolve_scene_image, subtitles_enabled
from application.ports import ConfigRepository, MediaGateway, NarrationGateway, StoryRepository
from domain.errors import AppError
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


class VideoPipelineUseCases:
    def __init__(
        self,
        config_repo: ConfigRepository,
        story_repo: StoryRepository,
        media: MediaGateway,
        narration: NarrationGateway,
        root: Path,
        emit: Callable[[str], None] = print,
    ):
        self._config_repo = config_repo
        self._story_repo = story_repo
        self._media = media
        self._narration = narration
        self._root = root.resolve()
        self._emit = emit

    @staticmethod
    def _ensure_dir(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cli_options(args: CommonArgs) -> CliOptions:
        return CliOptions(
            no_subtitles=args.no_subtitles,
            with_subtitles=args.with_subtitles,
            max_duration_sec=args.max_duration_sec,
        )

    def doctor(self, config_path: Path) -> None:
        config = self._config_repo.load_config(config_path)
        self._emit("Doctor checks:")
        ffmpeg_bin = self._media.which(config.ffmpeg.bin)
        self._media.which("ffprobe")
        self._emit(f"- ffmpeg: OK ({ffmpeg_bin})")
        self._emit("- ffprobe: OK")
        voice = self._narration.select_voice(config.tts.voice, config.tts.engine)
        self._emit(f"- tts: OK (engine={config.tts.engine}, voice={voice})")

    def tts(self, args: CommonArgs) -> None:
        config = self._config_repo.load_config(args.config)
        story = self._story_repo.load_story(args.story)
        paths = build_paths(config, self._root)
        self._ensure_dir(paths.audio)

        ffmpeg_bin = self._media.which(config.ffmpeg.bin)
        voice = self._narration.select_voice(config.tts.voice, config.tts.engine)
        scene_files: list[Path] = []
        for idx, scene in enumerate(story.scenes, start=1):
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
        config = self._config_repo.load_config(args.config)
        story = self._story_repo.load_story(args.story)
        paths = build_paths(config, self._root)
        width = config.project.width
        height = config.project.height
        subtitle_font_px = max(38, int(height * 0.034))
        subtitle_margin_lr = max(96, int(width * 0.11))
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
                max_gap = max(0.0, (scaled_dur - len(cues) * 0.42) / (len(cues) - 1))
                gap = min(0.05, max_gap)
            usable = max(0.05, scaled_dur - gap * max(0, len(cues) - 1))
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
        config = self._config_repo.load_config(args.config)
        story_path = args.story.resolve()
        story = self._story_repo.load_story(story_path)
        paths = build_paths(config, self._root)
        ffmpeg_bin = self._media.which(config.ffmpeg.bin)

        images_dir = resolve_images_dir(args.images_dir, story_path)
        options = self._cli_options(args)
        use_subtitles = subtitles_enabled(options, config)

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
            image = resolve_scene_image(scene, story_path, idx, images_dir, self._root)
            if not image.exists():
                raise AppError(f"Missing image for scene[{idx}]: {image}")

            wav = paths.audio / f"{scene.id}.wav"
            if not wav.exists():
                raise AppError(f"Missing per-scene audio: {wav} (run: tts)")

            duration = self._media.probe_duration(wav)
            if duration <= 0.05:
                continue

            scene_images.append(image)
            scene_durations.append(duration)

        if not scene_images:
            raise AppError("No scenes to render")

        max_dur = max_duration_sec(args.max_duration_sec, config.project.max_duration_sec)
        total_dur = sum(scene_durations)
        dur_scale = calc_duration_scale(total_dur, max_dur)
        for image, duration in zip(scene_images, scene_durations):
            entries.append(f"file '{image.as_posix()}'")
            entries.append(f"duration {duration * dur_scale:.3f}")
        entries.append(entries[-2])
        concat.write_text("\n".join(entries) + "\n", encoding="utf-8")

        out_mp4 = paths.out / "output.mp4"
        width = config.project.width
        height = config.project.height
        use_source_size = config.project.use_source_size
        if use_source_size:
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
            vf_parts.insert(0, f"crop={width}:{height}")
            vf_parts.insert(0, f"scale={width}:{height}:force_original_aspect_ratio=increase")
        if use_subtitles:
            if self._media.has_filter(ffmpeg_bin, "subtitles"):
                ass_path = ass.as_posix().replace("\\", "\\\\").replace(":", "\\:")
                vf_parts.append(f"subtitles=filename={ass_path}:fontsdir=/usr/share/fonts")
            else:
                self._emit("Subtitle filter not available. Fallback to drawtext burn-in from SRT.")
                vf_parts.extend(drawtext_filters_from_srt(srt, paths.tmp / "drawtext", width, height))
        vf = ",".join(vf_parts)
        self._media.run(base_cmd[:10] + ["-vf", vf] + base_cmd[10:])
        self._emit(f"Wrote {out_mp4}")

    def all(self, args: CommonArgs) -> None:
        config = self._config_repo.load_config(args.config)
        options = self._cli_options(args)
        self.tts(args)
        if subtitles_enabled(options, config):
            self.srt(args)
        self.render(args)

    def clean(self, config_path: Path, clean_all: bool = False) -> None:
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

