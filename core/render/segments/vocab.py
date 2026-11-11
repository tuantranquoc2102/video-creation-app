"""Segment 2 – vocabulary flashcards (word, IPA, part of speech, meaning, example)."""

from __future__ import annotations

from PIL import Image

from core.lesson.text import find_term_spans
from core.render import canvas as cv
from core.render.segments.common import POS_VI, Ctx, new_frame, section_shot
from core.render.timeline import AudioSequencer, Shot, SubCue, TTSFn

LABEL = "TỪ VỰNG · VOCABULARY"


def card_box(ctx: Ctx) -> tuple[int, int, int, int]:
    return (ctx.margin, ctx.content_top, ctx.w - ctx.margin, ctx.content_bottom)


def _draw_word_block(ctx: Ctx, img: Image.Image, item, x: int, y: int, w: int, max_h: int,
                     image_path: str | None = None) -> int:
    t = ctx.theme
    word = cv.fit_text(cv.plain(item.word, t.highlight), ctx.font, ctx.px(124), w, int(max_h * 0.32))
    y = cv.draw_layout(img, word, x, y, w, align="center", bold=True) + ctx.px(8)
    ipa = cv.layout_text(cv.plain(f"/{item.ipa}/", t.text_muted), ctx.font, ctx.px(50), w)
    y = cv.draw_layout(img, ipa, x, y, w, align="center") + ctx.px(20)
    pos_vi = POS_VI.get(item.pos.lower().strip())
    pos_label = f"{item.pos} · {pos_vi}" if pos_vi else item.pos
    box = cv.pill(img, pos_label, x + w // 2, y, ctx.font, ctx.px(32), bg=t.surface_2, fg=t.text, align="center", bold=False)
    y = box[3] + ctx.px(36)
    meaning = cv.fit_text(cv.plain(item.meaning_vi, t.text), ctx.font, ctx.px(68), w, int(max_h * 0.26))
    y = cv.draw_layout(img, meaning, x, y, w, align="center", bold=True)
    if image_path:
        picture = cv.contain_image(image_path, (int(w * 0.8), int(max_h * 0.34)))
        y += ctx.px(28)
        cv.paste_card(img, picture, x + (w - picture.width) // 2, y, ctx.px(24),
                      border=t.surface_2, border_width=ctx.px(3))
        y += picture.height
    return y


def _draw_example_block(ctx: Ctx, img: Image.Image, item, example_en: str, example_vi: str,
                        x: int, y: int, w: int, bottom: int) -> int:
    t = ctx.theme
    label = cv.layout_text(cv.plain("Trong hội thoại:", t.text_muted), ctx.font, ctx.px(32), w)
    y = cv.draw_layout(img, label, x, y, w, align="center") + ctx.px(12)
    runs = cv.highlight_runs(example_en, find_term_spans(example_en, item.word, item.forms), t.text, t.highlight)
    ex = cv.fit_text(runs, ctx.font, ctx.px(48), w, int((bottom - y) * 0.58), min_size=ctx.px(30))
    y = cv.draw_layout(img, ex, x, y, w, align="center", bold=True) + ctx.px(14)
    if example_vi:
        ex_vi = cv.fit_text(cv.plain(example_vi, t.text_vi), ctx.font, ctx.px(38), w,
                            max(ctx.px(40), bottom - y), min_size=ctx.px(26))
        y = cv.draw_layout(img, ex_vi, x, y, w, align="center")
    return y


def draw_vocab(ctx: Ctx, k: int) -> Image.Image:
    lesson = ctx.lesson
    t = ctx.theme
    item = lesson.vocabulary[k]
    example_en, example_vi = lesson.vocab_example(item)
    image = lesson.vocab_image_path(item)

    img = new_frame(ctx, LABEL, f"{k + 1}/{len(lesson.vocabulary)}")
    x0, y0, x1, y1 = card_box(ctx)
    cv.rounded_box(img, (x0, y0, x1, y1), radius=ctx.px(40), fill=t.surface, alpha=235)
    pad = ctx.px(48)
    card_h = y1 - y0

    if ctx.cfg.is_portrait:
        cx0, cw = x0 + pad, (x1 - x0) - 2 * pad
        y = _draw_word_block(ctx, img, item, cx0, y0 + ctx.px(64), cw, int(card_h * 0.7), image) + ctx.px(40)
        div_w = int(cw * 0.4)
        cv.rounded_box(img, (ctx.w // 2 - div_w // 2, y, ctx.w // 2 + div_w // 2, y + ctx.px(5)), ctx.px(3), t.accent)
        y += ctx.px(36)
        if example_en:
            _draw_example_block(ctx, img, item, example_en, example_vi, cx0, y, cw, y1 - pad)
        return img

    # Landscape: word block on the left, example on the right.
    col_w = ((x1 - x0) - 3 * pad) // 2
    lx, rx = x0 + pad, x0 + 2 * pad + col_w
    probe = Image.new("RGBA", img.size)
    h_word = _draw_word_block(ctx, probe, item, lx, 0, col_w, card_h - 2 * pad, image)
    _draw_word_block(ctx, img, item, lx, y0 + (card_h - h_word) // 2, col_w, card_h - 2 * pad, image)
    sep_x = x0 + pad + col_w + pad // 2
    cv.rounded_box(img, (sep_x - ctx.px(2), y0 + pad, sep_x + ctx.px(2), y1 - pad), ctx.px(2), t.surface_2)
    if example_en:
        h_ex = _draw_example_block(ctx, probe, item, example_en, example_vi, rx, 0, col_w, card_h - 2 * pad)
        _draw_example_block(ctx, img, item, example_en, example_vi, rx, y0 + (card_h - h_ex) // 2, col_w, y1 - pad)
    return img


def build_vocab(ctx: Ctx, tts: TTSFn) -> list[Shot]:
    """Per word: word × N (alternating voices) → VI meaning → example × N (alternating voices) → VI example."""
    lesson = ctx.lesson
    cfg = ctx.cfg
    n = len(lesson.vocabulary)
    voices = list(cfg.vocab_voices) or [cfg.narrator_en]
    shots = [section_shot(ctx, tts, 2, "Vocabulary", f"{n} từ vựng cần nhớ", "Nghe – nhắc lại – ghi nhớ", "vocabulary")]
    for k, item in enumerate(lesson.vocabulary):
        example_en, example_vi = lesson.vocab_example(item)
        seq = AudioSequencer(tts, cfg.gap)

        word_times = max(1, cfg.word_repeat)
        for r in range(word_times):
            seq.say(item.word, voices[r % len(voices)], gap=0.45 if r < word_times - 1 else None)
        if cfg.vi_narration:
            seq.speak(item.meaning_vi, cfg.narrator_en, cfg.narrator_vi)
        ex_times = max(1, cfg.example_repeat)
        for r in range(ex_times):
            seq.speak(example_en, voices[r % len(voices)], cfg.narrator_vi,
                      gap=0.5 if r < ex_times - 1 else None)
        if cfg.read_example_vi and example_vi:
            seq.speak(example_vi, cfg.narrator_en, cfg.narrator_vi)

        duration = seq.duration + 0.4
        shots.append(
            Shot(
                image=draw_vocab(ctx, k),
                duration=duration,
                segment="vocabulary",
                audio=seq.cues,
                subs=[
                    SubCue(
                        0,
                        duration,
                        en=f"{item.word} /{item.ipa}/ — {example_en}",
                        vi=f"{item.word}: {item.meaning_vi} — {example_vi}",
                    )
                ],
            )
        )
    return shots
