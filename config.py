"""Application configuration."""

import os

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

# Fonts (auto-discovered from assets/fonts/)
FONTS: dict[str, str] = {}
if os.path.isdir(FONTS_DIR):
    for f in sorted(os.listdir(FONTS_DIR)):
        if f.lower().endswith((".ttf", ".otf")):
            name = os.path.splitext(f)[0]
            FONTS[name] = os.path.join(FONTS_DIR, f)

# Prefer a font that covers Vietnamese + IPA glyphs.  (Alphabetical order
# would pick "Arial Rounded Bold", which lacks most Vietnamese letters.)
_PREFERRED_FONTS = ("Arial Unicode",)
DEFAULT_FONT = next(
    (FONTS[n] for n in _PREFERRED_FONTS if n in FONTS),
    next(iter(FONTS.values()), "Arial"),
)
DEFAULT_FONT_NAME = next((n for n, p in FONTS.items() if p == DEFAULT_FONT), None)

# Video defaults
VIDEO_RESOLUTIONS = {
    "16:9 (1920x1080)": (1920, 1080),
    "9:16 (1080x1920)": (1080, 1920),
}

DEFAULT_RESOLUTION = "9:16 (1080x1920)"
DEFAULT_FPS = 30

# TTS
TTS_LANGUAGES = {
    "Tiếng Việt": "vi",
    "English": "en",
    "日本語": "ja",
    "中文": "zh",
    "한국어": "ko",
}

TTS_SPEEDS = {
    "Chậm": 0.8,
    "Bình thường": 1.0,
    "Nhanh": 1.2,
}

# Speaker voice options – Edge TTS (en-US)
# Sorted: deep/mature first → young.  Each entry has voice_id, gender, description.
SPEAKER_VOICES: dict[str, dict[str, str]] = {
    # ── Male (deep → young) ──────────────────────────────────────────
    "🎙️ Christopher (Nam – trầm, uy tín)": {
        "voice_id": "en-US-ChristopherNeural",
        "gender": "male",
        "engine": "edge",
    },
    "🎙️ Eric (Nam – trầm, lý trí)": {
        "voice_id": "en-US-EricNeural",
        "gender": "male",
        "engine": "edge",
    },
    "🎙️ Guy (Nam – trầm, nhiệt huyết)": {
        "voice_id": "en-US-GuyNeural",
        "gender": "male",
        "engine": "edge",
    },
    "🎙️ Steffan (Nam – trung, điềm đạm)": {
        "voice_id": "en-US-SteffanNeural",
        "gender": "male",
        "engine": "edge",
    },
    "🎙️ Roger (Nam – trung, sôi nổi)": {
        "voice_id": "en-US-RogerNeural",
        "gender": "male",
        "engine": "edge",
    },
    "🎙️ Andrew (Nam – ấm, tự tin)": {
        "voice_id": "en-US-AndrewNeural",
        "gender": "male",
        "engine": "edge",
    },
    "🎙️ Brian (Nam – trẻ, thân thiện)": {
        "voice_id": "en-US-BrianNeural",
        "gender": "male",
        "engine": "edge",
    },
    # ── Female (deep → young) ────────────────────────────────────────
    "🎤 Aria (Nữ – trầm, tự tin)": {
        "voice_id": "en-US-AriaNeural",
        "gender": "female",
        "engine": "edge",
    },
    "🎤 Michelle (Nữ – trung, dễ chịu)": {
        "voice_id": "en-US-MichelleNeural",
        "gender": "female",
        "engine": "edge",
    },
    "🎤 Jenny (Nữ – trung, thân thiện)": {
        "voice_id": "en-US-JennyNeural",
        "gender": "female",
        "engine": "edge",
    },
    "🎤 Ava (Nữ – trẻ, biểu cảm)": {
        "voice_id": "en-US-AvaNeural",
        "gender": "female",
        "engine": "edge",
    },
    "🎤 Emma (Nữ – trẻ, vui vẻ)": {
        "voice_id": "en-US-EmmaNeural",
        "gender": "female",
        "engine": "edge",
    },
    "🎤 Ana (Nữ – nhí, dễ thương)": {
        "voice_id": "en-US-AnaNeural",
        "gender": "female",
        "engine": "edge",
    },
}

# Speaker voice options – Edge TTS (vi-VN)
SPEAKER_VOICES_VI: dict[str, dict[str, str]] = {
    "🎙️ NamMinh (Nam – trầm, chuyên nghiệp)": {
        "voice_id": "vi-VN-NamMinhNeural",
        "gender": "male",
        "engine": "edge",
    },
    "🎤 HoaiMy (Nữ – nhẹ nhàng, tự nhiên)": {
        "voice_id": "vi-VN-HoaiMyNeural",
        "gender": "female",
        "engine": "edge",
    },
}

DEFAULT_TTS_ENGINE = "Edge TTS"

# Default voices (Edge TTS voice ids) – two distinct voices so speakers
# are distinguishable out of the box.
DEFAULT_VOICE_EN_MALE = "en-US-AndrewNeural"
DEFAULT_VOICE_EN_FEMALE = "en-US-AvaNeural"
DEFAULT_VOICE_EN_NARRATOR = "en-US-JennyNeural"
DEFAULT_VOICE_VI = "vi-VN-HoaiMyNeural"

DEFAULT_SPEAKER_VOICES: dict[str, dict[str, str]] = {
    "speaker 1": {"voice_id": DEFAULT_VOICE_EN_MALE, "gender": "male", "engine": "edge"},
    "speaker 2": {"voice_id": DEFAULT_VOICE_EN_FEMALE, "gender": "female", "engine": "edge"},
}

# Local persistence (SQLite) & caches
DB_PATH = os.environ.get("VIDEO_APP_DB", os.path.join(DATA_DIR, "app.db"))
TTS_CACHE_DIR = os.path.join(DATA_DIR, "tts_cache")
LESSON_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "lessons")
SAMPLES_DIR = os.path.join(BASE_DIR, "samples", "lessons")

# Channel logo (watermark at the bottom centre of every lesson-video frame)
BRAND_DIR = os.path.join(ASSETS_DIR, "brand")
_LOGO = os.path.join(BRAND_DIR, "daily-dialogues-logo.png")
DEFAULT_LOGO: str | None = _LOGO if os.path.isfile(_LOGO) else None

# Supported file types
SUPPORTED_TEXT_FILES = ["txt", "csv"]
SUPPORTED_IMAGE_FILES = ["png", "jpg", "jpeg", "webp"]

# ---------------------------------------------------------------------------
# CSV video-type definitions
# ---------------------------------------------------------------------------
# Each entry describes a CSV format the user can upload.
#   key            – internal identifier stored in the video record
#   label          – display name in the UI
#   icon           – emoji for the selector card
#   description    – short helper text
#   required_cols  – columns that MUST be present (after reading with the
#                    correct separator)
#   optional_cols  – columns that MAY be present
#   separator      – CSV delimiter
#   sample         – a tiny inline example shown to the user

CSV_VIDEO_TYPES: dict[str, dict] = {
    "dialogue": {
        "label": "Hội thoại 2 người",
        "icon": "💬",
        "description": "Video hội thoại giữa 2 nhân vật, mỗi hàng là một lượt nói.",
        "required_cols": ["speaker 1", "speaker 2"],
        "optional_cols": [],
        "separator": ";",
        "sample": (
            "speaker 1;speaker 2\n"
            "Xin chào! Hôm nay bạn có khỏe không?;\n"
            ";Tôi khỏe, cảm ơn bạn! Còn bạn thì sao?\n"
        ),
    },
    "vocabulary": {
        "label": "Từ vựng",
        "icon": "📖",
        "description": "Video học từ vựng với phiên âm IPA, nghĩa, ví dụ và hình minh họa.",
        "required_cols": ["english", "ipa", "vietnam", "example", "translate"],
        "optional_cols": ["image"],
        "separator": ";",
        "sample": (
            "english;ipa;vietnam;example;translate;image\n"
            "abandon;əˈbændən;bỏ rơi, từ bỏ;She had to abandon her car.;Cô ấy phải bỏ lại xe.;abandon.png\n"
        ),
    },
}
