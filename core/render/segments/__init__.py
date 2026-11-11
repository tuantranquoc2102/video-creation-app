"""Lesson video segments: intro → dialogue → vocabulary → exercises → recap."""

from core.render.segments.common import Ctx
from core.render.segments.dialogue import build_dialogue, draw_dialogue
from core.render.segments.exercise import build_exercises, draw_exercise
from core.render.segments.intro import build_intro, draw_intro
from core.render.segments.outro import build_outro, draw_recap
from core.render.segments.vocab import build_vocab, draw_vocab

__all__ = [
    "Ctx",
    "build_dialogue",
    "build_exercises",
    "build_intro",
    "build_outro",
    "build_vocab",
    "draw_dialogue",
    "draw_exercise",
    "draw_intro",
    "draw_recap",
    "draw_vocab",
]
