"""SubRip (.srt) export for the English and Vietnamese subtitle tracks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TimedCue:
    start: float
    end: float
    text: str


def format_timestamp(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[TimedCue]) -> str:
    blocks = []
    n = 0
    for cue in cues:
        text = (cue.text or "").strip()
        if not text or cue.end <= cue.start:
            continue
        n += 1
        blocks.append(f"{n}\n{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n{text}\n")
    return "\n".join(blocks)


def write_srt(cues: list[TimedCue], path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_srt(cues))
    return path
