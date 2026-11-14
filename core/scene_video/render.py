"""Render a :class:`Story` – each scene's illustration fills the frame, one speech bubble per turn.

Only the current speaker's bubble is on screen (English line + Vietnamese translation);
the next turn replaces it with the next speaker's bubble.  Bubble position and tail
direction come from ``Scene.bubbles`` (per character, per scene).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from config import SCENE_OUTPUT_DIR
from core.lesson.text import split_by_language
from core.render import canvas as cv
from core.render.assemble import ProgressFn, default_tts, encode_shots, prefetch_tts
from core.render.config import RenderConfig
from core.render.segments.common import resolve_voices
from core.render.subtitles import write_srt
from core.render.timeline import AudioSequencer, Shot, SubCue, TTSFn
from core.scene_video.schema import BubbleLayout, Story, story_to_json
from core.utils import resolve_output_path, safe_filename, slugify

# Name / outline colour per character (order of ``Story.characters``).
SPEAKER_COLORS = ("#4f46e5", "#be185d", "#0f766e", "#b45309")
_SUPERSAMPLE = 2  # bubble shapes are drawn at 2× then scaled down → smooth edges


@dataclass
class SceneStyle:
    bubble_width: float = 0.62      # max bubble width, fraction of the frame width
    font_scale: float = 1.0         # multiplier for the text size
    tail_length: float = 1.0        # multiplier for the tail length
    fit: str = "cover"              # "cover" = fill & crop, "contain" = whole image on a blurred backdrop
    show_name: bool = True          # speaker name above the English line
    vi_audio: bool = False          # also read the Vietnamese translation aloud
    scene_pause: float = 0.6        # seconds the illustration is shown alone before the first bubble
    bubble_fill: str = "#ffffff"
    bubble_alpha: int = 245         # opacity of the whole bubble (0–255)
    text_en: str = "#0f172a"
    text_vi: str = "#475569"


@dataclass
class SceneRenderResult:
    video_path: str
    srt_en_path: str
    srt_vi_path: str
    thumbnail_path: str
    story_path: str
    out_dir: str
    duration: float
    segments: list[dict]
    tts_fallbacks: list[dict]
    speech: list[dict]


# ---------------------------------------------------------------------------
# Scene illustration
# ---------------------------------------------------------------------------
@lru_cache(maxsize=32)
def _scene_base(path: str, mtime: float, size: tuple[int, int], fit: str, bg: str) -> Image.Image:
    if fit != "contain":
        return cv.cover_image(path, size, 0.5)
    src = cv.load_image(path)
    blur = cv.cover_image(path, size, 0.5).filter(ImageFilter.GaussianBlur(radius=max(8, min(size) // 30)))
    base = Image.alpha_composite(blur, Image.new("RGBA", size, cv.rgba(bg, 150)))
    scale = min(size[0] / src.width, size[1] / src.height)
    fg = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), Image.Resampling.LANCZOS)
    base.alpha_composite(fg, dest=((size[0] - fg.width) // 2, (size[1] - fg.height) // 2))
    return base


def _placeholder(cfg: RenderConfig, scene_no: int) -> Image.Image:
    img = cv.background(cfg)
    u = min(cfg.size) / 1080
    lay = cv.layout_text(cv.plain(f"Phân cảnh {scene_no}\n(chưa có hình)", cfg.theme.text_muted),
                         cfg.font_path, int(56 * u), int(cfg.size[0] * 0.8))
    cv.draw_layout(img, lay, int(cfg.size[0] * 0.1), (cfg.size[1] - lay.height) // 2,
                   int(cfg.size[0] * 0.8), align="center")
    return img


def scene_base(cfg: RenderConfig, style: SceneStyle, image_path: str | None, scene_no: int) -> Image.Image:
    if image_path and os.path.isfile(image_path):
        return _scene_base(image_path, os.path.getmtime(image_path), tuple(cfg.size), style.fit, cfg.theme.bg).copy()
    return _placeholder(cfg, scene_no)


# ---------------------------------------------------------------------------
# Speech bubble
# ---------------------------------------------------------------------------
@dataclass
class Bubble:
    image: Image.Image                       # transparent layer: body + tail + outline
    body: tuple[int, int, int, int]          # (x, y, w, h) of the body inside the layer
    tail_len: int


def _tail_polygon(tail: str, body: tuple[int, int, int, int], length: int, half: int, radius: int):
    """Triangle (three points) for *tail*, base overlapping the body edge; ``None`` for no tail."""
    x0, y0, w, h = body
    x1, y1 = x0 + w, y0 + h
    if tail == "none" or length <= 0:
        return None
    inset = max(2, radius // 2)  # base sits inside the body so the union has no seam
    if tail in ("left", "right"):
        cy = y0 + h / 2
        half = min(half, max(4, h / 2 - radius))
        if tail == "left":
            return [(x0 + inset, cy - half), (x0 + inset, cy + half), (x0 - length, cy)]
        return [(x1 - inset, cy - half), (x1 - inset, cy + half), (x1 + length, cy)]

    side = tail.split("-")[1] if "-" in tail else "centre"
    frac, lean = {"left": (0.26, -0.55), "right": (0.74, 0.55), "centre": (0.5, 0.0)}[side]
    lo, hi = x0 + radius + half, x1 - radius - half
    bx = x0 + w / 2 if lo > hi else min(max(x0 + w * frac, lo), hi)
    if tail.startswith("down"):
        return [(bx - half, y1 - inset), (bx + half, y1 - inset), (bx + lean * length, y1 + length)]
    return [(bx - half, y0 + inset), (bx + half, y0 + inset), (bx + lean * length, y0 - length)]


def _bubble_shape(size: tuple[int, int], body: tuple[int, int, int, int], radius: int, tail: str,
                  tail_len: int, tail_half: int, outline: int) -> tuple[Image.Image, Image.Image]:
    """(fill mask, outline mask) of the body ∪ tail, anti-aliased."""
    ss = _SUPERSAMPLE
    big = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    draw = ImageDraw.Draw(big)
    x, y, w, h = (v * ss for v in body)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=radius * ss, fill=255)
    poly = _tail_polygon(tail, (x, y, w, h), tail_len * ss, tail_half * ss, radius * ss)
    if poly:
        draw.polygon(poly, fill=255)
    fill = big.resize(size, Image.Resampling.LANCZOS)
    return fill, fill.filter(ImageFilter.MaxFilter(2 * outline + 1))


def draw_bubble(story: Story, scene_idx: int, turn_idx: int, cfg: RenderConfig, style: SceneStyle) -> Bubble:
    turn = story.scenes[scene_idx].dialogue[turn_idx]
    layout = story.layout(scene_idx, turn.speaker)
    char = story.character(turn.speaker)
    color = SPEAKER_COLORS[story.char_index(turn.speaker) % len(SPEAKER_COLORS)]
    w, h = cfg.size
    u = min(w, h) / 1080

    def px(v: float) -> int:
        return int(round(v * u))

    pad_x, pad_y = px(34), px(24)
    inner = max(px(160), int(w * style.bubble_width) - 2 * pad_x)
    fs = style.font_scale
    name = cv.layout_text(cv.plain(char.name if char else turn.speaker, color), cfg.font_path, px(30 * fs), inner, 1.1)
    en = cv.fit_text(cv.plain(turn.en, style.text_en), cfg.font_path, px(46 * fs), inner, int(h * 0.30), line_spacing=1.2)
    vi = cv.fit_text(cv.plain(turn.vi, style.text_vi), cfg.font_path, px(36 * fs), inner, int(h * 0.22), line_spacing=1.2)
    gap1, gap2 = px(6), px(12)
    name_h = name.height + gap1 if style.show_name else 0
    bw = max(en.width, vi.width, name.width if style.show_name else 0) + 2 * pad_x
    bh = pad_y + name_h + en.height + gap2 + vi.height + pad_y

    radius = min(px(34), bh // 2)
    outline = max(2, px(4))
    tail_len = px(64 * style.tail_length)
    m = tail_len + outline + 2  # room for the tail on every side keeps the maths simple
    size = (bw + 2 * m, bh + 2 * m)
    fill_mask, outline_mask = _bubble_shape(size, (m, m, bw, bh), radius, layout.tail, tail_len, px(24), outline)

    img = Image.new("RGBA", size, cv.rgba(color))
    img.putalpha(outline_mask)
    body = Image.new("RGBA", size, cv.rgba(style.bubble_fill))
    body.putalpha(fill_mask)
    img.alpha_composite(body)

    y = m + pad_y
    if style.show_name:
        y = cv.draw_layout(img, name, m + pad_x, y, bold=True) + gap1
    y = cv.draw_layout(img, en, m + pad_x, y, bold=True) + gap2
    cv.draw_layout(img, vi, m + pad_x, y)
    if style.bubble_alpha < 255:
        img.putalpha(img.getchannel("A").point(lambda a: a * style.bubble_alpha // 255))
    return Bubble(img, (m, m, bw, bh), tail_len)


def _place(bubble: Bubble, layout: BubbleLayout, size: tuple[int, int]) -> tuple[int, int]:
    """Top-left of the bubble layer so the body is centred on the layout point, kept inside the frame."""
    w, h = size
    bx, by, bw, bh = bubble.body
    edge = max(4, int(min(w, h) * 0.015))
    t = bubble.tail_len
    left = edge + (t if layout.tail == "left" else t // 2 if layout.tail.endswith("-left") else 0)
    right = edge + (t if layout.tail == "right" else t // 2 if layout.tail.endswith("-right") else 0)
    top = edge + (t if layout.tail.startswith("up") else 0)
    bottom = edge + (t if layout.tail.startswith("down") else 0)
    x = int(layout.x * w - bw / 2)
    y = int(layout.y * h - bh / 2)
    x = max(left, min(x, w - right - bw))
    y = max(top, min(y, h - bottom - bh))
    return x - bx, y - by


def draw_scene_frame(
    story: Story,
    scene_idx: int,
    turn_idxs: list[int],
    image_path: str | None,
    cfg: RenderConfig,
    style: SceneStyle | None = None,
) -> Image.Image:
    """The scene illustration with the bubbles of *turn_idxs* (usually one; several for review)."""
    style = style or SceneStyle()
    img = scene_base(cfg, style, image_path, scene_idx + 1)
    for ti in turn_idxs:
        turn = story.scenes[scene_idx].dialogue[ti]
        bubble = draw_bubble(story, scene_idx, ti, cfg, style)
        x, y = _place(bubble, story.layout(scene_idx, turn.speaker), cfg.size)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.paste(bubble.image, (x, y))  # paste clips at the frame edge (alpha_composite would raise)
        img.alpha_composite(layer)
    return img


def review_turns(story: Story, scene_idx: int) -> list[int]:
    """One turn per speaker of the scene (their longest line) – used to position all bubbles at once."""
    scene = story.scenes[scene_idx]
    picks = []
    for cid in scene.speakers():
        turns = [i for i, t in enumerate(scene.dialogue) if t.speaker == cid]
        picks.append(max(turns, key=lambda i: len(scene.dialogue[i].en) + len(scene.dialogue[i].vi)))
    return picks


# ---------------------------------------------------------------------------
# Shots & video
# ---------------------------------------------------------------------------
def _speech_items(story: Story, cfg: RenderConfig, style: SceneStyle, voices: dict[str, str]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for scene in story.scenes:
        for turn in scene.dialogue:
            for text in (turn.en, turn.vi) if style.vi_audio else (turn.en,):
                items += [(chunk.strip(), cfg.narrator_vi if lang == "vi" else voices[turn.speaker])
                          for lang, chunk in split_by_language(text) if chunk.strip()]
    return list(dict.fromkeys(items))


def build_scene_shots(story: Story, images: dict[int, str], cfg: RenderConfig, style: SceneStyle, tts: TTSFn,
                      progress_cb: ProgressFn | None = None) -> list[Shot]:
    voices = resolve_voices(story, cfg)
    shots: list[Shot] = []
    for si, scene in enumerate(story.scenes):
        segment = f"scene-{si + 1}"
        path = images.get(si)
        if style.scene_pause > 0:
            shots.append(Shot(image=draw_scene_frame(story, si, [], path, cfg, style),
                              duration=style.scene_pause, segment=segment))
        for ti, turn in enumerate(scene.dialogue):
            seq = AudioSequencer(tts, cfg.gap)
            seq.speak(turn.en, voices[turn.speaker], cfg.narrator_vi)
            if style.vi_audio:
                seq.speak(turn.vi, voices[turn.speaker], cfg.narrator_vi)
            duration = max(1.5, seq.duration)
            char = story.character(turn.speaker)
            name = char.name if char else turn.speaker
            shots.append(Shot(
                image=draw_scene_frame(story, si, [ti], path, cfg, style),
                duration=duration,
                segment=segment,
                audio=seq.cues,
                subs=[SubCue(0, duration, en=f"{name}: {turn.en}", vi=f"{name}: {turn.vi}")],
            ))
        if progress_cb:
            progress_cb("frames", si + 1, len(story.scenes))
    return shots


def render_scene_video(
    story: Story,
    images: dict[int, str],
    cfg: RenderConfig | None = None,
    style: SceneStyle | None = None,
    *,
    video_name: str | None = None,
    output_root: str = SCENE_OUTPUT_DIR,
    tts: TTSFn | None = None,
    progress_cb: ProgressFn | None = None,
) -> SceneRenderResult:
    """*images* maps scene index → illustration path; every scene must have one."""
    cfg = cfg or RenderConfig()
    style = style or SceneStyle()
    tts = tts or default_tts()
    missing = [i + 1 for i in range(len(story.scenes)) if not (images.get(i) and os.path.isfile(images[i]))]
    if missing:
        raise ValueError("Thiếu hình ảnh cho phân cảnh: " + ", ".join(map(str, missing)))
    started = time.monotonic()

    out_dir = os.path.join(output_root, slugify(story.story_id, default="story"))
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="scene_")
    try:
        prefetch_tts(_speech_items(story, cfg, style, resolve_voices(story, cfg)), tts, progress_cb)
        shots = build_scene_shots(story, images, cfg, style, tts, progress_cb)

        thumb_path = os.path.join(out_dir, "thumbnail.png")
        first_bubble = next((s for s in shots if s.audio), shots[0])
        first_bubble.image.convert("RGB").save(thumb_path)
        video_path = resolve_output_path(safe_filename(video_name or story.title_en, default=story.story_id),
                                         "mp4", out_dir, overwrite=True)
        tl = encode_shots(shots, cfg, video_path, work, progress_cb)
        del shots

        srt_en = write_srt(tl.cues_en, os.path.join(out_dir, "subtitles.en.srt"))
        srt_vi = write_srt(tl.cues_vi, os.path.join(out_dir, "subtitles.vi.srt"))
        story_path = os.path.join(out_dir, "story.json")
        with open(story_path, "w", encoding="utf-8") as fh:
            fh.write(story_to_json(story))
        manifest = {
            "story_id": story.story_id,
            "title_en": story.title_en,
            "rendered_at": datetime.now().isoformat(timespec="seconds"),
            "render_seconds": round(time.monotonic() - started, 1),
            "duration": round(tl.duration, 3),
            "video": os.path.basename(video_path),
            "segments": tl.segments,
            "shots": tl.shots,
            "tts_fallbacks": getattr(tts, "fallbacks", []),
            "speech": tl.speech,
            "style": asdict(style),
            "render_config": cfg.to_dict(),
        }
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)

        return SceneRenderResult(
            video_path=video_path,
            srt_en_path=srt_en,
            srt_vi_path=srt_vi,
            thumbnail_path=thumb_path,
            story_path=story_path,
            out_dir=out_dir,
            duration=tl.duration,
            segments=tl.segments,
            tts_fallbacks=list(getattr(tts, "fallbacks", [])),
            speech=tl.speech,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
