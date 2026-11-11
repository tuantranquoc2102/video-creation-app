import copy

import pytest

from core.lesson import LessonLoadError, has_errors, parse_lesson, validate_lesson
from core.lesson.text import blank_to_speech, contains_term, find_term_spans, is_vietnamese


# ---------------------------------------------------------------- text helpers
@pytest.mark.parametrize(
    "text, term, expected",
    [
        ("but it costs a bit more", "cost", True),
        ("We stopped there", "stop", True),
        ("She is removing it", "remove", True),
        ("He carried it", "carry", True),
        ("Express is ninety", "express", True),
        ("expressway", "express", False),  # whole words only
        ("I picked them up", "pick up", False),  # discontinuous phrase not matched…
        ("I picked up them", "pick up", True),   # …but inflected head is
    ],
)
def test_contains_term(text, term, expected):
    assert contains_term(text, term) is expected


def test_irregular_forms_via_extra_forms():
    assert not contains_term("I paid already", "pay")
    assert contains_term("I paid already", "pay", ["paid"])


def test_find_term_spans_positions():
    text = "How much is it per kilo?"
    (start, end), = find_term_spans(text, "per")
    assert text[start:end] == "per"


def test_is_vietnamese_and_blank():
    assert is_vietnamese("Giặt nhanh") and not is_vietnamese("Express laundry")
    assert blank_to_speech("Remove this ____ please") == "Remove this blank please"


# ---------------------------------------------------------------- schema
def test_sample_lesson_is_valid(sample_lesson):
    issues = validate_lesson(sample_lesson)
    assert not has_errors(issues), issues
    assert len(sample_lesson.vocabulary) == 10


def test_ipa_slashes_are_stripped(sample_dict):
    d = copy.deepcopy(sample_dict)
    d["vocabulary"][0]["ipa"] = "/ɪkˈspres/"
    assert parse_lesson(d).vocabulary[0].ipa == "ɪkˈspres"


def test_invalid_json_and_unknown_fields_are_reported(sample_dict):
    with pytest.raises(LessonLoadError):
        parse_lesson("{not json")
    d = copy.deepcopy(sample_dict)
    d["meta"]["unexpected"] = 1
    with pytest.raises(LessonLoadError) as exc:
        parse_lesson(d)
    assert any("meta.unexpected" in e for e in exc.value.errors)


def test_vocab_example_falls_back_to_dialogue(sample_lesson):
    item = sample_lesson.vocabulary[0]
    en, vi = sample_lesson.vocab_example(item)
    assert en == sample_lesson.dialogue[item.dialogue_idx].en
    assert vi == sample_lesson.dialogue[item.dialogue_idx].vi


# ---------------------------------------------------------------- validators
def _issues(d):
    return validate_lesson(parse_lesson(d))


def _paths(issues, severity="error"):
    return [i.path for i in issues if i.severity == severity]


def test_wrong_vocab_count(sample_dict):
    d = copy.deepcopy(sample_dict)
    d["vocabulary"].pop()
    assert "vocabulary" in _paths(_issues(d))


def test_word_must_appear_in_referenced_turn(sample_dict):
    d = copy.deepcopy(sample_dict)
    d["vocabulary"][0]["dialogue_idx"] = 2  # 'express' is not in turn 2
    errs = [i for i in _issues(d) if i.severity == "error"]
    assert any(i.path == "vocabulary[0].dialogue_idx" and "lượt [0" in i.message for i in errs)


def test_duplicate_word_and_unknown_speaker(sample_dict):
    d = copy.deepcopy(sample_dict)
    d["vocabulary"][1]["word"] = "Express"
    d["vocabulary"][1]["dialogue_idx"] = 0
    d["dialogue"][3]["speaker"] = "Z"
    errs = _paths(_issues(d))
    assert "vocabulary[1].word" in errs and "dialogue[3].speaker" in errs


def test_exercise_rules(sample_dict):
    d = copy.deepcopy(sample_dict)
    d["exercises"][0]["answer"] = "không có"          # answer not in options
    d["exercises"][1]["prompt_en"] = "No blank here"   # fill_blank without ____
    d["exercises"][3]["prompt_vi"] = None              # translate without VI prompt
    errs = _paths(_issues(d))
    assert {"exercises[0].answer", "exercises[1].prompt_en", "exercises[3].prompt_vi"} <= set(errs)


def test_answer_leak_is_warned(sample_dict):
    d = copy.deepcopy(sample_dict)
    d["exercises"][2]["prompt_en"] = "Is the answer receipt?"
    assert "exercises[2].prompt_en" in _paths(_issues(d), "warning")


def test_long_sentence_warning_respects_level(sample_dict):
    d = copy.deepcopy(sample_dict)
    d["meta"]["level"] = "A1"
    assert any(p.startswith("dialogue[") for p in _paths(_issues(d), "warning"))
