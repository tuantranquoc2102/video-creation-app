import os

import pytest

from core.utils import (
    codecs_for,
    hex_to_rgb,
    is_within,
    mime_for,
    normalize_ipa,
    resolve_output_path,
    safe_filename,
    slugify,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Express Laundry is HOW MUCH?", "Express Laundry is HOW MUCH"),
        ("../../etc/passwd", "etc passwd"),
        ("a/b\\c:d", "a b c d"),
        ("   ", "video"),
        (None, "video"),
        ("Giặt nhanh", "Giặt nhanh"),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_slugify_handles_vietnamese():
    assert slugify("Giặt nhanh – Đà Nẵng!") == "giat-nhanh-da-nang"


def test_resolve_output_path_stays_inside_and_never_overwrites(tmp_path):
    d = str(tmp_path)
    p1 = resolve_output_path("../escape", "mp4", d)
    assert is_within(p1, d)
    open(p1, "w").close()
    p2 = resolve_output_path("../escape", "mp4", d)
    assert p2 != p1 and p2.endswith("escape (2).mp4")
    assert resolve_output_path("../escape", "mp4", d, overwrite=True) == p1


def test_codecs_and_mime():
    assert codecs_for("webm") == ("libvpx", "libvorbis")  # aac is invalid in webm
    assert codecs_for("MP4") == ("libx264", "aac")
    assert mime_for("mov") == "video/quicktime"


def test_hex_and_ipa():
    assert hex_to_rgb("#1a1a2e") == (26, 26, 46)
    assert hex_to_rgb("fff") == (255, 255, 255)
    with pytest.raises(ValueError):
        hex_to_rgb("zzz")
    assert normalize_ipa("/əˈbændən/") == "əˈbændən"
    assert normalize_ipa("[kæt]") == "kæt"
    assert normalize_ipa(float("nan").__str__()) == ""


def test_is_within(tmp_path):
    assert is_within(str(tmp_path / "a" / "b.mp4"), str(tmp_path))
    assert not is_within(os.path.dirname(str(tmp_path)), str(tmp_path))
