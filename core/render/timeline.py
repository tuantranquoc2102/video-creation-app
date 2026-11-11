"""Timeline primitives: shots (still frame + duration), audio cues, subtitle cues."""

from __future__ import annotations

import os
import wave
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from PIL import Image

from core.lesson.text import split_by_language
from core.tts_service import get_audio_duration

# (text, voice_id) -> path of an audio file
TTSFn = Callable[[str, str], str]


@dataclass
class AudioCue:
    path: str
    start: float          # seconds, relative to the shot start
    duration: float
    text: str = ""        # what is spoken (for the speech plan / review)
    voice: str = ""


@dataclass
class SubCue:
    start: float          # seconds, relative to the shot start
    end: float
    en: str = ""
    vi: str = ""


@dataclass
class Shot:
    image: Image.Image
    duration: float
    segment: str
    audio: list[AudioCue] = field(default_factory=list)
    subs: list[SubCue] = field(default_factory=list)


class AudioSequencer:
    """Lays out spoken lines one after another inside a single shot."""

    def __init__(self, tts: TTSFn, gap: float):
        self.tts = tts
        self.gap = gap
        self.t = 0.0
        self.cues: list[AudioCue] = []

    def say(self, text: str, voice: str, gap: float | None = None) -> tuple[float, float]:
        """Queue *text* with exactly *voice*; return its (start, end) relative to the shot."""
        text = (text or "").strip()
        if not text:
            return self.t, self.t
        path = self.tts(text, voice)
        dur = get_audio_duration(path)
        start = self.t
        self.cues.append(AudioCue(path=path, start=start, duration=dur, text=text, voice=voice))
        self.t = start + dur + (self.gap if gap is None else gap)
        return start, start + dur

    def speak(
        self,
        text: str,
        en_voice: str,
        vi_voice: str,
        gap: float | None = None,
        chunk_gap: float = 0.15,
    ) -> tuple[float, float]:
        """Queue mixed-language *text*: English chunks use *en_voice*, Vietnamese *vi_voice*."""
        chunks = split_by_language(text)
        if not chunks:
            return self.t, self.t
        start = self.t
        end = start
        for i, (lang, chunk) in enumerate(chunks):
            last = i == len(chunks) - 1
            _, end = self.say(chunk, vi_voice if lang == "vi" else en_voice, gap=gap if last else chunk_gap)
        return start, end

    def pause(self, seconds: float) -> None:
        self.t += seconds

    @property
    def duration(self) -> float:
        return self.t


def make_tick_wav(path: str, freq: float = 1200.0, length: float = 0.07, sr: int = 44100) -> str:
    """Write a short, soft click (used for the exercise countdown)."""
    if os.path.isfile(path):
        return path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    t = np.linspace(0, length, int(sr * length), endpoint=False)
    env = np.exp(-t * 60)
    samples = (0.35 * np.sin(2 * np.pi * freq * t) * env * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.tobytes())
    return path
