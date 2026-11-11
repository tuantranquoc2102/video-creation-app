"""Video business-logic service.

Pure functions that operate on data – no Streamlit imports allowed.
This makes the logic testable without running a Streamlit server.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta
from typing import Sequence

import pandas as pd

from config import CSV_VIDEO_TYPES, OUTPUT_DIR
from core.utils import normalize_ipa, safe_filename


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def detect_csv_type(df: pd.DataFrame) -> str | None:
    """Return the CSV_VIDEO_TYPES key that matches *df*'s columns, or None."""
    cols = {c.strip().lower() for c in df.columns}
    for key, spec in CSV_VIDEO_TYPES.items():
        required = {c.lower() for c in spec["required_cols"]}
        if required.issubset(cols):
            return key
    return None


def parse_csv(raw_bytes: bytes, separator: str = ";") -> pd.DataFrame:
    """Read raw bytes into a DataFrame using the given separator.

    Tries the explicit *separator* first.  If that produces only one column
    (likely wrong delimiter), falls back to the Python csv sniffer to
    auto-detect the real delimiter.
    """
    df = pd.read_csv(io.BytesIO(raw_bytes), sep=separator, engine="python")

    # If we only got 1 column the separator was probably wrong – retry
    # with auto-detection via ``sep=None`` (uses the csv.Sniffer).
    if len(df.columns) <= 1:
        df = pd.read_csv(io.BytesIO(raw_bytes), sep=None, engine="python")

    # Normalize column names to lowercase & stripped so downstream code
    # can safely use ``row.get("image")``, ``row.get("english")``, etc.
    df.columns = [c.strip().lower() for c in df.columns]

    return df


def csv_to_text(df: pd.DataFrame, csv_type: str) -> str:
    """Convert a typed CSV DataFrame into a flat text for TTS / preview.

    Returns a human-readable version of the content.
    """
    if csv_type == "dialogue":
        lines: list[str] = []
        for _, row in df.iterrows():
            s1 = str(row.get("speaker 1", "")).strip()
            s2 = str(row.get("speaker 2", "")).strip()
            if s1 and s1.lower() != "nan":
                lines.append(f"Speaker 1: {s1}")
            if s2 and s2.lower() != "nan":
                lines.append(f"Speaker 2: {s2}")
        return "\n".join(lines)

    if csv_type == "vocabulary":
        lines = []
        for _, row in df.iterrows():
            word = row.get("english", "")
            ipa = normalize_ipa(row.get("ipa", ""))
            vn = row.get("vietnam", "")
            ex = row.get("example", "")
            tr = row.get("translate", "")
            lines.append(f"{word} /{ipa}/ – {vn}\n  Ex: {ex}\n  ({tr})")
        return "\n\n".join(lines)

    # Fallback: join all cells
    return "\n".join(df.astype(str).apply(lambda r: " | ".join(r), axis=1))


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def build_video_entry(
    *,
    name: str,
    resolution: str,
    fps: int,
    fmt: str,
    text_style: str,
    text_content: str,
    tts_lang: str,
    tts_speed: str,
    tts_engine: str,
    bg_mode: str,
    content_type: str = "text",
    csv_type: str | None = None,
) -> dict:
    """Build a normalised video record dict ready for session state."""
    return {
        "name": name,
        "resolution": resolution,
        "fps": fps,
        "format": fmt,
        "text_style": text_style,
        "text_content": text_content,
        "tts_lang": tts_lang,
        "tts_speed": tts_speed,
        "tts_engine": tts_engine,
        "bg_mode": bg_mode,
        "content_type": content_type,
        "csv_type": csv_type,
        "status": "Hoàn thành",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "output_path": os.path.join(OUTPUT_DIR, f"{safe_filename(name)}.{fmt}"),
    }


# ---------------------------------------------------------------------------
# Filter / sort
# ---------------------------------------------------------------------------
def filter_videos(
    videos: list[dict],
    *,
    search: str = "",
    status: str = "Tất cả",
    resolution: str = "Tất cả",
    sort_by: str = "Mới nhất",
) -> list[dict]:
    """Return a filtered & sorted copy of *videos*."""
    result = list(videos)

    if search:
        q = search.lower()
        result = [v for v in result if q in v.get("name", "").lower()]

    if status != "Tất cả":
        result = [v for v in result if v.get("status") == status]

    if resolution != "Tất cả":
        result = [v for v in result if v.get("resolution", "") == resolution]

    sort_keys = {
        "Mới nhất": (lambda v: v.get("created_at", ""), True),
        "Cũ nhất":  (lambda v: v.get("created_at", ""), False),
        "Tên A-Z":  (lambda v: v.get("name", "").lower(), False),
        "Tên Z-A":  (lambda v: v.get("name", "").lower(), True),
    }
    key_fn, reverse = sort_keys.get(sort_by, sort_keys["Mới nhất"])
    result.sort(key=key_fn, reverse=reverse)
    return result


def get_recent(videos: Sequence[dict], limit: int = 5) -> list[dict]:
    """Return the *limit* most recent videos."""
    return sorted(videos, key=lambda v: v.get("created_at", ""), reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------
def weekly_counts(videos: Sequence[dict]) -> tuple[list[str], list[int]]:
    """Return (date_labels, counts) for the last 7 days."""
    labels: list[str] = []
    counts: list[int] = []
    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        labels.append(day.strftime("%d/%m"))
        day_str = day.strftime("%Y-%m-%d")
        counts.append(sum(1 for v in videos if v.get("created_at", "").startswith(day_str)))
    return labels, counts
