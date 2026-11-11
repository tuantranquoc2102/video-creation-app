"""Segment 4 – recap of all vocabulary + call to action."""

from __future__ import annotations

import math

from PIL import Image

from core.render import canvas as cv
from core.render.segments.common import Ctx, new_frame
from core.render.timeline import AudioSequencer, Shot, SubCue, TTSFn

LABEL = "ÔN TẬP · RECAP"
CTA_VI = "Lưu video để ôn lại nhé!"
CTA_EN = "Save this video to review!"


def draw_recap(ctx: Ctx, current: int | None = None) -> Image.Image:
    """Vocabulary list; row *current* (the word being read) is highlighted."""
    t = ctx.theme
    items = ctx.lesson.vocabulary
    img = new_frame(ctx, LABEL)

    cols = 1 if ctx.cfg.is_portrait else 2
    rows = math.ceil(len(items) / cols)
    footer_h = ctx.px(170)
    top, bottom = ctx.content_top, ctx.content_bottom - footer_h
    row_gap = ctx.px(14)
    col_gap = ctx.px(28)
    row_h = min(ctx.px(120), (bottom - top - row_gap * (rows - 1)) // max(1, rows))
    col_w = (ctx.content_width - col_gap * (cols - 1)) // cols
    size = min(ctx.px(46), int(row_h * 0.5))

    for i, item in enumerate(items):
        c, r = (i // rows, i % rows) if cols > 1 else (0, i)
        x = ctx.margin + c * (col_w + col_gap)
        y = top + r * (row_h + row_gap)
        active = i == current
        cv.rounded_box(img, (x, y, x + col_w, y + row_h), radius=ctx.px(22),
                       fill=t.speaker_a if active else t.surface, alpha=255 if active else 235,
                       outline=t.highlight if active else None, outline_width=ctx.px(3) if active else 0)
        runs = [(f"{i + 1}. ", t.text if active else t.text_muted), (item.word, t.highlight), ("  ", None),
                (item.meaning_vi, t.text if active else t.text_vi)]
        lay = cv.fit_text(runs, ctx.font, size, col_w - ctx.px(48), int(size * 1.3), min_size=max(12, size // 2))
        cv.draw_layout(img, lay, x + ctx.px(24), y + (row_h - lay.height) // 2, bold=active)

    y = bottom + ctx.px(36)
    cta = cv.layout_text(cv.plain(CTA_VI, t.highlight), ctx.font, ctx.px(52), ctx.content_width)
    y = cv.draw_layout(img, cta, ctx.margin, y, ctx.content_width, align="center", bold=True) + ctx.px(6)
    sub = cv.layout_text(cv.plain(CTA_EN, t.text_muted), ctx.font, ctx.px(36), ctx.content_width)
    cv.draw_layout(img, sub, ctx.margin, y, ctx.content_width, align="center")
    return img


def build_outro(ctx: Ctx, tts: TTSFn) -> list[Shot]:
    """Intro line → each word read on its own (row highlighted, pause to repeat) → call to action."""
    en, vi = ctx.cfg.narrator_en, ctx.cfg.narrator_vi
    shots: list[Shot] = []

    seq = AudioSequencer(tts, ctx.cfg.gap)
    if ctx.cfg.vi_narration:
        seq.speak("Cùng ôn lại các từ vựng hôm nay nhé.", en, vi)
    else:
        seq.say("Let's review today's words.", en)
    d = max(1.5, seq.duration)
    shots.append(Shot(draw_recap(ctx), d, "recap", seq.cues, [SubCue(0, d, en=CTA_EN, vi=CTA_VI)]))

    for i, item in enumerate(ctx.lesson.vocabulary):
        seq = AudioSequencer(tts, ctx.cfg.gap)
        seq.say(item.word, en, gap=ctx.cfg.recap_pause)  # one word at a time, then a pause to repeat
        d = max(1.2, seq.duration)
        shots.append(Shot(draw_recap(ctx, current=i), d, "recap", seq.cues,
                          [SubCue(0, d, en=item.word, vi=item.meaning_vi)]))

    seq = AudioSequencer(tts, ctx.cfg.gap)
    if ctx.cfg.vi_narration:
        seq.speak("Hãy lưu video lại để ôn tập thường xuyên nhé!", en, vi)
    else:
        seq.say(CTA_EN, en)
    d = max(2.5, seq.duration + 1.0)
    shots.append(Shot(draw_recap(ctx), d, "recap", seq.cues, [SubCue(0, d, en=CTA_EN, vi=CTA_VI)]))
    return shots
