"""Story schema – a dialogue split into scenes, each scene shown over its own illustration.

Accepted input (see ``samples/scenes/job-interviews-b1.json``) is the scene-based lesson file:

```json
{
  "lesson_id": "job-interviews-b1",
  "schema_version": 3,
  "meta": {"title_en": "A Job Interview", "title_vi": "…", …},
  "characters": [{"id": "A", "name": "Mia", "gender": "female", "voice_id": "en-US-JennyNeural", …}],
  "scenes": [
    {"scene_id": 1, "setting_en": "…", "image_prompt": "…",
     "dialogue": [{"speaker": "A", "en": "…", "vi": "…"}],
     "bubbles": {"A": {"x": 0.27, "y": 0.2, "tail": "down"}}}
  ],
  "vocabulary": […], "exercises": […]
}
```

Only ``lesson_id``, ``meta.title_en``, ``characters`` and ``scenes[].dialogue`` are needed here;
other fields (``visual_description``, ``vocabulary``, ``exercises``…) are kept untouched on export.
``bubbles`` is optional and written by this app: where each character's speech bubble sits in
that scene (centre of the bubble as a fraction of the frame) and where its tail points.

Two older shapes are still read: the flat story (``story_id`` + ``scenes``) and the v1 Lesson
JSON (``meta`` + root ``dialogue``), which becomes a one-scene story.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from config import SCENE_SAMPLES_DIR
from core.lesson.schema import Character, Lesson

TailDirection = Literal["down", "down-left", "down-right", "up", "up-left", "up-right", "left", "right", "none"]
TAIL_DIRECTIONS: tuple[str, ...] = get_args(TailDirection)

MAX_CHARACTERS = 4


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BubbleLayout(_Model):
    x: float = Field(default=0.5, ge=0.0, le=1.0, description="Bubble centre, fraction of the frame width")
    y: float = Field(default=0.2, ge=0.0, le=1.0, description="Bubble centre, fraction of the frame height")
    tail: TailDirection = "down"


class SceneTurn(_Model):
    speaker: str = Field(min_length=1)
    en: str = Field(min_length=1)
    vi: str = Field(min_length=1)


class Scene(_Model):
    id: str | None = None
    title_en: str | None = None
    title_vi: str | None = None
    setting_en: str | None = Field(default=None, description="What happens in the scene (shown to the reviewer)")
    image_prompt: str | None = Field(default=None, description="Prompt used to generate the illustration")
    image: str | None = Field(default=None, description="Suggested file name of the illustration (informative)")
    dialogue: list[SceneTurn] = Field(min_length=1)
    bubbles: dict[str, BubbleLayout] = Field(default_factory=dict)

    def speakers(self) -> list[str]:
        """Character ids that speak in this scene, in order of first appearance."""
        return list(dict.fromkeys(t.speaker for t in self.dialogue))


class Story(_Model):
    story_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    title_en: str = Field(min_length=1)
    title_vi: str | None = None
    characters: list[Character] = Field(min_length=1, max_length=MAX_CHARACTERS)
    scenes: list[Scene] = Field(min_length=1)

    # The uploaded document when it was a scene-based lesson file – exported back with ``bubbles`` added.
    _source: dict | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _check_references(self) -> "Story":
        ids = [c.id for c in self.characters]
        if len(set(ids)) != len(ids):
            raise ValueError("characters: id nhân vật bị trùng")
        for i, scene in enumerate(self.scenes):
            for j, turn in enumerate(scene.dialogue):
                if turn.speaker not in ids:
                    raise ValueError(f"scenes[{i}].dialogue[{j}].speaker: không có nhân vật '{turn.speaker}'")
            for cid in scene.bubbles:
                if cid not in ids:
                    raise ValueError(f"scenes[{i}].bubbles: không có nhân vật '{cid}'")
        return self

    # -- convenience -------------------------------------------------------
    def character(self, char_id: str) -> Character | None:
        return next((c for c in self.characters if c.id == char_id), None)

    def char_index(self, char_id: str) -> int:
        return next((i for i, c in enumerate(self.characters) if c.id == char_id), 0)

    def default_layout(self, char_id: str) -> BubbleLayout:
        """Characters spread left → right near the top, tails pointing down at them."""
        n = len(self.characters)
        if n == 1:
            return BubbleLayout()
        spread = min(0.46, 0.7 / (n - 1))
        x = 0.5 + (self.char_index(char_id) - (n - 1) / 2) * spread
        return BubbleLayout(x=round(x, 3), y=0.2, tail="down")

    def layout(self, scene_idx: int, char_id: str) -> BubbleLayout:
        return self.scenes[scene_idx].bubbles.get(char_id) or self.default_layout(char_id)

    @property
    def turn_count(self) -> int:
        return sum(len(s.dialogue) for s in self.scenes)

    def display_text(self) -> str:
        """Every character the video draws (names and both languages) – for font coverage checks."""
        parts = [c.name for c in self.characters]
        parts += [text for s in self.scenes for t in s.dialogue for text in (t.en, t.vi)]
        return "\n".join(parts)

    def extras(self) -> dict[str, int]:
        """Sizes of the source sections this video does not render (vocabulary, exercises)."""
        src = self._source or {}
        return {k: len(src[k]) for k in ("vocabulary", "exercises") if isinstance(src.get(k), list) and src[k]}


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------
class StoryLoadError(ValueError):
    """Raised when a story cannot be parsed; ``errors`` holds readable messages."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _format(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()]


def _from_lesson(data: dict) -> Story:
    lesson = Lesson.model_validate(data)
    return Story(
        story_id=lesson.lesson_id,
        title_en=lesson.meta.title_en,
        title_vi=lesson.meta.title_vi,
        characters=lesson.characters,
        scenes=[Scene(
            title_vi=lesson.meta.title_vi,
            image=lesson.meta.scene_image,
            dialogue=[SceneTurn(speaker=d.speaker, en=d.en, vi=d.vi) for d in lesson.dialogue],
        )],
    )


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _from_scene_lesson(data: dict) -> Story:
    """Scene-based lesson file (``lesson_id`` + ``meta`` + ``scenes``) → :class:`Story`."""
    meta = _dict(data.get("meta"))
    normalized = {
        "story_id": data.get("lesson_id"),
        "title_en": meta.get("title_en") or meta.get("topic"),
        "title_vi": meta.get("title_vi"),
        "characters": [
            {"id": c.get("id"), "name": c.get("name"), "gender": c.get("gender"),
             "voice": c.get("voice_id") or c.get("voice")}
            if isinstance(c, dict) else c
            for c in _list(data.get("characters"))
        ],
        "scenes": [
            {
                "id": None if sc.get("scene_id") is None else str(sc["scene_id"]),
                "title_en": sc.get("title_en"),
                "title_vi": sc.get("title_vi"),
                "setting_en": sc.get("setting_en"),
                "image_prompt": sc.get("image_prompt"),
                "dialogue": [
                    {"speaker": t.get("speaker"), "en": t.get("en"), "vi": t.get("vi")} if isinstance(t, dict) else t
                    for t in _list(sc.get("dialogue"))
                ],
                "bubbles": _dict(sc.get("bubbles")),
            }
            if isinstance(sc, dict) else sc
            for sc in _list(data.get("scenes"))
        ],
    }
    story = Story.model_validate(normalized)
    story._source = data
    return story


def parse_story(data: str | bytes | dict) -> Story:
    """Parse a scene-based lesson file (``str``/``bytes``/``dict``) – see the module docstring."""
    if isinstance(data, (str, bytes)):
        try:
            raw = data.decode("utf-8-sig") if isinstance(data, bytes) else data
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoryLoadError([f"JSON không hợp lệ: {exc}"]) from exc
    if not isinstance(data, dict):
        raise StoryLoadError(["File JSON phải là một object {…}."])
    try:
        if "scenes" in data and "story_id" not in data:
            return _from_scene_lesson(data)
        if "scenes" not in data and "dialogue" in data and "meta" in data:
            return _from_lesson(data)
        return Story.model_validate(data)
    except ValidationError as exc:
        raise StoryLoadError(_format(exc)) from exc


def load_story_file(path: str) -> Story:
    with open(path, "rb") as fh:
        return parse_story(fh.read())


def list_sample_stories(directory: str = SCENE_SAMPLES_DIR) -> dict[str, str]:
    if not os.path.isdir(directory):
        return {}
    return {f: os.path.join(directory, f) for f in sorted(os.listdir(directory)) if f.lower().endswith(".json")}


def story_to_json(story: Story) -> str:
    """The story as JSON.  A scene-based lesson file is returned as uploaded, plus ``bubbles`` per scene."""
    if story._source is None:
        return story.model_dump_json(indent=2, exclude_none=True)
    doc = copy.deepcopy(story._source)
    for raw, scene in zip(doc["scenes"], story.scenes):
        if scene.bubbles:
            raw["bubbles"] = {cid: b.model_dump() for cid, b in scene.bubbles.items()}
    return json.dumps(doc, ensure_ascii=False, indent=2)
