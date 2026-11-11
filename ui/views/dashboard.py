"""Dashboard view – statistics, chart, recent activity."""

import pandas as pd
import streamlit as st

from core.state import get_videos, get_stats
from core.video_service import get_recent, weekly_counts
from ui.components.page_header import render_page_header
from ui.components.video_card import STATUS_DISPLAY
from ui.navigation import navigate_to


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _render_metrics() -> None:
    stats = get_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📊 Tổng số Video", stats["total"])
    c2.metric("✅ Hoàn thành", stats["done"])
    c3.metric("⏳ Đang xử lý", stats["processing"])
    c4.metric("❌ Lỗi", stats["error"])


def _render_quick_actions() -> None:
    st.markdown("### ⚡ Thao tác nhanh")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.button("🎓 Tạo video bài học", use_container_width=True,
                  on_click=navigate_to, args=("lesson_video",))
    with c2:
        st.button("💬 Tạo video hội thoại", use_container_width=True,
                  on_click=navigate_to, args=("dialogue_video",))
    with c3:
        st.button("📂 Xem tất cả Video", use_container_width=True,
                  on_click=navigate_to, args=("manage_videos",))


def _render_recent_activity() -> None:
    st.markdown("### 📋 Video gần đây")
    recent = get_recent(get_videos(), limit=5)

    if not recent:
        st.info("Chưa có video nào. Hãy bắt đầu tạo video đầu tiên! 🎬")
        return

    rows = [
        {
            "Tên video": v.get("name", "N/A"),
            "Độ phân giải": v.get("resolution", "N/A"),
            "Ngôn ngữ TTS": v.get("tts_lang", "N/A"),
            "Trạng thái": STATUS_DISPLAY.get(v.get("status", ""), v.get("status", "N/A")),
            "Ngày tạo": v.get("created_at", "N/A"),
        }
        for v in recent
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_chart() -> None:
    st.markdown("### 📈 Hoạt động tạo video (7 ngày gần đây)")
    labels, counts = weekly_counts(get_videos())
    chart = pd.DataFrame({"Ngày": labels, "Số video": counts}).set_index("Ngày")
    st.bar_chart(chart)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header("🏠", "Dashboard", "Tổng quan về hoạt động tạo video của bạn")

    _render_metrics()
    st.markdown("")
    _render_quick_actions()
    st.markdown("---")

    left, right = st.columns([3, 2])
    with left:
        _render_recent_activity()
    with right:
        _render_chart()
