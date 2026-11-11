"""Segment 0 – intro / hook card (also used as the thumbnail).

With a scene illustration the image fills the frame and the title sits on a
dark gradient (portrait: bottom, landscape: right); otherwise a text card.
"""

from __future__ import annotations

from PIL import Image

from core.render import canvas as cv
from core.render.segments.common import Ctx
from core.render.timeline import AudioSequencer, Shot, SubCue, TTSFn


def _draw_text_block(ctx: Ctx, img: Image.Image, x: int, y: int, w: int, scale: float = 1.0,
                     chips_row: bool = True) -> int:
    """Badge, titles, goal and chips stacked from *y*; returns the bottom y."""
    t = ctx.theme
    meta = ctx.lesson.meta
    cx = x + w // 2

    def px(v: float) -> int:
        return ctx.px(v * scale)

    box = cv.pill(img, f"{meta.level} · {meta.topic}", cx, y, ctx.font, px(38),
                  bg=t.surface, fg=t.accent, align="center")
    y = box[3] + px(40)

    title = cv.fit_text(cv.plain(meta.title_en, t.text), ctx.font, px(112), w, px(400))
    y = cv.draw_layout(img, title, x, y, w, align="center", bold=True) + px(20)

    title_vi = cv.fit_text(cv.plain(meta.title_vi, t.highlight), ctx.font, px(68), w, px(240))
    y = cv.draw_layout(img, title_vi, x, y, w, align="center", bold=True) + px(36)

    if meta.learning_goal_vi:
        goal = cv.layout_text(cv.plain(meta.learning_goal_vi, t.text_vi), ctx.font, px(44), w)
        y = cv.draw_layout(img, goal, x, y, w, align="center") + px(44)

    if not chips_row:
        return y - px(44)
    chips = [f"{len(ctx.lesson.dialogue)} câu hội thoại", f"{len(ctx.lesson.vocabulary)} từ vựng"]
    if ctx.lesson.exercises:
        chips.append(f"{len(ctx.lesson.exercises)} bài tập")
    size, gap = px(36), px(18)
    widths = [cv.text_width(c, ctx.font, size) + int(size * 1.4) for c in chips]
    if sum(widths) + gap * (len(chips) - 1) <= w:  # one row
        cx0 = x + (w - (sum(widths) + gap * (len(chips) - 1))) // 2
        for chip, cw in zip(chips, widths):
            b = cv.pill(img, chip, cx0, y, ctx.font, size, bg=t.speaker_a, fg=t.text)
            cx0 += cw + gap
        y = b[3]
    else:  # stacked
        for chip in chips:
            b = cv.pill(img, chip, cx, y, ctx.font, size, bg=t.speaker_a, fg=t.text, align="center")
            y = b[3] + gap
    return y


def draw_intro(ctx: Ctx) -> Image.Image:
    scene = ctx.scene
    if not scene:
        img = ctx.background()
        y = int(ctx.h * (0.22 if ctx.cfg.is_portrait else 0.14))
        _draw_text_block(ctx, img, ctx.margin, y, ctx.content_width)
        return img

    probe = Image.new("RGBA", (ctx.w, ctx.h))
    focus = ctx.lesson.meta.scene_focus_y
    if ctx.scene_fullscreen:
        # Illustration fills the whole 9:16 frame; title on a dark fade at the bottom.
        img = ctx.scene_frame()
        img.alpha_composite(cv.gradient(img.size, ctx.theme.bg, 0.50, 0.66, 235))
        x, w = ctx.margin, ctx.content_width
        region_top, region_bottom = int(ctx.h * 0.60), int(ctx.h * 0.90)
    elif ctx.cfg.is_portrait:
        # Illustration fills the top ~52 %, fading into the background; text below it.
        img = ctx.background()
        art_h = int(ctx.h * 0.52)
        art = cv.cover_image(scene, (ctx.w, art_h), focus)
        art.alpha_composite(cv.gradient(art.size, ctx.theme.bg, 0.80, 1.0, 255))
        img.alpha_composite(art, dest=(0, 0))
        x, w = ctx.margin, ctx.content_width
        region_top, region_bottom = art_h - ctx.px(30), int(ctx.h * 0.90)
    else:
        # Illustration as an exact 9:16 card on the left, text on the right.
        img = ctx.background()
        card_h = ctx.h - ctx.px(120)
        picture = ctx.scene_card(card_h)
        px0, py0 = ctx.margin, (ctx.h - card_h) // 2
        cv.paste_card(img, picture, px0, py0, ctx.px(32), border=ctx.theme.surface_2, border_width=ctx.px(4))
        x = px0 + picture.width + ctx.px(60)
        w = ctx.w - ctx.margin - x
        region_top, region_bottom = ctx.px(60), ctx.h - ctx.px(60)

    # Largest readable text scale that fits; drop the chip row before going below 0.8.
    avail = region_bottom - region_top
    options = [(s, True) for s in (1.0, 0.9, 0.8)] + [(s, False) for s in (0.9, 0.8, 0.7)]
    for scale, chips in options:
        height = _draw_text_block(ctx, probe, x, 0, w, scale, chips)
        if height <= avail:
            break
    top = region_top + max(0, (avail - height) // 2)
    _draw_text_block(ctx, img, x, top, w, scale, chips)
    return img


def _as_sentence(text: str) -> str:
    """Trim and make sure *text* ends with exactly one sentence terminator."""
    text = (text or "").strip()
    if not text:
        return ""
    text = text.rstrip(".。 ").rstrip()
    return text if text.endswith(("?", "!")) else text + "."


def intro_vi_lines(meta) -> list[str]:
    """Vietnamese narration for the intro: always names the topic, then the learning goal.

    The goal is read as written (it may be phrased "Sau bài học, …"), never glued
    after "Hôm nay chúng ta học:" – that produced nonsense and skipped the topic.
    """
    lines = [f"Hôm nay chúng ta học chủ đề: {_as_sentence(meta.title_vi)}"]
    goal = _as_sentence(meta.learning_goal_vi or "")
    if goal and goal.casefold() != _as_sentence(meta.title_vi).casefold():
        lines.append(goal)
    return lines


def build_intro(ctx: Ctx, tts: TTSFn) -> list[Shot]:
    meta = ctx.lesson.meta
    en, vi = ctx.cfg.narrator_en, ctx.cfg.narrator_vi
    seq = AudioSequencer(tts, ctx.cfg.gap)
    seq.speak(meta.title_en, en, vi)
    if ctx.cfg.vi_narration:
        for line in intro_vi_lines(meta):
            seq.speak(line, en, vi)
    duration = max(3.5, seq.duration + 0.5)
    return [
        Shot(
            image=draw_intro(ctx),
            duration=duration,
            segment="intro",
            audio=seq.cues,
            subs=[SubCue(0, duration, en=meta.title_en, vi=meta.title_vi)],
        )
    ]
