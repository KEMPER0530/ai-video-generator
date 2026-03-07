from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Optional

from .errors import AppError

FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def format_srt_time(sec: float) -> str:
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


def format_ass_time(sec: float) -> str:
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


def srt_time_to_sec(ts: str) -> float:
    match = re.match(r"^(\d+):(\d{2}):(\d{2}),(\d{3})$", ts.strip())
    if not match:
        raise AppError(f"Invalid SRT time: {ts}")
    h, mi, s, ms = match.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip(), flags=re.MULTILINE)
    cues: list[tuple[float, float, str]] = []
    for block in blocks:
        lines = [line.rstrip("\n") for line in block.splitlines() if line.strip() != ""]
        if len(lines) < 3:
            continue
        match = re.match(r"^(.+?)\s*-->\s*(.+)$", lines[1].strip())
        if not match:
            continue
        start = srt_time_to_sec(match.group(1))
        end = srt_time_to_sec(match.group(2))
        cue_text = "\n".join(lines[2:])
        if end > start and cue_text.strip():
            cues.append((start, end, cue_text))
    return cues


def escape_ass_text(text: str) -> str:
    escaped = text.replace("\\", r"\\")
    escaped = escaped.replace("{", r"\{").replace("}", r"\}")
    return escaped.replace("\n", r"\N")


def caption_from_narration(text: str, width_chars: int = 22) -> str:
    chunks: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        chunks.extend(
            textwrap.wrap(
                line,
                width=width_chars,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
        )
    punct_only = re.compile(r"^[、。,.!！?？・…ー〜～「」『』（）()\[\]【】\s]+$")
    if len(chunks) >= 2 and punct_only.fullmatch(chunks[-1]):
        chunks[-2] = f"{chunks[-2]}{chunks[-1]}"
        chunks.pop()
    if len(chunks) >= 2 and len(re.sub(r"\s+", "", chunks[-1])) <= 2:
        chunks[-2] = f"{chunks[-2]}{chunks[-1]}"
        chunks.pop()
    return "\n".join(chunks)


def split_subtitle_cues(text: str, width_chars: int = 20, max_lines_per_cue: int = 2) -> list[str]:
    flat = " ".join(x.strip() for x in text.splitlines() if x.strip())
    if not flat:
        return []
    clauses = [m.group(0).strip() for m in re.finditer(r"[^、。！？!?]+[、。！？!?]?|[、。！？!?]", flat)]
    clauses = [c for c in clauses if c and not re.fullmatch(r"[、。！？!?]+", c)]
    if not clauses:
        clauses = [flat]
    merged: list[str] = []
    i = 0
    while i < len(clauses):
        current = clauses[i]
        current_len = len(re.sub(r"\s+", "", current))
        if current_len < 10 and i + 1 < len(clauses):
            merged.append((current + clauses[i + 1]).strip())
            i += 2
            continue
        merged.append(current)
        i += 1

    cues: list[str] = []
    span = max(1, max_lines_per_cue)
    for clause in merged:
        wrapped = caption_from_narration(clause, width_chars=width_chars)
        lines = [ln.strip() for ln in wrapped.splitlines() if ln.strip()]
        if not lines:
            continue
        for idx in range(0, len(lines), span):
            cue = "\n".join(lines[idx : idx + span]).strip()
            if cue:
                cues.append(cue)
    return cues


def cue_char_weight(text: str) -> int:
    raw = re.sub(r"\s+", "", text)
    count = len(raw)
    count += raw.count("、") * 2 + raw.count("。") * 4 + raw.count("！") * 3 + raw.count("？") * 3
    count += raw.count("!") * 3 + raw.count("?") * 3
    return max(1, count)


def find_fontfile(candidates: Optional[tuple[str, ...]] = None) -> Optional[Path]:
    for raw in candidates or FONT_CANDIDATES:
        path = Path(raw)
        if path.exists():
            return path
    return None


def drawtext_filters_from_srt(srt_path: Path, tmp_dir: Path, width: int, height: int) -> list[str]:
    cues = parse_srt(srt_path)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fontfile = find_fontfile()
    base = [
        f"fontsize={max(42, int(height * 0.040))}",
        "fontcolor=white",
        "borderw=3.2",
        "bordercolor=black@0.90",
        "shadowx=1",
        "shadowy=1",
        "shadowcolor=black@0.45",
        "line_spacing=8",
        "x=(w-text_w)/2",
        f"y=h-text_h-{max(120, int(height * 0.09))}",
    ]
    if fontfile is not None:
        escaped = fontfile.as_posix().replace("\\", "\\\\").replace(":", r"\:")
        base.insert(0, f"fontfile={escaped}")

    filters: list[str] = []
    for idx, (start, end, cue_text) in enumerate(cues, start=1):
        textfile = tmp_dir / f"sub_{idx:04d}.txt"
        textfile.write_text(cue_text, encoding="utf-8")
        escaped_textfile = textfile.as_posix().replace("\\", "\\\\").replace(":", r"\:")
        opts = [f"textfile={escaped_textfile}", *base, f"enable='between(t,{start:.3f},{end:.3f})'"]
        filters.append("drawtext=" + ":".join(opts))
    return filters

