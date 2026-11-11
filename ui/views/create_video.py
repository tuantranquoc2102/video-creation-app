"""Create-video view – text input, background, TTS & video settings."""

import os
import tempfile
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
    DEFAULT_VOICE_EN_FEMALE,
    SUPPORTED_IMAGE_FILES,
    TTS_LANGUAGES,
    TTS_SPEEDS,
    VIDEO_RESOLUTIONS,
)
from core.state import add_video
from core.video_service import (
    build_video_entry,
    csv_to_text,
    detect_csv_type,
    parse_csv,
)
from core.generators import generate_video
from core.utils import mime_for
from ui.components.csv_preview import (
    render_auto_detect_result,
    render_csv_preview,
    render_csv_type_selector,
    render_sample_format,
)
from ui.components.page_header import render_page_header


# ---------------------------------------------------------------------------
# Section renderers – each returns the collected user input.
# ---------------------------------------------------------------------------
def _render_text_input() -> tuple[str, pd.DataFrame | None, str, str | None]:
    """Render the content-input section.

    Returns
    -------
    text : str
        Flat text content (for TTS / preview).
    csv_data : DataFrame | None
        Raw CSV data if the user uploaded a CSV.
    content_type : str
        "text" | "txt_file" | "csv"
    csv_type : str | None
        CSV_VIDEO_TYPES key when content_type == "csv".
    """
    st.markdown("#### 📄 Nhập nội dung")

    method = st.radio(
        "Chọn cách nhập nội dung:",
        ["✍️ Nhập trực tiếp", "📁 Upload file (.txt)", "📊 Upload file (.csv)"],
        horizontal=True,
    )

    text = ""
    csv_data: pd.DataFrame | None = None
    content_type = "text"
    csv_type: str | None = None

    # ── Direct text input ─────────────────────────────────────────────
    if method == "✍️ Nhập trực tiếp":
        text = st.text_area(
            "Nhập nội dung cho video:",
            height=200,
            placeholder=(
                "Nhập nội dung script cho video tại đây...\n\n"
                "Mỗi đoạn văn sẽ tương ứng với một scene trong video."
            ),
        )

    # ── TXT file ──────────────────────────────────────────────────────
    elif method == "📁 Upload file (.txt)":
        content_type = "txt_file"
        f = st.file_uploader(
            "Chọn file văn bản",
            type=["txt"],
            help="Upload file .txt chứa nội dung script",
        )
        if f:
            text = f.read().decode("utf-8")
            with st.expander("👁️ Xem trước nội dung", expanded=True):
                st.text(text)

    # ── CSV file (dialogue / vocabulary / …) ──────────────────────────
    elif method == "📊 Upload file (.csv)":
        content_type = "csv"
        text, csv_data, csv_type = _render_csv_workflow()

    return text, csv_data, content_type, csv_type


def _render_csv_workflow() -> tuple[str, pd.DataFrame | None, str | None]:
    """Handle the full CSV flow: type select → upload → detect → preview.

    Returns (text, csv_data, csv_type).
    """
    # Step 1 – let user pick CSV type
    csv_type = render_csv_type_selector()

    if csv_type:
        render_sample_format(csv_type)

    st.markdown("---")

    # Step 2 – upload
    spec = CSV_VIDEO_TYPES.get(csv_type, {}) if csv_type else {}
    sep = spec.get("separator", ";")

    f = st.file_uploader(
        "📂 Upload file CSV",
        type=["csv"],
        help=f"Separator: `{sep}`" if csv_type else "Upload file CSV",
    )

    if not f:
        return "", None, csv_type

    raw = f.read()
    try:
        df = parse_csv(raw, separator=sep)
    except Exception as exc:
        st.error(f"❌ Không thể đọc file CSV: {exc}")
        return "", None, csv_type

    # Step 3 – auto-detect if user hasn't selected
    detected = detect_csv_type(df)
    if not csv_type and detected:
        csv_type = detected
        st.session_state["_csv_type_selected"] = detected

    render_auto_detect_result(detected)

    # If still unknown after detection, let user re-pick or show raw table
    if not csv_type:
        st.markdown("**Dữ liệu CSV (raw):**")
        st.dataframe(df, use_container_width=True, hide_index=True)
        return "", df, None

    # Step 4 – validate required columns
    required = {c.lower() for c in CSV_VIDEO_TYPES[csv_type]["required_cols"]}
    actual = {c.strip().lower() for c in df.columns}
    missing = required - actual
    if missing:
        st.error(
            f"⚠️ Thiếu cột bắt buộc: **{', '.join(missing)}**. "
            f"File cần có: {', '.join(f'`{c}`' for c in CSV_VIDEO_TYPES[csv_type]['required_cols'])}"
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        return "", df, csv_type

    # Step 5 – rich preview + convert to text
    render_csv_preview(df, csv_type)
    text = csv_to_text(df, csv_type)

    with st.expander("📄 Văn bản TTS sẽ được tạo", expanded=False):
        st.text(text)

    return text, df, csv_type


# ---------------------------------------------------------------------------
# Background, TTS, Video settings
# ---------------------------------------------------------------------------
def _render_background() -> dict:
    st.markdown("#### 🖼️ Hình nền (Background)")

    mode = st.radio(
        "Chọn hình nền:",
        ["🎨 Màu nền đơn sắc", "🖼️ Upload hình ảnh", "📁 Chọn từ thư viện"],
        horizontal=True,
    )
    cfg: dict = {"mode": mode}

    if mode == "🎨 Màu nền đơn sắc":
        c1, c2 = st.columns(2)
        with c1:
            cfg["color"] = st.color_picker("Chọn màu nền:", "#1a1a2e")
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
        )
        if imgs:
            cols = st.columns(min(len(imgs), 4))
            for i, img in enumerate(imgs):
                with cols[i % 4]:
                    st.image(img, caption=img.name, use_container_width=True)
            cfg["images"] = imgs

    elif mode == "📁 Chọn từ thư viện":
        if os.path.isdir(ASSETS_DIR):
            files = [
                f
                for f in os.listdir(ASSETS_DIR)
                if f.rsplit(".", 1)[-1].lower() in SUPPORTED_IMAGE_FILES
            ]
            if files:
                sel = st.multiselect("Chọn hình ảnh:", files)
                if sel:
                    cols = st.columns(min(len(sel), 4))
                    for i, name in enumerate(sel):
                        with cols[i % 4]:
                            st.image(
                                os.path.join(ASSETS_DIR, name),
                                caption=name,
                                use_container_width=True,
                            )
                    cfg["images_from_library"] = sel
            else:
                st.info("📂 Thư mục `assets/` chưa có hình ảnh. Hãy thêm ảnh vào thư mục này.")
        else:
            st.info("📂 Thư mục `assets/` chưa tồn tại.")

    return cfg


def _render_tts() -> dict:
    st.markdown("#### 🔊 Cài đặt Text-to-Speech (TTS)")
    c1, c2, c3 = st.columns(3)

    with c1:
        lang_labels = list(TTS_LANGUAGES.keys())
        lang = st.selectbox(
            "Ngôn ngữ:",
            lang_labels,
            index=lang_labels.index("English"),
            help="Chỉ áp dụng cho gTTS. Edge TTS dùng giọng en-US mặc định.",
        )
    with c2:
        speed_label = st.selectbox("Tốc độ đọc:", list(TTS_SPEEDS.keys()), index=1)
    with c3:
        engines = ["Edge TTS", "gTTS (Google)"]
        default_idx = engines.index(DEFAULT_TTS_ENGINE) if DEFAULT_TTS_ENGINE in engines else 0
        engine = st.selectbox(
            "Engine TTS:",
            engines,
            index=default_idx,
        )

    return {
        "language": lang,
        "language_code": TTS_LANGUAGES[lang],
        "speed": TTS_SPEEDS[speed_label],
        "speed_label": speed_label,
        "engine": engine,
    }


def _render_video_settings() -> dict:
    st.markdown("#### ⚙️ Cài đặt Video")
    c1, c2, c3 = st.columns(3)

    with c1:
        res = st.selectbox(
            "Độ phân giải:",
            list(VIDEO_RESOLUTIONS.keys()),
            index=list(VIDEO_RESOLUTIONS.keys()).index(DEFAULT_RESOLUTION),
        )
    with c2:
        fps = st.number_input("FPS:", min_value=15, max_value=60, value=DEFAULT_FPS, step=5)
    with c3:
        fmt = st.selectbox("Định dạng:", ["MP4", "AVI", "MOV", "WEBM"])

    c4, c5 = st.columns(2)
    with c4:
        name = st.text_input(
            "Tên video:",
            value=f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            help="Tên file output (không cần đuôi mở rộng)",
        )
    with c5:
        style = st.selectbox(
            "Kiểu chữ trên video:",
            ["Không hiển thị chữ", "Subtitle phía dưới", "Chữ giữa màn hình", "Karaoke style"],
        )

    return {
        "resolution": res,
        "resolution_size": VIDEO_RESOLUTIONS[res],
        "fps": fps,
        "format": fmt.lower(),
        "name": name,
        "text_style": style,
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
def _render_preview(
    text: str,
    bg: dict,
    tts: dict,
    vid: dict,
    content_type: str,
    csv_type: str | None,
) -> None:
    st.markdown("---")
    st.markdown("### 👀 Xem trước cấu hình")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**📝 Nội dung:**")
        if content_type == "csv" and csv_type:
            spec = CSV_VIDEO_TYPES[csv_type]
            st.markdown(f"Loại: **{spec['icon']} {spec['label']}**")
        if text:
            st.text(text[:300] + ("..." if len(text) > 300 else ""))
        else:
            st.warning("Chưa có nội dung")

        st.markdown(
            f"**🔊 TTS:**\n"
            f"- Ngôn ngữ: `{tts['language']}`\n"
            f"- Tốc độ: `{tts['speed_label']}`\n"
            f"- Engine: `{tts['engine']}`"
        )

    with c2:
        st.markdown(
            f"**🎬 Video:**\n"
            f"- Tên: `{vid['name']}`\n"
            f"- Độ phân giải: `{vid['resolution']}`\n"
            f"- FPS: `{vid['fps']}`\n"
            f"- Định dạng: `{vid['format'].upper()}`\n"
            f"- Kiểu chữ: `{vid['text_style']}`"
        )
        st.markdown(f"**🖼️ Hình nền:**\n- Chế độ: {bg['mode']}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header(
        "🎥",
        "Tạo Video Mới",
        "Tạo video từ nội dung text với hình nền và giọng đọc TTS",
    )

    text, _csv, content_type, csv_type = _render_text_input()
    st.markdown("---")
    bg = _render_background()
    st.markdown("---")
    tts = _render_tts()
    st.markdown("---")
    vid = _render_video_settings()

    _render_preview(text, bg, tts, vid, content_type, csv_type)
    st.markdown("---")

    can_generate = content_type == "csv" and csv_type is not None and _csv is not None and bool(text)
    if content_type != "csv":
        st.info(
            "💡 Chế độ nhập text / .txt chưa hỗ trợ tạo video thật. "
            "Hãy dùng CSV (hội thoại / từ vựng) hoặc trang **🎓 Video Bài Học**."
        )

    # Generate button
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        clicked = st.button(
            "🚀 Tạo Video",
            use_container_width=True,
            type="primary",
            disabled=not can_generate,
        )

    if clicked and can_generate:
        # Determine background colour for the generator
        bg_color = bg.get("color", "#1a1a2e")

        # Resolve background images to file paths
        bg_image_paths: list[str] | None = None
        if bg.get("images"):
            # Uploaded files → save to temp dir
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

        # ------------------------------------------------------------------
        # CSV-based generation (dialogue / vocabulary)
        # ------------------------------------------------------------------
        if content_type == "csv" and csv_type and _csv is not None:
            progress_bar = st.progress(0, text="⏳ Đang tạo video...")
            status_text = st.empty()

            def _on_progress(current: int, total: int) -> None:
                pct = current / total
                progress_bar.progress(pct, text=f"⏳ Đang xử lý {current}/{total} scenes...")

            try:
                # Resolve TTS language for generator
                gen_lang = tts["language_code"]
                # For vocabulary, words & examples are always English
                if csv_type == "vocabulary":
                    gen_lang = "en"

                # Pass explicit voices so English text is never read by a
                # Vietnamese voice (previous default behaviour).
                extra_opts: dict = {}
                if tts["engine"] == "Edge TTS":
                    if csv_type == "dialogue":
                        extra_opts["speaker_voices"] = DEFAULT_SPEAKER_VOICES
                    elif csv_type == "vocabulary":
                        extra_opts["voice"] = {
                            "voice_id": DEFAULT_VOICE_EN_FEMALE, "engine": "edge",
                        }

                output_path = generate_video(
                    csv_type,
                    _csv,
                    name=vid["name"],
                    lang=gen_lang,
                    size=vid["resolution_size"],
                    bg_color=bg_color,
                    bg_images=bg_image_paths,
                    fps=vid["fps"],
                    fmt=vid["format"],
                    progress_cb=_on_progress,
                    **extra_opts,
                )

                progress_bar.progress(1.0, text="✅ Hoàn thành!")

                entry = build_video_entry(
                    name=vid["name"],
                    resolution=vid["resolution"],
                    fps=vid["fps"],
                    fmt=vid["format"],
                    text_style=vid["text_style"],
                    text_content=text,
                    tts_lang=tts["language"],
                    tts_speed=tts["speed_label"],
                    tts_engine=tts["engine"],
                    bg_mode=bg["mode"],
                    content_type=content_type,
                    csv_type=csv_type,
                )
                entry["output_path"] = output_path
                entry["status"] = "Hoàn thành"
                add_video(entry)

                st.success(f"✅ Đã tạo thành công video: **{vid['name']}**")
                st.balloons()

                # Offer download
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
                    text_style=vid["text_style"],
                    text_content=text,
                    tts_lang=tts["language"],
                    tts_speed=tts["speed_label"],
                    tts_engine=tts["engine"],
                    bg_mode=bg["mode"],
                    content_type=content_type,
                    csv_type=csv_type,
                )
                entry["status"] = "Lỗi"
                add_video(entry)
                st.error(f"❌ Lỗi khi tạo video: {exc}")

    elif clicked:
        st.error("⚠️ Vui lòng upload CSV hợp lệ trước khi tạo video.")
