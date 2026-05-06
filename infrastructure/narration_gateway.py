from __future__ import annotations

from pathlib import Path

from domain.errors import AppError
from infrastructure.process_runner import SubprocessRunner


# gTTS / macOS say / espeak-ng を同じインターフェースで扱うTTS実装。
class MultiEngineNarrationGateway:
    def __init__(self, runner: SubprocessRunner):
        self._runner = runner

    def select_voice(self, voice: str, engine: str) -> str:
        # 実行前に声や言語が存在するか確認し、早めに分かりやすく失敗させる。
        if engine == "gtts":
            try:
                from gtts.lang import tts_langs
            except Exception as exc:
                raise AppError("gTTS is not installed") from exc
            langs = tts_langs()
            if voice not in langs:
                raise AppError(f"Language not available for gTTS: {voice}")
            return voice
        if engine == "say":
            try:
                out = self._runner.check_output(["say", "-v", "?"])
            except AppError as exc:
                raise AppError("macOS `say` is not available") from exc
            voices = {line.split()[0] for line in out.splitlines() if line.strip()}
            if voice not in voices:
                raise AppError(f"Voice not available for say: {voice} (try: `say -v ?`)")
            return voice
        if engine == "espeak-ng":
            binary = self._runner.which("espeak-ng")
            try:
                out = self._runner.check_output([binary, "--voices"])
            except AppError as exc:
                raise AppError("Failed to list voices via `espeak-ng --voices`") from exc
            if voice not in out:
                raise AppError(f"Voice not available for espeak-ng: {voice} (try: `espeak-ng --voices`)")
            return voice
        raise AppError(f"Unsupported tts.engine: {engine}")

    def _ffmpeg_convert_to_wav(self, ffmpeg_bin: str, in_path: Path, out_wav: Path) -> None:
        # 後段の結合処理に合わせ、すべてのTTS出力をモノラル16kHz WAVへそろえる。
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        self._runner.run(
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

    def synthesize_to_wav(
        self,
        text: str,
        out_wav: Path,
        voice: str,
        rate: int,
        engine: str,
        ffmpeg_bin: str,
    ) -> None:
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        if engine == "gtts":
            # gTTSはMP3を生成するため、保存後にWAVへ変換する。
            try:
                from gtts import gTTS
            except Exception as exc:
                raise AppError("gTTS is not installed") from exc
            tmp_mp3 = out_wav.with_suffix(".gtts.mp3")
            try:
                gTTS(text=text, lang=voice).save(str(tmp_mp3))
            except Exception as exc:
                raise AppError(f"gTTS request failed: {exc}") from exc
            self._ffmpeg_convert_to_wav(ffmpeg_bin, tmp_mp3, out_wav)
            return
        if engine == "say":
            # macOS sayはAIFF出力を作り、ffmpegでWAVへ変換する。
            aiff = out_wav.with_suffix(".aiff")
            self._runner.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text])
            self._ffmpeg_convert_to_wav(ffmpeg_bin, aiff, out_wav)
            return
        if engine == "espeak-ng":
            # espeak-ngはWAVを直接出せるが、形式統一のため再変換する。
            tmp_wav = out_wav.with_suffix(".espeak.wav")
            self._runner.run(["espeak-ng", "-v", voice, "-s", str(rate), "-w", str(tmp_wav), text])
            self._ffmpeg_convert_to_wav(ffmpeg_bin, tmp_wav, out_wav)
            return
        raise AppError(f"Unsupported tts.engine: {engine}")
