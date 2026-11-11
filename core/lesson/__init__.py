"""Lesson domain: schema, validation and import of bilingual lesson content."""

from core.lesson.importers import LessonLoadError, list_sample_lessons, load_lesson_file, parse_lesson
from core.lesson.schema import Character, DialogueTurn, Exercise, Lesson, LessonMeta, VocabItem
from core.lesson.validators import Issue, has_errors, validate_lesson

__all__ = [
    "Character",
    "DialogueTurn",
    "Exercise",
    "Issue",
    "Lesson",
    "LessonLoadError",
    "LessonMeta",
    "VocabItem",
    "has_errors",
    "list_sample_lessons",
    "load_lesson_file",
    "parse_lesson",
    "validate_lesson",
]
