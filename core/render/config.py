"""Render configuration & theme for lesson videos."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from config import (
    DEFAULT_FONT,
    DEFAULT_LOGO,
    DEFAULT_VOICE_EN_FEMALE,
    DEFAULT_VOICE_EN_MALE,
    DEFAULT_VOICE_EN_NARRATOR,
    DEFAULT_VOICE_VI,
)


@dataclass(frozen=True)
class Theme:
    """Colour tokens (hex).  Contrast of text on bubble/surface ≥ 4.5:1."""

    bg: str = "#0f172a"            # slate-900
    surface: str = "#1e293b"       # slate-800 – cards
    surface_2: str = "#334155"     # slate-700 – option boxes
    text: str = "#f8fafc"
    text_muted: str = "#94a3b8"
    text_vi: str = "#e2e8f0"
    accent: str = "#818cf8"        # indigo-400 – labels / pills
    speaker_a: str = "#4f46e5"     # indigo-600 bubble
    speaker_b: str = "#7e22ce"     # purple-700 bubble
    highlight: str = "#facc15"     # yellow-400 – vocabulary words
    correct: str = "#16a34a"       # green-600
    bg_overlay_alpha: int = 150    # darken background images for readability


@dataclass
class RenderConfig:
    size: tuple[int, int] = (1080, 1920)
    fps: int = 30
    theme: Theme = field(default_factory=Theme)
    bg_image: str | None = None
    font_path: str = DEFAULT_FONT

    # Voices (Edge TTS ids)
    narrator_en: str = DEFAULT_VOICE_EN_NARRATOR
    narrator_vi: str = DEFAULT_VOICE_VI
    default_female_voice: str = DEFAULT_VOICE_EN_FEMALE
    default_male_voice: str = DEFAULT_VOICE_EN_MALE
    voice_overrides: dict[str, str] = field(default_factory=dict)  # character id → voice

    # Pacing / content options
    vi_narration: bool = True        # Vietnamese narrator for section titles, meanings, explanations
    dialogue_vi_audio: bool = False  # also read each dialogue translation aloud
    # Vocabulary: word and example are read N times, cycling through these voices.
    vocab_voices: tuple[str, ...] = ("en-US-JennyNeural", "en-US-GuyNeural")
    word_repeat: int = 2             # times the vocabulary word is spoken
    example_repeat: int = 2          # times the example sentence is spoken
    read_example_vi: bool = True     # read the Vietnamese translation of the example
    use_scene_background: bool = True  # blurred scene illustration behind cards
    # Portrait videos: "fullscreen" = illustration fills the 9:16 frame (intro + dialogue);
    # "panel" = illustration cropped into a panel above the chat.
    scene_layout: str = "fullscreen"
    think_seconds: int | None = None # override every exercise's countdown
    gap: float = 0.6                 # silence after each spoken line (s)
    tick_sound: bool = True          # tick during exercise countdown
    history_bubbles: int = 3         # dialogue: previous turns kept on screen
    recap_pause: float = 1.0         # recap: silence after each word (time to repeat it)

    # Channel logo watermark (bottom centre, semi-transparent); None = no logo
    logo_path: str | None = DEFAULT_LOGO
    logo_opacity: float = 0.35       # 0 = invisible … 1 = opaque
    logo_scale: float = 0.12         # logo width as a fraction of the frame's short side

    # Encoding
    preset: str = "medium"           # x264 preset

    @property
    def is_portrait(self) -> bool:
        return self.size[1] >= self.size[0]

    def to_dict(self) -> dict:
        return asdict(self)
