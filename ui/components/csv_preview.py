"""CSV type-selector & preview component.

Renders:
1. A card-based selector for the user to pick the CSV type.
2. Auto-detection from uploaded data.
3. A rich preview tailored to each CSV type (dialogue bubbles, vocab cards).
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from config import CSV_VIDEO_TYPES
from core.utils import normalize_ipa


# ---------------------------------------------------------------------------
# Type selector
# ---------------------------------------------------------------------------
def render_csv_type_selector() -> str | None:
    """Show cards for each CSV type, return selected key or None."""
    st.markdown("#### 📋 Chọn loại nội dung CSV")

    cols = st.columns(len(CSV_VIDEO_TYPES))
    selected: str | None = st.session_state.get("_csv_type_selected")

    for col, (key, spec) in zip(cols, CSV_VIDEO_TYPES.items()):
        with col:
            is_active = selected == key
            border = "2px solid #667eea" if is_active else "1px solid #ffffff20"
            bg = "#667eea18" if is_active else "#ffffff06"

            st.markdown(
                f"""
                <div style="border:{border}; background:{bg};
                     border-radius:12px; padding:1rem; text-align:center;
                     min-height:160px;">
                    <div style="font-size:2rem;">{spec['icon']}</div>
                    <div style="font-weight:700; margin:0.4rem 0;">{spec['label']}</div>
                    <div style="font-size:0.8rem; color:#aaa;">{spec['description']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "✅ Đã chọn" if is_active else "Chọn",
                key=f"csv_sel_{key}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["_csv_type_selected"] = key
                st.rerun()

    return st.session_state.get("_csv_type_selected")


# ---------------------------------------------------------------------------
# Auto-detect banner
# ---------------------------------------------------------------------------
def render_auto_detect_result(detected_key: str | None) -> None:
    """Show an info banner about auto-detection result."""
    if detected_key:
        spec = CSV_VIDEO_TYPES[detected_key]
        st.success(
            f"🔍 Tự động nhận dạng: **{spec['icon']} {spec['label']}** — "
            f"File CSV của bạn khớp với định dạng này."
        )
    else:
        st.warning(
            "🔍 Không thể tự động nhận dạng loại CSV. "
            "Hãy chọn loại nội dung phía trên."
        )


# ---------------------------------------------------------------------------
# Rich previews per CSV type
# ---------------------------------------------------------------------------
def render_csv_preview(df: pd.DataFrame, csv_type: str) -> None:
    """Dispatch to the right preview renderer."""
    renderers = {
        "dialogue": _preview_dialogue,
        "vocabulary": _preview_vocabulary,
    }
    renderer = renderers.get(csv_type)
    if renderer:
        renderer(df)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def _preview_dialogue(df: pd.DataFrame) -> None:
    """Render dialogue rows as chat-like bubbles."""
    st.markdown("##### 💬 Xem trước hội thoại")

    for _, row in df.iterrows():
        s1 = str(row.get("speaker 1", "")).strip()
        s2 = str(row.get("speaker 2", "")).strip()

        if s1 and s1.lower() != "nan":
            s1 = escape(s1)
            st.markdown(
                f"""<div style="display:flex; margin-bottom:0.5rem;">
                    <div style="background:#667eea33; border-radius:12px 12px 12px 0;
                         padding:0.6rem 1rem; max-width:70%;">
                        <span style="font-size:0.7rem; color:#667eea; font-weight:600;">
                            Speaker 1
                        </span><br>{s1}
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

        if s2 and s2.lower() != "nan":
            s2 = escape(s2)
            st.markdown(
                f"""<div style="display:flex; justify-content:flex-end; margin-bottom:0.5rem;">
                    <div style="background:#764ba233; border-radius:12px 12px 0 12px;
                         padding:0.6rem 1rem; max-width:70%; text-align:right;">
                        <span style="font-size:0.7rem; color:#764ba2; font-weight:600;">
                            Speaker 2
                        </span><br>{s2}
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.caption(f"Tổng cộng: {len(df)} dòng hội thoại")


def _preview_vocabulary(df: pd.DataFrame) -> None:
    """Render vocabulary rows as flashcard-style cards."""
    st.markdown("##### 📖 Xem trước từ vựng")

    has_image = "image" in [c.strip().lower() for c in df.columns]

    for _, row in df.iterrows():
        word = escape(str(row.get("english", "")))
        ipa = escape(normalize_ipa(row.get("ipa", "")))
        vn = escape(str(row.get("vietnam", "")))
        ex = escape(str(row.get("example", "")))
        tr = escape(str(row.get("translate", "")))
        img = escape(str(row.get("image", ""))) if has_image else ""

        img_html = ""
        if img and str(img).strip() and str(img).strip().lower() != "nan":
            img_html = (
                f'<div style="margin-top:0.4rem;font-size:0.75rem;color:#888;">'
                f'🖼️ {img}</div>'
            )

        st.markdown(
            f"""<div style="background:#ffffff08; border:1px solid #ffffff15;
                 border-radius:12px; padding:1rem; margin-bottom:0.75rem;">
                <div style="display:flex; align-items:baseline; gap:0.8rem; flex-wrap:wrap;">
                    <span style="font-size:1.25rem; font-weight:700; color:#667eea;">{word}</span>
                    <span style="font-size:0.9rem; color:#aaa;">/{ipa}/</span>
                    <span style="font-size:0.9rem; color:#e0e0e0;">— {vn}</span>
                </div>
                <div style="margin-top:0.5rem; padding-left:0.5rem;
                     border-left:3px solid #667eea44; color:#ccc; font-size:0.85rem;">
                    📝 {ex}<br>
                    <span style="color:#aaa;">🔄 {tr}</span>
                </div>
                {img_html}
            </div>""",
            unsafe_allow_html=True,
        )

    st.caption(f"Tổng cộng: {len(df)} từ vựng")


# ---------------------------------------------------------------------------
# Sample format helper
# ---------------------------------------------------------------------------
def render_sample_format(csv_type: str) -> None:
    """Show the expected CSV format as a code block."""
    spec = CSV_VIDEO_TYPES.get(csv_type)
    if not spec:
        return

    st.markdown("**📌 Định dạng CSV mẫu:**")
    st.code(spec["sample"], language="csv")
    st.caption(
        f"Separator: `{spec['separator']}` — "
        f"Cột bắt buộc: {', '.join(f'`{c}`' for c in spec['required_cols'])}"
    )
