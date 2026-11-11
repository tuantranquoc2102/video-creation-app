"""Reusable page-header component."""

import streamlit as st


def render_page_header(icon: str, title: str, subtitle: str = "") -> None:
    """Render a styled page header with optional subtitle."""
    st.markdown(
        f'<p class="main-header">{icon} {title}</p>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(subtitle)
    st.markdown("---")
