"""Shared layout context, header and section-title cards."""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from core.lesson.schema import Lesson
from core.render import canvas as cv
from core.render.config import RenderConfig
from core.render.timeline import AudioSequencer, Shot, SubCue, TTSFn

# Alternate voices used when both characters would otherwise share a voice.
_ALT_VOICE = {"female": "en-US-EmmaNeural", "male": "en-US-BrianNeural"}

POS_VI = {
    "noun": "danh từ",
    "verb": "động từ",
    "adjective": "tính từ",
    "adverb": "trạng từ",
    "preposition": "giới từ",
    "pronoun": "đại từ",
    "conjunction": "liên từ",
    "phrase": "cụm từ",
    "phrasal verb": "cụm động từ",
    "idiom": "thành ngữ",
    "interjection": "thán từ",
}


@dataclass
class Ctx:
    lesson: Lesson
    cfg: RenderConfig
    voices: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.voices = resolve_voices(self.lesson, self.cfg)

    # geometry ---------------------------------------------------------------
    @property
    def w(self) -> int:
        return self.cfg.size[0]

    @property
    def h(self) -> int:
        return self.cfg.size[1]

    @property
    def u(self) -> float:
        """Scale unit: 1.0 for 1080 px on the short side."""
        return min(self.w, self.h) / 1080

    def px(self, v: float) -> int:
        return int(round(v * self.u))

    @property
    def margin(self) -> int:
        return int(self.w * 0.06)

    @property
    def content_top(self) -> int:
        return int(self.h * (0.14 if self.cfg.is_portrait else 0.18))

    @property
    def content_bottom(self) -> int:
        # Portrait: keep clear of the Shorts/Reels/TikTok UI overlay at the bottom.
        if self.cfg.is_portrait:
            return int(self.h * 0.80)
        # Landscape: leave room for the channel logo at the bottom centre.
        return int(self.h * (0.86 if self.cfg.logo_path else 0.93))

    @property
    def content_width(self) -> int:
        return self.w - 2 * self.margin

    @property
    def font(self) -> str:
        return self.cfg.font_path

    @property
    def theme(self):
        return self.cfg.theme

    # images ----------------------------------------------------------------
    @property
    def scene(self) -> str | None:
        return self.lesson.scene_path

    def background(self) -> Image.Image:
        return cv.background(self.cfg, self.scene, self.lesson.meta.scene_focus_y)

    @property
    def scene_fullscreen(self) -> bool:
        """Portrait video + illustration + full-screen layout."""
        return bool(self.scene) and self.cfg.is_portrait and self.cfg.scene_layout == "fullscreen"

    def scene_frame(self) -> Image.Image:
        """The illustration filling the whole 9:16 frame, darkened at top/bottom for text."""
        img = cv.cover_image(self.scene, (self.w, self.h), self.lesson.meta.scene_focus_y)
        img.alpha_composite(_top_gradient(img.size, self.theme.bg, 0.22, 240))  # header readability
        return img

    def scene_card(self, height: int) -> Image.Image:
        """The illustration as an exact 9:16 card of *height* pixels (minimal crop)."""
        return cv.cover_image(self.scene, (int(height * 9 / 16), height), self.lesson.meta.scene_focus_y)

    # voices ----------------------------------------------------------------
    def voice_for(self, char_id: str) -> str:
        return self.voices.get(char_id, self.cfg.narrator_en)

    def speaker_color(self, char_id: str) -> str:
        first = self.lesson.characters[0].id
        return self.theme.speaker_a if char_id == first else self.theme.speaker_b


def _top_gradient(size: tuple[int, int], color: str, end: float, max_alpha: int) -> Image.Image:
    """*color* at the top fading to transparent at fraction *end* of the height."""
    return cv.gradient(size, color, 1.0 - end, 1.0, max_alpha).transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def resolve_voices(lesson: Lesson, cfg: RenderConfig) -> dict[str, str]:
    """character id → voice id: override > lesson JSON > default by gender, kept distinct."""
    voices: dict[str, str] = {}
    for c in lesson.characters:
        voice = cfg.voice_overrides.get(c.id) or c.voice
        if not voice:
            voice = cfg.default_female_voice if c.gender == "female" else cfg.default_male_voice
        if voice in voices.values():
            voice = _ALT_VOICE[c.gender] if _ALT_VOICE[c.gender] not in voices.values() else voice
        voices[c.id] = voice
    return voices


# ---------------------------------------------------------------------------
# Frame scaffolding
# ---------------------------------------------------------------------------
def new_frame(ctx: Ctx, label: str, counter: str | None = None, base: Image.Image | None = None) -> Image.Image:
    """Background (or *base*) + header (section pill, counter, lesson title)."""
    img = base if base is not None else ctx.background()
    t = ctx.theme
    y0 = int(ctx.h * (0.05 if ctx.cfg.is_portrait else 0.045))
    size = ctx.px(34)
    box = cv.pill(img, label, ctx.margin, y0, ctx.font, size, bg=t.surface, fg=t.accent)
    if counter:
        cv.pill(img, counter, ctx.w - ctx.margin, y0, ctx.font, size, bg=t.surface, fg=t.text, align="right")
    if base is not None:  # over a photo/illustration: put the title in its own dark pill
        title = cv.truncate(ctx.lesson.meta.title_en, ctx.font, ctx.px(30), ctx.content_width - ctx.px(60))
        cv.pill(img, title, ctx.margin, box[3] + ctx.px(12), ctx.font, ctx.px(30),
                bg=t.surface, fg=t.text_vi, bold=False)
        return img
    title = cv.truncate(ctx.lesson.meta.title_en, ctx.font, ctx.px(32), ctx.content_width)
    lay = cv.layout_text(cv.plain(title, t.text_muted), ctx.font, ctx.px(32), ctx.content_width)
    cv.draw_layout(img, lay, ctx.margin, box[3] + ctx.px(14))
    return img


def draw_section_card(ctx: Ctx, number: int, title_en: str, title_vi: str, hint_vi: str = "") -> Image.Image:
    img = ctx.background()
    t = ctx.theme
    cx = ctx.w // 2
    y = int(ctx.h * (0.33 if ctx.cfg.is_portrait else 0.26))
    cv.circle(img, (cx, y), ctx.px(90), t.speaker_a)
    num = cv.layout_text(cv.plain(str(number), t.text), ctx.font, ctx.px(110), 400)
    cv.draw_layout(img, num, cx - num.width // 2, y - num.line_height // 2 - ctx.px(6), bold=True)
    y += ctx.px(150)
    for text, size, color, bold in (
        (f"PHẦN {number}", 36, t.accent, True),
        (title_en, 96, t.text, True),
        (title_vi, 60, t.highlight, True),
        (hint_vi, 40, t.text_muted, False),
    ):
        if not text:
            continue
        lay = cv.layout_text(cv.plain(text, color), ctx.font, ctx.px(size), ctx.content_width)
        y = cv.draw_layout(img, lay, ctx.margin, y, ctx.content_width, align="center", bold=bold)
        y += ctx.px(18)
    return img


_NUM_VI = {1: "một", 2: "hai", 3: "ba", 4: "bốn"}


def section_shot(
    ctx: Ctx,
    tts: TTSFn,
    number: int,
    title_en: str,
    title_vi: str,
    hint_vi: str,
    segment: str,
) -> Shot:
    seq = AudioSequencer(tts, ctx.cfg.gap)
    seq.speak(title_en, ctx.cfg.narrator_en, ctx.cfg.narrator_vi, gap=0.3)
    if ctx.cfg.vi_narration:
        seq.speak(f"Phần {_NUM_VI.get(number, number)}: {title_vi}.", ctx.cfg.narrator_en, ctx.cfg.narrator_vi)
    duration = max(2.5, seq.duration + 0.4)
    return Shot(
        image=draw_section_card(ctx, number, title_en, title_vi, hint_vi),
        duration=duration,
        segment=segment,
        audio=seq.cues,
        subs=[SubCue(0, duration, en=title_en, vi=title_vi)],
    )
