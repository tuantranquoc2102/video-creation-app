"""Lesson video page – Lesson JSON → validated → previewed → 4-part bilingual video.

Segments: Intro → Hội thoại (song ngữ) → 10 Từ vựng → Bài tập tự nhớ → Ôn tập.
No AI is involved: the lesson content comes from a JSON file (hand-written or
produced by a later content-generation stage).
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import replace

import pandas as pd
import streamlit as st

from config import (
    DEFAULT_FONT_NAME,
    DEFAULT_LOGO,
    DEFAULT_VOICE_EN_NARRATOR,
    DEFAULT_VOICE_VI,
    FONTS,
    SPEAKER_VOICES,
    SPEAKER_VOICES_VI,
    SUPPORTED_IMAGE_FILES,
    VIDEO_RESOLUTIONS,
)
from core.lesson import (
    Lesson,
    LessonLoadError,
    has_errors,
    list_sample_lessons,
    load_lesson_file,
    parse_lesson,
    validate_lesson,
)
from core.lesson.importers import lesson_to_json
from core.render import RenderConfig, render_lesson_video, render_preview_frames
from core.render.canvas import missing_glyphs
from core.render.segments.common import resolve_voices
from core.state import STATUS_DONE, STATUS_ERROR, add_video
from core.utils import mime_for
from core.video_service import build_video_entry
from ui.components.page_header import render_page_header

_EN_VOICE_BY_ID = {v["voice_id"]: label for label, v in SPEAKER_VOICES.items()}
_VI_VOICE_BY_ID = {v["voice_id"]: label for label, v in SPEAKER_VOICES_VI.items()}
_PREVIEW_KEY = "_lesson_preview_frames"


# ---------------------------------------------------------------------------
# 1. Source
# ---------------------------------------------------------------------------
def _render_source() -> Lesson | None:
    st.markdown("#### 📚 Nguồn bài học (Lesson JSON)")
    samples = list_sample_lessons()
    options = ["📂 Upload file JSON"] + (["📚 Bài mẫu có sẵn"] if samples else [])
    mode = st.radio("Chọn nguồn:", options, horizontal=True, index=len(options) - 1, key="lsn_source")

    try:
        if mode == "📚 Bài mẫu có sẵn":
            c1, c2 = st.columns([3, 1])
            with c1:
                name = st.selectbox("Bài mẫu:", list(samples), key="lsn_sample")
            path = samples[name]
            with c2:
                st.markdown("")
                with open(path, "rb") as fh:
                    st.download_button("⬇️ Tải JSON mẫu", fh.read(), file_name=name,
                                       mime="application/json", use_container_width=True)
            return load_lesson_file(path)

        st.caption("Dùng file mẫu làm template: mỗi bài gồm `meta`, 2 `characters`, "
                   "`dialogue` (en + vi), đúng 10 `vocabulary`, và `exercises`.")
        f = st.file_uploader("Chọn file .json", type=["json"], key="lsn_upload")
        if not f:
            return None
        lesson = parse_lesson(f.getvalue())
        _attach_uploaded_images(lesson)
        return lesson
    except LessonLoadError as exc:
        st.error("❌ File bài học không hợp lệ:")
        st.code("\n".join(exc.errors), language="text")
        return None


_IMG_CACHE_KEY = "_lesson_img_cache"


def _attach_uploaded_images(lesson: Lesson) -> None:
    """If the uploaded JSON references images, ask for them and use their folder as base dir."""
    refs = lesson.asset_refs()
    if not refs:
        return
    wanted = sorted({os.path.basename(rel) for _, rel in refs})
    st.markdown("##### 🖼️ Hình minh hoạ được tham chiếu trong JSON")
    st.caption("Cần upload: " + ", ".join(f"`{n}`" for n in wanted))
    files = st.file_uploader("Upload hình minh hoạ", type=SUPPORTED_IMAGE_FILES,
                             accept_multiple_files=True, key="lsn_imgs")
    if not files:
        return
    signature = (lesson.lesson_id, tuple(sorted((f.name, f.size) for f in files)))
    cached = st.session_state.get(_IMG_CACHE_KEY)
    if cached and cached[0] == signature and os.path.isdir(cached[1]):
        base = cached[1]
    else:
        base = tempfile.mkdtemp(prefix="lesson_assets_")
        by_name = {os.path.basename(f.name): f for f in files}
        for _, rel in refs:  # keep the relative path layout of the JSON
            up = by_name.get(os.path.basename(rel))
            dst = os.path.normpath(os.path.join(base, rel))
            if up is not None and dst.startswith(base + os.sep):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as fh:
                    fh.write(up.getbuffer())
        st.session_state[_IMG_CACHE_KEY] = (signature, base)
    lesson.set_base_dir(base)
    missing = [n for n in wanted if n not in {os.path.basename(f.name) for f in files}]
    if missing:
        st.warning("⚠️ Còn thiếu: " + ", ".join(missing))


# ---------------------------------------------------------------------------
# 2. Validation & content review
# ---------------------------------------------------------------------------
def _render_validation(lesson: Lesson) -> bool:
    """Show checks; return True if rendering is allowed (no errors)."""
    issues = validate_lesson(lesson)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💬 Lượt thoại", len(lesson.dialogue))
    c2.metric("📖 Từ vựng", len(lesson.vocabulary))
    c3.metric("✍️ Bài tập", len(lesson.exercises))
    c4.metric("🎯 Trình độ", lesson.meta.level)

    if errors:
        st.error(f"❌ {len(errors)} lỗi cần sửa trước khi tạo video.")
    elif warnings:
        st.warning(f"⚠️ Không có lỗi, {len(warnings)} cảnh báo cần người duyệt xem lại.")
    else:
        st.success("✅ Bài học đạt tất cả kiểm tra tự động.")
    if issues:
        with st.expander("🔍 Chi tiết kiểm tra", expanded=bool(errors)):
            st.dataframe(
                pd.DataFrame([{"Mức": "❌ Lỗi" if i.severity == "error" else "⚠️ Cảnh báo",
                               "Vị trí": i.path, "Nội dung": i.message} for i in issues]),
                use_container_width=True, hide_index=True,
            )
    return not has_errors(issues)


def _render_content(lesson: Lesson) -> None:
    st.markdown(f"#### 📝 Nội dung: {lesson.meta.title_en} — *{lesson.meta.title_vi}*")
    names = {c.id: c.name for c in lesson.characters}
    t1, t2, t3 = st.tabs(["💬 Hội thoại song ngữ", "📖 Từ vựng", "✍️ Bài tập"])
    with t1:
        st.dataframe(pd.DataFrame([{"#": i + 1, "Nhân vật": names.get(d.speaker, d.speaker),
                                    "English": d.en, "Tiếng Việt": d.vi}
                                   for i, d in enumerate(lesson.dialogue)]),
                     use_container_width=True, hide_index=True)
    with t2:
        st.dataframe(pd.DataFrame([{"#": i + 1, "Từ": v.word, "IPA": f"/{v.ipa}/", "Loại": v.pos,
                                    "Nghĩa": v.meaning_vi, "Lượt thoại": v.dialogue_idx + 1}
                                   for i, v in enumerate(lesson.vocabulary)]),
                     use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(pd.DataFrame([{"#": i + 1, "Loại": e.type, "Câu hỏi": e.prompt_en or e.prompt_vi,
                                    "Lựa chọn": " | ".join(e.options), "Đáp án": e.answer,
                                    "Giây suy nghĩ": e.think_seconds}
                                   for i, e in enumerate(lesson.exercises)]),
                     use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# 3. Settings
# ---------------------------------------------------------------------------
def _voice_select(label: str, catalog: dict, by_id: dict, default_id: str, key: str) -> str:
    labels = list(catalog)
    default_label = by_id.get(default_id)
    index = labels.index(default_label) if default_label in labels else 0
    return catalog[st.selectbox(label, labels, index=index, key=key)]["voice_id"]


def _render_settings(lesson: Lesson) -> tuple[RenderConfig, str]:
    st.markdown("#### ⚙️ Cài đặt video")
    c1, c2, c3 = st.columns(3)
    with c1:
        res_labels = list(VIDEO_RESOLUTIONS)
        res = st.selectbox("Độ phân giải:", res_labels, index=res_labels.index("9:16 (1080x1920)"), key="lsn_res")
    with c2:
        fps = st.select_slider("FPS:", [24, 25, 30], value=30, key="lsn_fps",
                               help="Video là các khung tĩnh – 24/25 fps giúp encode nhanh hơn.")
    with c3:
        bg_color = st.color_picker("Màu nền:", "#0f172a", key="lsn_bg")

    bg_file = st.file_uploader("Ảnh nền (tuỳ chọn – sẽ được làm tối để chữ dễ đọc):",
                               type=SUPPORTED_IMAGE_FILES, key="lsn_bg_img")

    font_names = list(FONTS)
    font_path = None
    if font_names:
        idx = font_names.index(DEFAULT_FONT_NAME) if DEFAULT_FONT_NAME in font_names else 0
        font_path = FONTS[st.selectbox("Font chữ:", font_names, index=idx, key="lsn_font")]

    st.markdown("#### 🎙️ Giọng đọc")
    defaults = resolve_voices(lesson, RenderConfig())
    overrides: dict[str, str] = {}
    cols = st.columns(len(lesson.characters))
    for col, ch in zip(cols, lesson.characters):
        with col:
            overrides[ch.id] = _voice_select(
                f"{ch.name} ({'nữ' if ch.gender == 'female' else 'nam'}):",
                SPEAKER_VOICES, _EN_VOICE_BY_ID, defaults[ch.id], key=f"lsn_v_{lesson.lesson_id}_{ch.id}",
            )
    if len(set(overrides.values())) < len(overrides):
        st.warning("⚠️ Hai nhân vật đang dùng cùng một giọng – người xem sẽ khó phân biệt.")

    c1, c2 = st.columns(2)
    with c1:
        narrator_en = _voice_select("Người dẫn (tiếng Anh):", SPEAKER_VOICES, _EN_VOICE_BY_ID,
                                    DEFAULT_VOICE_EN_NARRATOR, key="lsn_narr_en")
    with c2:
        narrator_vi = _voice_select("Người dẫn (tiếng Việt):", SPEAKER_VOICES_VI, _VI_VOICE_BY_ID,
                                    DEFAULT_VOICE_VI, key="lsn_narr_vi")

    st.markdown("#### 📖 Phần từ vựng")
    st.caption("Mỗi từ: đọc từ N lần (luân phiên 2 giọng) → nghĩa tiếng Việt → câu ví dụ N lần "
               "(luân phiên 2 giọng) → bản dịch tiếng Việt của câu ví dụ.")
    defaults_vocab = RenderConfig().vocab_voices
    c1, c2 = st.columns(2)
    with c1:
        vv1 = _voice_select("Giọng tiếng Anh 1:", SPEAKER_VOICES, _EN_VOICE_BY_ID, defaults_vocab[0], key="lsn_vv1")
        word_repeat = st.slider("Số lần đọc từ vựng:", 1, 4, 2, key="lsn_repeat")
        read_example_vi = st.toggle("Đọc bản dịch tiếng Việt của câu ví dụ", value=True, key="lsn_ex_vi")
    with c2:
        vv2 = _voice_select("Giọng tiếng Anh 2:", SPEAKER_VOICES, _EN_VOICE_BY_ID, defaults_vocab[1], key="lsn_vv2")
        example_repeat = st.slider("Số lần đọc câu ví dụ:", 1, 4, 2, key="lsn_ex_repeat")
    if vv1 == vv2:
        st.warning("⚠️ Hai giọng đọc từ vựng đang giống nhau.")

    st.markdown("#### 🧩 Nội dung & nhịp độ")
    st.caption("Mọi câu có lẫn tiếng Anh và tiếng Việt được tự tách: phần tiếng Anh đọc bằng giọng Anh, "
               "phần tiếng Việt bằng giọng Việt. Đặt thuật ngữ tiếng Anh trong ngoặc kép \"…\" để chắc chắn được đọc bằng giọng Anh.")
    c1, c2 = st.columns(2)
    with c1:
        vi_narration = st.toggle("Đọc tiếng Việt (tiêu đề phần, nghĩa từ, giải thích)", value=True, key="lsn_vi")
        dialogue_vi_audio = st.toggle("Đọc cả bản dịch tiếng Việt của hội thoại", value=False, key="lsn_dlg_vi",
                                      help="Video dài hơn; phù hợp người mới bắt đầu.")
        tick = st.toggle("Âm 'tích tắc' khi đếm ngược", value=True, key="lsn_tick")
    with c2:
        think = st.slider("Thời gian suy nghĩ mỗi bài tập (giây, 0 = theo file):", 0, 15, 0, key="lsn_think")
        scene_bg = st.toggle("Dùng hình minh hoạ (làm mờ) làm nền các khung", value=True, key="lsn_scene_bg",
                             disabled=lesson.scene_path is None,
                             help="Chỉ áp dụng khi bài học có meta.scene_image.")
        layout_labels = {"fullscreen": "Toàn màn hình 9:16", "panel": "Khung phía trên khung chat"}
        scene_layout = st.radio(
            "Hiển thị hình minh hoạ (video dọc):", list(layout_labels), format_func=layout_labels.get,
            horizontal=True, key="lsn_scene_layout", disabled=lesson.scene_path is None,
            help="Video ngang luôn hiển thị ảnh dạng thẻ 9:16 bên trái.",
        )

    st.markdown("#### 🏷️ Logo kênh")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        show_logo = st.toggle("Hiện logo (giữa, dưới màn hình)", value=DEFAULT_LOGO is not None, key="lsn_logo_on")
        logo_file = st.file_uploader("Logo khác (PNG nền trong suốt):", type=["png", "webp"], key="lsn_logo_up",
                                     disabled=not show_logo)
    with c2:
        logo_opacity = st.slider("Độ mờ logo (% hiển thị):", 10, 80, 35, step=5, key="lsn_logo_op",
                                 disabled=not show_logo) / 100
    with c3:
        logo_scale = st.slider("Kích thước logo (% cạnh ngắn):", 6, 20, 12, key="lsn_logo_sz",
                               disabled=not show_logo) / 100
    logo_path = None
    if show_logo:
        if logo_file is not None:
            tmp = tempfile.mkdtemp(prefix="lesson_logo_")
            logo_path = os.path.join(tmp, "logo" + os.path.splitext(logo_file.name)[1].lower())
            with open(logo_path, "wb") as fh:
                fh.write(logo_file.getbuffer())
        else:
            logo_path = DEFAULT_LOGO
        if logo_path is None:
            st.info("Chưa có logo mặc định (`assets/brand/daily-dialogues-logo.png`) – hãy upload logo.")
        else:
            st.image(logo_path, width=72, caption="Logo sẽ dùng")

    name = st.text_input("Tên file video:", value=lesson.meta.title_en, key=f"lsn_name_{lesson.lesson_id}",
                         help="Video được lưu trong output/lessons/<lesson_id>/")

    bg_path = None
    if bg_file is not None:
        tmp_dir = tempfile.mkdtemp(prefix="lesson_bg_")
        bg_path = os.path.join(tmp_dir, os.path.basename(bg_file.name))
        with open(bg_path, "wb") as fh:
            fh.write(bg_file.getbuffer())

    base = RenderConfig()
    cfg = RenderConfig(
        size=VIDEO_RESOLUTIONS[res],
        font_path=font_path or base.font_path,
        theme=replace(base.theme, bg=bg_color),
        fps=int(fps),
        bg_image=bg_path,
        narrator_en=narrator_en,
        narrator_vi=narrator_vi,
        voice_overrides=overrides,
        vi_narration=vi_narration,
        dialogue_vi_audio=dialogue_vi_audio,
        word_repeat=word_repeat,
        example_repeat=example_repeat,
        read_example_vi=read_example_vi,
        vocab_voices=(vv1, vv2),
        use_scene_background=scene_bg,
        scene_layout=scene_layout,
        logo_path=logo_path,
        logo_opacity=logo_opacity,
        logo_scale=logo_scale,
        think_seconds=think or None,
        tick_sound=tick,
    )

    missing = missing_glyphs(cfg.font_path, lesson_to_json(lesson))
    if missing:
        st.error(f"❌ Font đã chọn không hiển thị được các ký tự: `{missing}` – hãy chọn font khác (vd. Arial Unicode).")
    return cfg, name


# ---------------------------------------------------------------------------
# 4. Preview
# ---------------------------------------------------------------------------
def _render_preview(lesson: Lesson, cfg: RenderConfig) -> None:
    st.markdown("#### 👁️ Xem trước khung hình")
    if st.button("🖼️ Tạo ảnh xem trước", key="lsn_preview_btn"):
        with st.spinner("Đang vẽ khung hình..."):
            st.session_state[_PREVIEW_KEY] = (lesson.lesson_id, render_preview_frames(lesson, cfg))
    cached = st.session_state.get(_PREVIEW_KEY)
    if cached and cached[0] == lesson.lesson_id:
        frames = cached[1]
        per_row = 3 if cfg.is_portrait else 2
        items = list(frames.items())
        for i in range(0, len(items), per_row):
            cols = st.columns(per_row)
            for col, (label, img) in zip(cols, items[i:i + per_row]):
                col.image(img, caption=label, use_container_width=True)
        st.caption("Ảnh xem trước dùng đúng bộ vẽ của video (không có âm thanh). Bấm lại nếu đổi cài đặt.")


# ---------------------------------------------------------------------------
# 5. Generate
# ---------------------------------------------------------------------------
_STAGE_RANGE = {"tts": (0.0, 0.35), "frames": (0.35, 0.45), "audio": (0.45, 0.5), "encode": (0.5, 1.0)}
_STAGE_LABEL = {"tts": "Tạo giọng đọc", "frames": "Vẽ khung hình", "audio": "Trộn âm thanh", "encode": "Encode video"}


def _record(lesson: Lesson, cfg: RenderConfig, name: str, status: str, output_path: str | None) -> None:
    res_label = next((k for k, v in VIDEO_RESOLUTIONS.items() if v == tuple(cfg.size)), str(cfg.size))
    entry = build_video_entry(
        name=name, resolution=res_label, fps=cfg.fps, fmt="mp4", text_style="Lesson",
        text_content="\n".join(f"{d.speaker}: {d.en} | {d.vi}" for d in lesson.dialogue),
        tts_lang="English + Tiếng Việt", tts_speed="Bình thường", tts_engine="Edge TTS",
        bg_mode="Ảnh nền" if cfg.bg_image else "Màu nền", content_type="lesson", csv_type="lesson",
    )
    entry["status"] = status
    entry["lesson_id"] = lesson.lesson_id
    if output_path:
        entry["output_path"] = output_path
    add_video(entry)


def _handle_generate(lesson: Lesson, cfg: RenderConfig, name: str) -> None:
    bar = st.progress(0.0, text="⏳ Bắt đầu...")
    started = time.monotonic()

    def _progress(stage: str, done: int, total: int) -> None:
        lo, hi = _STAGE_RANGE.get(stage, (0.0, 1.0))
        pct = lo + (hi - lo) * (done / max(1, total))
        mins, secs = divmod(int(time.monotonic() - started), 60)
        bar.progress(min(1.0, pct), text=f"⏳ {_STAGE_LABEL.get(stage, stage)} {done}/{total} — {mins}:{secs:02d}")

    try:
        result = render_lesson_video(lesson, cfg, video_name=name, progress_cb=_progress)
    except Exception as exc:  # surface any failure to the user and keep a record
        bar.empty()
        _record(lesson, cfg, name, STATUS_ERROR, None)
        st.error(f"❌ Lỗi khi tạo video: {exc}")
        return

    mins, secs = divmod(int(time.monotonic() - started), 60)
    bar.progress(1.0, text=f"✅ Hoàn thành sau {mins}:{secs:02d}")
    _record(lesson, cfg, name, STATUS_DONE, result.video_path)

    dm, ds = divmod(int(result.duration), 60)
    st.success(f"✅ Đã tạo video **{os.path.basename(result.video_path)}** — thời lượng {dm}:{ds:02d}")
    if result.tts_fallbacks:
        st.warning(
            f"⚠️ {len(result.tts_fallbacks)} câu dùng giọng dự phòng gTTS do Edge TTS lỗi tạm thời. "
            "Hãy nghe lại và tạo lại video nếu cần."
        )
        st.json(result.tts_fallbacks, expanded=False)

    st.video(result.video_path)
    st.dataframe(pd.DataFrame([{"Phần": s["name"], "Bắt đầu (s)": s["start"], "Kết thúc (s)": s["end"]}
                               for s in result.segments]), hide_index=True, use_container_width=True)

    c1, c2, c3, c4 = st.columns(4)
    with open(result.video_path, "rb") as fh:
        c1.download_button("⬇️ Video MP4", fh.read(), file_name=os.path.basename(result.video_path),
                           mime=mime_for("mp4"), use_container_width=True)
    with open(result.srt_en_path, "rb") as fh:
        c2.download_button("⬇️ Phụ đề EN", fh.read(), file_name=f"{lesson.lesson_id}.en.srt",
                           mime="application/x-subrip", use_container_width=True)
    with open(result.srt_vi_path, "rb") as fh:
        c3.download_button("⬇️ Phụ đề VI", fh.read(), file_name=f"{lesson.lesson_id}.vi.srt",
                           mime="application/x-subrip", use_container_width=True)
    with open(result.thumbnail_path, "rb") as fh:
        c4.download_button("⬇️ Thumbnail", fh.read(), file_name=f"{lesson.lesson_id}.png",
                           mime="image/png", use_container_width=True)
    st.caption(f"📁 Tất cả file nằm trong `{result.lesson_dir}`")

    with st.expander("🔊 Kịch bản giọng đọc (ai đọc gì, lúc nào)"):
        st.caption("Dùng để kiểm tra: phần tiếng Anh phải là giọng en-US, phần tiếng Việt là giọng vi-VN.")
        st.dataframe(
            pd.DataFrame([{"Bắt đầu (s)": s["start"], "Phần": s["segment"],
                           "Ngôn ngữ": "🇻🇳 VI" if s["voice"].startswith("vi-") else "🇬🇧 EN",
                           "Giọng": s["voice"], "Nội dung": s["text"]} for s in result.speech]),
            hide_index=True, use_container_width=True,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header(
        "🎓",
        "Video Bài Học",
        "Hội thoại song ngữ Anh–Việt → 10 từ vựng → bài tập tự nhớ → ôn tập, từ một file Lesson JSON",
    )

    lesson = _render_source()
    if lesson is None:
        return
    st.markdown("---")
    can_render = _render_validation(lesson)
    _render_content(lesson)
    st.markdown("---")
    cfg, name = _render_settings(lesson)
    st.markdown("---")
    _render_preview(lesson, cfg)
    st.markdown("---")

    font_ok = not missing_glyphs(cfg.font_path, lesson_to_json(lesson))
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        clicked = st.button("🚀 Tạo Video Bài Học", type="primary", use_container_width=True,
                            disabled=not (can_render and font_ok))
        st.caption("Thường mất 1–3 phút; lần đầu lâu hơn do phải tạo giọng đọc (sau đó được cache).")
    if clicked:
        _handle_generate(lesson, cfg, name)
