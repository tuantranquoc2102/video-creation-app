"""Lesson video rendering (Pillow frames + MoviePy encoding)."""

from core.render.assemble import LessonRenderResult, render_lesson_video, render_preview_frames
from core.render.config import RenderConfig, Theme

__all__ = ["LessonRenderResult", "RenderConfig", "Theme", "render_lesson_video", "render_preview_frames"]
