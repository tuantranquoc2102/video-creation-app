"""Vocabulary video generator.

Produces a flashcard-style video:
  Scene per word → English word + IPA  →  Vietnamese meaning
                 → Example sentence    →  Translation
                 → (optional) illustration image
Each scene is voiced with TTS.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Sequence

import pandas as pd
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    concatenate_videoclips,
)

from config import DEFAULT_FONT, OUTPUT_DIR
from core.tts_service import get_audio_duration, synthesize, synthesize_edge
from core.utils import codecs_for, normalize_ipa, resolve_output_path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------
_COLOR_WORD = "#667eea"
_COLOR_IPA = "#aaa"
_COLOR_VN = "#e0e0e0"
_COLOR_EXAMPLE = "#ccc"
_COLOR_TRANSLATE = "#aaa"
_FONT = DEFAULT_FONT
_PADDING_SEC = 0.8  # breathing room between cards


# ---------------------------------------------------------------------------
# Scene builder helpers
# ---------------------------------------------------------------------------
def _make_word_scene(
    word: str,
    ipa: str,
    vn: str,
    example: str,
    translate: str,
    *,
    lang_word: str,
    voice: dict[str, str] | None = None,
    repeat_en: int = 1,
    enable_vn_tts: bool = False,
    voice_vn: dict[str, str] | None = None,
    size: tuple[int, int],
    bg_color: str,
    bg_image: str | None = None,
    word_image: str | None = None,
    font_size_word: int = 64,
    font_size_example: int = 30,
    font_name: str | None = None,
    font_name_vn: str | None = None,
    top_padding_pct: int = 18,
    fps: int,
    tmp_dir: str,
) -> CompositeVideoClip:
    """Build a single flashcard clip for one vocabulary word.

    Audio sequence:
      word_en × repeat_en → [vn_meaning TTS] → pause → example_en → [translate TTS] → pause
    """
    w, h = size
    font = font_name or _FONT
    font_vn = font_name_vn or font

    from moviepy import CompositeAudioClip

    # ── TTS helpers ───────────────────────────────────────────────────
    def _tts_en(text: str) -> str:
        if voice and voice.get("engine") == "edge":
            return synthesize_edge(text, voice_id=voice["voice_id"], output_dir=tmp_dir)
        return synthesize(text, lang=lang_word, output_dir=tmp_dir)

    def _tts_vn(text: str) -> str:
        if voice_vn and voice_vn.get("engine") == "edge":
            return synthesize_edge(text, voice_id=voice_vn["voice_id"], output_dir=tmp_dir)
        return synthesize(text, lang="vi", output_dir=tmp_dir)

    # ── Generate audio clips ──────────────────────────────────────────
    audio_parts: list = []
    cursor = 0.0

    # Word EN × repeat_en
    word_audio_path = _tts_en(word)
    word_dur = get_audio_duration(word_audio_path)
    for i in range(repeat_en):
        audio_parts.append(AudioFileClip(word_audio_path).with_start(cursor))
        cursor += word_dur + (_PADDING_SEC * 0.5 if i < repeat_en - 1 else _PADDING_SEC)

    # Vietnamese meaning TTS (optional)
    if enable_vn_tts and vn:
        vn_audio_path = _tts_vn(vn)
        vn_audio_dur = get_audio_duration(vn_audio_path)
        audio_parts.append(AudioFileClip(vn_audio_path).with_start(cursor))
        cursor += vn_audio_dur + _PADDING_SEC

    # Example sentence EN
    example_audio_path = _tts_en(example)
    example_dur = get_audio_duration(example_audio_path)
    audio_parts.append(AudioFileClip(example_audio_path).with_start(cursor))
    cursor += example_dur + _PADDING_SEC

    # Translate TTS (optional)
    if enable_vn_tts and translate:
        tr_audio_path = _tts_vn(translate)
        tr_audio_dur = get_audio_duration(tr_audio_path)
        audio_parts.append(AudioFileClip(tr_audio_path).with_start(cursor))
        cursor += tr_audio_dur + _PADDING_SEC

    total_dur = cursor

    # ── Background ────────────────────────────────────────────────────
    if bg_image:
        bg = ImageClip(bg_image).resized((w, h)).with_duration(total_dur)
    else:
        bg = ColorClip(size=(w, h), color=_hex_to_rgb(bg_color), duration=total_dur)

    # ── Text layers ───────────────────────────────────────────────────
    y_cursor = int(h * top_padding_pct / 100)

    word_clip = (
        TextClip(
            text=word, 
            font_size=font_size_word, 
            color=_COLOR_WORD, 
            font=font, 
            margin=_text_margin(font_size_word)
        )
        .with_duration(total_dur)
        .with_position(("center", y_cursor))
    )
    y_cursor += int(font_size_word * 1.25)

    ipa_clip = (
        TextClip(
            text=f"/{ipa}/" if ipa else " ",
            font_size=int(font_size_word * 0.5), 
            color=_COLOR_IPA, 
            font=font_vn, 
            margin=_text_margin(int(font_size_word * 0.5))
        )
        .with_duration(total_dur)
        .with_position(("center", y_cursor))
    )
    y_cursor += int(font_size_word * 0.9)

    vn_clip = (
        TextClip(
            text=vn, 
            font_size=int(font_size_word * 0.625), 
            color=_COLOR_VN, 
            font=font_vn, 
            method="caption", 
            size=(int(w * 0.8), None), 
            text_align="center", 
            margin=_text_margin(int(font_size_word * 0.625))
        )
        .with_duration(total_dur)
        .with_position(("center", y_cursor))
    )
    vn_h = vn_clip.size[1]
    y_cursor += vn_h + int(font_size_word * 0.4)

    # ── Optional illustration image ───────────────────────────────────
    img_clips: list = []
    if word_image and os.path.isfile(word_image):
        max_img_w = int(w * 0.5)
        max_img_h = int(h * 0.25)
        img_clip = ImageClip(word_image).with_duration(total_dur)
        iw, ih = img_clip.size
        scale = min(max_img_w / iw, max_img_h / ih, 1.0)
        if scale < 1.0:
            img_clip = img_clip.resized(scale)
        img_clip = img_clip.with_position(("center", y_cursor))
        img_clips.append(img_clip)
        y_cursor += int(img_clip.size[1]) + 20

    # Divider bar
    divider = (
        ColorClip(size=(int(w * 0.5), 2), color=_hex_to_rgb("#667eea"), duration=total_dur)
        .with_position(("center", y_cursor))
    )
    y_cursor += 30

    ex_clip = (
        TextClip(
            text=f"{example}",
            font_size=font_size_example,
            color=_COLOR_EXAMPLE,
            font=font,
            method="caption",
            size=(int(w * 0.8), None),
            text_align="center",
            margin=_text_margin(font_size_example),
        )
        .with_duration(total_dur)
        .with_position(("center", y_cursor))
    )
    ex_h = ex_clip.size[1]
    y_cursor += ex_h + 20

    tr_clip = (
        TextClip(
            text=f"{translate}",
            font_size=int(font_size_example * 0.93),
            color=_COLOR_TRANSLATE,
            font=font_vn,
            method="caption",
            size=(int(w * 0.8), None),
            text_align="center",
            margin=_text_margin(int(font_size_example * 0.93)),
        )
        .with_duration(total_dur)
        .with_position(("center", y_cursor))
    )

    # ── Combine audio ───────────────────────────────────────────────────
    combined_audio = CompositeAudioClip(audio_parts).with_duration(total_dur)

    # ── Compose ───────────────────────────────────────────────────────
    scene = CompositeVideoClip(
        [bg, word_clip, ipa_clip, vn_clip, *img_clips, divider, ex_clip, tr_clip],
        size=(w, h),
    )
    scene = scene.with_audio(combined_audio).with_fps(fps)
    return scene


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate(
    df: pd.DataFrame,
    *,
    name: str,
    lang: str = "en",
    size: tuple[int, int] = (1920, 1080),
    bg_color: str = "#1a1a2e",
    bg_images: list[str] | None = None,
    voice: dict[str, str] | None = None,
    repeat_en: int = 1,
    enable_vn_tts: bool = False,
    voice_vn: dict[str, str] | None = None,
    font_size_word: int = 64,
    font_size_example: int = 30,
    font_name: str | None = None,
    font_name_vn: str | None = None,
    top_padding_pct: int = 18,
    image_dir: str | None = None,
    fps: int = 30,
    fmt: str = "mp4",
    progress_cb=None,
    **_kwargs,
) -> str:
    """Generate a vocabulary flashcard video.

    Parameters
    ----------
    df : DataFrame
        Columns: english, ipa, vietnam, example, translate.
        Optional: image (filename referencing files in *image_dir*).
    name : str
        Output filename (without extension).
    lang : str
        Language code for TTS of the English word & example.
    voice : dict | None
        Voice config dict (engine, voice_id). Falls back to gTTS if None.
    font_size_word, font_size_example : int
        Font sizes for the word and example text.
    font_name : str | None
        Font file path. Falls back to DEFAULT_FONT.
    image_dir : str | None
        Directory containing illustration images referenced in the
        ``image`` column of the CSV.
    size, bg_color, fps, fmt
        Video settings.
    progress_cb : callable | None
        ``progress_cb(current, total)`` after each word.

    Returns
    -------
    str
        Absolute path to the output video.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="vocab_")

    # Resolve font_name (display key) → actual font file path
    from config import FONTS
    resolved_font = FONTS.get(font_name, _FONT) if font_name else _FONT
    resolved_font_vn = FONTS.get(font_name_vn, resolved_font) if font_name_vn else resolved_font

    if image_dir and not os.path.isdir(image_dir):
        log.warning("image_dir không tồn tại: %s", image_dir)

    scenes: list[CompositeVideoClip] = []
    total = len(df)

    for idx, (_, row) in enumerate(df.iterrows()):
        word = str(row.get("english", "")).strip()
        ipa = normalize_ipa(row.get("ipa", ""))
        vn = str(row.get("vietnam", "")).strip()
        example = str(row.get("example", "")).strip()
        translate = str(row.get("translate", "")).strip()

        if not word or word.lower() == "nan":
            continue

        # Resolve illustration image
        word_image: str | None = None
        img_name = str(row.get("image", "")).strip()
        if img_name and img_name.lower() != "nan" and image_dir:
            candidate = os.path.join(image_dir, img_name)
            if os.path.isfile(candidate):
                word_image = candidate
            else:
                log.warning("Từ #%d '%s': không tìm thấy ảnh %s", idx + 1, word, candidate)

        scene = _make_word_scene(
            word, ipa, vn, example, translate,
            lang_word="en",
            voice=voice,
            repeat_en=repeat_en,
            enable_vn_tts=enable_vn_tts,
            voice_vn=voice_vn,
            size=size,
            bg_color=bg_color,
            bg_image=bg_images[idx % len(bg_images)] if bg_images else None,
            word_image=word_image,
            font_size_word=font_size_word,
            font_size_example=font_size_example,
            font_name=resolved_font,
            font_name_vn=resolved_font_vn,
            top_padding_pct=top_padding_pct,
            fps=fps,
            tmp_dir=tmp_dir,
        )
        scenes.append(scene)

        if progress_cb:
            progress_cb(idx + 1, total)

    if not scenes:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ValueError("CSV không chứa từ vựng nào.")

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
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _text_margin(font_size: int) -> tuple[int, int]:
    """Return (horizontal, vertical) margin scaled to font size to prevent descender clipping."""
    return (0, int(font_size * 0.4))
