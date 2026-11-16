"""Page router – single source of truth for navigation.

Each route is declared once here.  Adding a new page only requires:
1. Create a view module in ``ui/views/``.
2. Add an entry to ``ROUTES``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ui.views import dashboard, create_video, manage_videos


def _dialogue_video_render():
    """Lazy import to avoid circular dependency."""
    from ui.views.dialogue_video import render
    render()


def _vocabulary_video_render():
    """Lazy import to avoid circular dependency."""
    from ui.views.vocabulary_video import render
    render()


def _join_video_render():
    """Lazy import to avoid circular dependency."""
    from ui.views.join_video import render
    render()


def _crawl_channel_render():
    """Lazy import to avoid circular dependency."""
    from ui.views.crawl_channel import render
    render()


def _scene_video_render():
    """Lazy import to avoid circular dependency."""
    from ui.views.scene_video import render
    render()


def _lesson_video_render():
    """Lazy import to avoid circular dependency."""
    from ui.views.lesson_video import render
    render()


# ---------------------------------------------------------------------------
# Route definition
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Route:
    key: str            # Internal identifier
    label: str          # Display label (shown in sidebar radio)
    icon: str           # Emoji icon
    render: Callable    # The view function to call

    @property
    def display_name(self) -> str:
        return f"{self.icon} {self.label}"


# Register all routes – order determines sidebar display order.
ROUTES: list[Route] = [
    Route(key="dashboard",        label="Dashboard",       icon="🏠", render=dashboard.render),
    Route(key="lesson_video",     label="Video Bài Học",   icon="🎓", render=_lesson_video_render),
    Route(key="scene_video",      label="Video Phân Cảnh", icon="🎞️", render=_scene_video_render),
    Route(key="dialogue_video",   label="Video Hội Thoại", icon="💬", render=_dialogue_video_render),
    Route(key="vocabulary_video", label="Video Từ Vựng",   icon="📖", render=_vocabulary_video_render),
    Route(key="join_video",       label="Ghép Video",      icon="🔗", render=_join_video_render),
    Route(key="crawl_channel",    label="Crawl Video Kênh", icon="🕸️", render=_crawl_channel_render),
    Route(key="create_video",     label="Tạo Video",       icon="🎥", render=create_video.render),
    Route(key="manage_videos",    label="Quản lý Video",   icon="📂", render=manage_videos.render),
]

# Lookup helpers
_ROUTE_BY_DISPLAY = {r.display_name: r for r in ROUTES}
DISPLAY_NAMES: list[str] = [r.display_name for r in ROUTES]


def get_route(display_name: str) -> Route:
    """Return the *Route* that matches the sidebar display name."""
    return _ROUTE_BY_DISPLAY[display_name]
