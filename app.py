"""Video Creation App – thin entry point.

Responsibilities:
1. Configure the Streamlit page (must happen before any other st call).
2. Inject global CSS.
3. Initialise session state.
4. Render the sidebar and route to the selected view.

All heavy lifting lives in ``core/`` (business logic) and ``ui/`` (presentation).
"""

import streamlit as st

from core.state import init as init_state
from ui.styles import inject_css
from ui.components.sidebar import render_sidebar
from ui.router import get_route

# ── Page config (must be the first Streamlit command) ─────────────────────
st.set_page_config(
    page_title="Video Creation App",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Bootstrap ─────────────────────────────────────────────────────────────
inject_css()
init_state()


def main() -> None:
    selected = render_sidebar()
    route = get_route(selected)
    route.render()


if __name__ == "__main__":
    main()
