"""Segment 1 – bilingual chat-style dialogue with highlighted vocabulary.

With a scene illustration, the image is shown in a panel (portrait: top,
landscape: left) and the chat bubbles use the remaining area.
"""

from __future__ import annotations

from PIL import Image

from core.lesson.text import find_term_spans, merge_spans
from core.render import canvas as cv
from core.render.segments.common import Ctx, new_frame, section_shot
from core.render.timeline import AudioSequencer, Shot, SubCue, TTSFn

LABEL = "HỘI THOẠI · CONVERSATION"
Box = tuple[int, int, int, int]


def turn_highlight_spans(ctx: Ctx, idx: int) -> list[tuple[int, int]]:
    text = ctx.lesson.dialogue[idx].en
    spans: list[tuple[int, int]] = []
    for item in ctx.lesson.vocab_for_turn(idx):
        spans.extend(find_term_spans(text, item.word, item.forms))
    return merge_spans(spans)


def _avatar(ctx: Ctx, char_id: str, diameter: int) -> Image.Image:
    char = ctx.lesson.character(char_id)
    img = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    r = diameter // 2
    cv.circle(img, (r, r), r, ctx.theme.text)
    cv.circle(img, (r, r), r - max(2, ctx.px(5)), ctx.speaker_color(char_id))
    initial = (char.name[:1] if char else char_id[:1]).upper()
    lay = cv.layout_text(cv.plain(initial, ctx.theme.text), ctx.font, int(diameter * 0.5), diameter, 1.0)
    cv.draw_layout(img, lay, 0, (diameter - lay.line_height) // 2, diameter, align="center", bold=True)
    return img


def _bubble(ctx: Ctx, idx: int, max_w: int, area_h: int) -> Image.Image:
    t = ctx.theme
    turn = ctx.lesson.dialogue[idx]
    char = ctx.lesson.character(turn.speaker)
    pad_x, pad_y = ctx.px(38), ctx.px(28)
    inner = max_w - 2 * pad_x

    name = cv.layout_text(cv.plain(char.name if char else turn.speaker, t.highlight), ctx.font, ctx.px(32), inner, 1.1)
    en_runs = cv.highlight_runs(turn.en, turn_highlight_spans(ctx, idx), t.text, t.highlight)
    en = cv.fit_text(en_runs, ctx.font, ctx.px(54), inner, int(area_h * 0.42), line_spacing=1.22)
    vi = cv.fit_text(cv.plain(turn.vi, t.text_vi), ctx.font, ctx.px(40), inner, int(area_h * 0.30), line_spacing=1.22)

    gap1, gap2 = ctx.px(10), ctx.px(18)
    bw = max(en.width, vi.width, name.width) + 2 * pad_x
    bh = pad_y + name.height + gap1 + en.height + gap2 + vi.height + pad_y

    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    cv.rounded_box(img, (0, 0, bw, bh), radius=ctx.px(36), fill=ctx.speaker_color(turn.speaker), alpha=245)
    y = cv.draw_layout(img, name, pad_x, pad_y, bold=True) + gap1
    y = cv.draw_layout(img, en, pad_x, y, bold=True) + gap2
    cv.draw_layout(img, vi, pad_x, y)
    return img


def _layout(ctx: Ctx) -> tuple[str, Box | None, Box]:
    """(mode, scene panel box or None, chat area box).

    Modes: ``plain`` (no illustration), ``fullscreen`` (portrait, illustration fills
    the 9:16 frame, chat at the bottom), ``panel`` (portrait, illustration above the
    chat), ``card`` (landscape, illustration as a 9:16 card on the left).
    """
    top, bottom = ctx.content_top, ctx.content_bottom
    left, right = ctx.margin, ctx.w - ctx.margin
    if not ctx.scene:
        return "plain", None, (left, top, right, bottom)
    if ctx.scene_fullscreen:
        return "fullscreen", None, (left, int(ctx.h * 0.50), right, bottom)
    if ctx.cfg.is_portrait:
        panel = (left, top, right, top + int(ctx.h * 0.27))
        return "panel", panel, (left, panel[3] + ctx.px(32), right, bottom)
    card_w = int((bottom - top) * 9 / 16)
    panel = (left, top, left + card_w, bottom)
    return "card", panel, (panel[2] + ctx.px(48), top, right, bottom)


def _draw_scene_panel(ctx: Ctx, img: Image.Image, box: Box) -> None:
    x0, y0, x1, y1 = box
    picture = cv.cover_image(ctx.scene, (x1 - x0, y1 - y0), ctx.lesson.meta.scene_focus_y)
    cv.paste_card(img, picture, x0, y0, ctx.px(32), border=ctx.theme.surface_2, border_width=ctx.px(4))


def draw_dialogue(ctx: Ctx, idx: int) -> Image.Image:
    lesson = ctx.lesson
    mode, panel, (ax0, ay0, ax1, ay1) = _layout(ctx)
    base = None
    if mode == "fullscreen":
        base = ctx.scene_frame()
        # Dark fade behind the chat so bubbles stay readable over the illustration.
        start = max(0.0, (ay0 - ctx.px(160)) / ctx.h)
        base.alpha_composite(cv.gradient(base.size, ctx.theme.bg, start, ay0 / ctx.h + 0.05, 215))
    img = new_frame(ctx, LABEL, f"{idx + 1}/{len(lesson.dialogue)}", base=base)
    if panel:
        _draw_scene_panel(ctx, img, panel)

    area_w, area_h = ax1 - ax0, ay1 - ay0
    avatar_d = ctx.px(92)
    av_gap = ctx.px(16)
    share = 0.86 if mode != "plain" or ctx.cfg.is_portrait else 0.62
    max_w = int(area_w * share) - avatar_d - av_gap
    gap = ctx.px(28)

    history = min(2, ctx.cfg.history_bubbles) if mode == "fullscreen" else ctx.cfg.history_bubbles
    start = max(0, idx - max(1, history) + 1)
    bubbles = [(j, _bubble(ctx, j, max_w, area_h)) for j in range(start, idx + 1)]

    # Keep the newest bubbles that fit (current turn is always shown).
    visible: list[tuple[int, Image.Image]] = []
    total = 0
    for j, b in reversed(bubbles):
        need = b.height + (gap if visible else 0)
        if visible and total + need > area_h:
            break
        visible.insert(0, (j, b))
        total += need

    first_id = lesson.characters[0].id
    # Full-screen: chat grows upward from the bottom so the faces stay visible.
    y = ay1 - total if mode == "fullscreen" else ay0
    for j, bubble in visible:
        speaker = lesson.dialogue[j].speaker
        factor = 1.0 if j == idx else 0.45
        avatar = _avatar(ctx, speaker, avatar_d)
        if speaker == first_id:
            ax = ax0
            bx = ax + avatar_d + av_gap
        else:
            ax = ax1 - avatar_d
            bx = ax - av_gap - bubble.width
        img.alpha_composite(cv.fade(avatar, factor), dest=(ax, y))
        img.alpha_composite(cv.fade(bubble, factor), dest=(bx, y))
        y += bubble.height + gap
    return img


def build_dialogue(ctx: Ctx, tts: TTSFn) -> list[Shot]:
    shots = [
        section_shot(ctx, tts, 1, "Conversation", "Hội thoại", "Nghe và đọc song ngữ Anh – Việt", "dialogue")
    ]
    for i, turn in enumerate(ctx.lesson.dialogue):
        voice = ctx.voice_for(turn.speaker)
        seq = AudioSequencer(tts, ctx.cfg.gap)
        # English line in the character's voice; any Vietnamese inside it goes to the VI voice.
        seq.speak(turn.en, voice, ctx.cfg.narrator_vi)
        if ctx.cfg.dialogue_vi_audio:
            seq.speak(turn.vi, voice, ctx.cfg.narrator_vi)
        duration = max(1.5, seq.duration)
        char = ctx.lesson.character(turn.speaker)
        name = char.name if char else turn.speaker
        shots.append(
            Shot(
                image=draw_dialogue(ctx, i),
                duration=duration,
                segment="dialogue",
                audio=seq.cues,
                subs=[SubCue(0, duration, en=f"{name}: {turn.en}", vi=f"{name}: {turn.vi}")],
            )
        )
    return shots
