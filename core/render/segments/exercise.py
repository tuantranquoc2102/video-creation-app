"""Segment 3 – active-recall exercises: question → countdown → answer."""

from __future__ import annotations

from typing import Literal

from PIL import Image

from core.lesson.schema import Exercise
from core.lesson.text import BLANK_RE, blank_to_speech, is_vietnamese
from core.render import canvas as cv
from core.render.segments.common import Ctx, new_frame, section_shot
from core.render.segments.vocab import card_box
from core.render.timeline import AudioCue, AudioSequencer, Shot, SubCue, TTSFn

LABEL = "BÀI TẬP · PRACTICE"
State = Literal["question", "countdown", "answer"]

TYPE_LABEL_VI = {
    "multiple_choice": "Chọn đáp án đúng",
    "fill_blank": "Điền vào chỗ trống",
    "translate_vi_en": "Dịch sang tiếng Anh",
    "comprehension": "Trả lời câu hỏi",
}
LETTERS = "ABCD"


def think_seconds(ctx: Ctx, ex: Exercise) -> int:
    return ctx.cfg.think_seconds or ex.think_seconds


def _prompts(ctx: Ctx, ex: Exercise, revealed: bool) -> tuple[list[cv.Run], list[cv.Run]]:
    """(main prompt runs, secondary prompt runs)."""
    t = ctx.theme
    if ex.type == "translate_vi_en":
        return cv.plain(ex.prompt_vi or "", t.text), cv.plain(ex.prompt_en or "", t.text_muted)
    text = ex.prompt_en or ex.prompt_vi or ""
    if ex.type == "fill_blank" and revealed:
        text = BLANK_RE.sub(ex.answer, text, count=1)
        start = text.find(ex.answer)
        runs = cv.highlight_runs(text, [(start, start + len(ex.answer))] if start >= 0 else [], t.text, t.correct)
    else:
        spans = [m.span() for m in BLANK_RE.finditer(text)]
        runs = cv.highlight_runs(text, spans, t.text, t.highlight)
    secondary = cv.plain(ex.prompt_vi or "", t.text_muted) if ex.prompt_en else []
    return runs, secondary


def _draw_footer(ctx: Ctx, img: Image.Image, ex: Exercise, state: State, remaining: int | None,
                 box: tuple[int, int, int, int]) -> None:
    """Countdown ring (question/countdown) or explanation (answer) inside *box*."""
    t = ctx.theme
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if state in ("question", "countdown"):
        total = think_seconds(ctx, ex)
        hint_size = ctx.px(34)
        r = max(ctx.px(40), min(ctx.px(95), (h - hint_size * 2) // 2 - ctx.px(10), w // 2 - ctx.px(10)))
        cx = x0 + w // 2
        cy = y0 + (h - (2 * r + ctx.px(18) + hint_size)) // 2 + r
        frac = (remaining / total) if (state == "countdown" and remaining) else 1.0
        ring_color = t.highlight if state == "countdown" else t.surface_2
        cv.ring(img, (cx, cy), r, ctx.px(14), ring_color, frac, track=t.surface_2)
        label = str(remaining) if state == "countdown" and remaining else "?"
        num = cv.layout_text(cv.plain(label, t.text), ctx.font, int(r * 1.1), 2 * r, 1.0)
        cv.draw_layout(img, num, cx - r, cy - num.line_height // 2 - ctx.px(4), 2 * r, align="center", bold=True)
        hint = "Tự trả lời trước khi xem đáp án!" if state == "countdown" else "Sẵn sàng…"
        lay = cv.layout_text(cv.plain(hint, t.text_muted), ctx.font, hint_size, w)
        cv.draw_layout(img, lay, x0, cy + r + ctx.px(18), w, align="center")
    elif ex.explanation_vi:
        inner = w - ctx.px(48)
        lay = cv.fit_text(cv.plain(ex.explanation_vi, t.text_vi), ctx.font, ctx.px(40), inner, h - ctx.px(48))
        top = y0 + (h - lay.height) // 2
        cv.rounded_box(img, (x0, top - ctx.px(20), x1, top + lay.height + ctx.px(20)),
                       radius=ctx.px(20), fill=t.bg, alpha=160)
        cv.draw_layout(img, lay, x0 + ctx.px(24), top, inner, align="center")


def draw_exercise(ctx: Ctx, k: int, state: State, remaining: int | None = None) -> Image.Image:
    lesson = ctx.lesson
    t = ctx.theme
    ex = lesson.exercises[k]
    revealed = state == "answer"

    img = new_frame(ctx, LABEL, f"{k + 1}/{len(lesson.exercises)}")
    x0, y0, x1, y1 = card_box(ctx)
    cv.rounded_box(img, (x0, y0, x1, y1), radius=ctx.px(40), fill=t.surface, alpha=235)
    pad = ctx.px(48)
    card_h = y1 - y0

    # Portrait: question on top, footer at the bottom.  Landscape: footer in a right column.
    if ctx.cfg.is_portrait:
        cx0, cw = x0 + pad, (x1 - x0) - 2 * pad
        footer_h = int(card_h * 0.27)
        footer_box = (cx0, y1 - pad - footer_h, cx0 + cw, y1 - pad)
        content_bottom = footer_box[1] - ctx.px(20)
    else:
        total_w = (x1 - x0) - 3 * pad
        cw = int(total_w * 0.66)
        cx0 = x0 + pad
        fx0 = cx0 + cw + pad
        footer_box = (fx0, y0 + pad, x1 - pad, y1 - pad)
        content_bottom = y1 - pad

    y = y0 + pad
    box = cv.pill(img, TYPE_LABEL_VI[ex.type], cx0, y, ctx.font, ctx.px(34), bg=t.speaker_a, fg=t.text)
    y = box[3] + ctx.px(32)

    main, secondary = _prompts(ctx, ex, revealed)
    if ex.type == "translate_vi_en" and secondary:  # instruction above the VI sentence
        lay = cv.layout_text(secondary, ctx.font, ctx.px(36), cw)
        y = cv.draw_layout(img, lay, cx0, y) + ctx.px(14)
        secondary = []
    avail_h = content_bottom - y
    lay = cv.fit_text(main, ctx.font, ctx.px(60), cw, int(avail_h * 0.30))
    y = cv.draw_layout(img, lay, cx0, y, bold=True) + ctx.px(14)
    if secondary:
        lay = cv.fit_text(secondary, ctx.font, ctx.px(38), cw, int(avail_h * 0.14))
        y = cv.draw_layout(img, lay, cx0, y) + ctx.px(10)
    y += ctx.px(20)

    if ex.options:
        opt_gap = ctx.px(16)
        n = len(ex.options)
        slot = (content_bottom - y - opt_gap * (n - 1)) // n
        box_pad = min(ctx.px(18), max(ctx.px(6), slot // 6))
        for i, opt in enumerate(ex.options):
            is_answer = opt == ex.answer
            letter_color = t.text if (revealed and is_answer) else t.accent
            runs = [(f"{LETTERS[i]}.  ", letter_color), (opt, t.text)]
            lay = cv.fit_text(runs, ctx.font, ctx.px(46), cw - ctx.px(110), max(ctx.px(30), slot - 2 * box_pad),
                              min_size=ctx.px(24))
            bh = lay.height + 2 * box_pad
            fill = t.correct if (revealed and is_answer) else t.surface_2
            dim = revealed and not is_answer
            cv.rounded_box(img, (cx0, y, cx0 + cw, y + bh), radius=ctx.px(22), fill=fill, alpha=110 if dim else 255)
            text_layer = Image.new("RGBA", (cw, bh), (0, 0, 0, 0))
            cv.draw_layout(text_layer, lay, ctx.px(28), box_pad, bold=revealed and is_answer)
            img.alpha_composite(cv.fade(text_layer, 0.5 if dim else 1.0), dest=(cx0, y))
            if revealed and is_answer:
                mark = cv.layout_text(cv.plain("✓", t.text), ctx.font, min(ctx.px(52), bh), 200, 1.0)
                cv.draw_layout(img, mark, cx0 + cw - ctx.px(70), y + (bh - mark.line_height) // 2, bold=True)
            y += bh + opt_gap
    elif revealed:  # open answer
        lay = cv.fit_text(cv.plain(ex.answer, t.text), ctx.font, ctx.px(54), cw - ctx.px(56),
                          max(ctx.px(60), int((content_bottom - y) * 0.6)))
        bh = lay.height + ctx.px(40)
        cv.rounded_box(img, (cx0, y, cx0 + cw, y + bh), radius=ctx.px(24), fill=t.correct)
        cv.draw_layout(img, lay, cx0 + ctx.px(28), y + ctx.px(20), bold=True)

    _draw_footer(ctx, img, ex, state, remaining, footer_box)
    return img


def build_exercises(ctx: Ctx, tts: TTSFn, tick_path: str | None) -> list[Shot]:
    lesson = ctx.lesson
    if not lesson.exercises:
        return []
    shots = [
        section_shot(ctx, tts, 3, "Practice", "Bài tập tự nhớ",
                     "Tạm dừng video nếu cần thêm thời gian", "exercises")
    ]
    for k, ex in enumerate(lesson.exercises):
        # 1) Question
        en_v, vi_v = ctx.cfg.narrator_en, ctx.cfg.narrator_vi
        seq = AudioSequencer(tts, ctx.cfg.gap)
        if ex.prompt_en:
            seq.speak(blank_to_speech(ex.prompt_en), en_v, vi_v, gap=0.35)
        if ex.prompt_vi:
            seq.speak(ex.prompt_vi, en_v, vi_v)
        q_dur = max(2.0, seq.duration + 0.3)
        shots.append(Shot(draw_exercise(ctx, k, "question"), q_dur, "exercises", seq.cues,
                          [SubCue(0, q_dur, en=ex.prompt_en or "", vi=ex.prompt_vi or "")]))

        # 2) Countdown – one still per second
        total = think_seconds(ctx, ex)
        for remaining in range(total, 0, -1):
            audio = [AudioCue(tick_path, 0.0, 0.07)] if (tick_path and ctx.cfg.tick_sound) else []
            shots.append(Shot(draw_exercise(ctx, k, "countdown", remaining), 1.0, "exercises", audio))

        # 3) Answer
        seq = AudioSequencer(tts, ctx.cfg.gap)
        seq.speak(ex.answer, en_v, vi_v)
        if ctx.cfg.vi_narration and ex.explanation_vi:
            seq.speak(ex.explanation_vi, en_v, vi_v)
        a_dur = max(2.5, seq.duration + 0.6)
        shots.append(Shot(draw_exercise(ctx, k, "answer"), a_dur, "exercises", seq.cues,
                          [SubCue(0, a_dur, en=ex.answer if not is_vietnamese(ex.answer) else "",
                                  vi=ex.explanation_vi or (ex.answer if is_vietnamese(ex.answer) else ""))]))
    return shots
