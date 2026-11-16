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

Only ``lesson_id``, ``meta.title_en``, ``characters`` and ``scenes[].dialogue`` are required.
``vocabulary`` and ``exercises`` (optional) become the vocabulary / practice parts of the video, drawn
by the same builders as the lesson video; a vocabulary item points at its scene with ``scene_idx``
(the ``scene_id``) and its example is the line of that scene which uses the word.
Other fields (``visual_description``…) are ignored and kept untouched on export.
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
from core.lesson.schema import Character, DialogueTurn, Exercise, Lesson, LessonMeta, VocabItem
from core.lesson.text import find_term_spans

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
    # Optional lesson parts; ``VocabItem.dialogue_idx`` indexes the turns of all scenes in order.
    vocabulary: list[VocabItem] = Field(default_factory=list)
    exercises: list[Exercise] = Field(default_factory=list)
    topic: str | None = None
    level: str | None = None

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
        turns = sum(len(s.dialogue) for s in self.scenes)
        for i, item in enumerate(self.vocabulary):
            if item.dialogue_idx >= turns:
                raise ValueError(f"vocabulary[{i}].dialogue_idx: vượt quá số lượt thoại ({turns})")
        return self

    # -- convenience -------------------------------------------------------
    def character(self, char_id: str) -> Character | None:
        return next((c for c in self.characters if c.id == char_id), None)

    def char_index(self, char_id: str) -> int:
        return next((i for i, c in enumerate(self.characters) if c.id == char_id), 0)

    def default_layout(self, char_id: str) -> BubbleLayout:
        """Characters spread left → right near the top; tails lean towards each one's side."""
        n = len(self.characters)
        if n == 1:
            return BubbleLayout()
        spread = min(0.46, 0.7 / (n - 1))
        x = round(0.5 + (self.char_index(char_id) - (n - 1) / 2) * spread, 3)
        tail = "down-left" if x < 0.5 else "down-right" if x > 0.5 else "down"
        return BubbleLayout(x=x, y=0.2, tail=tail)

    def layout(self, scene_idx: int, char_id: str) -> BubbleLayout:
        return self.scenes[scene_idx].bubbles.get(char_id) or self.default_layout(char_id)

    @property
    def turn_count(self) -> int:
        return sum(len(s.dialogue) for s in self.scenes)

    def display_text(self) -> str:
        """Every character the video draws (names and both languages) – for font coverage checks."""
        parts = [c.name for c in self.characters]
        parts += [text for s in self.scenes for t in s.dialogue for text in (t.en, t.vi)]
        parts += [text for v in self.vocabulary
                  for text in (v.word, v.ipa, v.meaning_vi, v.example_en, v.example_vi)]
        parts += [text for e in self.exercises
                  for text in (e.prompt_en, e.prompt_vi, e.answer, e.explanation_vi, *e.options)]
        return "\n".join(p for p in parts if p)

    def flat_dialogue(self) -> list[SceneTurn]:
        return [t for s in self.scenes for t in s.dialogue]

    def to_lesson(self, scene_image: str | None = None) -> Lesson:
        """The story as a :class:`Lesson`, so the lesson video's vocabulary / exercise builders can draw it.

        Built without validation: every part is already validated here, and a story may have
        1–4 characters or no vocabulary, which the lesson schema does not allow.
        *scene_image* (optional) is blurred behind the cards, as in the lesson video.
        """
        meta = LessonMeta.model_construct(
            topic=self.topic or self.title_en, level=self.level or "A2", title_en=self.title_en,
            title_vi=self.title_vi or self.title_en, learning_goal_vi=None,
            scene_image=os.path.basename(scene_image) if scene_image else None, scene_focus_y=0.4,
        )
        lesson = Lesson.model_construct(
            lesson_id=self.story_id, schema_version=1, meta=meta, characters=list(self.characters),
            dialogue=[DialogueTurn(speaker=t.speaker, en=t.en, vi=t.vi) for t in self.flat_dialogue()],
            vocabulary=list(self.vocabulary), exercises=list(self.exercises),
        )
        return lesson.set_base_dir(os.path.dirname(os.path.abspath(scene_image)) if scene_image else None)

    def vocab_without_example(self) -> list[str]:
        """Words whose example line does not contain them (nothing gets highlighted on their card)."""
        turns = self.flat_dialogue()
        return [v.word for v in self.vocabulary
                if not find_term_spans(v.example_en or turns[v.dialogue_idx].en, v.word, v.forms)]


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
        vocabulary=[v.model_copy(update={"image": None}) for v in lesson.vocabulary],
        exercises=lesson.exercises,
        topic=lesson.meta.topic,
        level=lesson.meta.level,
    )


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_VOCAB_KEYS = ("word", "ipa", "pos", "meaning_vi", "forms", "example_en", "example_vi")


def _scene_position(scenes: list, ref) -> int | None:
    """Index of the scene a vocabulary ``scene_idx`` points at: its ``scene_id``, else its 1-based position."""
    for i, sc in enumerate(scenes):
        if isinstance(sc, dict) and sc.get("scene_id") is not None and str(sc["scene_id"]) == str(ref):
            return i
    if isinstance(ref, int) and not isinstance(ref, bool) and 1 <= ref <= len(scenes):
        return ref - 1
    return None


def _vocab_item(item, scenes: list):
    """Vocabulary entry of a scene-based file → :class:`VocabItem` input (``scene_idx`` → ``dialogue_idx``)."""
    if not isinstance(item, dict):
        return item
    out = {k: item[k] for k in _VOCAB_KEYS if item.get(k) is not None}
    if "dialogue_idx" in item:
        return {**out, "dialogue_idx": item["dialogue_idx"]}
    lines = [[t.get("en") if isinstance(t, dict) else None for t in _list(_dict(sc).get("dialogue"))] for sc in scenes]
    offsets = [sum(len(x) for x in lines[:i]) for i in range(len(lines))]

    def _uses(text) -> bool:
        return isinstance(text, str) and bool(find_term_spans(text, str(item.get("word") or ""), out.get("forms")))

    pos = _scene_position(scenes, item.get("scene_idx"))
    order = ([pos] if pos is not None else []) + [i for i in range(len(lines)) if i != pos]
    hit = next((offsets[i] + j for i in order for j, text in enumerate(lines[i]) if _uses(text)), None)
    if hit is None and pos is not None:
        hit = offsets[pos]          # word not found anywhere: fall back to the scene's first line
    return {**out, "dialogue_idx": hit if hit is not None else item.get("scene_idx")}


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
        "vocabulary": [_vocab_item(v, _list(data.get("scenes"))) for v in _list(data.get("vocabulary"))],
        "exercises": [
            {k: v for k, v in ex.items() if k in Exercise.model_fields} if isinstance(ex, dict) else ex
            for ex in _list(data.get("exercises"))
        ],
        "topic": meta.get("topic") if isinstance(meta.get("topic"), str) else None,
        "level": meta.get("level") if isinstance(meta.get("level"), str) else None,
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
