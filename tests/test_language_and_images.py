"""Language-aware voice routing, vocabulary reading order and illustrations."""

import copy
import os

import pytest
from PIL import Image

from core.lesson import has_errors, load_lesson_file, parse_lesson, validate_lesson
from core.lesson.text import split_by_language
from core.render import RenderConfig, render_preview_frames
from core.render.segments import Ctx
from core.render.segments.exercise import build_exercises
from core.render.segments.vocab import build_vocab
from core.render.timeline import AudioSequencer

from conftest import ROOT

HOTEL = os.path.join(ROOT, "samples", "lessons", "hotel-checkout-a2.json")
EN, VI = "en-NARRATOR", "vi-NARRATOR"


# ---------------------------------------------------------------- splitter
@pytest.mark.parametrize(
    "text, expected",
    [
        ("a discount for students = giảm giá cho sinh viên",
         [("en", "a discount for students"), ("vi", "giảm giá cho sinh viên")]),
        ('Tom nói: "Express is ninety." = chín mươi nghìn đồng.',
         [("vi", "Tom nói"), ("en", "Express is ninety."), ("vi", "chín mươi nghìn đồng.")]),
        ('"discount" nghĩa là gì?', [("en", "discount"), ("vi", "nghĩa là gì?")]),
        ('Which word means "biên nhận, hóa đơn"?', [("en", "Which word means"), ("vi", "biên nhận, hóa đơn?")]),
        ("Bao nhiêu tiền một ký vậy anh?", [("vi", "Bao nhiêu tiền một ký vậy anh?")]),
        ("Chị có muốn đặt taxi ra sân bay không?", [("vi", "Chị có muốn đặt taxi ra sân bay không?")]),
        ("Good morning! I'd like to check out, please. Room 512.",
         [("en", "Good morning! I'd like to check out, please. Room 512.")]),
        ("Tôi ở phòng 512.", [("vi", "Tôi ở phòng 512.")]),
        ("90,000 dong", [("en", "90,000 dong")]),
        ("có giá, tốn (tiền)", [("vi", "có giá, tốn tiền")]),
        ("", []),
    ],
)
def test_split_by_language(text, expected):
    assert split_by_language(text) == expected


def test_speak_routes_each_chunk_to_the_right_voice(fake_tts):
    seq = AudioSequencer(fake_tts, gap=0.5)
    seq.speak("stain = vết bẩn, vết ố", EN, VI)
    assert [(c.voice, c.text) for c in seq.cues] == [(EN, "stain"), (VI, "vết bẩn, vết ố")]
    # chunks are sequential, never overlapping
    assert seq.cues[1].start >= seq.cues[0].start + seq.cues[0].duration


# ---------------------------------------------------------------- vocabulary audio
def test_vocab_reading_order_and_alternating_voices(sample_lesson, fake_tts):
    cfg = RenderConfig(size=(270, 480), narrator_en=EN, narrator_vi=VI, vocab_voices=("en-V1", "en-V2"))
    shots = build_vocab(Ctx(sample_lesson, cfg), fake_tts)
    word_shot = shots[1]  # shots[0] is the section card
    item = sample_lesson.vocabulary[0]
    ex_en, ex_vi = sample_lesson.vocab_example(item)
    plan = [(c.voice, c.text) for c in word_shot.audio]
    expected_vi_example = [(VI, chunk) for _, chunk in split_by_language(ex_vi)]
    assert plan[:2] == [("en-V1", item.word), ("en-V2", item.word)]
    assert plan[2] == (VI, item.meaning_vi)
    assert plan[3:5] == [("en-V1", ex_en), ("en-V2", ex_en)]
    assert plan[5:] == expected_vi_example


def test_vocab_repeat_counts_are_configurable(sample_lesson, fake_tts):
    cfg = RenderConfig(size=(270, 480), word_repeat=3, example_repeat=1, read_example_vi=False,
                       vi_narration=False, vocab_voices=("en-V1", "en-V2"))
    plan = [(c.voice, c.text) for c in build_vocab(Ctx(sample_lesson, cfg), fake_tts)[1].audio]
    word = sample_lesson.vocabulary[0].word
    assert [v for v, t in plan if t == word] == ["en-V1", "en-V2", "en-V1"]
    assert len(plan) == 4  # 3 × word + 1 × example, no Vietnamese


def test_exercise_mixed_text_never_reads_vietnamese_with_english_voice(sample_lesson, fake_tts):
    cfg = RenderConfig(size=(270, 480), narrator_en=EN, narrator_vi=VI, tick_sound=False)
    for shot in build_exercises(Ctx(sample_lesson, cfg), fake_tts, None):
        for cue in shot.audio:
            chunks = split_by_language(cue.text)
            assert len(chunks) == 1, cue.text  # each cue is single-language
            assert cue.voice == (VI if chunks[0][0] == "vi" else EN), cue.text


# ---------------------------------------------------------------- images
def test_hotel_sample_has_valid_scene_image():
    lesson = load_lesson_file(HOTEL)
    assert lesson.scene_path and os.path.isfile(lesson.scene_path)
    assert not has_errors(validate_lesson(lesson))


def _hotel_dict():
    import json
    with open(HOTEL, encoding="utf-8") as fh:
        return json.load(fh)


def test_missing_and_escaping_images_are_errors(tmp_path):
    d = _hotel_dict()
    d["meta"]["scene_image"] = "../../etc/passwd"
    d["vocabulary"][0]["image"] = "nope.png"
    lesson = parse_lesson(d, base_dir=str(tmp_path))
    errs = {i.path: i.message for i in validate_lesson(lesson) if i.severity == "error"}
    assert "thư mục bài học" in errs["meta.scene_image"]
    assert "Không tìm thấy" in errs["vocabulary[0].image"]
    assert lesson.scene_path is None


def test_uploaded_json_without_images_reports_missing_folder():
    lesson = parse_lesson(_hotel_dict())  # no base_dir, as with a bare upload
    assert any(i.path == "meta.scene_image" and i.severity == "error" for i in validate_lesson(lesson))


def test_non_image_file_is_rejected(tmp_path):
    (tmp_path / "fake.png").write_text("not an image")
    d = _hotel_dict()
    d["meta"]["scene_image"] = "fake.png"
    errs = [i for i in validate_lesson(parse_lesson(d, base_dir=str(tmp_path))) if i.severity == "error"]
    assert any("không phải ảnh" in i.message for i in errs)


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
def test_scene_and_vocab_images_render(tmp_path, size):
    # A temporary lesson folder holding the scene illustration + one per-word image.
    d = _hotel_dict()
    d["vocabulary"][0]["image"] = "word.png"
    Image.new("RGB", (300, 200), "red").save(tmp_path / "word.png")
    scene_src = os.path.join(os.path.dirname(HOTEL), d["meta"]["scene_image"])
    (tmp_path / d["meta"]["scene_image"]).write_bytes(open(scene_src, "rb").read())
    lesson = parse_lesson(d, base_dir=str(tmp_path))
    assert not has_errors(validate_lesson(lesson))

    frames = render_preview_frames(lesson, RenderConfig(size=size))
    assert all(f.size == size for f in frames.values())
    vocab = frames["Từ vựng"]
    reds = sum(1 for px in vocab.getdata() if px[0] > 200 and px[1] < 40 and px[2] < 40)
    assert reds > 1000  # the per-word illustration is visible on the card


# ---------------------------------------------------------------- 9:16 layouts
def _mean_diff(a, b):
    from PIL import ImageChops, ImageStat
    return sum(ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB"))).mean) / 3


def test_fullscreen_layout_shows_whole_9_16_illustration():
    from core.render import canvas as cv
    from core.render.segments import draw_dialogue, draw_intro

    lesson = load_lesson_file(HOTEL)
    full = Ctx(lesson, RenderConfig(scene_layout="fullscreen"))
    panel = Ctx(lesson, RenderConfig(scene_layout="panel"))
    assert full.scene_fullscreen and not panel.scene_fullscreen

    # The middle band of the frame (characters) is the illustration itself, not a blurred background.
    scene = cv.cover_image(lesson.scene_path, (1080, 1920), lesson.meta.scene_focus_y)
    band = (0, 500, 1080, 900)
    for frame in (draw_intro(full), draw_dialogue(full, 0)):
        assert _mean_diff(frame.crop(band), scene.crop(band)) < 12
    assert _mean_diff(draw_dialogue(panel, 0).crop(band), scene.crop(band)) > 12


def test_landscape_uses_exact_9_16_card():
    lesson = load_lesson_file(HOTEL)
    ctx = Ctx(lesson, RenderConfig(size=(1920, 1080)))
    card = ctx.scene_card(900)
    assert card.size == (506, 900)  # 9:16
    assert not ctx.scene_fullscreen  # full-screen mode only applies to portrait videos
