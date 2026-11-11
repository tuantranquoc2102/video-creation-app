"""Manage-videos view – list, filter, delete videos."""

import pandas as pd
import streamlit as st

from config import VIDEO_RESOLUTIONS
from core.state import get_videos, get_stats, remove_videos_by_status
from core.video_service import filter_videos
from ui.components.page_header import render_page_header
from ui.components.video_card import STATUS_DISPLAY, render_video_card


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _render_filters() -> tuple[str, str, str, str]:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        search = st.text_input("🔍 Tìm kiếm:", placeholder="Tên video...")
    with c2:
        status = st.selectbox("Trạng thái:", ["Tất cả", "Hoàn thành", "Đang xử lý", "Lỗi"])
    with c3:
        sort_by = st.selectbox("Sắp xếp theo:", ["Mới nhất", "Cũ nhất", "Tên A-Z", "Tên Z-A"])
    with c4:
        resolution = st.selectbox("Độ phân giải:", ["Tất cả", *VIDEO_RESOLUTIONS.keys()])
    return search, status, sort_by, resolution


def _render_table(videos: list[dict]) -> None:
    if not videos:
        return
    rows = [
        {
            "Tên video": v.get("name", "N/A"),
            "Độ phân giải": v.get("resolution", "N/A"),
            "FPS": v.get("fps", "N/A"),
            "Định dạng": str(v.get("format", "N/A")).upper(),
            "TTS": f"{v.get('tts_lang', 'N/A')} ({v.get('tts_engine', 'N/A')})",
            "Trạng thái": STATUS_DISPLAY.get(v.get("status", ""), v.get("status", "N/A")),
            "Ngày tạo": v.get("created_at", "N/A"),
        }
        for v in videos
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_bulk_actions(videos: list[dict]) -> None:
    st.markdown("---")
    st.markdown("### 🔧 Thao tác hàng loạt")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑️ Xóa tất cả video có lỗi", type="secondary"):
            remove_videos_by_status("Lỗi")
            st.rerun()
    with c2:
        if st.button("📥 Xuất danh sách (CSV)", type="secondary"):
            if videos:
                csv = pd.DataFrame(videos).to_csv(index=False)
                st.download_button("💾 Tải CSV", data=csv, file_name="video_list.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header("📂", "Quản lý Video", "Xem, tìm kiếm và quản lý các video đã tạo")

    videos = get_videos()
    stats = get_stats()

    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Tổng số video", stats["total"])
    c2.metric("Hoàn thành", stats["done"])
    c3.metric("Lỗi", stats["error"])
    st.markdown("---")

    if not videos:
        st.markdown(
            '<div class="empty-state"><h3>📭 Chưa có video nào</h3>'
            "<p>Hãy chuyển sang tab <strong>Tạo Video</strong> để bắt đầu!</p></div>",
            unsafe_allow_html=True,
        )
        return

    # View toggle
    _, toggle_col = st.columns([4, 1])
    with toggle_col:
        table_mode = st.toggle("📊 Dạng bảng", value=False)

    # Filters
    search, status, sort_by, resolution = _render_filters()
    filtered = filter_videos(videos, search=search, status=status, resolution=resolution, sort_by=sort_by)

    st.markdown(f"**Hiển thị {len(filtered)}/{len(videos)} video**")
    st.markdown("---")

    if not filtered:
        st.warning("Không tìm thấy video phù hợp với bộ lọc.")
        return

    if table_mode:
        _render_table(filtered)
    else:
        for idx, video in enumerate(filtered):
            render_video_card(video, idx)

    _render_bulk_actions(videos)
