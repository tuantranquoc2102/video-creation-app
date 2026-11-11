"""Sidebar component."""

import streamlit as st

from ui.navigation import NAV_STATE_KEY
from ui.router import DISPLAY_NAMES

_APP_VERSION = "1.1"

def render_sidebar() -> str:
    """Render the sidebar and return the selected display-name string."""
    with st.sidebar:
        st.markdown("## 🎬 Digital Content Creation")

        st.markdown("---")
        selected = st.radio(
            "📌 Điều hướng",
            DISPLAY_NAMES,
            key=NAV_STATE_KEY,
            label_visibility="collapsed",
        )

        st.markdown("---")
        st.markdown(
            f'<div class="sidebar-footer">'
            f"Video Creation App v{_APP_VERSION}<br>"
            f"Built with ❤️ &amp; Streamlit"
            f"</div>",
            unsafe_allow_html=True,
        )

    return selected
