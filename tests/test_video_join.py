"""Video join: synthetic clips via the bundled ffmpeg (offline, a few seconds)."""

from __future__ import annotations

import subprocess

import imageio_ffmpeg
import pytest
from PIL import Image

from core.video_join import (
    LogoOptions,
    build_ffmpeg_command,
    extract_frame,
    join_videos,
    logo_geometry,
    preview_with_logo,
    probe,
)


def _make_clip(path, size, fps, duration, audio=True):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size[0]}x{size[1]}:rate={fps}:duration={duration}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


@pytest.fixture
def clips(tmp_path):
    a = _make_clip(tmp_path / "a.mp4", (320, 568), 30, 1.0, audio=True)
    b = _make_clip(tmp_path / "b.mp4", (640, 360), 25, 0.8, audio=False)  # other size/fps, silent
    return a, b


@pytest.fixture
def logo(tmp_path):
    path = tmp_path / "logo.png"
    Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(path)
    return str(path)


def test_probe(clips):
    info = probe(clips[0])
    assert (info.width, info.height) == (320, 568)
    assert info.has_audio and info.duration == pytest.approx(1.0, abs=0.1)
    assert not probe(clips[1]).has_audio


def test_probe_rejects_non_video(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_text("not a video")
    with pytest.raises(ValueError):
        probe(str(bad))


def test_join_mixed_clips_keeps_first_size_and_sums_duration(clips, tmp_path):
    seen = []
    out = join_videos(list(clips), str(tmp_path / "out.mp4"), progress_cb=seen.append)
    info = probe(out)
    assert (info.width, info.height) == (320, 568)
    assert info.fps == pytest.approx(30, abs=0.5)
    assert info.has_audio
    assert info.duration == pytest.approx(1.8, abs=0.15)
    assert seen and seen[-1] == 1.0


def test_join_with_logo_draws_bottom_centre(clips, logo, tmp_path):
    opts = LogoOptions(path=logo, scale=0.5, opacity=1.0, bottom_margin=0.05)
    out = join_videos(list(clips), str(tmp_path / "logo.mp4"), size=(320, 568), fps=30, logo=opts)
    frame = extract_frame(out, 1.4)  # inside the 2nd clip (letterboxed → black bars)
    x, y, w, h = logo_geometry((320, 568), (200, 100), opts)
    r, g, b = frame.getpixel((x + w // 2, y + h // 2))
    assert r > 200 and g < 60 and b < 60          # logo is red at bottom centre
    assert frame.getpixel((5, 5)) == pytest.approx((0, 0, 0), abs=20)  # letterbox bar


def test_logo_geometry_is_bottom_centre_and_even():
    x, y, w, h = logo_geometry((1080, 1920), (400, 200), LogoOptions(path="x", scale=0.2, bottom_margin=0.05))
    assert (w % 2, h % 2) == (0, 0)
    assert x == (1080 - w) // 2
    assert y + h == 1920 - int(1920 * 0.05)


def test_command_without_logo_has_no_overlay(clips):
    from core.video_join import probe as p

    cmd = build_ffmpeg_command([p(c) for c in clips], "o.webm", size=(320, 568), fps=30, fmt="webm")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay" not in graph and "anullsrc" in graph and "concat=n=2" in graph
    assert "libvpx" in cmd and "libvorbis" in cmd


def test_preview_with_logo(logo):
    img = preview_with_logo(Image.new("RGB", (640, 360), "white"), (320, 568), LogoOptions(path=logo))
    assert img.size == (320, 568)


def test_join_requires_input(tmp_path):
    with pytest.raises(ValueError):
        join_videos([], str(tmp_path / "o.mp4"))
