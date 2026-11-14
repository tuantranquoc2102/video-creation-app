"""Scene-video page – story JSON + one illustration per scene → video with speech bubbles.

Flow: upload JSON → one image uploader per scene → review each scene and adjust where
every character's bubble sits and where its tail points → render.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import replace

import pandas as pd
import streamlit as st

from config import (
    DEFAULT_FONT_NAME,
    DEFAULT_LOGO,
    DEFAULT_VOICE_VI,
    FONTS,
    SPEAKER_VOICES,
    SPEAKER_VOICES_VI,
    SUPPORTED_IMAGE_FILES,
    VIDEO_RESOLUTIONS,
)
from core.render import RenderConfig
from core.render.canvas import apply_logo, missing_glyphs
from core.render.segments.common import resolve_voices
from core.scene_video import (
    TAIL_DIRECTIONS,
    BubbleLayout,
    SceneStyle,
    Story,
    StoryLoadError,
    draw_scene_frame,
    list_sample_stories,
    load_story_file,
    parse_story,
    render_scene_video,
    review_turns,
    story_to_json,
)
from core.state import STATUS_DONE, STATUS_ERROR, add_video
from core.utils import mime_for
from core.video_service import build_video_entry
from ui.components.page_header import render_page_header

_EN_VOICE_BY_ID = {v["voice_id"]: label for label, v in SPEAKER_VOICES.items()}
_VI_VOICE_BY_ID = {v["voice_id"]: label for label, v in SPEAKER_VOICES_VI.items()}
_TAIL_LABELS = {
    "down": "↓ Xuống dưới",
    "down-left": "↙ Dưới – trái",
    "down-right": "↘ Dưới – phải",
    "up": "↑ Lên trên",
    "up-left": "↖ Trên – trái",
    "up-right": "↗ Trên – phải",
    "left": "← Sang trái",
    "right": "→ Sang phải",
    "none": "✕ Không có mũi tên",
}
_FIT_LABELS = {"cover": "Lấp đầy khung (cắt phần thừa)", "contain": "Hiện toàn bộ hình (nền mờ)"}
_ALL_SPEAKERS = "👥 Tất cả nhân vật (để căn vị trí)"
_PREVIEW_SHORT_SIDE = 540  # previews are drawn at half size – same layout, much faster
_UPLOAD_DIR_KEY = "_scene_upload_dir"


# ---------------------------------------------------------------------------
# 1. Source
# ---------------------------------------------------------------------------
def _render_source() -> Story | None:
    st.markdown("#### 📄 File kịch bản (JSON)")
    samples = list_sample_stories()
    options = ["📂 Upload file JSON"] + (["📚 Kịch bản mẫu"] if samples else [])
    mode = st.radio("Chọn nguồn:", options, horizontal=True, key="scn_source")
    try:
        if mode == "📚 Kịch bản mẫu":
            c1, c2 = st.columns([3, 1])
            with c1:
                name = st.selectbox("Kịch bản mẫu:", list(samples), key="scn_sample")
            with c2:
                st.markdown("")
                with open(samples[name], "rb") as fh:
                    st.download_button("⬇️ Tải JSON mẫu", fh.read(), file_name=name,
                                       mime="application/json", use_container_width=True)
            return load_story_file(samples[name])

        st.caption("Cấu trúc: `lesson_id`, `meta` (`title_en`, `title_vi`), `characters` (`id`, `name`, `gender`, "
                   "`voice_id`), `scenes` – mỗi phân cảnh có `scene_id`, `setting_en`, `image_prompt` và `dialogue` "
                   "gồm các câu `speaker` / `en` / `vi`. Tải kịch bản mẫu `job-interviews-b1.json` để dùng làm template.")
        f = st.file_uploader("Chọn file .json", type=["json"], key="scn_upload")
        return parse_story(f.getvalue()) if f else None
    except StoryLoadError as exc:
        st.error("❌ File kịch bản không hợp lệ:")
        st.code("\n".join(exc.errors), language="text")
        return None


def _render_summary(story: Story) -> None:
    st.markdown(f"#### 📝 {story.title_en}" + (f" — *{story.title_vi}*" if story.title_vi else ""))
    c1, c2, c3 = st.columns(3)
    c1.metric("🎬 Phân cảnh", len(story.scenes))
    c2.metric("💬 Lượt thoại", story.turn_count)
    c3.metric("🧑‍🤝‍🧑 Nhân vật", len(story.characters))
    extras = story.extras()
    if extras:
        labels = {"vocabulary": "từ vựng", "exercises": "bài tập"}
        st.caption("ℹ️ File còn có " + " và ".join(f"{n} {labels[k]}" for k, n in extras.items())
                   + " – trang này chỉ dựng phần hội thoại theo phân cảnh; các phần đó được giữ nguyên khi tải lại JSON.")
    names = {c.id: c.name for c in story.characters}
    with st.expander("Xem nội dung hội thoại"):
        st.dataframe(
            pd.DataFrame([
                {"Phân cảnh": si + 1, "Nhân vật": names.get(t.speaker, t.speaker), "English": t.en, "Tiếng Việt": t.vi}
                for si, scene in enumerate(story.scenes) for t in scene.dialogue
            ]),
            use_container_width=True, hide_index=True,
        )


# ---------------------------------------------------------------------------
# 2. One image per scene
# ---------------------------------------------------------------------------
def _store_image(upload) -> str:
    """Save an upload once (content-addressed) and return its path."""
    base = st.session_state.get(_UPLOAD_DIR_KEY)
    if not base or not os.path.isdir(base):
        base = st.session_state[_UPLOAD_DIR_KEY] = tempfile.mkdtemp(prefix="scene_imgs_")
    data = upload.getvalue()
    ext = os.path.splitext(upload.name)[1].lower()
    ext = ext if ext.lstrip(".") in SUPPORTED_IMAGE_FILES else ".png"
    path = os.path.join(base, hashlib.sha1(data).hexdigest()[:20] + ext)
    if not os.path.isfile(path):
        with open(path, "wb") as fh:
            fh.write(data)
    return path


def _scene_label(story: Story, si: int) -> str:
    scene = story.scenes[si]
    title = scene.title_vi or scene.title_en
    return f"Phân cảnh {si + 1}" + (f": {title}" if title else "")


def _render_images(story: Story) -> dict[int, str]:
    n = len(story.scenes)
    st.markdown(f"#### 🖼️ Hình ảnh cho {n} phân cảnh")
    st.caption("Mỗi phân cảnh cần 1 hình. Nên dùng hình cùng tỉ lệ với video (9:16 hoặc 16:9) "
               "và chừa khoảng trống phía trên nhân vật để đặt bubble.")
    images: dict[int, str] = {}
    per_row = 3
    for row in range(0, n, per_row):
        cols = st.columns(per_row)
        for col, si in zip(cols, range(row, min(n, row + per_row))):
            scene = story.scenes[si]
            with col:
                up = st.file_uploader(
                    _scene_label(story, si),
                    type=SUPPORTED_IMAGE_FILES,
                    key=f"scn_img_{story.story_id}_{si}",
                    help=(f"Gợi ý trong JSON: {scene.image} · " if scene.image else "")
                    + f"{len(scene.dialogue)} lượt thoại",
                )
                if up is not None:
                    images[si] = _store_image(up)
                    st.image(images[si], use_container_width=True)
                if scene.setting_en:
                    st.caption(scene.setting_en)
                if scene.image_prompt:
                    with st.expander("📋 Prompt tạo hình"):
                        st.text_area("Prompt", scene.image_prompt, height=220, label_visibility="collapsed",
                                     key=f"scn_prompt_{story.story_id}_{si}")
    missing = [si + 1 for si in range(n) if si not in images]
    if missing:
        st.warning(f"⚠️ Còn thiếu hình cho phân cảnh: {', '.join(map(str, missing))} ({n - len(missing)}/{n} đã có).")
    else:
        st.success(f"✅ Đã có đủ hình cho {n} phân cảnh.")
    return images


# ---------------------------------------------------------------------------
# 3. Settings
# ---------------------------------------------------------------------------
def _voice_select(label: str, catalog: dict, by_id: dict, default_id: str, key: str) -> str:
    labels = list(catalog)
    default_label = by_id.get(default_id)
    index = labels.index(default_label) if default_label in labels else 0
    return catalog[st.selectbox(label, labels, index=index, key=key)]["voice_id"]


def _render_settings(story: Story) -> tuple[RenderConfig, SceneStyle, str]:
    st.markdown("#### ⚙️ Cài đặt video")
    c1, c2, c3 = st.columns(3)
    with c1:
        res_labels = list(VIDEO_RESOLUTIONS)
        res = st.selectbox("Độ phân giải:", res_labels, index=res_labels.index("9:16 (1080x1920)"), key="scn_res")
    with c2:
        fps = st.select_slider("FPS:", [24, 25, 30], value=30, key="scn_fps")
    with c3:
        fit = st.selectbox("Hiển thị hình:", list(_FIT_LABELS), format_func=_FIT_LABELS.get, key="scn_fit")

    font_path = None
    font_names = list(FONTS)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if font_names:
            idx = font_names.index(DEFAULT_FONT_NAME) if DEFAULT_FONT_NAME in font_names else 0
            font_path = FONTS[st.selectbox("Font chữ:", font_names, index=idx, key="scn_font")]
    with c2:
        font_scale = st.slider("Cỡ chữ (%):", 60, 160, 100, step=5, key="scn_font_scale") / 100
    with c3:
        bubble_width = st.slider("Độ rộng bubble tối đa (% khung):", 30, 90, 62, key="scn_bubble_w") / 100
    with c4:
        tail_length = st.slider("Độ dài mũi tên (%):", 40, 250, 100, step=10, key="scn_tail_len") / 100

    st.markdown("#### 🎙️ Giọng đọc")
    defaults = resolve_voices(story, RenderConfig())
    overrides: dict[str, str] = {}
    cols = st.columns(len(story.characters))
    for col, ch in zip(cols, story.characters):
        with col:
            overrides[ch.id] = _voice_select(
                f"{ch.name} ({'nữ' if ch.gender == 'female' else 'nam'}):",
                SPEAKER_VOICES, _EN_VOICE_BY_ID, defaults[ch.id], key=f"scn_v_{story.story_id}_{ch.id}",
            )
    if len(set(overrides.values())) < len(overrides):
        st.warning("⚠️ Có nhân vật đang dùng cùng một giọng – người xem sẽ khó phân biệt.")
    c1, c2, c3 = st.columns(3)
    with c1:
        vi_audio = st.toggle("Đọc cả câu tiếng Việt", value=False, key="scn_vi_audio",
                             help="Sau câu tiếng Anh, đọc tiếp bản dịch bằng giọng Việt. Video sẽ dài hơn.")
    with c2:
        narrator_vi = _voice_select("Giọng tiếng Việt:", SPEAKER_VOICES_VI, _VI_VOICE_BY_ID,
                                    DEFAULT_VOICE_VI, key="scn_narr_vi")
    with c3:
        show_logo = st.toggle("Hiện logo kênh (giữa, dưới)", value=False, key="scn_logo",
                              disabled=DEFAULT_LOGO is None)

    name = st.text_input("Tên file video:", value=story.title_en, key=f"scn_name_{story.story_id}",
                         help="Video được lưu trong output/scenes/<story_id>/")

    base = RenderConfig()
    cfg = RenderConfig(
        size=VIDEO_RESOLUTIONS[res],
        fps=int(fps),
        font_path=font_path or base.font_path,
        narrator_vi=narrator_vi,
        voice_overrides=overrides,
        logo_path=DEFAULT_LOGO if show_logo else None,
    )
    style = SceneStyle(bubble_width=bubble_width, font_scale=font_scale, tail_length=tail_length,
                       fit=fit, vi_audio=vi_audio)
    return cfg, style, name


# ---------------------------------------------------------------------------
# 4. Review & bubble layout
# ---------------------------------------------------------------------------
def _preview_cfg(cfg: RenderConfig) -> RenderConfig:
    scale = _PREVIEW_SHORT_SIDE / min(cfg.size)
    return replace(cfg, size=(int(cfg.size[0] * scale), int(cfg.size[1] * scale)))


def _layout_controls(story: Story, si: int) -> None:
    """Per-character position / tail widgets; writes the result into ``story.scenes[si].bubbles``."""
    scene = story.scenes[si]
    for cid in scene.speakers():
        char = story.character(cid)
        current = story.layout(si, cid)
        key = f"scn_{story.story_id}_{si}_{cid}"
        st.markdown(f"**💬 {char.name if char else cid}**")
        x = st.slider("Ngang (trái → phải, %)", 0, 100, int(round(current.x * 100)), key=f"{key}_x")
        y = st.slider("Dọc (trên → dưới, %)", 0, 100, int(round(current.y * 100)), key=f"{key}_y")
        tail = st.selectbox("Hướng mũi tên", TAIL_DIRECTIONS, index=TAIL_DIRECTIONS.index(current.tail),
                            format_func=_TAIL_LABELS.get, key=f"{key}_tail")
        scene.bubbles[cid] = BubbleLayout(x=x / 100, y=y / 100, tail=tail)


def _render_review(story: Story, images: dict[int, str], cfg: RenderConfig, style: SceneStyle) -> None:
    st.markdown("#### 👁️ Review & chỉnh vị trí bubble chat")
    st.caption("Kéo thanh trượt để đặt bubble gần nhân vật và chọn hướng mũi tên chỉ vào người nói. "
               "Trong video, mỗi lượt chỉ hiện bubble của người đang nói (tiếng Anh + tiếng Việt), "
               "sau đó chuyển sang bubble của người tiếp theo.")
    pcfg = _preview_cfg(cfg)
    names = {c.id: c.name for c in story.characters}
    tabs = st.tabs([f"Cảnh {si + 1}" + ("" if si in images else " ⚠️") for si in range(len(story.scenes))])
    for si, tab in enumerate(tabs):
        scene = story.scenes[si]
        with tab:
            st.markdown(f"**{_scene_label(story, si)}** — {len(scene.dialogue)} lượt thoại")
            left, right = st.columns([3, 2] if cfg.is_portrait else [3, 1])
            with right:
                turn_labels = [_ALL_SPEAKERS] + [
                    f"{ti + 1}. {names.get(t.speaker, t.speaker)}: {t.en[:40]}" for ti, t in enumerate(scene.dialogue)
                ]
                pick = st.selectbox("Xem thử lượt thoại:", range(len(turn_labels)),
                                    format_func=turn_labels.__getitem__, key=f"scn_{story.story_id}_{si}_turn")
                _layout_controls(story, si)
            with left:
                turns = review_turns(story, si) if pick == 0 else [pick - 1]
                frame = draw_scene_frame(story, si, turns, images.get(si), pcfg, style)
                st.image(apply_logo(frame, pcfg).convert("RGB"), use_container_width=True)

    st.download_button(
        "💾 Tải JSON kèm vị trí bubble",
        story_to_json(story),
        file_name=f"{story.story_id}.json",
        mime="application/json",
        help="Lưu lại vị trí bubble và hướng mũi tên đã chỉnh; lần sau upload file này sẽ giữ nguyên bố cục.",
    )


# ---------------------------------------------------------------------------
# 5. Generate
# ---------------------------------------------------------------------------
_STAGE_RANGE = {"tts": (0.0, 0.35), "frames": (0.35, 0.45), "audio": (0.45, 0.5), "encode": (0.5, 1.0)}
_STAGE_LABEL = {"tts": "Tạo giọng đọc", "frames": "Vẽ khung hình", "audio": "Trộn âm thanh", "encode": "Encode video"}


def _record(story: Story, cfg: RenderConfig, name: str, status: str, output_path: str | None) -> None:
    res_label = next((k for k, v in VIDEO_RESOLUTIONS.items() if v == tuple(cfg.size)), str(cfg.size))
    entry = build_video_entry(
        name=name, resolution=res_label, fps=cfg.fps, fmt="mp4", text_style="Phân cảnh",
        text_content="\n".join(f"{t.speaker}: {t.en} | {t.vi}" for s in story.scenes for t in s.dialogue),
        tts_lang="English + Tiếng Việt", tts_speed="Bình thường", tts_engine="Edge TTS",
        bg_mode="Hình phân cảnh", content_type="scene", csv_type="scene",
    )
    entry["status"] = status
    entry["story_id"] = story.story_id
    if output_path:
        entry["output_path"] = output_path
    add_video(entry)


def _handle_generate(story: Story, images: dict[int, str], cfg: RenderConfig, style: SceneStyle, name: str) -> None:
    bar = st.progress(0.0, text="⏳ Bắt đầu...")
    started = time.monotonic()

    def _progress(stage: str, done: int, total: int) -> None:
        lo, hi = _STAGE_RANGE.get(stage, (0.0, 1.0))
        pct = lo + (hi - lo) * (done / max(1, total))
        mins, secs = divmod(int(time.monotonic() - started), 60)
        bar.progress(min(1.0, pct), text=f"⏳ {_STAGE_LABEL.get(stage, stage)} {done}/{total} — {mins}:{secs:02d}")

    try:
        result = render_scene_video(story, images, cfg, style, video_name=name, progress_cb=_progress)
    except Exception as exc:  # surface any failure to the user and keep a record
        bar.empty()
        _record(story, cfg, name, STATUS_ERROR, None)
        st.error(f"❌ Lỗi khi tạo video: {exc}")
        return

    mins, secs = divmod(int(time.monotonic() - started), 60)
    bar.progress(1.0, text=f"✅ Hoàn thành sau {mins}:{secs:02d}")
    _record(story, cfg, name, STATUS_DONE, result.video_path)

    dm, ds = divmod(int(result.duration), 60)
    st.success(f"✅ Đã tạo video **{os.path.basename(result.video_path)}** — thời lượng {dm}:{ds:02d}")
    if result.tts_fallbacks:
        st.warning(f"⚠️ {len(result.tts_fallbacks)} câu dùng giọng dự phòng gTTS do Edge TTS lỗi tạm thời. "
                   "Hãy nghe lại và tạo lại video nếu cần.")
    _, mid, _ = st.columns([1, 2, 1] if cfg.is_portrait else [1, 6, 1])
    with mid:
        st.video(result.video_path)

    c1, c2, c3, c4 = st.columns(4)
    for col, path, label, fname, mime in (
        (c1, result.video_path, "⬇️ Video MP4", os.path.basename(result.video_path), mime_for("mp4")),
        (c2, result.srt_en_path, "⬇️ Phụ đề EN", f"{story.story_id}.en.srt", "application/x-subrip"),
        (c3, result.srt_vi_path, "⬇️ Phụ đề VI", f"{story.story_id}.vi.srt", "application/x-subrip"),
        (c4, result.thumbnail_path, "⬇️ Thumbnail", f"{story.story_id}.png", "image/png"),
    ):
        with open(path, "rb") as fh:
            col.download_button(label, fh.read(), file_name=fname, mime=mime, use_container_width=True)
    st.caption(f"📁 Tất cả file nằm trong `{result.out_dir}`")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render() -> None:
    render_page_header(
        "🎞️",
        "Video Phân Cảnh",
        "Từ file JSON + hình ảnh từng phân cảnh → video hội thoại với bubble chat song ngữ Anh–Việt đặt cạnh nhân vật",
    )

    story = _render_source()
    if story is None:
        return
    _render_summary(story)
    st.markdown("---")
    images = _render_images(story)
    st.markdown("---")
    cfg, style, name = _render_settings(story)
    missing = missing_glyphs(cfg.font_path, story.display_text())
    if missing:
        st.error(f"❌ Font đã chọn không hiển thị được các ký tự: `{missing}` – hãy chọn font khác (vd. Arial Unicode).")
    st.markdown("---")
    _render_review(story, images, cfg, style)
    st.markdown("---")

    ready = len(images) == len(story.scenes) and not missing
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        clicked = st.button("🚀 Tạo Video Phân Cảnh", type="primary", use_container_width=True, disabled=not ready)
        if len(images) < len(story.scenes):
            st.caption("Cần upload đủ hình cho tất cả phân cảnh trước khi tạo video.")
    if clicked and ready:
        _handle_generate(story, images, cfg, style, name)
