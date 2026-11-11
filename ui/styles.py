"""Centralized CSS styles for the application.

All CSS is managed here so that styling is decoupled from page logic.
Import ``inject_css()`` once in ``app.py`` after ``st.set_page_config``.
"""

import streamlit as st

# ---------------------------------------------------------------------------
# Design tokens – change these to re-skin the entire app.
# ---------------------------------------------------------------------------
_GRADIENT_PRIMARY = "linear-gradient(90deg, #667eea 0%, #764ba2 100%)"
_GRADIENT_BG = "linear-gradient(135deg, #667eea22 0%, #764ba222 100%)"
_SIDEBAR_BG = "linear-gradient(180deg, #5289ff 0%, #F7F8F9 100%)"
_BORDER_ACCENT = "#667eea33"
_COLOR_SUCCESS = "#00c853"
_COLOR_WARNING = "#ffab00"
_COLOR_ERROR = "#ff1744"
_RADIUS = "12px"

# ---------------------------------------------------------------------------
# Style sheets
# ---------------------------------------------------------------------------
_GLOBAL_CSS = f"""
<style>
/* ── Header gradient text ─────────────────────────────────────────────── */
.main-header {{
    font-size: 2rem;
    font-weight: 700;
    background: {_GRADIENT_PRIMARY};
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.5rem;
}}

/* ── Metric cards ─────────────────────────────────────────────────────── */
div[data-testid="stMetric"] {{
    background: {_GRADIENT_BG};
    border: 1px solid {_BORDER_ACCENT};
    border-radius: {_RADIUS};
    padding: 1rem;
}}
div[data-testid="stMetric"] label {{
    font-size: 0.85rem;
    color: #888;
}}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background: {_SIDEBAR_BG};
}}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {{
    color: #e0e0e0;
}}

/* ── Status badges ────────────────────────────────────────────────────── */
.status-done       {{ color: {_COLOR_SUCCESS}; font-weight: 600; }}
.status-processing {{ color: {_COLOR_WARNING}; font-weight: 600; }}
.status-error      {{ color: {_COLOR_ERROR};   font-weight: 600; }}

/* ── Generic card ─────────────────────────────────────────────────────── */
.card {{
    background: #ffffff08;
    border: 1px solid #ffffff15;
    border-radius: {_RADIUS};
    padding: 1.2rem;
    margin-bottom: 1rem;
}}

/* ── Empty state ──────────────────────────────────────────────────────── */
.empty-state {{
    text-align: center;
    padding: 3rem;
}}
.empty-state p {{
    color: #888;
}}

/* ── Sidebar footer ───────────────────────────────────────────────────── */
.sidebar-footer {{
    text-align: center;
    color: #888;
    font-size: 0.75rem;
}}
</style>
"""


def inject_css() -> None:
    """Inject all custom CSS into the current Streamlit page.

    Call this exactly once in ``app.py`` right after ``st.set_page_config``.
    """
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)
