import json
import os
import subprocess

import imageio_ffmpeg
import pytest

from core.render import RenderConfig, render_lesson_video, render_preview_frames
from core.render.canvas import highlight_runs, layout_text, missing_glyphs
from core.render.segments.common import Ctx, resolve_voices
from core.render.subtitles import TimedCue, format_timestamp, to_srt

import config


def test_default_font_covers_vietnamese_and_ipa(sample_lesson):
    from core.lesson.importers import lesson_to_json

    assert missing_glyphs(config.DEFAULT_FONT, lesson_to_json(sample_lesson)) == ""


def test_layout_wraps_and_keeps_colours():
    runs = highlight_runs("How much is it per kilo?", [(15, 18)], "#ffffff", "#facc15")
    lay = layout_text(runs, config.DEFAULT_FONT, 40, 200)
    assert len(lay.lines) > 1
    coloured = [t for line, _ in lay.lines for t, c in line if c == "#facc15"]
    assert coloured == ["per"]
    assert all(w <= 200 for _, w in lay.lines)


def test_voices_are_distinct_when_lesson_has_none(sample_dict):
    from core.lesson import parse_lesson

    for c in sample_dict["characters"]:
        c.pop("voice")
        c["gender"] = "female"
    voices = resolve_voices(parse_lesson(sample_dict), RenderConfig())
    assert len(set(voices.values())) == 2


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
def test_preview_frames_have_video_size(sample_lesson, size):
    frames = render_preview_frames(sample_lesson, RenderConfig(size=size))
    assert {"Intro", "Hội thoại", "Từ vựng", "Ôn tập"} <= set(frames)
    assert all(img.size == size for img in frames.values())


def test_srt_format():
    assert format_timestamp(3725.5) == "01:02:05,500"
    srt = to_srt([TimedCue(0, 1.5, "Hi"), TimedCue(1.5, 2, ""), TimedCue(2, 3, "Bye")])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,500\nHi\n")
    assert "2\n00:00:02,000 --> 00:00:03,000\nBye" in srt  # empty cue skipped, numbering continuous


def test_end_to_end_render(sample_lesson, fake_tts, tmp_path):
    cfg = RenderConfig(size=(270, 480), fps=10, word_repeat=1, think_seconds=2, preset="ultrafast")
    stages = []
    result = render_lesson_video(
        sample_lesson, cfg, output_root=str(tmp_path / "out"), tts=fake_tts,
        progress_cb=lambda s, d, n: stages.append(s),
    )

    # Artefacts
    for p in (result.video_path, result.srt_en_path, result.srt_vi_path, result.thumbnail_path, result.manifest_path):
        assert os.path.isfile(p) and os.path.getsize(p) > 0
    assert [s["name"] for s in result.segments] == ["intro", "dialogue", "vocabulary", "exercises", "recap"]
    assert {"frames", "audio", "encode"} <= set(stages)

    # Every dialogue line and every exercise prompt was voiced
    spoken = [t for t, _ in fake_tts.calls]
    assert all(turn.en in spoken for turn in sample_lesson.dialogue)
    assert all(v.word in spoken for v in sample_lesson.vocabulary)

    # The encoded file has the expected duration and both streams
    probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", result.video_path],
                           capture_output=True, text=True).stderr
    assert "Video: h264" in probe and "Audio: aac" in probe and "270x480" in probe
    manifest = json.load(open(result.manifest_path, encoding="utf-8"))
    assert abs(manifest["duration"] - result.duration) < 0.01
    h, m, s = probe.split("Duration: ")[1].split(",")[0].split(":")
    assert abs(int(h) * 3600 + int(m) * 60 + float(s) - result.duration) < 0.5

    # Subtitles: one VI cue per dialogue turn
    vi = open(result.srt_vi_path, encoding="utf-8").read()
    assert all(turn.vi in vi for turn in sample_lesson.dialogue)


# ---------------------------------------------------------------- channel logo
def _logo_cfg(**kw):
    import config as app_config

    assert app_config.DEFAULT_LOGO, "assets/brand/daily-dialogues-logo.png missing"
    return RenderConfig(logo_path=app_config.DEFAULT_LOGO, **kw)


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
def test_logo_is_faint_bottom_centre_and_clear_of_content(sample_lesson, size):
    from PIL import ImageChops, ImageStat

    from core.render.canvas import logo_box
    from core.render.segments import Ctx

    with_logo = render_preview_frames(sample_lesson, _logo_cfg(size=size))["Từ vựng"]
    # Same logo config at opacity 0 → identical layout, only the watermark pixels differ.
    without = render_preview_frames(sample_lesson, _logo_cfg(size=size, logo_opacity=0))["Từ vựng"]
    box = logo_box(_logo_cfg(size=size))
    x0, y0, x1, y1 = box
    assert abs((x0 + x1) / 2 - size[0] / 2) <= 1          # horizontally centred
    assert y1 > size[1] * 0.9                             # at the bottom
    assert y0 >= Ctx(sample_lesson, _logo_cfg(size=size)).content_bottom  # never over cards/text

    diff = ImageChops.difference(with_logo, without)
    assert diff.getbbox() and diff.getbbox()[1] >= y0     # only the logo area changed
    mean_change = sum(ImageStat.Stat(diff.crop(box)).mean) / 3
    assert 2 < mean_change < 60                           # visible but faint


def test_logo_can_be_disabled(sample_lesson):
    from PIL import ImageChops

    # Portrait layout does not depend on the logo, so "no logo" == "invisible logo".
    a = render_preview_frames(sample_lesson, RenderConfig(logo_path=None))["Ôn tập"]
    b = render_preview_frames(sample_lesson, _logo_cfg(logo_opacity=0))["Ôn tập"]
    assert ImageChops.difference(a, b).getbbox() is None


def test_cli_logo_flags():
    from core.render.__main__ import build_parser, config_from_args

    assert config_from_args(build_parser().parse_args(["x.json", "--no-logo"])).logo_path is None
    cfg = config_from_args(build_parser().parse_args(["x.json", "--logo-opacity", "0.5"]))
    assert cfg.logo_path and cfg.logo_opacity == 0.5


def test_recap_reads_each_word_separately_with_pause(sample_lesson, fake_tts):
    from core.render.segments import Ctx
    from core.render.segments.outro import build_outro

    cfg = RenderConfig(size=(270, 480), recap_pause=1.0)
    shots = build_outro(Ctx(sample_lesson, cfg), fake_tts)
    word_shots = shots[1:-1]
    assert [s.audio[0].text for s in word_shots] == [v.word for v in sample_lesson.vocabulary]
    for s in word_shots:
        assert len(s.audio) == 1                                   # one word per shot
        assert s.duration >= s.audio[0].duration + 1.0 - 1e-6     # followed by ≥ 1 s pause
    assert not any("," in c.text and c.voice == cfg.narrator_en for s in shots for c in s.audio)


# ---------------------------------------------------------------- intro narration
@pytest.mark.parametrize(
    "title_vi, goal, expected",
    [
        ("Hỏi đường", "Sau bài học, người học có thể hỏi đường bằng tiếng Anh ở trình độ A1.",
         ["Hôm nay chúng ta học chủ đề: Hỏi đường.",
          "Sau bài học, người học có thể hỏi đường bằng tiếng Anh ở trình độ A1."]),
        ("Giặt nhanh mà giá BAO NHIÊU?", "Hỏi giá và dịch vụ ở tiệm giặt ủi",
         ["Hôm nay chúng ta học chủ đề: Giặt nhanh mà giá BAO NHIÊU?", "Hỏi giá và dịch vụ ở tiệm giặt ủi."]),
        ("Giới thiệu bản thân", None, ["Hôm nay chúng ta học chủ đề: Giới thiệu bản thân."]),
        ("Hỏi đường", "Hỏi đường.", ["Hôm nay chúng ta học chủ đề: Hỏi đường."]),  # no duplicate
    ],
)
def test_intro_vietnamese_lines_name_the_topic(title_vi, goal, expected):
    from types import SimpleNamespace

    from core.render.segments.intro import intro_vi_lines

    assert intro_vi_lines(SimpleNamespace(title_vi=title_vi, learning_goal_vi=goal)) == expected


def test_intro_audio_has_english_title_then_vietnamese_topic(sample_lesson, fake_tts):
    from core.render.segments import Ctx
    from core.render.segments.intro import build_intro

    cfg = RenderConfig(size=(270, 480), narrator_en="EN", narrator_vi="VI")
    cues = build_intro(Ctx(sample_lesson, cfg), fake_tts)[0].audio
    assert cues[0].voice == "EN" and cues[0].text == sample_lesson.meta.title_en
    vi_text = " ".join(c.text for c in cues if c.voice == "VI")
    assert "Hôm nay chúng ta học chủ đề" in vi_text and ".." not in vi_text
