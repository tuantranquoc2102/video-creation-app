"""Lesson JSON schema – the single source of truth for a lesson video.

Structural rules live here (types, required fields, enums).  Business /
quality rules (counts, word appears in dialogue, …) live in
:mod:`core.lesson.validators` so they can be reported as a list of issues
instead of failing on the first one.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from core.utils import is_within, normalize_ipa

SCHEMA_VERSION = 1

Level = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
ExerciseType = Literal["multiple_choice", "fill_blank", "translate_vi_en", "comprehension"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LessonMeta(_Model):
    topic: str = Field(min_length=1)
    level: Level = "A2"
    title_en: str = Field(min_length=1)
    title_vi: str = Field(min_length=1)
    learning_goal_vi: str | None = None
    scene_image: str | None = Field(
        default=None, description="Illustration of the dialogue scene, path relative to the lesson file"
    )
    scene_focus_y: float = Field(
        default=0.4, ge=0.0, le=1.0, description="Vertical focus (0 = top, 1 = bottom) when the image is cropped"
    )


class Character(_Model):
    id: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=30)
    gender: Literal["female", "male"]
    voice: str | None = Field(default=None, description="Edge TTS voice id, e.g. en-US-AvaNeural")


class DialogueTurn(_Model):
    speaker: str = Field(min_length=1)
    en: str = Field(min_length=1)
    vi: str = Field(min_length=1)


class VocabItem(_Model):
    word: str = Field(min_length=1)
    ipa: str = Field(min_length=1, description="Without surrounding slashes")
    pos: str = Field(min_length=1, description="noun, verb, adjective, …")
    meaning_vi: str = Field(min_length=1)
    dialogue_idx: int = Field(ge=0, description="Index of the dialogue turn that uses the word")
    forms: list[str] = Field(default_factory=list, description="Irregular forms used in the dialogue")
    example_en: str | None = Field(default=None, description="Defaults to the dialogue line")
    example_vi: str | None = Field(default=None, description="Defaults to the dialogue translation")
    image: str | None = Field(default=None, description="Optional illustration, path relative to the lesson file")

    @field_validator("ipa")
    @classmethod
    def _strip_slashes(cls, v: str) -> str:
        return normalize_ipa(v)


class Exercise(_Model):
    id: str = Field(min_length=1)
    type: ExerciseType
    prompt_en: str | None = None
    prompt_vi: str | None = None
    options: list[str] = Field(default_factory=list)
    answer: str = Field(min_length=1)
    explanation_vi: str | None = None
    think_seconds: int = Field(default=5, ge=2, le=15)
    vocab_refs: list[str] = Field(default_factory=list)


class Lesson(_Model):
    lesson_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    schema_version: int = SCHEMA_VERSION
    meta: LessonMeta
    characters: list[Character] = Field(min_length=2, max_length=2)
    dialogue: list[DialogueTurn] = Field(min_length=2)
    vocabulary: list[VocabItem] = Field(min_length=1)
    exercises: list[Exercise] = Field(default_factory=list)

    # Directory that relative asset paths (images) are resolved against.
    _base_dir: str | None = PrivateAttr(default=None)

    # -- assets --------------------------------------------------------------
    @property
    def base_dir(self) -> str | None:
        return self._base_dir

    def set_base_dir(self, directory: str | None) -> "Lesson":
        self._base_dir = os.path.abspath(directory) if directory else None
        return self

    def asset_refs(self) -> list[tuple[str, str]]:
        """``[(field path, relative path)]`` of every referenced image."""
        refs = []
        if self.meta.scene_image:
            refs.append(("meta.scene_image", self.meta.scene_image))
        refs += [(f"vocabulary[{i}].image", v.image) for i, v in enumerate(self.vocabulary) if v.image]
        return refs

    def asset_path(self, rel: str | None) -> str | None:
        """Absolute path of *rel* inside :attr:`base_dir`; ``None`` if unset or escaping it."""
        if not rel or not self._base_dir:
            return None
        path = os.path.normpath(os.path.join(self._base_dir, rel))
        return path if is_within(path, self._base_dir) else None

    @property
    def scene_path(self) -> str | None:
        path = self.asset_path(self.meta.scene_image)
        return path if path and os.path.isfile(path) else None

    def vocab_image_path(self, item: "VocabItem") -> str | None:
        path = self.asset_path(item.image)
        return path if path and os.path.isfile(path) else None

    # -- convenience -------------------------------------------------------
    def character(self, char_id: str) -> Character | None:
        return next((c for c in self.characters if c.id == char_id), None)

    def vocab_example(self, item: VocabItem) -> tuple[str, str]:
        """(example_en, example_vi) – falls back to the referenced dialogue turn."""
        turn = self.dialogue[item.dialogue_idx] if item.dialogue_idx < len(self.dialogue) else None
        en = item.example_en or (turn.en if turn else "")
        vi = item.example_vi or (turn.vi if turn else "")
        return en, vi

    def vocab_for_turn(self, idx: int) -> list[VocabItem]:
        return [v for v in self.vocabulary if v.dialogue_idx == idx]
