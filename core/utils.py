"""Small, dependency-free helpers shared by core modules (no Streamlit)."""

from __future__ import annotations

import os
import re
import unicodedata

from config import OUTPUT_DIR

# Characters that are unsafe in file names on macOS / Windows / Linux.
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# (video codec, audio codec) per container – ``aac`` is not valid in WebM.
VIDEO_CODECS: dict[str, tuple[str, str]] = {
    "mp4": ("libx264", "aac"),
    "mov": ("libx264", "aac"),
    "avi": ("mpeg4", "libmp3lame"),
    "webm": ("libvpx", "libvorbis"),
}

MIME_TYPES: dict[str, str] = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "webm": "video/webm",
}


def safe_filename(name: str | None, default: str = "video", max_len: int = 120) -> str:
    """Return *name* stripped of path separators and characters unsafe in file names.

    Unicode letters (e.g. Vietnamese) and spaces are kept so names stay readable.
    """
    text = unicodedata.normalize("NFC", str(name or ""))
    text = _INVALID_CHARS.sub(" ", text)
    # Drop tokens made only of dots (remnants of "../" path components).
    text = " ".join(tok for tok in text.split() if tok.strip("."))
    text = text.strip().strip(".").strip()
    text = text[:max_len].strip()
    return text or default


def slugify(text: str, default: str = "item", max_len: int = 60) -> str:
    """ASCII slug (``a-z0-9-``) – used for ids and directory names."""
    norm = unicodedata.normalize("NFKD", str(text or "")).replace("đ", "d").replace("Đ", "D")
    ascii_text = norm.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:max_len].strip("-")
    return slug or default


def is_within(path: str, directory: str) -> bool:
    """True if *path* resolves to a location inside *directory*."""
    real_path = os.path.realpath(path)
    real_dir = os.path.realpath(directory)
    try:
        return os.path.commonpath([real_path, real_dir]) == real_dir
    except ValueError:  # different drives on Windows
        return False


def resolve_output_path(
    name: str,
    fmt: str,
    directory: str = OUTPUT_DIR,
    *,
    overwrite: bool = False,
) -> str:
    """Build a safe output path ``<directory>/<name>.<fmt>``.

    The name is sanitised, the path is guaranteed to stay inside *directory*,
    and – unless *overwrite* – an existing file is never replaced: a numeric
    suffix `` (2)``, `` (3)`` … is appended instead.
    """
    os.makedirs(directory, exist_ok=True)
    base = safe_filename(name)
    ext = re.sub(r"[^a-z0-9]", "", str(fmt).lower()) or "mp4"

    path = os.path.join(directory, f"{base}.{ext}")
    if not overwrite:
        n = 2
        while os.path.exists(path):
            path = os.path.join(directory, f"{base} ({n}).{ext}")
            n += 1

    if not is_within(path, directory):  # defence in depth
        raise ValueError(f"Đường dẫn output không hợp lệ: {path!r}")
    return path


def codecs_for(fmt: str) -> tuple[str, str]:
    return VIDEO_CODECS.get(str(fmt).lower(), VIDEO_CODECS["mp4"])


def mime_for(fmt: str) -> str:
    return MIME_TYPES.get(str(fmt).lower().lstrip("."), "application/octet-stream")


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """'#1a1a2e' → (26, 26, 46). Accepts 3- or 6-digit hex."""
    h = str(hex_color).strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"Mã màu không hợp lệ: {hex_color!r}")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def normalize_ipa(ipa: str | None) -> str:
    """Strip surrounding slashes / brackets so the renderer can add its own."""
    text = str(ipa or "").strip()
    if text.lower() == "nan":
        return ""
    return text.strip("/[] ").strip()
