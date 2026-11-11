"""Dialogue video page – dedicated page for generating 2-speaker dialogue videos."""

import base64
import os
import tempfile
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from config import (
    ASSETS_DIR,
    CSV_VIDEO_TYPES,
    DEFAULT_FPS,
    DEFAULT_RESOLUTION,
    DEFAULT_SPEAKER_VOICES,
    DEFAULT_TTS_ENGINE,
    DEFAULT_FONT_NAME,
    FONTS,
    SPEAKER_VOICES,
    SUPPORTED_IMAGE_FILES,
    VIDEO_RESOLUTIONS,
)
from core.state import add_video
from core.video_service import build_video_entry, csv_to_text, parse_csv
from core.generators import generate_video
from core.utils import mime_for
from ui.components.csv_preview import render_csv_preview, render_sample_format
from ui.components.page_header import render_page_header

_DIALOGUE_SPEC = CSV_VIDEO_TYPES["dialogue"]


def _default_font_index(font_names: list[str]) -> int:
    """Default to the font that covers Vietnamese + IPA glyphs."""
    return font_names.index(DEFAULT_FONT_NAME) if DEFAULT_FONT_NAME in font_names else 0


# ---------------------------------------------------------------------------
# 1. CSV Upload & Validation
# ---------------------------------------------------------------------------
def _render_csv_upload() -> tuple[str, pd.DataFrame | None]:
    """Upload, validate, and preview the dialogue CSV.

    Returns (text_for_preview, dataframe_or_None).
    """
    st.markdown("#### 📂 Upload file CSV hội thoại")

    render_sample_format("dialogue")
    st.markdown("")

    f = st.file_uploader(
        "Chọn file CSV",
        type=["csv"],
        help=f"Separator: `;` — Cần có cột: {', '.join(f'`{c}`' for c in _DIALOGUE_SPEC['required_cols'])}",
        key="dlg_csv_uploader",
    )

    if not f:
        return "", None

    raw = f.read()
    sep = _DIALOGUE_SPEC["separator"]
    try:
        df = parse_csv(raw, separator=sep)
    except Exception as exc:
        st.error(f"❌ Không thể đọc file CSV: {exc}")
        return "", None

    # Validate required columns
    required = {c.lower() for c in _DIALOGUE_SPEC["required_cols"]}
    actual = {c.strip().lower() for c in df.columns}
    missing = required - actual
    if missing:
        st.error(
            f"⚠️ Thiếu cột bắt buộc: **{', '.join(missing)}**. "
            f"File cần có: {', '.join(f'`{c}`' for c in _DIALOGUE_SPEC['required_cols'])}"
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        return "", None

    # Rich preview
    render_csv_preview(df, "dialogue")
    text = csv_to_text(df, "dialogue")

    with st.expander("📄 Văn bản TTS sẽ được tạo", expanded=False):
        st.text(text)

    return text, df


# ---------------------------------------------------------------------------
# 2. Speaker voices
# ---------------------------------------------------------------------------
def _render_speaker_voices() -> dict[str, dict[str, str]]:
    st.markdown("#### 🎙️ Giọng đọc cho từng Speaker")

    voice_labels = list(SPEAKER_VOICES.keys())

    def _default_index(speaker: str) -> int:
        """Index of the default voice for *speaker* (distinct voices per speaker)."""
        wanted = DEFAULT_SPEAKER_VOICES[speaker]["voice_id"]
        for i, label in enumerate(voice_labels):
            if SPEAKER_VOICES[label]["voice_id"] == wanted:
                return i
        return 0

    vc1, vc2 = st.columns(2)
    with vc1:
        st.caption("🗣️ Speaker 1")
        v1 = st.selectbox(
            "Giọng Speaker 1",
            voice_labels,
            index=_default_index("speaker 1"),
            key="dlg_voice_s1",
            label_visibility="collapsed",
        )
    with vc2:
        st.caption("🗣️ Speaker 2")
        v2 = st.selectbox(
            "Giọng Speaker 2",
            voice_labels,
            index=_default_index("speaker 2"),
            key="dlg_voice_s2",
            label_visibility="collapsed",
        )

    return {
        "speaker 1": SPEAKER_VOICES[v1],
        "speaker 2": SPEAKER_VOICES[v2],
    }


# ---------------------------------------------------------------------------
# Preview helper
# ---------------------------------------------------------------------------
_PREVIEW_S1_COLOR = "#667eea"
_PREVIEW_S2_COLOR = "#764ba2"


def _render_preview(
    display: dict,
    bg: dict,
    vid: dict,
) -> None:
    """Render a live HTML/CSS mockup with background image support."""
    bubble_chat = display["bubble_chat"]
    font_size = display["font_size_text"]
    font_color = display["font_color"]
    padding_top_pct = int(display.get("padding_top", 0.15) * 100)

    preview_fs = max(12, int(font_size * 0.45))
    top = f"{padding_top_pct}%"

    # --- Resolve background for preview ---
    bg_style = ""
    if bg.get("images"):
        # Uploaded images – use the first one as preview
        img_file = bg["images"][0]
        img_file.seek(0)
        b64 = base64.b64encode(img_file.read()).decode()
        img_file.seek(0)
        bg_style = (
            f"background:url(data:image/{img_file.name.rsplit('.', 1)[-1].lower()};base64,{b64}) "
            f"center/cover no-repeat;"
        )
    elif bg.get("images_from_library"):
        # Library images – read the first file
        first = bg["images_from_library"][0]
        path = os.path.join(ASSETS_DIR, first)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
            ext = first.rsplit(".", 1)[-1].lower()
            bg_style = f"background:url(data:image/{ext};base64,{b64}) center/cover no-repeat;"
    if not bg_style:
        color = bg.get("color", "#1a1a2e")
        bg_style = f"background:{color};"

    # --- Build HTML ---
    # Tail circles CSS helper: 3 circles large→small, above the bubble, inward
    def _tail_css(color: str, is_left: bool, bubble_top: str) -> str:
        sizes = [22, 16, 10]
        circles = ""
        for i, sz in enumerate(sizes):
            # Start at center of bubble (~35% from edge), drift outward
            if is_left:
                h_pct = 35 - i * 3
                pos = f"left:{h_pct}%"
            else:
                h_pct = 35 - i * 3
                pos = f"right:{h_pct}%"
            opacity = round(0.85 - i * 0.15, 2)
            vert = f"top:calc({bubble_top} - {2.0 + i * 2.2}%)"
            circles += (
                f'<div style="position:absolute;{vert};{pos};'
                f'width:{sz}px;height:{sz}px;border-radius:50%;'
                f'background:{color};opacity:{opacity};"></div>\n'
            )
        return circles

    # Preview dimensions based on selected resolution
    res_w, res_h = vid.get("resolution_size", (1080, 1920))
    # Scale down so the longest side is ~768px
    max_side = 768
    ratio = min(max_side / res_w, max_side / res_h)
    pw, ph = int(res_w * ratio), int(res_h * ratio)
    res_label = f"{res_w}×{res_h}"

    if bubble_chat:
        tail_s1 = _tail_css(_PREVIEW_S1_COLOR, is_left=True, bubble_top=top)
        tail_s2 = _tail_css(_PREVIEW_S2_COLOR, is_left=False, bubble_top=f"calc({top} + 18%)")
        html = f"""
<div style="position:relative;width:{pw}px;height:{ph}px;{bg_style}
            border-radius:12px;overflow:hidden;border:1px solid #444;margin:0 auto;">
  <div style="position:absolute;top:{top};left:6%;max-width:70%;
              background:{_PREVIEW_S1_COLOR}dd;border-radius:16px;
              padding:10px 16px;">
    <span style="font-size:{preview_fs}px;color:{font_color};">
      Hello! How are you today?</span>
  </div>
  {tail_s1}
  <div style="position:absolute;top:calc({top} + 18%);right:6%;max-width:70%;
              background:{_PREVIEW_S2_COLOR}dd;border-radius:16px;
              padding:10px 16px;text-align:right;">
    <span style="font-size:{preview_fs}px;color:{font_color};">
      I'm fine, thanks! And you?</span>
  </div>
  {tail_s2}
</div>"""
    else:
        html = f"""
<div style="position:relative;width:{pw}px;height:{ph}px;{bg_style}
            border-radius:12px;overflow:hidden;border:1px solid #444;margin:0 auto;">
  <div style="position:absolute;top:0;left:0;width:100%;height:4px;
              background:{_PREVIEW_S1_COLOR};"></div>
  <div style="position:absolute;top:{top};left:6%;width:80%;">
    <span style="font-size:{preview_fs}px;color:{font_color};text-align:left;display:block;">
      Hello! How are you today?</span>
  </div>
  <div style="position:absolute;top:calc({top} + 18%);right:6%;width:80%;">
    <span style="font-size:{preview_fs}px;color:{font_color};text-align:right;display:block;">
      I'm fine, thanks! And you?</span>
  </div>
</div>"""

    st.markdown(f"#### 👁️ Preview ({res_label})")
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 3. Display settings (bubble, font size, font color)
# ---------------------------------------------------------------------------
def _render_display_settings() -> dict:
    st.markdown("#### 🎨 Cài đặt hiển thị")

    bubble_chat = st.toggle(
        "Hiển thị bubble chat",
        value=True,
        help="Bật để hiển thị lời thoại trong khung chat bubble. Tắt để hiển thị text thuần trên nền.",
        key="dlg_bubble",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        font_size_text = st.number_input(
            "Cỡ chữ nội dung:",
            min_value=20,
            max_value=96,
            value=55,
            step=2,
            key="dlg_fs_text",
        )
    with c2:
        font_color = st.color_picker(
            "Màu chữ nội dung:",
            value="#FFFFFF",
            key="dlg_font_color",
        )
    with c3:
        padding_top = st.slider(
            "Padding top (%):",
            min_value=0,
            max_value=80,
            value=50,
            step=1,
            help="Khoảng cách từ cạnh trên khung hình đến vị trí text/bubble (% chiều cao).",
            key="dlg_pad_top",
        )

    # Font selection
    font_names = list(FONTS.keys())
    selected_font = None
    if font_names:
        selected_font = st.selectbox(
            "Font chữ:",
            font_names,
            index=_default_font_index(font_names),
            key="dlg_font",
        )

    # --- Live preview ---
    # (rendered later in render() after background is selected)

    return {
        "bubble_chat": bubble_chat,
        "font_size_text": font_size_text,
        "font_color": font_color,
        "font_name": selected_font,
        "padding_top": padding_top / 100.0,
    }


# ---------------------------------------------------------------------------
# 4. Background
# ---------------------------------------------------------------------------
def _render_background() -> dict:
    st.markdown("#### 🖼️ Hình nền")

    mode = st.radio(
        "Chọn hình nền:",
        ["🎨 Màu nền đơn sắc", "🖼️ Upload hình ảnh", "📁 Chọn từ thư viện"],
        horizontal=True,
        key="dlg_bg_mode",
    )
    cfg: dict = {"mode": mode}

    if mode == "🎨 Màu nền đơn sắc":
        c1, c2 = st.columns(2)
        with c1:
            cfg["color"] = st.color_picker("Chọn màu nền:", "#008000", key="dlg_bg_color")
        with c2:
            st.markdown("")
            st.markdown("")
            st.markdown(
                f'<div style="width:100%;height:80px;background:{cfg["color"]};'
                f'border-radius:8px;border:1px solid #333;"></div>',
                unsafe_allow_html=True,
            )

    elif mode == "🖼️ Upload hình ảnh":
        imgs = st.file_uploader(
            "Upload hình ảnh nền",
            type=SUPPORTED_IMAGE_FILES,
            accept_multiple_files=True,
            help="Hỗ trợ: PNG, JPG, JPEG, WEBP",
            key="dlg_bg_upload",
        )
        if imgs:
            cfg["images"] = imgs

    elif mode == "📁 Chọn từ thư viện":
        if os.path.isdir(ASSETS_DIR):
            files = [
                fn
                for fn in os.listdir(ASSETS_DIR)
                if fn.rsplit(".", 1)[-1].lower() in SUPPORTED_IMAGE_FILES
            ]
            if files:
                sel = st.multiselect("Chọn hình ảnh:", files, key="dlg_bg_lib")
                if sel:
                    cfg["images_from_library"] = sel
            else:
                st.info("📂 Thư mục `assets/` chưa có hình ảnh.")
        else:
            st.info("📂 Thư mục `assets/` chưa tồn tại.")

    return cfg


# ---------------------------------------------------------------------------
# 5. Video settings
# ---------------------------------------------------------------------------
def _render_video_settings() -> dict:
    st.markdown("#### ⚙️ Cài đặt Video")
    c1, c2, c3 = st.columns(3)

    with c1:
        res = st.selectbox(
            "Độ phân giải:",
            list(VIDEO_RESOLUTIONS.keys()),
            index=list(VIDEO_RESOLUTIONS.keys()).index(DEFAULT_RESOLUTION),
            key="dlg_res",
        )
    with c2:
        fps = st.number_input(
            "FPS:", min_value=15, max_value=60, value=DEFAULT_FPS, step=5, key="dlg_fps",
        )
    with c3:
        fmt = st.selectbox("Định dạng:", ["MP4", "AVI", "MOV", "WEBM"], key="dlg_fmt")

    name = st.text_input(
        "Tên video:",
        value=f"dialogue_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Tên file output (không cần đuôi mở rộng)",
        key="dlg_name",
    )

    return {
        "resolution": res,
        "resolution_size": VIDEO_RESOLUTIONS[res],
        "fps": fps,
        "format": fmt.lower(),
        "name": name,
    }


# ---------------------------------------------------------------------------
# 6. Generate handler
# ---------------------------------------------------------------------------
def _handle_generate(
    df: pd.DataFrame,
    text: str,
    speaker_voices: dict,
    display: dict,
    bg: dict,
    vid: dict,
) -> None:
    """Run the dialogue video generator."""
    bg_color = bg.get("color", "#1a1a2e")

    # Resolve background images
    bg_image_paths: list[str] | None = None
    if bg.get("images"):
        tmp_img_dir = tempfile.mkdtemp(prefix="bg_imgs_")
        bg_image_paths = []
        for uploaded in bg["images"]:
            dst = os.path.join(tmp_img_dir, uploaded.name)
            with open(dst, "wb") as f:
                f.write(uploaded.getbuffer())
            bg_image_paths.append(dst)
    elif bg.get("images_from_library"):
        bg_image_paths = [
            os.path.join(ASSETS_DIR, fname)
            for fname in bg["images_from_library"]
        ]

    progress_bar = st.progress(0, text="⏳ Đang tạo video...")
    _start_time = time.monotonic()

    def _on_progress(current: int, total: int) -> None:
        pct = current / total
        elapsed = time.monotonic() - _start_time
        mins, secs = divmod(int(elapsed), 60)
        time_str = f"{mins}:{secs:02d}"
        progress_bar.progress(pct, text=f"⏳ Đang xử lý {current}/{total} scenes ({int(pct * 100)}%) — {time_str}")

    try:
        output_path = generate_video(
            "dialogue",
            df,
            name=vid["name"],
            lang="en",
            size=vid["resolution_size"],
            bg_color=bg_color,
            bg_images=bg_image_paths,
            fps=vid["fps"],
            fmt=vid["format"],
            progress_cb=_on_progress,
            bubble_chat=display["bubble_chat"],
            speaker_voices=speaker_voices,
            font_size_text=display["font_size_text"],
            font_color=display["font_color"],
            font_name=display.get("font_name"),
            padding_top=display.get("padding_top", 0.15),
        )

        elapsed = time.monotonic() - _start_time
        mins, secs = divmod(int(elapsed), 60)
        progress_bar.progress(1.0, text=f"✅ Hoàn thành! ({mins}:{secs:02d})")

        entry = build_video_entry(
            name=vid["name"],
            resolution=vid["resolution"],
            fps=vid["fps"],
            fmt=vid["format"],
            text_style="Dialogue",
            text_content=text,
            tts_lang="English",
            tts_speed="Bình thường",
            tts_engine=DEFAULT_TTS_ENGINE,
            bg_mode=bg["mode"],
            content_type="csv",
            csv_type="dialogue",
        )
        entry["output_path"] = output_path
        entry["status"] = "Hoàn thành"
        add_video(entry)

        st.success(f"✅ Đã tạo thành công video: `{os.path.basename(output_path)}`")
        st.balloons()

        with open(output_path, "rb") as vf:
            st.download_button(
                "⬇️ Tải video",
                data=vf,
                file_name=os.path.basename(output_path),
                mime=mime_for(vid["format"]),
            )

    except Exception as exc:
        progress_bar.empty()
        entry = build_video_entry(
            name=vid["name"],
            resolution=vid["resolution"],
            fps=vid["fps"],
            fmt=vid["format"],
            text_style="Dialogue",
            text_content=text,
            tts_lang="English",
            tts_speed="Bình thường",
            tts_engine=DEFAULT_TTS_ENGINE,
            bg_mode=bg["mode"],
            content_type="csv",
            csv_type="dialogue",
        )
        entry["status"] = "Lỗi"
        add_video(entry)
        st.error(f"❌ Lỗi khi tạo video: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header(
        "💬",
        "Video Hội Thoại",
        "Tạo video hội thoại 2 người từ file CSV",
    )

    # CSV upload & validation
    text, df = _render_csv_upload()
    st.markdown("---")

    # Speaker voices
    speaker_voices = _render_speaker_voices()
    st.markdown("---")

    # Video settings
    vid = _render_video_settings()
    st.markdown("---")

    # Background
    bg = _render_background()
    st.markdown("---")

    # Display settings (bubble, font size, font color)
    display = _render_display_settings()
    st.markdown("---")

    # Live preview (uses display + bg + vid settings)
    _render_preview(display, bg, vid)
    st.markdown("---")

    # Generate
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        clicked = st.button(
            "🚀 Tạo Video Hội Thoại",
            use_container_width=True,
            type="primary",
            disabled=(not text or df is None),
        )

    if clicked and text and df is not None:
        _handle_generate(df, text, speaker_voices, display, bg, vid)
    elif clicked:
        st.error("⚠️ Vui lòng upload file CSV hội thoại trước khi tạo video.")
