"""Dialogue video generator.

Produces a video where two speakers take turns.
Each turn shows the speaker's text on screen with a chat-bubble style
while the corresponding TTS audio plays.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Sequence

import numpy as np
import pandas as pd
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

from config import DEFAULT_FONT, OUTPUT_DIR
from core.tts_service import get_audio_duration, synthesize, synthesize_edge
from core.utils import codecs_for, resolve_output_path

# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------
_SPEAKER_COLORS = {
    "speaker 1": {"bg": "#667eea", "text": "white", "label": "Speaker 1"},
    "speaker 2": {"bg": "#764ba2", "text": "white", "label": "Speaker 2"},
}
_PADDING_SEC = 0.5  # silence padding after each turn
_FONT_SIZE_TEXT = 36
_BUBBLE_RADIUS = 30
_BUBBLE_PADDING_X = 40
_BUBBLE_PADDING_Y = 30
_PADDING_TOP = 0.15          # default vertical offset (fraction of height)
_FONT = DEFAULT_FONT


# ---------------------------------------------------------------------------
# Bubble helper
# ---------------------------------------------------------------------------
def _make_bubble_image(
    width: int,
    height: int,
    color: tuple[int, int, int],
    radius: int = _BUBBLE_RADIUS,
) -> np.ndarray:
    """Create a rounded-rectangle RGBA image as a numpy array."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [(0, 0), (width - 1, height - 1)],
        radius=radius,
        fill=(*color, 220),  # slightly transparent
    )
    return np.array(img)


def _make_circle_image(
    diameter: int,
    color: tuple[int, int, int],
    alpha: int = 220,
) -> np.ndarray:
    """Create a circle RGBA image as a numpy array."""
    img = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [(0, 0), (diameter - 1, diameter - 1)],
        fill=(*color, alpha),
    )
    return np.array(img)


def _wrap_text(text: str, font_path: str | None, font_size: int, max_width: int) -> str:
    """Word-wrap *text* so no line exceeds *max_width* pixels.

    Uses Pillow to measure each word.  Lines are broken at spaces only,
    keeping words intact (unlike MoviePy's built-in ``__break_text``).
    """
    if font_path:
        pil_font = ImageFont.truetype(font_path, font_size)
    else:
        pil_font = ImageFont.load_default(font_size)

    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)

    def _measure(s: str) -> int:
        bbox = draw.textbbox((0, 0), s, font=pil_font)
        return bbox[2] - bbox[0]

    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current_line = ""
        for word in words:
            candidate = f"{current_line} {word}" if current_line else word
            if _measure(candidate) <= max_width:
                current_line = candidate
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core scene builder
# ---------------------------------------------------------------------------
def _build_scene(
    speaker_key: str,
    text: str,
    *,
    voice: dict[str, str] | None = None,
    lang: str = "en",
    size: tuple[int, int],
    bg_color: str,
    bg_image: str | None = None,
    bubble_chat: bool = False,
    font_cfg: dict | None = None,
    fps: int,
    tmp_dir: str,
) -> CompositeVideoClip:
    """Create a single dialogue-turn clip (background + label + text + audio)."""
    w, h = size
    style = _SPEAKER_COLORS.get(speaker_key, _SPEAKER_COLORS["speaker 1"])
    fc = font_cfg or {}
    fs_text = fc.get("font_size_text", _FONT_SIZE_TEXT)
    f_color = fc.get("font_color", "white")
    f_font = fc.get("font", _FONT)
    pad_top = fc.get("padding_top", _PADDING_TOP)

    # TTS – dispatch based on voice engine
    if voice and voice.get("engine") == "edge":
        audio_path = synthesize_edge(
            text, voice_id=voice["voice_id"], output_dir=tmp_dir,
        )
    else:
        tld = voice.get("tld", "com") if voice else "com"
        v_lang = voice.get("lang", lang) if voice else lang
        audio_path = synthesize(text, lang=v_lang, tld=tld, output_dir=tmp_dir)
    duration = get_audio_duration(audio_path) + _PADDING_SEC

    # Background
    if bg_image:
        bg_clip = ImageClip(bg_image).resized((w, h)).with_duration(duration)
    else:
        bg_clip = ColorClip(size=(w, h), color=_hex_to_rgb(bg_color), duration=duration)

    if bubble_chat:
        return _compose_bubble(
            bg_clip, speaker_key, text, style, duration, w, h, fps, audio_path,
            fs_text=fs_text, f_color=f_color, f_font=f_font, pad_top=pad_top,
        )

    return _compose_plain(
        bg_clip, speaker_key, style, text, duration, w, h, fps, audio_path,
        fs_text=fs_text, f_color=f_color, f_font=f_font, pad_top=pad_top,
    )


def _compose_plain(
    bg_clip,
    speaker_key: str,
    style: dict,
    text: str,
    duration: float,
    w: int,
    h: int,
    fps: int,
    audio_path: str,
    *,
    fs_text: int = _FONT_SIZE_TEXT,
    f_color: str = "white",
    f_font: str = _FONT,
    pad_top: float = _PADDING_TOP,
) -> CompositeVideoClip:
    """Plain layout: text aligned left/right by speaker + accent bar."""
    is_left = speaker_key == "speaker 1"
    margin_x = int(w * 0.06)
    text_w = int(w * 0.8)
    align = "left" if is_left else "right"
    x_pos = margin_x if is_left else w - text_w - margin_x
    y_pos = int(h * pad_top)

    # Word-wrap manually to avoid MoviePy splitting words mid-character.
    wrapped = _wrap_text(text, f_font, fs_text, text_w)

    # Spoken text
    txt_clip = (
        TextClip(
            text=wrapped,
            font_size=fs_text,
            color=f_color,
            font=f_font,
            method="label",
            text_align=align,
            margin=_text_margin(fs_text),
        )
        .with_duration(duration)
        .with_position((x_pos, y_pos))
    )

    # Accent bar at top
    bar = ColorClip(
        size=(w, 6), color=_hex_to_rgb(style["bg"]), duration=duration
    ).with_position(("center", 0))

    scene = CompositeVideoClip([bg_clip, bar, txt_clip], size=(w, h))
    scene = scene.with_audio(AudioFileClip(audio_path))
    scene = scene.with_fps(fps)
    return scene


def _compose_bubble(
    bg_clip,
    speaker_key: str,
    text: str,
    style: dict,
    duration: float,
    w: int,
    h: int,
    fps: int,
    audio_path: str,
    *,
    fs_text: int = _FONT_SIZE_TEXT,
    f_color: str = "white",
    f_font: str = _FONT,
    pad_top: float = _PADDING_TOP,
) -> CompositeVideoClip:
    """Chat-bubble layout: rounded bubble with text."""
    is_left = speaker_key == "speaker 1"
    bubble_color = _hex_to_rgb(style["bg"])
    margin_x = int(w * 0.06)
    max_bubble_w = min(int(w * 0.7), w - 2 * margin_x)

    # Max width available for the text content (inside bubble padding).
    max_text_w = max_bubble_w - 2 * _BUBBLE_PADDING_X

    # Word-wrap text ourselves (MoviePy's __break_text has a bug that splits
    # words mid-character). We then render using method="label" so MoviePy
    # does not re-wrap.
    wrapped = _wrap_text(text, f_font, fs_text, max_text_w)

    txt_clip = TextClip(
        text=wrapped,
        font_size=fs_text,
        color=f_color,
        font=f_font,
        method="label",
        text_align="left",
        margin=(0, int(fs_text * 0.4)),
    )
    txt_w, txt_h = txt_clip.size

    # Clamp clip width so bubble never overflows the video
    if txt_w > max_text_w:
        txt_w = max_text_w

    # Bubble dimensions
    bw = txt_w + 2 * _BUBBLE_PADDING_X
    bh = txt_h + 2 * _BUBBLE_PADDING_Y

    # Bubble image clip
    bubble_arr = _make_bubble_image(bw, bh, bubble_color)
    bubble_clip = (
        ImageClip(bubble_arr, is_mask=False)
        .with_duration(duration)
    )

    # Horizontal position: left-aligned or right-aligned with margin
    if is_left:
        bx = margin_x
    else:
        bx = w - bw - margin_x

    # Vertical: offset from top
    by = int(h * pad_top)

    bubble_clip = bubble_clip.with_position((bx, by))
    txt_clip = (
        txt_clip
        .with_duration(duration)
        .with_position((bx + _BUBBLE_PADDING_X, by + _BUBBLE_PADDING_Y))
    )

    # --- Tail: 3 circles (large → small) pointing UP toward the speaker ---
    tail_clips = []
    # Scale circle sizes relative to video width (base: 1080px)
    scale = w / 1080.0
    radii = [int(30 * scale), int(20 * scale), int(12 * scale)]
    gap_y = int(6 * scale)
    bubble_color_rgb = bubble_color

    # Start just above the bubble, build upward
    drift_px = int(24 * scale)
    # Anchor at horizontal center of bubble
    cx_start = bx + bw // 2
    if is_left:
        drift = -drift_px
    else:
        drift = drift_px

    cy = by - int(8 * scale)  # start just above the bubble top
    for i, d in enumerate(radii):
        cy -= d + gap_y
        circle_arr = _make_circle_image(d, bubble_color_rgb, alpha=200 - i * 30)
        cx = cx_start + drift * i - d // 2
        circle_clip = (
            ImageClip(circle_arr, is_mask=False)
            .with_duration(duration)
            .with_position((cx, cy))
        )
        tail_clips.append(circle_clip)

    scene = CompositeVideoClip(
        [bg_clip, bubble_clip, txt_clip, *tail_clips], size=(w, h),
    )
    scene = scene.with_audio(AudioFileClip(audio_path))
    scene = scene.with_fps(fps)
    return scene


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate(
    df: pd.DataFrame,
    *,
    name: str,
    lang: str = "vi",
    size: tuple[int, int] = (1920, 1080),
    bg_color: str = "#1a1a2e",
    bg_images: list[str] | None = None,
    bubble_chat: bool = False,
    speaker_voices: dict[str, dict[str, str]] | None = None,
    font_size_text: int = _FONT_SIZE_TEXT,
    font_color: str = "white",
    font_name: str | None = None,
    padding_top: float = _PADDING_TOP,
    fps: int = 30,
    fmt: str = "mp4",
    progress_cb=None,
    **_kwargs,
) -> str:
    """Generate a dialogue video from the DataFrame.

    Parameters
    ----------
    df : DataFrame
        Must have columns ``speaker 1`` and ``speaker 2``.
    name : str
        Output filename (without extension).
    lang : str
        Language code for TTS.
    size : tuple
        (width, height).
    bg_color : str
        Hex background colour.
    fps : int
        Frames per second.
    fmt : str
        Container format (``"mp4"``, ``"avi"``, …).
    progress_cb : callable | None
        ``progress_cb(current_index, total)`` called after each turn.

    Returns
    -------
    str
        Absolute path to the generated video file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="dialogue_")

    # Build font config dict
    from config import FONTS
    font_cfg = {
        "font_size_text": font_size_text,
        "font_color": font_color,
        "font": FONTS.get(font_name, _FONT) if font_name else _FONT,
        "padding_top": padding_top,
    }

    scenes: list[CompositeVideoClip] = []
    total_rows = len(df)
    scene_idx = 0

    # Resolve per-speaker voice settings
    def _voice(key: str) -> dict[str, str] | None:
        if speaker_voices and key in speaker_voices:
            return speaker_voices[key]
        return None

    for idx, (_, row) in enumerate(df.iterrows()):
        s1 = str(row.get("speaker 1", "")).strip()
        s2 = str(row.get("speaker 2", "")).strip()

        if s1 and s1.lower() != "nan":
            bg_img = bg_images[scene_idx % len(bg_images)] if bg_images else None
            scenes.append(
                _build_scene(
                    "speaker 1", s1,
                    voice=_voice("speaker 1"), lang=lang,
                    size=size, bg_color=bg_color, bg_image=bg_img,
                    bubble_chat=bubble_chat, font_cfg=font_cfg,
                    fps=fps, tmp_dir=tmp_dir,
                )
            )
            scene_idx += 1

        if s2 and s2.lower() != "nan":
            bg_img = bg_images[scene_idx % len(bg_images)] if bg_images else None
            scenes.append(
                _build_scene(
                    "speaker 2", s2,
                    voice=_voice("speaker 2"), lang=lang,
                    size=size, bg_color=bg_color, bg_image=bg_img,
                    bubble_chat=bubble_chat, font_cfg=font_cfg,
                    fps=fps, tmp_dir=tmp_dir,
                )
            )
            scene_idx += 1

        if progress_cb:
            progress_cb(idx + 1, total_rows)

    if not scenes:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ValueError("CSV không chứa nội dung hội thoại nào.")

    final = concatenate_videoclips(scenes, method="compose")
    output_path = resolve_output_path(name, fmt, OUTPUT_DIR)
    codec, audio_codec = codecs_for(fmt)
    try:
        final.write_videofile(
            output_path,
            fps=fps,
            codec=codec,
            audio_codec=audio_codec,
            logger=None,
        )
    finally:
        final.close()
        for s in scenes:
            s.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return output_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#1a1a2e' to (26, 26, 46)."""
    from core.utils import hex_to_rgb

    return hex_to_rgb(hex_color)


def _text_margin(font_size: int) -> tuple[int, int]:
    """Return (horizontal, vertical) margin scaled to font size to prevent descender clipping."""
    return (0, int(font_size * 0.4))
