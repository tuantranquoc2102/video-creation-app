"""Scene video – story schema, bubble drawing and an offline end-to-end render."""

from __future__ import annotations

import json
import os

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from core.render import RenderConfig
from core.scene_video import (
    TAIL_DIRECTIONS,
    BubbleLayout,
    SceneStyle,
    StoryLoadError,
    draw_scene_frame,
    load_story_file,
    parse_story,
    render_scene_video,
    review_turns,
    story_to_json,
)
from core.scene_video.render import _place, draw_bubble
from ui.navigation import NAV_STATE_KEY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "scenes", "coffee-shop-a2.json")
BG = (40, 120, 200)


@pytest.fixture
def story():
    return load_story_file(SAMPLE)


@pytest.fixture
def images(story, tmp_path):
    paths = {}
    for i in range(len(story.scenes)):
        p = tmp_path / f"scene{i}.png"
        Image.new("RGB", (540, 960), BG).save(p)
        paths[i] = str(p)
    return paths


def test_sample_story_parses(story):
    assert len(story.scenes) == 3 and story.turn_count == 10
    assert story.scenes[0].speakers() == ["B", "A"]
    assert story.layout(0, "A").x == 0.3                       # from the JSON
    a, b = story.layout(1, "A"), story.layout(1, "B")           # defaults: left / right, tail down
    assert a.x < 0.5 < b.x and a.tail == b.tail == "down"


def test_roundtrip_keeps_layout(story):
    story.scenes[2].bubbles["B"] = BubbleLayout(x=0.8, y=0.6, tail="up-left")
    again = parse_story(story_to_json(story))
    assert again.layout(2, "B") == BubbleLayout(x=0.8, y=0.6, tail="up-left")


def test_lesson_json_becomes_one_scene(sample_dict):
    story = parse_story(sample_dict)
    assert len(story.scenes) == 1 and story.turn_count == len(sample_dict["dialogue"])
    assert story.story_id == sample_dict["lesson_id"]


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d["scenes"][0]["dialogue"][0].update(speaker="Z"), "không có nhân vật 'Z'"),
        (lambda d: d["scenes"][0]["bubbles"].update(Z={"x": 0.5}), "không có nhân vật 'Z'"),
        (lambda d: d["scenes"][0]["bubbles"]["A"].update(tail="sideways"), "tail"),
        (lambda d: d["scenes"][0]["bubbles"]["A"].update(x=1.5), "x"),
        (lambda d: d.update(scenes=[]), "scenes"),
        (lambda d: d["scenes"][0].update(unknown=1), "unknown"),
    ],
)
def test_invalid_story_is_rejected(mutate, needle):
    with open(SAMPLE, encoding="utf-8") as fh:
        data = json.load(fh)
    mutate(data)
    with pytest.raises(StoryLoadError) as exc:
        parse_story(data)
    assert needle in str(exc.value)


def test_bad_json_is_rejected():
    with pytest.raises(StoryLoadError):
        parse_story(b"{not json")
    with pytest.raises(StoryLoadError):
        parse_story("[]")


@pytest.mark.parametrize("tail", TAIL_DIRECTIONS)
def test_tail_points_where_asked(story, tail):
    cfg = RenderConfig(size=(540, 960))
    story.scenes[0].bubbles["A"] = BubbleLayout(x=0.5, y=0.5, tail=tail)
    bubble = draw_bubble(story, 0, 1, cfg, SceneStyle())
    bx, by, bw, bh = bubble.body
    alpha = bubble.image.getchannel("A")
    pad = 8  # clear of the outline
    outside = {
        "left": alpha.crop((0, 0, bx - pad, alpha.height)).getbbox(),
        "right": alpha.crop((bx + bw + pad, 0, alpha.width, alpha.height)).getbbox(),
        "up": alpha.crop((0, 0, alpha.width, by - pad)).getbbox(),
        "down": alpha.crop((0, by + bh + pad, alpha.width, alpha.height)).getbbox(),
    }
    drawn = {side for side, box in outside.items() if box}
    expected = set() if tail == "none" else {tail.split("-")[0]}
    assert drawn == expected
    if "-" in tail:  # diagonal tails lean towards their side
        band = (0, 0, alpha.width, by - pad) if tail.startswith("up") else (0, by + bh + pad, alpha.width, alpha.height)
        x0, _, x1, _ = alpha.crop(band).getbbox()
        centre = bx + bw / 2
        assert (x0 + x1) / 2 < centre if tail.endswith("left") else (x0 + x1) / 2 > centre


@pytest.mark.parametrize("x,y,tail", [(0, 0, "up-left"), (1, 1, "down-right"), (0, 1, "left"), (1, 0, "right")])
def test_bubble_stays_inside_frame(story, x, y, tail):
    cfg = RenderConfig(size=(540, 960))
    layout = BubbleLayout(x=x, y=y, tail=tail)
    story.scenes[0].bubbles["A"] = layout
    bubble = draw_bubble(story, 0, 1, cfg, SceneStyle())
    left, top = _place(bubble, layout, cfg.size)
    box = bubble.image.getchannel("A").getbbox()
    assert left + box[0] >= 0 and top + box[1] >= 0
    assert left + box[2] <= cfg.size[0] and top + box[3] <= cfg.size[1]


@pytest.mark.parametrize("size", [(540, 960), (960, 540)])
@pytest.mark.parametrize("fit", ["cover", "contain"])
def test_frame_shows_only_requested_bubbles(story, images, size, fit):
    cfg = RenderConfig(size=size, logo_path=None)
    style = SceneStyle(fit=fit)
    empty = draw_scene_frame(story, 0, [], images[0], cfg, style)
    one = draw_scene_frame(story, 0, [0], images[0], cfg, style)
    both = draw_scene_frame(story, 0, review_turns(story, 0), images[0], cfg, style)
    assert empty.size == one.size == both.size == size

    def white(img):
        return sum(1 for p in img.convert("RGB").resize((96, 96)).getdata() if min(p) > 235)

    assert white(empty) == 0 < white(one) < white(both)
    # Turn 0 is spoken by B (right side): the left third of the frame is untouched.
    crop = (0, 0, size[0] // 4, size[1])
    assert list(one.crop(crop).getdata()) == list(empty.crop(crop).getdata())


def test_missing_image_uses_placeholder_for_preview_but_blocks_render(story, images, fake_tts, tmp_path):
    frame = draw_scene_frame(story, 1, [0], None, RenderConfig(size=(270, 480)))
    assert frame.size == (270, 480)
    del images[1]
    with pytest.raises(ValueError, match="phân cảnh: 2"):
        render_scene_video(story, images, RenderConfig(size=(270, 480)), output_root=str(tmp_path), tts=fake_tts)


def test_end_to_end_render(story, images, fake_tts, tmp_path):
    cfg = RenderConfig(size=(270, 480), fps=10, preset="ultrafast", logo_path=None)
    stages = []
    result = render_scene_video(
        story, images, cfg, SceneStyle(vi_audio=True), output_root=str(tmp_path / "out"), tts=fake_tts,
        progress_cb=lambda s, d, n: stages.append(s),
    )
    for p in (result.video_path, result.srt_en_path, result.srt_vi_path, result.thumbnail_path, result.story_path):
        assert os.path.isfile(p) and os.path.getsize(p) > 0
    assert [s["name"] for s in result.segments] == ["scene-1", "scene-2", "scene-3"]
    assert {"tts", "frames", "audio", "encode"} <= set(stages)

    spoken = [t for t, _ in fake_tts.calls]
    for scene in story.scenes:
        for turn in scene.dialogue:
            assert any(turn.en.startswith(s) or s in turn.en for s in spoken)
    # Speakers alternate in dialogue order, each with their own voice; VI lines use the Vietnamese voice.
    voices = {s["voice"] for s in result.speech}
    assert {"en-US-AvaNeural", "en-US-AndrewNeural", cfg.narrator_vi} <= voices
    first = [s for s in result.speech if s["segment"] == "scene-1"][0]
    assert first["voice"] == "en-US-AndrewNeural" and first["text"].startswith("Good morning")

    with open(result.srt_en_path, encoding="utf-8") as fh:
        srt = fh.read()
    assert "Tom: Good morning! What can I get for you?" in srt and "Anna: Thank you. You're very kind!" in srt
    assert parse_story(open(result.story_path, encoding="utf-8").read()).turn_count == 10
    assert result.duration > 10 * 1.5


def test_page_shows_one_uploader_per_scene_and_layout_controls(tmp_db):
    app = os.path.join(ROOT, "app.py")
    at = AppTest.from_file(app, default_timeout=60)
    at.session_state[NAV_STATE_KEY] = "🎞️ Video Phân Cảnh"
    at.session_state["scn_source"] = "📚 Kịch bản mẫu"
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("Hình ảnh cho 3 phân cảnh" in m.value for m in at.markdown)
    assert any("Còn thiếu hình cho phân cảnh: 1, 2, 3" in w.value for w in at.warning)
    # 3 scenes × 2 speakers × (x, y) sliders and one tail selector per speaker
    assert sum(1 for s in at.slider if s.key and s.key.endswith(("_x", "_y"))) == 12
    tails = [s for s in at.selectbox if s.key and s.key.endswith("_tail")]
    assert len(tails) == 6
    gen = next(b for b in at.button if "Tạo Video Phân Cảnh" in b.label)
    assert gen.disabled                      # no images yet

    tails[0].select("left").run()            # changing the tail re-renders without error
    assert not at.exception


# ---------------------------------------------------------------------------
# Scene-based lesson file (lesson_id + meta + scenes, schema_version 3)
# ---------------------------------------------------------------------------
LESSON_V3 = os.path.join(ROOT, "samples", "scenes", "job-interviews-b1.json")


@pytest.fixture
def v3_dict():
    with open(LESSON_V3, encoding="utf-8") as fh:
        return json.load(fh)


def test_scene_lesson_file_parses(v3_dict):
    story = parse_story(v3_dict)
    assert story.story_id == "job-interviews-b1" and story.title_en == "A Job Interview"
    assert story.title_vi == "Buổi phỏng vấn xin việc"
    assert [(c.id, c.name, c.gender, c.voice) for c in story.characters] == [
        ("A", "Mia", "female", "en-US-JennyNeural"), ("B", "Alex", "male", "en-US-GuyNeural")]
    assert len(story.scenes) == 3 and story.turn_count == 12
    first = story.scenes[0]
    assert first.id == "1" and first.setting_en.startswith("Inside a modern technology company")
    assert first.image_prompt.endswith("--ar 9:16")
    assert first.dialogue[0].en == "Hello, I'm here for the interview." and first.speakers() == ["A", "B"]
    assert story.extras() == {"vocabulary": 10, "exercises": 5}
    assert "ˈ" not in story.display_text()          # IPA is not drawn → not part of the font check


def test_scene_lesson_export_keeps_every_field_and_adds_bubbles(v3_dict):
    story = parse_story(v3_dict)
    assert json.loads(story_to_json(story)) == v3_dict            # untouched until a bubble is placed
    story.scenes[1].bubbles["B"] = BubbleLayout(x=0.7, y=0.35, tail="down-left")
    exported = json.loads(story_to_json(story))
    assert exported["scenes"][1].pop("bubbles") == {"B": {"x": 0.7, "y": 0.35, "tail": "down-left"}}
    assert exported == v3_dict
    exported["scenes"][1]["bubbles"] = {"B": {"x": 0.7, "y": 0.35, "tail": "down-left"}}
    assert parse_story(exported).layout(1, "B") == BubbleLayout(x=0.7, y=0.35, tail="down-left")


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d.pop("lesson_id"), "story_id"),
        (lambda d: d["characters"][0].update(gender="other"), "characters.0.gender"),
        (lambda d: d["scenes"][1]["dialogue"][2].pop("vi"), "scenes.1.dialogue.2.vi"),
        (lambda d: d["scenes"][2]["dialogue"][0].update(speaker="C"), "không có nhân vật 'C'"),
        (lambda d: d["scenes"][0].update(dialogue=[]), "scenes.0.dialogue"),
        (lambda d: d.update(scenes="oops"), "scenes"),
    ],
)
def test_scene_lesson_errors_are_located(v3_dict, mutate, needle):
    mutate(v3_dict)
    with pytest.raises(StoryLoadError) as exc:
        parse_story(v3_dict)
    assert needle in str(exc.value)


def test_scene_lesson_renders_with_its_voices(v3_dict, fake_tts, tmp_path):
    story = parse_story(v3_dict)
    images = {}
    for i in range(3):
        images[i] = str(tmp_path / f"s{i}.png")
        Image.new("RGB", (270, 480), BG).save(images[i])
    cfg = RenderConfig(size=(270, 480), fps=10, preset="ultrafast", logo_path=None)
    result = render_scene_video(story, images, cfg, output_root=str(tmp_path / "out"), tts=fake_tts)
    assert [s["name"] for s in result.segments] == ["scene-1", "scene-2", "scene-3"]
    assert [(s["voice"], s["text"]) for s in result.speech[:2]] == [
        ("en-US-JennyNeural", "Hello, I'm here for the interview."),
        ("en-US-GuyNeural", "Welcome, Mia. Please sit down."),
    ]
    assert len(result.speech) == 12
    saved = json.load(open(result.story_path, encoding="utf-8"))
    assert saved["schema_version"] == 3 and len(saved["vocabulary"]) == 10


def test_page_with_scene_lesson_sample(tmp_db):
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    at.session_state[NAV_STATE_KEY] = "🎞️ Video Phân Cảnh"
    at.session_state["scn_source"] = "📚 Kịch bản mẫu"
    at.session_state["scn_sample"] = "job-interviews-b1.json"
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert not at.error
    assert any("Hình ảnh cho 3 phân cảnh" in m.value for m in at.markdown)
    assert any("10 từ vựng và 5 bài tập" in c.value for c in at.caption)
    assert sum(1 for t in at.text_area if t.key and t.key.startswith("scn_prompt_")) == 3
    assert len([s for s in at.selectbox if s.key and s.key.endswith("_tail")]) == 6
