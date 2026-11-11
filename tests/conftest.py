"""Shared fixtures – tests run offline (fake TTS) and never touch real data/."""

from __future__ import annotations

import hashlib
import os
import sys
import wave

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SAMPLE_LESSON = os.path.join(ROOT, "samples", "lessons", "laundry-a2.json")


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    import config

    path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    return path


@pytest.fixture
def fake_tts(tmp_path):
    """TTS stand-in: writes a silent mono WAV whose length depends on the text."""
    out_dir = tmp_path / "tts"
    out_dir.mkdir()
    calls: list[tuple[str, str]] = []

    def _tts(text: str, voice: str) -> str:
        calls.append((text, voice))
        key = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()[:16]
        path = out_dir / f"{key}.wav"
        if not path.exists():
            sr = 16000
            n = int(sr * (0.2 + 0.01 * len(text)))
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(b"\x00\x00" * n)
        return str(path)

    _tts.calls = calls  # type: ignore[attr-defined]
    return _tts


@pytest.fixture
def sample_lesson():
    from core.lesson import load_lesson_file

    return load_lesson_file(SAMPLE_LESSON)


@pytest.fixture
def sample_dict():
    import json

    with open(SAMPLE_LESSON, encoding="utf-8") as fh:
        return json.load(fh)
