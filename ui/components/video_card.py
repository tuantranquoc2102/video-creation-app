"""Video card component – used by the manage-videos view."""

import os

import streamlit as st

from core.state import remove_video
from core.utils import mime_for

STATUS_ICONS: dict[str, str] = {
    "Hoàn thành": "🟢",
    "Đang xử lý": "🟡",
    "Lỗi": "🔴",
}

STATUS_DISPLAY: dict[str, str] = {
    "Hoàn thành": "🟢 Hoàn thành",
    "Đang xử lý": "🟡 Đang xử lý",
    "Lỗi": "🔴 Lỗi",
}


def render_video_card(video: dict, idx: int) -> None:
    """Render a single video card row with expand/delete actions.

    Widget keys use the persistent record ``id`` (not the list position) so
    toggles stay attached to the right video after filtering/deleting.
    """
    status = video.get("status", "")
    icon = STATUS_ICONS.get(status, "⚪")
    vid_key = video.get("id", idx)
    detail_key = f"detail_{vid_key}"
    output_path = video.get("output_path") or ""
    file_exists = bool(output_path) and os.path.isfile(output_path)

    with st.container():
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

        with col1:
            st.markdown(f"**🎬 {video.get('name', 'N/A')}**")
            st.caption(f"📅 {video.get('created_at', 'N/A')}")

        with col2:
            st.markdown(f"📐 {video.get('resolution', 'N/A')}")
            st.caption(f"🔊 {video.get('tts_lang', 'N/A')} | {video.get('tts_engine', 'N/A')}")

        with col3:
            st.markdown(f"{icon} {status or 'N/A'}")
            st.caption(f"🎞️ {str(video.get('format', 'mp4')).upper()} | {video.get('fps', 30)} FPS")

        with col4:
            ca, cb = st.columns(2)
            with ca:
                if st.button("👁️", key=f"view_{vid_key}", help="Xem chi tiết"):
                    st.session_state[detail_key] = not st.session_state.get(detail_key, False)
            with cb:
                if st.button("🗑️", key=f"del_{vid_key}", help="Xóa video (cả file trong output/)"):
                    remove_video(video)
                    st.rerun()

        # Expandable detail
        if st.session_state.get(detail_key, False):
            with st.expander("📋 Chi tiết video", expanded=True):
                if file_exists:
                    st.video(output_path)
                    with open(output_path, "rb") as fh:
                        st.download_button(
                            "⬇️ Tải video",
                            data=fh,
                            file_name=os.path.basename(output_path),
                            mime=mime_for(video.get("format", "mp4")),
                            key=f"dl_{vid_key}",
                        )
                elif output_path:
                    st.warning(f"Không tìm thấy file: `{output_path}`")

                dc1, dc2 = st.columns(2)
                with dc1:
                    st.markdown("**Cấu hình video:**")
                    st.json({
                        "Tên": video.get("name"),
                        "Độ phân giải": video.get("resolution"),
                        "FPS": video.get("fps"),
                        "Định dạng": video.get("format"),
                        "Kiểu chữ": video.get("text_style"),
                    })
                with dc2:
                    st.markdown("**Cấu hình TTS:**")
                    st.json({
                        "Ngôn ngữ": video.get("tts_lang"),
                        "Tốc độ": video.get("tts_speed"),
                        "Engine": video.get("tts_engine"),
                        "Hình nền": video.get("bg_mode"),
                    })
                if video.get("text_content"):
                    st.markdown("**Nội dung script:**")
                    st.text_area(
                        "Script",
                        video["text_content"],
                        height=150,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"script_{vid_key}",
                    )

        st.divider()
