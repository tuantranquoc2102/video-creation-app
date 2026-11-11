"""Load lessons from JSON (file path, bytes or str)."""

from __future__ import annotations

import json
import os

from pydantic import ValidationError

from config import SAMPLES_DIR
from core.lesson.schema import Lesson


class LessonLoadError(ValueError):
    """Raised when a lesson cannot be parsed; ``errors`` holds readable messages."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _format_pydantic(exc: ValidationError) -> list[str]:
    msgs = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        msgs.append(f"{loc}: {e['msg']}")
    return msgs


def parse_lesson(data: str | bytes | dict, base_dir: str | None = None) -> Lesson:
    """Parse lesson JSON (``str``/``bytes``) or an already-decoded ``dict``.

    *base_dir* is where relative image paths are resolved (the JSON's folder).
    """
    if isinstance(data, (str, bytes)):
        try:
            raw = data.decode("utf-8-sig") if isinstance(data, bytes) else data
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LessonLoadError([f"JSON không hợp lệ: {exc}"]) from exc
    if not isinstance(data, dict):
        raise LessonLoadError(["Lesson JSON phải là một object {…}."])
    try:
        return Lesson.model_validate(data).set_base_dir(base_dir)
    except ValidationError as exc:
        raise LessonLoadError(_format_pydantic(exc)) from exc


def load_lesson_file(path: str) -> Lesson:
    with open(path, "rb") as fh:
        return parse_lesson(fh.read(), base_dir=os.path.dirname(os.path.abspath(path)))


def list_sample_lessons(directory: str = SAMPLES_DIR) -> dict[str, str]:
    """``{file name: absolute path}`` of bundled sample lessons."""
    if not os.path.isdir(directory):
        return {}
    return {
        f: os.path.join(directory, f)
        for f in sorted(os.listdir(directory))
        if f.lower().endswith(".json")
    }


def lesson_to_json(lesson: Lesson) -> str:
    return lesson.model_dump_json(indent=2, exclude_none=True)
