"""Channel-crawler page – list the videos of a YouTube / TikTok / Facebook link, export CSV."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.channel_crawler import (
    CSV_COLUMNS,
    KIND_LIVE,
    KIND_SHORT,
    KIND_VIDEO,
    CrawlResult,
    crawl,
    detect_platform,
    parse_urls,
    videos_to_csv,
)
from ui.components.page_header import render_page_header

_RESULT_KEY = "_crawl_result"
_KIND_LABELS = {"Video": KIND_VIDEO, "Shorts": KIND_SHORT, "Live": KIND_LIVE}
_TABLE_COLUMNS = [
    "platform", "channel", "title", "kind", "upload_date", "duration",
    "view_count", "like_count", "comment_count", "tags", "description", "url", "error",
]


def _render_form() -> tuple[list[str], dict]:
    st.markdown("#### 🔗 Link cần crawl")
    text = st.text_area(
        "Link kênh hoặc video (mỗi link một dòng):",
        placeholder="https://www.youtube.com/@tenkenh\nhttps://www.tiktok.com/@tenkenh\nhttps://www.facebook.com/watch/?v=...",
        height=120,
        key="crawl_urls",
    )
    st.caption(
        "✅ **YouTube**: kênh, playlist, video · ✅ **TikTok**: kênh, video · "
        "⚠️ **Facebook**: chỉ hỗ trợ link từng video/reel (không liệt kê được toàn bộ video của trang). "
        "Chỉ đọc metadata công khai, không tải video."
    )

    c1, c2, c3 = st.columns([1, 2, 2])
    with c1:
        limit = st.number_input(
            "Số video tối đa:",
            min_value=0,
            max_value=5000,
            value=50,
            step=10,
            help="Giới hạn cho mỗi link (với kênh YouTube: mỗi mục Video / Shorts / Live). 0 = lấy tất cả.",
            key="crawl_limit",
        )
    with c2:
        kinds = st.multiselect(
            "Loại nội dung:",
            list(_KIND_LABELS),
            default=list(_KIND_LABELS),
            help="Chỉ áp dụng phân loại cho YouTube; TikTok/Facebook luôn là Video.",
            key="crawl_kinds",
        )
    with c3:
        details = st.checkbox(
            "Lấy metadata chi tiết (mô tả, tag, ngày đăng, lượt thích)",
            value=True,
            help="Cần mở từng video YouTube nên chậm hơn (~1 giây/video). Bỏ chọn để chỉ lấy tiêu đề, link, lượt xem.",
            key="crawl_details",
        )

    urls = parse_urls(text)
    invalid = [u for u in urls if detect_platform(u) is None]
    for u in invalid:
        st.warning(f"⚠️ Bỏ qua link không thuộc YouTube / TikTok / Facebook: `{u}`")
    urls = [u for u in urls if u not in invalid]
    return urls, {
        "limit": int(limit) or None,
        "kinds": [_KIND_LABELS[k] for k in kinds],
        "details": details,
    }


def _run(urls: list[str], opts: dict) -> None:
    progress = st.progress(0.0, text="⏳ Đang lấy danh sách video...")

    def _on_progress(done: int, total: int, message: str) -> None:
        progress.progress(done / total if total else 0.0, text=f"⏳ {message}")

    try:
        result = crawl(urls, progress_cb=_on_progress, **opts)
    finally:
        progress.empty()
    st.session_state[_RESULT_KEY] = result


def _render_result(result: CrawlResult) -> None:
    for url, message in result.errors:
        st.error(f"❌ `{url}` — {message}")
    if not result.videos:
        if not result.errors:
            st.info("ℹ️ Không tìm thấy video nào phù hợp.")
        return

    failed = sum(1 for v in result.videos if v.error)
    channels = len({(v.platform, v.channel) for v in result.videos})
    st.success(f"✅ Tìm thấy **{len(result.videos)}** video từ {channels} kênh.")
    if failed:
        st.warning(f"⚠️ {failed} video không lấy được metadata chi tiết (xem cột *error*); các cột cơ bản vẫn có.")

    df = pd.DataFrame([v.to_row() for v in result.videos], columns=CSV_COLUMNS)
    st.dataframe(
        df[_TABLE_COLUMNS],
        hide_index=True,
        use_container_width=True,
        column_config={
            "url": st.column_config.LinkColumn("url"),
            "description": st.column_config.TextColumn("description", width="large"),
        },
    )
    st.download_button(
        "💾 Tải CSV",
        data=videos_to_csv(result.videos),
        file_name=f"channel_videos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        type="primary",
        help=f"File CSV UTF-8 gồm {len(CSV_COLUMNS)} cột: " + ", ".join(CSV_COLUMNS),
    )


def render() -> None:
    render_page_header(
        "🕸️",
        "Crawl Video Kênh",
        "Lấy danh sách video kèm metadata (tiêu đề, mô tả, tag, lượt xem...) từ link kênh và xuất ra CSV",
    )

    urls, opts = _render_form()
    ready = bool(urls) and bool(opts["kinds"])
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        clicked = st.button("🕸️ Bắt đầu crawl", use_container_width=True, type="primary", disabled=not ready)
    if clicked and ready:
        _run(urls, opts)

    result = st.session_state.get(_RESULT_KEY)
    if result is not None:
        st.markdown("---")
        _render_result(result)
