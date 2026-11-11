"""Deterministic quality checks for a :class:`Lesson`.

Returns a list of :class:`Issue` instead of raising, so the UI / pipeline can
show every problem at once.  ``error`` blocks rendering; ``warning`` is
advisory and should be reviewed by a human.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from PIL import Image, UnidentifiedImageError

from config import SPEAKER_VOICES, SPEAKER_VOICES_VI
from core.lesson.schema import Lesson
from core.lesson.text import (
    BLANK_RE,
    contains_term,
    is_vietnamese,
    split_sentences,
    word_count,
)

Severity = Literal["error", "warning"]

# Recommended max words per sentence for each CEFR level (advisory).
MAX_WORDS_PER_SENTENCE = {"A1": 8, "A2": 12, "B1": 16, "B2": 20, "C1": 25, "C2": 30}
RECOMMENDED_TURNS = (8, 14)
HARD_TURN_LIMITS = (4, 24)
MAX_EXERCISES = 10

_KNOWN_VOICES = {v["voice_id"] for v in {**SPEAKER_VOICES, **SPEAKER_VOICES_VI}.values()}


@dataclass(frozen=True)
class Issue:
    severity: Severity
    path: str
    message: str


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


def validate_lesson(lesson: Lesson, *, expected_vocab: int = 10) -> list[Issue]:
    issues: list[Issue] = []

    def err(path: str, msg: str) -> None:
        issues.append(Issue("error", path, msg))

    def warn(path: str, msg: str) -> None:
        issues.append(Issue("warning", path, msg))

    # ── Characters ────────────────────────────────────────────────────────
    ids = [c.id for c in lesson.characters]
    if len(set(ids)) != len(ids):
        err("characters", "ID nhân vật bị trùng.")
    for i, c in enumerate(lesson.characters):
        if c.voice and c.voice not in _KNOWN_VOICES:
            warn(f"characters[{i}].voice", f"Giọng '{c.voice}' không có trong danh sách cấu hình – kiểm tra lại voice id.")
    voices = [c.voice for c in lesson.characters if c.voice]
    if len(voices) == 2 and voices[0] == voices[1]:
        warn("characters", "Hai nhân vật đang dùng cùng một giọng đọc.")

    # ── Dialogue ──────────────────────────────────────────────────────────
    n_turns = len(lesson.dialogue)
    if not HARD_TURN_LIMITS[0] <= n_turns <= HARD_TURN_LIMITS[1]:
        err("dialogue", f"Hội thoại có {n_turns} lượt; cho phép {HARD_TURN_LIMITS[0]}–{HARD_TURN_LIMITS[1]}.")
    elif not RECOMMENDED_TURNS[0] <= n_turns <= RECOMMENDED_TURNS[1]:
        warn("dialogue", f"Hội thoại có {n_turns} lượt; khuyến nghị {RECOMMENDED_TURNS[0]}–{RECOMMENDED_TURNS[1]}.")

    max_words = MAX_WORDS_PER_SENTENCE[lesson.meta.level]
    prev_speaker = None
    for i, turn in enumerate(lesson.dialogue):
        p = f"dialogue[{i}]"
        if turn.speaker not in ids:
            err(f"{p}.speaker", f"Speaker '{turn.speaker}' không thuộc danh sách nhân vật {ids}.")
        if turn.speaker == prev_speaker:
            warn(f"{p}.speaker", "Cùng một nhân vật nói 2 lượt liên tiếp.")
        prev_speaker = turn.speaker
        if not is_vietnamese(turn.vi):
            warn(f"{p}.vi", "Bản dịch không có dấu tiếng Việt – kiểm tra lại.")
        if is_vietnamese(turn.en):
            err(f"{p}.en", "Câu tiếng Anh chứa ký tự tiếng Việt.")
        for s in split_sentences(turn.en):
            if word_count(s) > max_words:
                warn(f"{p}.en", f"Câu dài {word_count(s)} từ (> {max_words} cho trình độ {lesson.meta.level}): “{s}”")

    # ── Vocabulary ────────────────────────────────────────────────────────
    n_vocab = len(lesson.vocabulary)
    if n_vocab != expected_vocab:
        err("vocabulary", f"Cần đúng {expected_vocab} từ vựng, hiện có {n_vocab}.")
    seen: set[str] = set()
    for i, v in enumerate(lesson.vocabulary):
        p = f"vocabulary[{i}]"
        key = v.word.casefold()
        if key in seen:
            err(f"{p}.word", f"Từ '{v.word}' bị trùng.")
        seen.add(key)
        if not v.ipa:
            err(f"{p}.ipa", "Thiếu phiên âm IPA.")
        if not is_vietnamese(v.meaning_vi):
            warn(f"{p}.meaning_vi", "Nghĩa tiếng Việt không có dấu – kiểm tra lại.")
        if v.dialogue_idx >= n_turns:
            err(f"{p}.dialogue_idx", f"dialogue_idx={v.dialogue_idx} vượt quá số lượt thoại ({n_turns}).")
        elif not contains_term(lesson.dialogue[v.dialogue_idx].en, v.word, v.forms):
            hint = ""
            elsewhere = [j for j, t in enumerate(lesson.dialogue) if contains_term(t.en, v.word, v.forms)]
            if elsewhere:
                hint = f" (có ở lượt {elsewhere})"
            err(f"{p}.dialogue_idx", f"Từ '{v.word}' không xuất hiện trong lượt thoại {v.dialogue_idx}{hint}. "
                                     "Nếu dùng dạng bất quy tắc, thêm vào 'forms'.")
        if v.example_en and not contains_term(v.example_en, v.word, v.forms):
            warn(f"{p}.example_en", f"Câu ví dụ không chứa từ '{v.word}'.")

    # ── Images ────────────────────────────────────────────────────────────
    for path_label, rel in lesson.asset_refs():
        if lesson.base_dir is None:
            err(path_label, f"Chưa có thư mục chứa ảnh '{rel}' – hãy upload ảnh kèm theo.")
            continue
        abs_path = lesson.asset_path(rel)
        if abs_path is None:
            err(path_label, f"Đường dẫn ảnh '{rel}' phải nằm trong thư mục bài học.")
        elif not os.path.isfile(abs_path):
            err(path_label, f"Không tìm thấy ảnh '{rel}'.")
        else:
            try:
                with Image.open(abs_path) as im:
                    im.verify()
            except (UnidentifiedImageError, OSError) as exc:
                err(path_label, f"File '{rel}' không phải ảnh hợp lệ: {exc}")

    # ── Exercises ─────────────────────────────────────────────────────────
    if not lesson.exercises:
        warn("exercises", "Bài học chưa có bài tập.")
    if len(lesson.exercises) > MAX_EXERCISES:
        warn("exercises", f"Có {len(lesson.exercises)} bài tập – video sẽ dài; khuyến nghị ≤ {MAX_EXERCISES}.")
    ex_ids: set[str] = set()
    for i, ex in enumerate(lesson.exercises):
        p = f"exercises[{i}]"
        if ex.id in ex_ids:
            err(f"{p}.id", f"ID bài tập '{ex.id}' bị trùng.")
        ex_ids.add(ex.id)
        if not (ex.prompt_en or ex.prompt_vi):
            err(p, "Bài tập cần prompt_en hoặc prompt_vi.")

        if ex.options:
            if not 2 <= len(ex.options) <= 4:
                err(f"{p}.options", "Cần 2–4 lựa chọn.")
            if len({o.casefold() for o in ex.options}) != len(ex.options):
                err(f"{p}.options", "Các lựa chọn bị trùng nhau.")
            if ex.answer not in ex.options:
                err(f"{p}.answer", f"Đáp án '{ex.answer}' không nằm trong options.")

        if ex.type == "multiple_choice" and not ex.options:
            err(f"{p}.options", "Bài trắc nghiệm cần options.")
        if ex.type == "fill_blank":
            if not ex.prompt_en or not BLANK_RE.search(ex.prompt_en):
                err(f"{p}.prompt_en", "Bài điền từ cần prompt_en có chỗ trống '____'.")
        if ex.type == "translate_vi_en" and not ex.prompt_vi:
            err(f"{p}.prompt_vi", "Bài dịch Việt→Anh cần prompt_vi.")
        if ex.type == "comprehension" and not ex.prompt_en:
            err(f"{p}.prompt_en", "Câu hỏi đọc hiểu cần prompt_en.")

        # The answer must not be visible in the question.
        for field_name in ("prompt_en", "prompt_vi"):
            prompt = getattr(ex, field_name) or ""
            if ex.type != "translate_vi_en" or field_name == "prompt_en":
                if ex.answer.casefold() in prompt.casefold():
                    warn(f"{p}.{field_name}", "Câu hỏi có thể đang lộ đáp án.")

        for ref in ex.vocab_refs:
            if ref.casefold() not in seen:
                warn(f"{p}.vocab_refs", f"'{ref}' không có trong danh sách từ vựng.")

    return issues
