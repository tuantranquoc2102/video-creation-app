"""Pillow drawing primitives: fonts, backgrounds, rich (multi-colour) text, shapes.

Frames are rendered as still images with Pillow instead of many MoviePy
``TextClip`` objects: this gives per-word colouring (vocabulary highlight),
reliable Vietnamese/IPA glyphs and much faster encoding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from core.render.config import RenderConfig
from core.utils import hex_to_rgb

Run = tuple[str, "str | None"]  # (text, hex colour) – colour None = spacing only


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
@lru_cache(maxsize=256)
def get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, max(8, int(size)))


@lru_cache(maxsize=4096)
def _glyph_bitmap(path: str, ch: str) -> bytes:
    font = get_font(path, 32)
    im = Image.new("L", (64, 64))
    ImageDraw.Draw(im).text((8, 8), ch, font=font, fill=255)
    return im.tobytes()


def missing_glyphs(font_path: str, text: str) -> str:
    """Characters of *text* that *font_path* cannot render (drawn as .notdef)."""
    notdef = _glyph_bitmap(font_path, "\U000F0000")  # private-use, never present
    chars = sorted({c for c in text if not c.isspace()})
    return "".join(c for c in chars if _glyph_bitmap(font_path, c) == notdef)


# ---------------------------------------------------------------------------
# Colours & background
# ---------------------------------------------------------------------------
def rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (*hex_to_rgb(hex_color), alpha)


@lru_cache(maxsize=8)
def _background(size: tuple[int, int], color: str, image_path: str | None, overlay: int) -> Image.Image:
    base = Image.new("RGBA", size, rgba(color))
    if image_path:
        with Image.open(image_path) as src:
            photo = ImageOps.fit(src.convert("RGBA"), size, Image.Resampling.LANCZOS)
        base = Image.alpha_composite(base, photo)
        base = Image.alpha_composite(base, Image.new("RGBA", size, rgba(color, overlay)))
    return base


@lru_cache(maxsize=4)
def _scene_background(size: tuple[int, int], path: str, focus_y: float, color: str) -> Image.Image:
    """Blurred, darkened scene illustration – keeps cards readable but on-theme."""
    blurred = cover_image(path, size, focus_y).filter(ImageFilter.GaussianBlur(radius=max(8, min(size) // 40)))
    return Image.alpha_composite(blurred, Image.new("RGBA", size, rgba(color, 205)))


def background(cfg: RenderConfig, scene: str | None = None, focus_y: float = 0.4) -> Image.Image:
    """Frame background: explicit bg image > blurred scene illustration > solid colour."""
    if not cfg.bg_image and scene and cfg.use_scene_background:
        return _scene_background(tuple(cfg.size), scene, focus_y, cfg.theme.bg).copy()
    return _background(tuple(cfg.size), cfg.theme.bg, cfg.bg_image, cfg.theme.bg_overlay_alpha).copy()


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
@lru_cache(maxsize=16)
def load_image(path: str) -> Image.Image:
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGBA")


def cover_image(path: str, size: tuple[int, int], focus_y: float = 0.5) -> Image.Image:
    """Scale & crop to fill *size*, keeping the vertical *focus_y* point in view."""
    return ImageOps.fit(load_image(path), size, Image.Resampling.LANCZOS, centering=(0.5, focus_y))


def contain_image(path: str, max_size: tuple[int, int]) -> Image.Image:
    """Scale down (never up beyond 1.5×) to fit inside *max_size*, keeping aspect ratio."""
    src = load_image(path)
    scale = min(max_size[0] / src.width, max_size[1] / src.height, 1.5)
    return src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), Image.Resampling.LANCZOS)


@lru_cache(maxsize=8)
def _logo_layer(path: str, width: int, opacity: float) -> Image.Image:
    logo = load_image(path)
    height = max(1, int(logo.height * width / logo.width))
    logo = logo.resize((width, height), Image.Resampling.LANCZOS)
    alpha = logo.getchannel("A").point(lambda a: int(a * max(0.0, min(1.0, opacity))))
    logo.putalpha(alpha)
    return logo


def logo_box(cfg: RenderConfig) -> tuple[int, int, int, int] | None:
    """Where the watermark goes: bottom centre, sized from the frame's short side."""
    if not cfg.logo_path:
        return None
    w, h = cfg.size
    size = max(24, int(min(w, h) * cfg.logo_scale * (1.0 if h >= w else 0.75)))
    bottom_margin = int(h * (0.035 if h >= w else 0.02))
    x0 = (w - size) // 2
    y1 = h - bottom_margin
    return (x0, y1 - size, x0 + size, y1)


def apply_logo(img: Image.Image, cfg: RenderConfig) -> Image.Image:
    """Overlay the channel logo (faint) at the bottom centre of *img* in place."""
    box = logo_box(cfg)
    if box is None or cfg.logo_opacity <= 0:
        return img
    layer = _logo_layer(cfg.logo_path, box[2] - box[0], round(cfg.logo_opacity, 3))
    y = box[3] - layer.height
    img.alpha_composite(layer, dest=(box[0], y))
    return img


def round_corners(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    return out


def paste_card(img: Image.Image, picture: Image.Image, x: int, y: int, radius: int,
               border: str | None = None, border_width: int = 0) -> tuple[int, int, int, int]:
    """Paste *picture* with rounded corners (and optional border); return its box."""
    if border and border_width:
        rounded_box(img, (x - border_width, y - border_width, x + picture.width + border_width,
                          y + picture.height + border_width), radius + border_width, border)
    img.alpha_composite(round_corners(picture, radius), dest=(int(x), int(y)))
    return (x, y, x + picture.width, y + picture.height)


def gradient(size: tuple[int, int], color: str, start: float, end: float, max_alpha: int,
             horizontal: bool = False) -> Image.Image:
    """Transparent → *color* ramp between fractions *start* and *end* of the axis."""
    w, h = size
    length = w if horizontal else h
    ramp = Image.new("L", (length, 1))
    a, b = int(start * length), max(int(start * length) + 1, int(end * length))
    ramp.putdata([0 if i < a else max_alpha if i >= b else int(max_alpha * (i - a) / (b - a)) for i in range(length)])
    alpha = ramp.resize((w, h)) if horizontal else ramp.rotate(-90, expand=True).resize((w, h))
    layer = Image.new("RGBA", size, rgba(color))
    layer.putalpha(alpha)
    return layer


# ---------------------------------------------------------------------------
# Rich text layout
# ---------------------------------------------------------------------------
@dataclass
class TextLayout:
    lines: list[tuple[list[Run], float]]   # (runs, pixel width)
    font: ImageFont.FreeTypeFont
    line_height: int

    @property
    def height(self) -> int:
        return self.line_height * len(self.lines)

    @property
    def width(self) -> int:
        return int(max((w for _, w in self.lines), default=0))


def plain(text: str, color: str) -> list[Run]:
    return [(text, color)]


def highlight_runs(text: str, spans: list[tuple[int, int]], base: str, hl: str) -> list[Run]:
    """Split *text* into runs, colouring each ``(start, end)`` span with *hl*."""
    runs: list[Run] = []
    pos = 0
    for start, end in spans:
        if start > pos:
            runs.append((text[pos:start], base))
        runs.append((text[start:end], hl))
        pos = end
    if pos < len(text):
        runs.append((text[pos:], base))
    return runs


_NEWLINE = None  # sentinel in word list


def _to_words(runs: list[Run]) -> list[list[Run] | None]:
    words: list[list[Run] | None] = []
    cur: list[Run] = []
    for text, color in runs:
        for part in re.split(r"(\s+)", text):
            if not part:
                continue
            if part.isspace():
                if cur:
                    words.append(cur)
                    cur = []
                words.extend([_NEWLINE] * part.count("\n"))
            elif cur and cur[-1][1] == color:
                cur[-1] = (cur[-1][0] + part, color)
            else:
                cur.append((part, color))
    if cur:
        words.append(cur)
    return words


def layout_text(
    runs: list[Run],
    font_path: str,
    size: int,
    max_width: int,
    line_spacing: float = 1.2,
) -> TextLayout:
    """Greedy word-wrap of coloured *runs* within *max_width* pixels."""
    font = get_font(font_path, size)
    space = font.getlength(" ")
    lines: list[tuple[list[Run], float]] = [([], 0.0)]
    for word in _to_words(runs):
        if word is _NEWLINE:
            lines.append(([], 0.0))
            continue
        ww = sum(font.getlength(t) for t, _ in word)
        line, width = lines[-1]
        if line and width + space + ww > max_width:
            lines.append(([], 0.0))
            line, width = lines[-1]
        if line:
            line.append((" ", None))
            width += space
        line.extend(word)
        lines[-1] = (line, width + ww)
    while len(lines) > 1 and not lines[-1][0]:
        lines.pop()
    ascent, descent = font.getmetrics()
    return TextLayout(lines=lines, font=font, line_height=int((ascent + descent) * line_spacing))


def fit_text(
    runs: list[Run],
    font_path: str,
    size: int,
    max_width: int,
    max_height: int,
    min_size: int | None = None,
    line_spacing: float = 1.2,
) -> TextLayout:
    """Like :func:`layout_text` but shrinks the font until the text fits *max_height*."""
    min_size = min_size or max(12, int(size * 0.5))
    cur = size
    while True:
        lay = layout_text(runs, font_path, cur, max_width, line_spacing)
        if lay.height <= max_height or cur <= min_size:
            return lay
        cur = max(min_size, int(cur * 0.92))


def draw_layout(
    img: Image.Image,
    layout: TextLayout,
    x: int,
    y: int,
    box_width: int | None = None,
    align: str = "left",
    bold: bool = False,
) -> int:
    """Draw *layout* at (x, y); return the y just below the text."""
    draw = ImageDraw.Draw(img)
    font = layout.font
    stroke = max(1, round(font.size / 30)) if bold else 0
    box_width = box_width or layout.width
    for runs, width in layout.lines:
        if align == "center":
            cx = x + (box_width - width) / 2
        elif align == "right":
            cx = x + box_width - width
        else:
            cx = x
        for text, color in runs:
            if color is not None:
                draw.text((cx, y), text, font=font, fill=color, stroke_width=stroke, stroke_fill=color)
            cx += font.getlength(text)
        y += layout.line_height
    return y


def text_width(text: str, font_path: str, size: int) -> int:
    return int(get_font(font_path, size).getlength(text))


def truncate(text: str, font_path: str, size: int, max_width: int) -> str:
    if text_width(text, font_path, size) <= max_width:
        return text
    while text and text_width(text + "…", font_path, size) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


# ---------------------------------------------------------------------------
# Shapes (drawn on small layers then alpha-composited → real transparency)
# ---------------------------------------------------------------------------
def rounded_box(
    img: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    fill: str,
    alpha: int = 255,
    outline: str | None = None,
    outline_width: int = 0,
) -> None:
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, w - 1, h - 1),
        radius=radius,
        fill=rgba(fill, alpha),
        outline=rgba(outline) if outline else None,
        width=outline_width,
    )
    img.alpha_composite(layer, dest=(x0, y0))


def circle(img: Image.Image, center: tuple[int, int], radius: int, fill: str, alpha: int = 255) -> None:
    cx, cy = center
    d = radius * 2
    layer = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((0, 0, d - 1, d - 1), fill=rgba(fill, alpha))
    img.alpha_composite(layer, dest=(int(cx - radius), int(cy - radius)))


def ring(
    img: Image.Image,
    center: tuple[int, int],
    radius: int,
    width: int,
    color: str,
    fraction: float = 1.0,
    track: str | None = None,
) -> None:
    """Progress ring starting at 12 o'clock, clockwise, *fraction* ∈ [0, 1]."""
    cx, cy = center
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw = ImageDraw.Draw(img)
    if track:
        draw.ellipse(bbox, outline=rgba(track), width=width)
    if fraction > 0:
        draw.arc(bbox, start=-90, end=-90 + 360 * min(1.0, fraction), fill=rgba(color), width=width)


def pill(
    img: Image.Image,
    text: str,
    x: int,
    y: int,
    font_path: str,
    size: int,
    bg: str,
    fg: str,
    pad_x: int | None = None,
    pad_y: int | None = None,
    align: str = "left",
    bold: bool = True,
) -> tuple[int, int, int, int]:
    """Rounded label; *x* is the left edge (or right edge when align='right')."""
    pad_x = pad_x if pad_x is not None else int(size * 0.7)
    pad_y = pad_y if pad_y is not None else int(size * 0.35)
    lay = layout_text(plain(text, fg), font_path, size, 10_000, line_spacing=1.0)
    w = lay.width + 2 * pad_x
    h = lay.line_height + 2 * pad_y
    if align == "right":
        x -= w
    elif align == "center":
        x -= w // 2
    rounded_box(img, (x, y, x + w, y + h), radius=h // 2, fill=bg)
    draw_layout(img, lay, x + pad_x, y + pad_y, bold=bold)
    return (x, y, x + w, y + h)


def fade(img: Image.Image, factor: float) -> Image.Image:
    """Return a copy of an RGBA *img* with its alpha multiplied by *factor*."""
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda a: int(a * factor)))
    return out
