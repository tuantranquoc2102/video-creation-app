"""Programmatic navigation (kept separate from the router to avoid import cycles)."""

from __future__ import annotations

import streamlit as st

# Session-state key of the sidebar radio – set it (from a callback) to navigate.
NAV_STATE_KEY = "nav"


def navigate_to(route_key: str) -> None:
    """Button ``on_click`` callback: switch the sidebar selection to *route_key*."""
    from ui.router import ROUTES  # lazy: router imports the views

    route = next(r for r in ROUTES if r.key == route_key)
    st.session_state[NAV_STATE_KEY] = route.display_name
