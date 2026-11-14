"""Join-video page – concatenate uploaded clips into one video, optional logo watermark."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from config import DEFAULT_FPS, DEFAULT_LOGO, OUTPUT_DIR, SUPPORTED_IMAGE_FILES, VIDEO_RESOLUTIONS
from core.state import STATUS_DONE, STATUS_ERROR, add_video
from core.utils import mime_for, resolve_output_path
from core.video_join import (
    SUPPORTED_VIDEO_FILES,
    LogoOptions,
    VideoInfo,
    extract_frame,
    join_videos,
    preview_with_logo,
    probe,
)
from core.video_service import build_video_entry
from ui.components.page_header import render_page_header

_CACHE_KEY = "_join_upload_cache"
_KEEP_FIRST = "Giữ theo video đầu tiên"
_LOGO_DEFAULT = "🏷️ Logo mặc định của kênh"
_LOGO_UPLOAD = "📤 Upload logo"


# ---------------------------------------------------------------------------
# Upload → temp files (cached across reruns)
# ---------------------------------------------------------------------------
def _fingerprint(files) -> str:
    h = hashlib.sha1()
    for f in files:
        h.update(f"{f.name}|{f.size}|{getattr(f, 'file_id', '')}".encode())
    return h.hexdigest()


def _save_uploads(files) -> list[dict]:
    """Write uploads to a temp dir once; return ``[{name, path, info|error}]``."""
    key = _fingerprint(files)
    cached = st.session_state.get(_CACHE_KEY)
    if cached and cached["key"] == key and all(os.path.isfile(i["path"]) for i in cached["items"]):
        return cached["items"]
    if cached:
        shutil.rmtree(cached["dir"], ignore_errors=True)

    tmp_dir = tempfile.mkdtemp(prefix="join_src_")
    items = []
    for idx, f in enumerate(files):
        # Prefix with index: two uploads may share a name.
        path = os.path.join(tmp_dir, f"{idx:03d}_{os.path.basename(f.name)}")
        with open(path, "wb") as fh:
            fh.write(f.getbuffer())
        item: dict = {"name": f.name, "path": path, "info": None, "error": None}
        try:
            item["info"] = probe(path)
        except Exception as exc:  # unreadable / not a video
            item["error"] = str(exc)
        items.append(item)
    st.session_state[_CACHE_KEY] = {"key": key, "dir": tmp_dir, "items": items}
    return items


# ---------------------------------------------------------------------------
# 1. Clips & order
# ---------------------------------------------------------------------------
def _fmt_duration(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m}:{s:02d}"


def _render_clips() -> list[dict]:
    st.markdown("#### 📂 Chọn các video cần ghép")
    files = st.file_uploader(
        "Upload video",
        type=SUPPORTED_VIDEO_FILES,
        accept_multiple_files=True,
        help=f"Hỗ trợ: {', '.join(e.upper() for e in SUPPORTED_VIDEO_FILES)}",
        key="join_upload",
    )
    if not files:
        st.session_state.pop(_CACHE_KEY, None)
        st.info("ℹ️ Upload ít nhất 2 video. Có thể sắp xếp lại thứ tự sau khi upload.")
        return []

    with st.spinner("Đang đọc thông tin video..."):
        items = _save_uploads(files)

    bad = [i for i in items if i["error"]]
    for i in bad:
        st.error(f"❌ {i['name']}: {i['error']}")
    good = [i for i in items if not i["error"]]
    if not good:
        return []

    st.markdown("**Thứ tự ghép** — sửa cột *Thứ tự* để sắp xếp lại, bỏ chọn *Dùng* để loại clip.")
    table = pd.DataFrame(
        {
            "Thứ tự": list(range(1, len(good) + 1)),
            "Dùng": [True] * len(good),
            "File": [i["name"] for i in good],
            "Kích thước": [f"{i['info'].width}×{i['info'].height}" for i in good],
            "FPS": [round(i["info"].fps, 2) for i in good],
            "Thời lượng": [_fmt_duration(i["info"].duration) for i in good],
            "Âm thanh": ["✅" if i["info"].has_audio else "🔇" for i in good],
        }
    )
    edited = st.data_editor(
        table,
        hide_index=True,
        use_container_width=True,
        disabled=["File", "Kích thước", "FPS", "Thời lượng", "Âm thanh"],
        column_config={
            "Thứ tự": st.column_config.NumberColumn(min_value=1, step=1, width="small"),
            "Dùng": st.column_config.CheckboxColumn(width="small"),
        },
        key=f"join_order_{st.session_state[_CACHE_KEY]['key'][:8]}",
    )
    # Stable sort: ties keep upload order.
    edited = edited.assign(_pos=range(len(edited))).sort_values(["Thứ tự", "_pos"], kind="stable")
    ordered = [good[int(pos)] for pos, use in zip(edited["_pos"], edited["Dùng"]) if use]

    if ordered:
        total = sum(i["info"].duration for i in ordered)
        st.caption(
            f"🎞️ {len(ordered)} clip — tổng thời lượng ≈ **{_fmt_duration(total)}** · "
            + " → ".join(i["name"] for i in ordered)
        )
    return ordered


# ---------------------------------------------------------------------------
# 2. Output settings
# ---------------------------------------------------------------------------
def _render_output_settings(clips: list[dict]) -> dict:
    st.markdown("#### ⚙️ Cài đặt video đầu ra")
    first: VideoInfo | None = clips[0]["info"] if clips else None

    c1, c2, c3 = st.columns(3)
    with c1:
        res_label = st.selectbox(
            "Độ phân giải:",
            [_KEEP_FIRST, *VIDEO_RESOLUTIONS.keys()],
            help="Các clip khác kích thước sẽ được co giãn giữ tỉ lệ và thêm viền đen.",
            key="join_res",
        )
    with c2:
        fps = st.number_input(
            "FPS:",
            min_value=15,
            max_value=60,
            value=int(round(first.fps)) if first else DEFAULT_FPS,
            step=1,
            key="join_fps",
        )
    with c3:
        fmt = st.selectbox("Định dạng:", ["MP4", "MOV", "WEBM", "AVI"], key="join_fmt")

    name = st.text_input(
        "Tên video:",
        value=f"joined_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Tên file output (không cần đuôi mở rộng)",
        key="join_name",
    )

    if res_label == _KEEP_FIRST:
        size = (first.width, first.height) if first else None
        res_display = f"{size[0]}x{size[1]}" if size else _KEEP_FIRST
    else:
        size = VIDEO_RESOLUTIONS[res_label]
        res_display = res_label
    return {"size": size, "resolution": res_display, "fps": int(fps), "format": fmt.lower(), "name": name}


# ---------------------------------------------------------------------------
# 3. Logo
# ---------------------------------------------------------------------------
def _store_logo_upload(upload) -> str:
    data = upload.getvalue()
    key = hashlib.sha1(data).hexdigest()[:16]
    path = os.path.join(tempfile.gettempdir(), f"join_logo_{key}{os.path.splitext(upload.name)[1].lower()}")
    if not os.path.isfile(path):
        with open(path, "wb") as fh:
            fh.write(data)
    return path


def _render_logo_settings() -> LogoOptions | None:
    st.markdown("#### 🏷️ Logo")
    if not st.checkbox("Thêm logo vào giữa phía dưới video", value=False, key="join_logo_on"):
        return None

    sources = ([_LOGO_DEFAULT] if DEFAULT_LOGO else []) + [_LOGO_UPLOAD]
    source = st.radio("Nguồn logo:", sources, horizontal=True, key="join_logo_src")
    path: str | None = None
    if source == _LOGO_DEFAULT:
        path = DEFAULT_LOGO
    else:
        up = st.file_uploader(
            "Upload logo (khuyến nghị PNG nền trong suốt)",
            type=SUPPORTED_IMAGE_FILES,
            key="join_logo_upload",
        )
        if up:
            path = _store_logo_upload(up)
    if not path:
        st.warning("⚠️ Chưa có file logo — video sẽ được ghép không có logo.")
        return None

    c1, c2, c3 = st.columns(3)
    with c1:
        scale = st.slider("Kích thước (% cạnh ngắn):", 5, 50, 15, key="join_logo_scale")
    with c2:
        opacity = st.slider("Độ đậm (%):", 10, 100, 100, step=5, key="join_logo_opacity")
    with c3:
        margin = st.slider("Cách đáy (% chiều cao):", 0, 30, 4, key="join_logo_margin")
    return LogoOptions(path=path, scale=scale / 100, opacity=opacity / 100, bottom_margin=margin / 100)


# ---------------------------------------------------------------------------
# 4. Preview
# ---------------------------------------------------------------------------
def _render_preview(clips: list[dict], out: dict, logo: LogoOptions | None) -> None:
    if not clips or not out["size"]:
        return
    st.markdown(f"#### 👁️ Xem trước khung hình ({out['size'][0]}×{out['size'][1]})")
    first = clips[0]
    try:
        frame = extract_frame(first["path"], min(1.0, first["info"].duration / 2))
        img = preview_with_logo(frame, out["size"], logo)
    except Exception as exc:
        st.caption(f"Không tạo được ảnh xem trước: {exc}")
        return
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.image(img, caption=f"Khung hình từ {first['name']}", use_container_width=True)


# ---------------------------------------------------------------------------
# 5. Generate
# ---------------------------------------------------------------------------
def _entry(out: dict, clips: list[dict], logo: LogoOptions | None) -> dict:
    entry = build_video_entry(
        name=out["name"],
        resolution=out["resolution"],
        fps=out["fps"],
        fmt=out["format"],
        text_style="Ghép video",
        text_content="\n".join(c["name"] for c in clips),
        tts_lang="-",
        tts_speed="-",
        tts_engine="-",
        bg_mode="-",
        content_type="join",
    )
    entry["source_clips"] = [c["name"] for c in clips]
    entry["logo"] = bool(logo)
    return entry


def _handle_generate(clips: list[dict], out: dict, logo: LogoOptions | None) -> None:
    output_path = resolve_output_path(out["name"], out["format"], OUTPUT_DIR)
    progress = st.progress(0.0, text="⏳ Đang ghép video...")
    started = time.monotonic()

    def _on_progress(frac: float) -> None:
        mins, secs = divmod(int(time.monotonic() - started), 60)
        progress.progress(frac, text=f"⏳ Đang ghép video... {int(frac * 100)}% — {mins}:{secs:02d}")

    entry = _entry(out, clips, logo)
    try:
        join_videos(
            [c["path"] for c in clips],
            output_path,
            size=out["size"],
            fps=out["fps"],
            fmt=out["format"],
            logo=logo,
            progress_cb=_on_progress,
        )
    except Exception as exc:
        progress.empty()
        entry["status"] = STATUS_ERROR
        entry["output_path"] = None
        add_video(entry)
        st.error(f"❌ Lỗi khi ghép video: {exc}")
        return

    mins, secs = divmod(int(time.monotonic() - started), 60)
    progress.progress(1.0, text=f"✅ Hoàn thành! ({mins}:{secs:02d})")
    entry["status"] = STATUS_DONE
    entry["output_path"] = output_path
    add_video(entry)

    st.success(f"✅ Đã tạo video: `{os.path.basename(output_path)}`")
    st.video(output_path)
    with open(output_path, "rb") as fh:
        st.download_button(
            "⬇️ Tải video",
            data=fh,
            file_name=os.path.basename(output_path),
            mime=mime_for(out["format"]),
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header(
        "🔗",
        "Ghép Video",
        "Nối nhiều video thành một video mới theo thứ tự tùy chọn, có thể thêm logo ở giữa phía dưới",
    )

    clips = _render_clips()
    st.markdown("---")
    out = _render_output_settings(clips)
    st.markdown("---")
    logo = _render_logo_settings()
    st.markdown("---")
    _render_preview(clips, out, logo)

    ready = len(clips) >= 2
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        clicked = st.button("🔗 Ghép Video", use_container_width=True, type="primary", disabled=not ready)
    if clips and not ready:
        st.caption("Cần chọn ít nhất 2 clip để ghép.")
    if clicked and ready:
        _handle_generate(clips, out, logo)
