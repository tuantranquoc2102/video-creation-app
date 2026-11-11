"""Headless smoke test: every page renders without exceptions."""

import os

import pytest
from streamlit.testing.v1 import AppTest

from ui.navigation import NAV_STATE_KEY
from ui.router import DISPLAY_NAMES

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


@pytest.mark.parametrize("page", DISPLAY_NAMES)
def test_page_renders(page, tmp_db):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state[NAV_STATE_KEY] = page
    at.run()
    assert not at.exception, [e.message for e in at.exception]


def test_lesson_page_sample_validates_and_previews(tmp_db):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state[NAV_STATE_KEY] = "🎓 Video Bài Học"
    at.session_state["lsn_sample"] = "laundry-a2.json"  # a complete sample (no external image needed)
    at.run()
    assert not at.exception
    assert any("đạt tất cả kiểm tra" in s.value for s in at.success)
    gen = next(b for b in at.button if "Tạo Video Bài Học" in b.label)
    assert not gen.disabled
    next(b for b in at.button if "xem trước" in b.label).click().run()
    assert not at.exception
