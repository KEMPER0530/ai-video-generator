#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# このスクリプトは「台本JSON + 画像」から動画を作るCLIです。
# 主な流れは次の3段階です。
# 1) TTSでシーンごとの音声を作る
# 2) 必要なら字幕ファイル(SRT/ASS)を作る
# 3) 画像と音声をFFmpegで結合してMP4を作る

def _die(msg: str) -> None:
    """エラーメッセージを表示して、異常終了します。"""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def _load_json(path: Path) -> Dict[str, Any]:
    """JSONファイルを読み込み、dictとして返します。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _die(f"Missing file: {path}")
    except json.JSONDecodeError as e:
        _die(f"Invalid JSON: {path} ({e})")


def _ensure_dir(path: Path) -> None:
    """ディレクトリが無ければ作成します。"""
    path.mkdir(parents=True, exist_ok=True)


def _which(bin_name: str) -> str:
    """実行コマンドのパスを解決します。見つからなければ終了します。"""
    if "/" in bin_name or bin_name.startswith("."):
        base = Path(__file__).resolve().parent
        cand = (base / bin_name).resolve() if not os.path.isabs(bin_name) else Path(bin_name)
        if cand.exists():
            return str(cand)
    found = shutil.which(bin_name)
    if not found:
        _die(f"Command not found: {bin_name}")
    return found


def _run(cmd: List[str], *, cwd: Optional[Path] = None) -> None:
    """外部コマンドを実行します。失敗したら終了します。"""
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)
    except subprocess.CalledProcessError as e:
        _die(f"Command failed ({e.returncode}): {' '.join(cmd)}")


@dataclass(frozen=True)
class Paths:
    root: Path
    out: Path
    audio: Path
    tmp: Path


def _paths(config: Dict[str, Any]) -> Paths:
    """設定ファイルから出力先ディレクトリ群を組み立てます。"""
    root = Path(__file__).resolve().parent
    out_dir = str(config["project"]["out_dir"])
    out = Path(out_dir) if os.path.isabs(out_dir) else (root / out_dir)
    return Paths(root=root, out=out, audio=out / "audio", tmp=out / "tmp")


def _tts_engine(config: Dict[str, Any]) -> str:
    """設定からTTSエンジン名を取得し、値を検証します。"""
    tts = config.get("tts", {})
    engine = str(tts.get("engine", "gtts")).strip().lower()
    if engine not in {"say", "espeak-ng", "gtts"}:
        _die("tts.engine must be one of: gtts, say, espeak-ng")
    return engine


def _select_voice(voice: str, engine: str) -> str:
    """選択されたTTSエンジンで利用可能な音声/言語か確認します。"""
    if engine == "gtts":
        try:
            from gtts.lang import tts_langs
        except Exception:
            _die("gTTS is not installed")
        langs = tts_langs()
        if voice not in langs:
            _die(f"Language not available for gTTS: {voice}")
        return voice
    if engine == "say":
        try:
            out = subprocess.check_output(["say", "-v", "?"], text=True)
        except Exception:
            _die("macOS `say` is not available")
        voices = {line.split()[0] for line in out.splitlines() if line.strip()}
        if voice not in voices:
            _die(f"Voice not available for say: {voice} (try: `say -v ?`)")
        return voice
    if engine == "espeak-ng":
        bin_path = _which("espeak-ng")
        try:
            out = subprocess.check_output([bin_path, "--voices"], text=True)
        except Exception:
            _die("Failed to list voices via `espeak-ng --voices`")
        if voice not in out:
            _die(f"Voice not available for espeak-ng: {voice} (try: `espeak-ng --voices`)")
        return voice
    _die(f"Unsupported tts.engine: {engine}")
    return voice


def _ffmpeg_convert_to_wav(ffmpeg_bin: str, in_path: Path, out_wav: Path) -> None:
    """音声ファイルを16kHz/モノラル/WAVに変換します。"""
    _ensure_dir(out_wav.parent)
    _run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(in_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(out_wav),
        ]
    )


def _tts_to_wav(text: str, out_wav: Path, voice: str, rate: int, engine: str, ffmpeg_bin: str) -> None:
    """テキストからWAV音声を生成します（gTTS/say/espeak-ng対応）。"""
    _ensure_dir(out_wav.parent)
    if engine == "gtts":
        try:
            from gtts import gTTS
        except Exception:
            _die("gTTS is not installed")
        tmp_mp3 = out_wav.with_suffix(".gtts.mp3")
        try:
            gTTS(text=text, lang=voice).save(str(tmp_mp3))
        except Exception as e:
            _die(f"gTTS request failed: {e}")
        _ffmpeg_convert_to_wav(ffmpeg_bin, tmp_mp3, out_wav)
        return
    if engine == "say":
        aiff = out_wav.with_suffix(".aiff")
        _run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text])
        _ffmpeg_convert_to_wav(ffmpeg_bin, aiff, out_wav)
        return
    if engine == "espeak-ng":
        tmp_wav = out_wav.with_suffix(".espeak.wav")
        _run(["espeak-ng", "-v", voice, "-s", str(rate), "-w", str(tmp_wav), text])
        _ffmpeg_convert_to_wav(ffmpeg_bin, tmp_wav, out_wav)
        return
    _die(f"Unsupported tts.engine: {engine}")


def _probe_duration(path: Path) -> float:
    """ffprobeで音声/動画の長さ（秒）を取得します。"""
    ffprobe = _which("ffprobe")
    out = subprocess.check_output(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    ).strip()
    try:
        return float(out)
    except ValueError:
        _die(f"Failed to parse duration from ffprobe: {out}")


def _probe_image_size(path: Path) -> Tuple[int, int]:
    """ffprobeで画像の幅と高さを取得します。"""
    ffprobe = _which("ffprobe")
    out = subprocess.check_output(
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
        ],
        text=True,
    ).strip()
    try:
        w_str, h_str = out.split("x", 1)
        return int(w_str), int(h_str)
    except Exception:
        _die(f"Failed to parse image size via ffprobe: {path} ({out})")
    return 0, 0


def _max_duration_sec(args: argparse.Namespace, config: Dict[str, Any]) -> Optional[float]:
    """CLI引数とconfigから、動画の最大尺（秒）を決定します。"""
    if getattr(args, "max_duration_sec", None) is not None:
        v = float(args.max_duration_sec)
    else:
        v = float(config.get("project", {}).get("max_duration_sec", 0) or 0)
    if v <= 0:
        return None
    return v


def _calc_duration_scale(total_duration: float, max_duration_sec: Optional[float]) -> float:
    """最大尺に収めるための倍率を計算します。"""
    if not max_duration_sec or total_duration <= 0:
        return 1.0
    if total_duration <= max_duration_sec:
        return 1.0
    return max_duration_sec / total_duration


def _atempo_filter(speed: float) -> str:
    """FFmpegのatempoフィルタ文字列を作成します。"""
    # speed > 1.0 means faster playback (shorter duration)
    if speed <= 0:
        _die(f"Invalid speed for atempo: {speed}")
    parts: List[str] = []
    remain = speed
    while remain > 2.0:
        parts.append("atempo=2.0")
        remain /= 2.0
    while remain < 0.5:
        parts.append("atempo=0.5")
        remain /= 0.5
    parts.append(f"atempo={remain:.6f}")
    return ",".join(parts)


def _format_srt_time(sec: float) -> str:
    """秒をSRT形式の時刻文字列へ変換します。"""
    if sec < 0:
        sec = 0
    ms_total = int(round(sec * 1000.0))
    ms = ms_total % 1000
    s_total = ms_total // 1000
    s = s_total % 60
    m_total = s_total // 60
    m = m_total % 60
    h = m_total // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_ass_time(sec: float) -> str:
    """秒をASS形式の時刻文字列へ変換します。"""
    if sec < 0:
        sec = 0
    cs_total = int(round(sec * 100.0))
    cs = cs_total % 100
    s_total = cs_total // 100
    s = s_total % 60
    m_total = s_total // 60
    m = m_total % 60
    h = m_total // 60
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass_text(text: str) -> str:
    """ASS字幕で壊れやすい文字をエスケープします。"""
    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{").replace("}", r"\}")
    text = text.replace("\n", r"\N")
    return text


def _caption_from_narration(text: str, width_chars: int = 22) -> str:
    """字幕を見やすくするために改行・折り返しを行います。"""
    # Keep explicit line breaks and wrap long lines for readability.
    chunks: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        chunks.extend(textwrap.wrap(line, width=width_chars, break_long_words=True, replace_whitespace=False))
    return "\n".join(chunks)


def _split_tokens(text: str) -> List[str]:
    """キーワード抽出用に、日本語/英語トークンへ分割します。"""
    # Japanese/English mixed token extraction for keyword fallback.
    patterns = [
        r"[A-Za-z0-9][A-Za-z0-9+\-]{1,15}",
        r"[ァ-ヶー]{2,16}",
        r"[一-龥々〆ヵヶ]{2,10}",
    ]
    tokens: List[str] = []
    for p in patterns:
        tokens.extend(re.findall(p, text))
    return tokens


def _extract_scene_keywords(scene: Dict[str, Any], max_keywords: int = 3) -> List[str]:
    """シーンごとの強調キーワードを取得します。"""
    explicit = scene.get("keywords")
    tokens: List[str] = []
    if isinstance(explicit, list):
        tokens = [str(x).strip() for x in explicit if str(x).strip()]
    elif isinstance(explicit, str):
        tokens = [x.strip() for x in re.split(r"[、,，/／・\s]+", explicit) if x.strip()]

    if not tokens:
        seed = []
        on_screen = str(scene.get("on_screen_text") or "").strip()
        narration = str(scene.get("narration") or "").strip()
        if on_screen:
            seed.append(on_screen)
        if narration:
            seed.append(narration)
        tokens = _split_tokens(" ".join(seed))

    stop = {
        "これ",
        "それ",
        "ため",
        "こと",
        "よう",
        "今回",
        "基本",
        "必要",
        "可能",
        "です",
        "ます",
    }
    out: List[str] = []
    seen: set[str] = set()
    for t in tokens:
        t = t.strip("「」『』()（）[]【】.,、。!！?？")
        if len(t) < 2 or t in stop:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_keywords:
            break
    if out:
        return out
    return [str(scene.get("id") or "ポイント")]


def _resolve_images_dir(images_dir_arg: str, story_path: Path) -> Path:
    """--images-dirをstoryファイル基準で絶対パスへ変換します。"""
    p = Path(images_dir_arg)
    if p.is_absolute():
        return p
    return (story_path.parent / p).resolve()


def _subtitles_enabled(args: argparse.Namespace, config: Dict[str, Any]) -> bool:
    """字幕を出すかどうかをCLI引数とconfigから判定します。"""
    if getattr(args, "no_subtitles", False):
        return False
    if getattr(args, "with_subtitles", False):
        return True
    return bool(config.get("subtitles", {}).get("enabled", True))


def _resolve_scene_image(
    scene: Dict[str, Any],
    story_path: Path,
    index: int,
    images_dir: Optional[Path],
) -> Path:
    """シーンのimage指定から実ファイルパスを解決します。"""
    image = str(scene.get("image", "")).strip()
    sid = str(scene.get("id") or f"s{index}")

    if image:
        p = Path(image)
        if p.is_absolute():
            return p
        candidates: List[Path] = []
        if images_dir is not None:
            candidates.append((images_dir / p).resolve())
            # Avoid duplicated "images/images/..." when image path already starts with "images/".
            if len(p.parts) >= 2 and p.parts[0].lower() == "images":
                candidates.append((images_dir / Path(*p.parts[1:])).resolve())
        candidates.append((story_path.parent / p).resolve())
        # Also try repository root (same directory as run.py) for common `images/...` layout.
        candidates.append((Path(__file__).resolve().parent / p).resolve())

        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    if images_dir is not None:
        return (images_dir / f"{sid}.png").resolve()

    _die(f"scene[{index}] missing required field: image (or pass --images-dir)")
    return Path("/")


def cmd_doctor(args: argparse.Namespace) -> None:
    """依存コマンドとTTS設定をチェックします。"""
    config = _load_json(Path(args.config))
    print("Doctor checks:")

    ffmpeg_bin = _which(str(config["ffmpeg"]["bin"]))
    _which("ffprobe")
    print(f"- ffmpeg: OK ({ffmpeg_bin})")
    print("- ffprobe: OK")

    engine = _tts_engine(config)
    voice = _select_voice(str(config["tts"]["voice"]), engine)
    print(f"- tts: OK (engine={engine}, voice={voice})")


def cmd_tts(args: argparse.Namespace) -> None:
    """シーンごとの音声と結合済みナレーション音声を作成します。"""
    config = _load_json(Path(args.config))
    story = _load_json(Path(args.story))
    p = _paths(config)
    _ensure_dir(p.audio)

    ffmpeg_bin = _which(str(config["ffmpeg"]["bin"]))
    engine = _tts_engine(config)
    voice = _select_voice(str(config["tts"]["voice"]), engine)
    rate = int(config["tts"]["rate"])

    scene_files: List[Tuple[str, Path]] = []
    for i, scene in enumerate(story["scenes"], start=1):
        sid = str(scene.get("id") or f"s{i}")
        narration = str(scene.get("narration", "")).strip()
        if not narration:
            _die(f"scene[{i}] missing narration")
        wav = p.audio / f"{sid}.wav"
        _tts_to_wav(narration, wav, voice, rate, engine, ffmpeg_bin)
        scene_files.append((sid, wav))
        print(f"TTS {sid}: {wav}")

    concat_list = p.tmp / "concat_audio.txt"
    _ensure_dir(p.tmp)
    concat_list.write_text(
        "\n".join([f"file '{wav.as_posix()}'" for _, wav in scene_files]) + "\n",
        encoding="utf-8",
    )

    master_wav = p.audio / "narration.wav"
    _run(
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
    print(f"Wrote {master_wav}")


def cmd_srt(args: argparse.Namespace) -> None:
    """字幕ファイル（SRT/ASS）を作成します。"""
    config = _load_json(Path(args.config))
    story = _load_json(Path(args.story))
    p = _paths(config)
    width = int(config["project"]["width"])
    height = int(config["project"]["height"])

    srt_lines: List[str] = []
    ass_events: List[str] = []
    idx = 1
    t = 0.0
    durations: List[float] = []
    scenes_buf: List[Dict[str, Any]] = []
    for i, scene in enumerate(story["scenes"], start=1):
        sid = str(scene.get("id") or f"s{i}")
        wav = p.audio / f"{sid}.wav"
        if not wav.exists():
            _die(f"Missing per-scene audio: {wav} (run: tts)")
        durations.append(_probe_duration(wav))
        scenes_buf.append(scene)

    # 各シーンの元の長さ合計を計算し、必要なら1分などの上限に合わせて縮める倍率を作ります。
    total_dur = sum(d for d in durations if d > 0.05)
    dur_scale = _calc_duration_scale(total_dur, _max_duration_sec(args, config))

    for i, scene in enumerate(scenes_buf, start=1):
        dur = durations[i - 1]
        text = str(scene.get("narration") or "").strip()
        if not text or dur <= 0.05:
            continue
        scaled_dur = dur * dur_scale
        srt_lines.append(str(idx))
        srt_lines.append(f"{_format_srt_time(t)} --> {_format_srt_time(t + scaled_dur)}")
        srt_lines.append(text)
        srt_lines.append("")

        keywords = _extract_scene_keywords(scene, max_keywords=3)
        # 1シーン内でキーワードを順番に表示するため、1キーワードあたりの表示時間を計算します。
        segment = max(scaled_dur / max(1, len(keywords)), 0.35)
        for ki, kw in enumerate(keywords):
            ks = t + ki * segment
            ke = min(t + scaled_dur, ks + segment)
            if (ke - ks) < 0.25:
                continue
            wrapped_kw = _caption_from_narration(kw, width_chars=8)
            ass_kw = _escape_ass_text(wrapped_kw)
            # Pop-in animation + fade for emphasized keyword captions.
            effect = r"{\an5\fscx65\fscy65\t(0,220,\fscx106\fscy106)\fad(120,180)}"
            ass_events.append(
                "Dialogue: 0,"
                f"{_format_ass_time(ks)},"
                f"{_format_ass_time(ke)},"
                "Keyword,,0,0,0,,"
                f"{effect}{ass_kw}"
            )
        idx += 1
        t += scaled_dur

    out_srt = p.out / "subtitles.srt"
    out_ass = p.out / "subtitles.ass"
    _ensure_dir(p.out)
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
                "Style: Keyword,Noto Sans CJK JP,"
                f"{max(52, int(height * 0.06))},"
                "&H00FFFFFF,&H000000FF,&H00101010,&H70000000,"
                "1,0,0,0,100,100,0,0,1,3.8,0.6,5,"
                f"{max(56, int(width * 0.06))},{max(56, int(width * 0.06))},{max(110, int(height * 0.09))},1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *ass_events,
            "",
        ]
    )
    out_ass.write_text(ass_content, encoding="utf-8")
    print(f"Wrote {out_srt}")
    print(f"Wrote {out_ass}")


def cmd_render(args: argparse.Namespace) -> None:
    """画像・音声・字幕を組み合わせて最終MP4を作成します。"""
    config = _load_json(Path(args.config))
    story_path = Path(args.story).resolve()
    story = _load_json(story_path)
    p = _paths(config)
    ffmpeg_bin = _which(str(config["ffmpeg"]["bin"]))

    images_dir = _resolve_images_dir(args.images_dir, story_path)
    use_subtitles = _subtitles_enabled(args, config)

    audio = p.audio / "narration.wav"
    if not audio.exists():
        _die(f"Missing audio: {audio} (run: tts)")

    ass = p.out / "subtitles.ass"
    if use_subtitles and not ass.exists():
        _die(f"Missing subtitles: {ass} (run: srt)")

    concat = p.tmp / "images.txt"
    _ensure_dir(p.tmp)

    entries: List[str] = []
    scene_durations: List[float] = []
    scene_images: List[Path] = []
    for i, scene in enumerate(story["scenes"], start=1):
        sid = str(scene.get("id") or f"s{i}")
        img = _resolve_scene_image(scene, story_path, i, images_dir)
        if not img.exists():
            _die(f"Missing image for scene[{i}]: {img}")

        wav = p.audio / f"{sid}.wav"
        if not wav.exists():
            _die(f"Missing per-scene audio: {wav} (run: tts)")

        dur = _probe_duration(wav)
        if dur <= 0.05:
            continue

        scene_durations.append(dur)
        scene_images.append(img)

    if not scene_images:
        _die("No scenes to render")

    max_dur = _max_duration_sec(args, config)
    total_dur = sum(scene_durations)
    dur_scale = _calc_duration_scale(total_dur, max_dur)
    # concat用リストを作成。duration を調整することで画像切り替えのテンポを統一します。
    for img, dur in zip(scene_images, scene_durations):
        entries.append(f"file '{img.as_posix()}'")
        entries.append(f"duration {dur * dur_scale:.3f}")
    entries.append(entries[-2])
    concat.write_text("\n".join(entries) + "\n", encoding="utf-8")

    out_mp4 = p.out / "output.mp4"
    use_source_size = bool(config.get("project", {}).get("use_source_size", True))
    width = int(config["project"]["width"])
    height = int(config["project"]["height"])
    if use_source_size:
        base_w, base_h = _probe_image_size(scene_images[0])
        for img in scene_images[1:]:
            w, h = _probe_image_size(img)
            if (w, h) != (base_w, base_h):
                _die(
                    "All scene images must have same size when project.use_source_size=true: "
                    f"{scene_images[0]}={base_w}x{base_h}, {img}={w}x{h}"
                )
        width, height = base_w, base_h
    fps = int(config["project"]["fps"])

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
    # 動画尺を縮めた場合、音声側も同じ比率で速くして長さを合わせます。
    if dur_scale < 0.999:
        speed = 1.0 / dur_scale
        base_cmd.extend(["-filter:a", _atempo_filter(speed)])
        print(f"Duration fit: total {total_dur:.2f}s -> target scale {dur_scale:.4f} (audio speed x{speed:.4f})")
    else:
        print(f"Duration fit: total {total_dur:.2f}s (no speed change)")
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

    # 映像フィルタの組み立て。必要に応じてサイズ変換や字幕焼き込みを追加します。
    vf_parts: List[str] = [f"fps={fps}"]
    if not use_source_size:
        vf_parts.insert(0, f"crop={width}:{height}")
        vf_parts.insert(0, f"scale={width}:{height}:force_original_aspect_ratio=increase")
    if use_subtitles:
        # Render with ASS burn-in subtitles (centered, readable, animated fade).
        ass_path = ass.as_posix().replace("\\", "\\\\").replace(":", "\\:")
        vf_parts.append(f"subtitles=filename={ass_path}:fontsdir=/usr/share/fonts")
    vf = ",".join(vf_parts)
    _run(base_cmd[:10] + ["-vf", vf] + base_cmd[10:])

    print(f"Wrote {out_mp4}")


def cmd_all(args: argparse.Namespace) -> None:
    """tts -> srt(必要時) -> render を順番に実行します。"""
    config = _load_json(Path(args.config))
    use_subtitles = _subtitles_enabled(args, config)
    cmd_tts(args)
    if use_subtitles:
        cmd_srt(args)
    cmd_render(args)


def cmd_clean(args: argparse.Namespace) -> None:
    """出力ディレクトリを削除してクリーンアップします。"""
    root = Path(__file__).resolve().parent
    outputs_root = root / "outputs"
    _ensure_dir(outputs_root)

    if args.all:
        for child in outputs_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        print(f"Cleaned all outputs under: {outputs_root}")
        return

    config = _load_json(Path(args.config))
    p = _paths(config)
    if p.out.exists():
        shutil.rmtree(p.out)
    _ensure_dir(p.out)
    print(f"Cleaned output dir: {p.out}")


def main() -> None:
    """CLIエントリーポイント。サブコマンドを定義して実行します。"""
    ap = argparse.ArgumentParser(prog="ai-video-generator/run.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", required=True)
        p.add_argument("--story", required=True)
        p.add_argument(
            "--images-dir",
            required=True,
            help="Base directory for scene images.",
        )
        p.add_argument("--no-subtitles", action="store_true", help="Disable subtitle burn-in for this run.")
        p.add_argument("--with-subtitles", action="store_true", help="Enable subtitle burn-in for this run.")
        p.add_argument("--max-duration-sec", type=float, default=None, help="Target max output duration in seconds.")

    p_doc = sub.add_parser("doctor", help="check local dependencies")
    p_doc.add_argument("--config", required=True)
    p_doc.set_defaults(func=cmd_doctor)

    p_tts = sub.add_parser("tts", help="generate per-scene TTS + narration.wav")
    add_common(p_tts)
    p_tts.set_defaults(func=cmd_tts)

    p_srt = sub.add_parser("srt", help="create subtitles.srt from scene timings")
    add_common(p_srt)
    p_srt.set_defaults(func=cmd_srt)

    p_r = sub.add_parser("render", help="render output.mp4 via ffmpeg")
    add_common(p_r)
    p_r.set_defaults(func=cmd_render)

    p_all = sub.add_parser("all", help="run tts -> srt -> render")
    add_common(p_all)
    p_all.set_defaults(func=cmd_all)

    p_clean = sub.add_parser("clean", help="clean generated output directories")
    p_clean.add_argument("--config", default="configs/config.docker.cpu.json")
    p_clean.add_argument("--all", action="store_true", help="clean all subdirectories under outputs/")
    p_clean.set_defaults(func=cmd_clean)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
