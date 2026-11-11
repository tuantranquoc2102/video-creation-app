"""Vocabulary video page – dedicated page for generating vocabulary flashcard videos."""

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
    DEFAULT_TTS_ENGINE,
    DEFAULT_FONT_NAME,
    FONTS,
    SPEAKER_VOICES,
    SPEAKER_VOICES_VI,
    SUPPORTED_IMAGE_FILES,
    VIDEO_RESOLUTIONS,
)
from core.state import add_video
from core.video_service import build_video_entry, csv_to_text, parse_csv
from core.generators import generate_video
from core.utils import mime_for
from ui.components.csv_preview import render_csv_preview, render_sample_format
from ui.components.page_header import render_page_header

_VOCAB_SPEC = CSV_VIDEO_TYPES["vocabulary"]


def _default_font_index(font_names: list[str]) -> int:
    """Default to the font that covers Vietnamese + IPA glyphs."""
    return font_names.index(DEFAULT_FONT_NAME) if DEFAULT_FONT_NAME in font_names else 0


# ---------------------------------------------------------------------------
# 1. CSV Upload & Validation
# ---------------------------------------------------------------------------
def _render_csv_upload() -> tuple[str, pd.DataFrame | None]:
    """Upload, validate, and preview the vocabulary CSV.

    Returns (text_for_preview, dataframe_or_None).
    """
    st.markdown("#### 📂 Upload file CSV từ vựng")

    render_sample_format("vocabulary")
    st.markdown("")

    f = st.file_uploader(
        "Chọn file CSV",
        type=["csv"],
        help=(
            f"Separator: `;` — Cần có cột: "
            f"{', '.join(f'`{c}`' for c in _VOCAB_SPEC['required_cols'])}"
            f" — Cột tùy chọn: `image`"
        ),
        key="vocab_csv_uploader",
    )

    if not f:
        return "", None

    raw = f.read()
    sep = _VOCAB_SPEC["separator"]
    try:
        df = parse_csv(raw, separator=sep)
    except Exception as exc:
        st.error(f"❌ Không thể đọc file CSV: {exc}")
        return "", None

    # Validate required columns
    required = {c.lower() for c in _VOCAB_SPEC["required_cols"]}
    actual = {c.strip().lower() for c in df.columns}
    missing = required - actual
    if missing:
        st.error(
            f"⚠️ Thiếu cột bắt buộc: **{', '.join(missing)}**. "
            f"File cần có: {', '.join(f'`{c}`' for c in _VOCAB_SPEC['required_cols'])}"
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        return "", None

    # Rich preview
    render_csv_preview(df, "vocabulary")
    text = csv_to_text(df, "vocabulary")

    with st.expander("📄 Văn bản TTS sẽ được tạo", expanded=False):
        st.text(text)

    return text, df


# ---------------------------------------------------------------------------
# 2. Image folder upload
# ---------------------------------------------------------------------------
_IMG_CACHE_KEY = "_vocab_img_cache"


def _render_image_upload(df: pd.DataFrame | None) -> str | None:
    """Upload a folder of images referenced in the CSV `image` column.

    Returns a temp directory path containing the uploaded images, or None.
    Images are cached in session state so the temp dir survives Streamlit
    reruns (e.g. when the Generate button triggers a rerun).
    """
    has_image_col = (
        df is not None and "image" in [c.strip().lower() for c in df.columns]
    )

    if not has_image_col:
        return None

    st.markdown("#### 🖼️ Upload hình minh họa từ vựng")
    st.caption(
        "Upload các file hình ảnh tương ứng với cột `image` trong CSV. "
        "Tên file phải khớp chính xác."
    )

    imgs = st.file_uploader(
        "Chọn hình ảnh minh họa",
        type=SUPPORTED_IMAGE_FILES,
        accept_multiple_files=True,
        help="Hỗ trợ: PNG, JPG, JPEG, WEBP",
        key="vocab_img_upload",
    )

    if not imgs:
        # Clear cache if user removed all images
        st.session_state.pop(_IMG_CACHE_KEY, None)
        return None

    # ── Check if we already cached these exact files ──────────────────
    current_names = sorted(f.name for f in imgs)
    cached = st.session_state.get(_IMG_CACHE_KEY)
    if cached and cached["names"] == current_names and os.path.isdir(cached["dir"]):
        # Verify files still exist on disk
        all_ok = all(
            os.path.isfile(os.path.join(cached["dir"], n)) for n in current_names
        )
        if all_ok:
            tmp_dir = cached["dir"]
        else:
            tmp_dir = _save_images_to_temp(imgs)
            st.session_state[_IMG_CACHE_KEY] = {"names": current_names, "dir": tmp_dir}
    else:
        tmp_dir = _save_images_to_temp(imgs)
        st.session_state[_IMG_CACHE_KEY] = {"names": current_names, "dir": tmp_dir}

    # ── Show match status ─────────────────────────────────────────────
    uploaded_names = [f.name for f in imgs]
    referenced = set()
    for _, row in df.iterrows():
        img_name = str(row.get("image", "")).strip()
        if img_name and img_name.lower() != "nan":
            referenced.add(img_name)

    matched = referenced & set(uploaded_names)
    missing = referenced - set(uploaded_names)

    if matched:
        st.success(f"✅ Đã khớp {len(matched)}/{len(referenced)} hình ảnh")
    if missing:
        st.warning(f"⚠️ Thiếu hình ảnh: {', '.join(sorted(missing))}")

    # Show what's actually on disk for debugging
    files_on_disk = os.listdir(tmp_dir) if os.path.isdir(tmp_dir) else []
    st.caption(f"📁 Thư mục ảnh: {len(files_on_disk)} file(s) — `{tmp_dir}`")

    return tmp_dir


def _save_images_to_temp(imgs) -> str:
    """Write uploaded Streamlit files to a temp directory."""
    tmp_dir = tempfile.mkdtemp(prefix="vocab_imgs_")
    for uploaded in imgs:
        dst = os.path.join(tmp_dir, uploaded.name)
        data = uploaded.getbuffer()
        with open(dst, "wb") as fh:
            fh.write(data)
    return tmp_dir


# ---------------------------------------------------------------------------
# 3. Voice selection
# ---------------------------------------------------------------------------
def _render_voice_settings() -> dict:
    """Let user pick voices, repeat count, and Vietnamese TTS toggle."""
    st.markdown("#### 🎙️ Giọng đọc")

    # --- English voice ---
    voice_labels = list(SPEAKER_VOICES.keys())
    selected = st.selectbox(
        "Giọng đọc tiếng Anh:",
        voice_labels,
        index=0,
        key="vocab_voice",
    )
    voice_en = SPEAKER_VOICES[selected]

    # --- Repeat English word ---
    repeat_en = st.slider(
        "Lặp lại phát âm tiếng Anh (từ vựng):",
        min_value=1,
        max_value=5,
        value=1,
        step=1,
        help="Số lần đọc lại từ tiếng Anh để người học nghe rõ hơn",
        key="vocab_repeat_en",
    )

    st.markdown("---")

    # --- Vietnamese TTS toggle ---
    enable_vn_tts = st.checkbox(
        "🇻🇳 Bật TTS tiếng Việt (đọc nghĩa & bản dịch)",
        value=False,
        help="Nếu bật, video sẽ thêm giọng đọc tiếng Việt cho phần dịch nghĩa và bản dịch câu ví dụ",
        key="vocab_vn_tts",
    )

    voice_vn = None
    if enable_vn_tts:
        vn_labels = list(SPEAKER_VOICES_VI.keys())
        selected_vn = st.selectbox(
            "Giọng đọc tiếng Việt:",
            vn_labels,
            index=0,
            key="vocab_voice_vn",
        )
        voice_vn = SPEAKER_VOICES_VI[selected_vn]

    return {
        "voice_en": voice_en,
        "repeat_en": repeat_en,
        "enable_vn_tts": enable_vn_tts,
        "voice_vn": voice_vn,
    }


# ---------------------------------------------------------------------------
# 4. Display settings
# ---------------------------------------------------------------------------
def _render_display_settings() -> dict:
    st.markdown("#### 🎨 Cài đặt hiển thị")

    c1, c2, c3 = st.columns(3)
    with c1:
        font_size_word = st.number_input(
            "Cỡ chữ từ vựng:",
            min_value=20,
            max_value=120,
            value=64,
            step=2,
            key="vocab_fs_word",
        )
    with c2:
        font_size_example = st.number_input(
            "Cỡ chữ ví dụ:",
            min_value=16,
            max_value=80,
            value=30,
            step=2,
            key="vocab_fs_example",
        )
    with c3:
        top_padding = st.number_input(
            "Top padding (%):",
            min_value=0,
            max_value=50,
            value=18,
            step=1,
            help="Khoảng cách từ đỉnh video đến dòng chữ đầu tiên (% chiều cao)",
            key="vocab_top_padding",
        )

    # Font selection
    font_names = list(FONTS.keys())
    selected_font = None
    selected_font_vn = None
    if font_names:
        c3, c4 = st.columns(2)
        with c3:
            selected_font = st.selectbox(
                "Font chữ (tiếng Anh):",
                font_names,
                index=_default_font_index(font_names),
                key="vocab_font",
            )
        with c4:
            selected_font_vn = st.selectbox(
                "Font chữ (tiếng Việt):",
                font_names,
                index=_default_font_index(font_names),
                help="Chọn font hỗ trợ tiếng Việt để tránh bể chữ",
                key="vocab_font_vn",
            )

    return {
        "font_size_word": font_size_word,
        "font_size_example": font_size_example,
        "font_name": selected_font,
        "font_name_vn": selected_font_vn,
        "top_padding": top_padding,
    }


# ---------------------------------------------------------------------------
# 5. Background
# ---------------------------------------------------------------------------
def _render_background() -> dict:
    st.markdown("#### 🖼️ Hình nền")

    mode = st.radio(
        "Chọn hình nền:",
        ["🎨 Màu nền đơn sắc", "🖼️ Upload hình ảnh", "📁 Chọn từ thư viện"],
        horizontal=True,
        key="vocab_bg_mode",
    )
    cfg: dict = {"mode": mode}

    if mode == "🎨 Màu nền đơn sắc":
        c1, c2 = st.columns(2)
        with c1:
            cfg["color"] = st.color_picker(
                "Chọn màu nền:", "#1a1a2e", key="vocab_bg_color",
            )
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
            key="vocab_bg_upload",
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
                sel = st.multiselect("Chọn hình ảnh:", files, key="vocab_bg_lib")
                if sel:
                    cfg["images_from_library"] = sel
            else:
                st.info("📂 Thư mục `assets/` chưa có hình ảnh.")
        else:
            st.info("📂 Thư mục `assets/` chưa tồn tại.")

    return cfg


# ---------------------------------------------------------------------------
# 6. Video settings
# ---------------------------------------------------------------------------
def _render_video_settings() -> dict:
    st.markdown("#### ⚙️ Cài đặt Video")
    c1, c2, c3 = st.columns(3)

    with c1:
        res = st.selectbox(
            "Độ phân giải:",
            list(VIDEO_RESOLUTIONS.keys()),
            index=list(VIDEO_RESOLUTIONS.keys()).index(DEFAULT_RESOLUTION),
            key="vocab_res",
        )
    with c2:
        fps = st.number_input(
            "FPS:", min_value=15, max_value=60, value=DEFAULT_FPS, step=5,
            key="vocab_fps",
        )
    with c3:
        fmt = st.selectbox(
            "Định dạng:", ["MP4", "AVI", "MOV", "WEBM"], key="vocab_fmt",
        )

    name = st.text_input(
        "Tên video:",
        value=f"vocabulary_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Tên file output (không cần đuôi mở rộng)",
        key="vocab_name",
    )

    return {
        "resolution": res,
        "resolution_size": VIDEO_RESOLUTIONS[res],
        "fps": fps,
        "format": fmt.lower(),
        "name": name,
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
_PREVIEW_WORD_COLOR = "#667eea"


def _render_preview(display: dict, bg: dict, vid: dict) -> None:
    """Render an HTML/CSS mockup of a vocabulary flashcard."""
    fs_word = display["font_size_word"]
    fs_ex = display["font_size_example"]

    preview_fs_word = max(14, int(fs_word * 0.45))
    preview_fs_ex = max(10, int(fs_ex * 0.45))

    # Background style
    bg_style = ""
    if bg.get("images"):
        img_file = bg["images"][0]
        img_file.seek(0)
        b64 = base64.b64encode(img_file.read()).decode()
        img_file.seek(0)
        bg_style = (
            f"background:url(data:image/{img_file.name.rsplit('.', 1)[-1].lower()}"
            f";base64,{b64}) center/cover no-repeat;"
        )
    elif bg.get("images_from_library"):
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

    # Resolution preview
    res_w, res_h = vid.get("resolution_size", (1080, 1920))
    max_side = 768
    ratio = min(max_side / res_w, max_side / res_h)
    pw, ph = int(res_w * ratio), int(res_h * ratio)
    res_label = f"{res_w}×{res_h}"

    top_pad = display.get("top_padding", 18)

    html = f"""
<div style="position:relative;width:{pw}px;height:{ph}px;{bg_style}
            border-radius:12px;overflow:hidden;border:1px solid #444;margin:0 auto;
            display:flex;flex-direction:column;align-items:center;padding-top:{top_pad}%;">
  <div style="font-size:{preview_fs_word}px;font-weight:700;color:{_PREVIEW_WORD_COLOR};">
    abandon</div>
  <div style="font-size:{max(10, preview_fs_word - 6)}px;color:#aaa;margin-top:4px;">
    /əˈbændən/</div>
  <div style="font-size:{max(10, preview_fs_word - 4)}px;color:#e0e0e0;margin-top:8px;">
    bỏ rơi, từ bỏ</div>
  <div style="width:40%;height:2px;background:{_PREVIEW_WORD_COLOR};margin:12px 0;"></div>
  <div style="font-size:{preview_fs_ex}px;color:#ccc;text-align:center;padding:0 10%;">
    📝 She had to abandon her car.</div>
  <div style="font-size:{max(9, preview_fs_ex - 2)}px;color:#aaa;margin-top:6px;text-align:center;padding:0 10%;">
    🔄 Cô ấy phải bỏ lại xe.</div>
</div>"""

    st.markdown(f"#### 👁️ Preview ({res_label})")
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 7. Generate handler
# ---------------------------------------------------------------------------
def _handle_generate(
    df: pd.DataFrame,
    text: str,
    voice_cfg: dict,
    display: dict,
    bg: dict,
    vid: dict,
    image_dir: str | None,
) -> None:
    """Run the vocabulary video generator."""
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
        progress_bar.progress(
            pct,
            text=f"⏳ Đang xử lý {current}/{total} từ vựng ({int(pct * 100)}%) — {time_str}",
        )

    try:
        output_path = generate_video(
            "vocabulary",
            df,
            name=vid["name"],
            lang="en",
            size=vid["resolution_size"],
            bg_color=bg_color,
            bg_images=bg_image_paths,
            fps=vid["fps"],
            fmt=vid["format"],
            progress_cb=_on_progress,
            voice=voice_cfg["voice_en"],
            repeat_en=voice_cfg["repeat_en"],
            enable_vn_tts=voice_cfg["enable_vn_tts"],
            voice_vn=voice_cfg["voice_vn"],
            font_size_word=display["font_size_word"],
            font_size_example=display["font_size_example"],
            font_name=display.get("font_name"),
            font_name_vn=display.get("font_name_vn"),
            top_padding_pct=display.get("top_padding", 18),
            image_dir=image_dir,
        )

        elapsed = time.monotonic() - _start_time
        mins, secs = divmod(int(elapsed), 60)
        progress_bar.progress(1.0, text=f"✅ Hoàn thành! ({mins}:{secs:02d})")

        entry = build_video_entry(
            name=vid["name"],
            resolution=vid["resolution"],
            fps=vid["fps"],
            fmt=vid["format"],
            text_style="Vocabulary",
            text_content=text,
            tts_lang="English",
            tts_speed="Bình thường",
            tts_engine=DEFAULT_TTS_ENGINE,
            bg_mode=bg["mode"],
            content_type="csv",
            csv_type="vocabulary",
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
            text_style="Vocabulary",
            text_content=text,
            tts_lang="English",
            tts_speed="Bình thường",
            tts_engine=DEFAULT_TTS_ENGINE,
            bg_mode=bg["mode"],
            content_type="csv",
            csv_type="vocabulary",
        )
        entry["status"] = "Lỗi"
        add_video(entry)
        st.error(f"❌ Lỗi khi tạo video: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header(
        "📖",
        "Video Từ Vựng",
        "Tạo video học từ vựng từ file CSV với phiên âm IPA, nghĩa, ví dụ và hình minh họa",
    )

    # CSV upload & validation
    text, df = _render_csv_upload()
    st.markdown("---")

    # Image uploads (only shown if CSV has `image` column)
    image_dir = _render_image_upload(df)
    if image_dir:
        st.markdown("---")

    # Voice
    voice_cfg = _render_voice_settings()
    st.markdown("---")

    # Video settings
    vid = _render_video_settings()
    st.markdown("---")

    # Background
    bg = _render_background()
    st.markdown("---")

    # Display settings
    display = _render_display_settings()
    st.markdown("---")

    # Preview
    _render_preview(display, bg, vid)
    st.markdown("---")

    # Generate button
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        clicked = st.button(
            "🚀 Tạo Video Từ Vựng",
            use_container_width=True,
            type="primary",
            disabled=(not text or df is None),
        )

    if clicked and text and df is not None:
        _handle_generate(df, text, voice_cfg, display, bg, vid, image_dir)
    elif clicked:
        st.error("⚠️ Vui lòng upload file CSV từ vựng trước khi tạo video.")
