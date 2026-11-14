"""Build a complete lesson video from a :class:`Lesson`.

Pipeline (all deterministic, no AI):

1. Build shots per segment (Pillow frames + TTS audio cues + subtitle cues).
2. Lay shots on a global timeline.
3. Mix every audio cue into a single WAV track (numpy) – avoids keeping
   dozens of ffmpeg readers open.
4. Save frames as PNG and stream them through one ``VideoClip`` whose frame
   function loads the current still lazily – memory stays flat regardless
   of video length.
5. Encode H.264/AAC MP4 + write SRT (EN, VI), thumbnail, lesson.json, manifest.json.
"""

from __future__ import annotations

import bisect
import json
import os
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import imageio_ffmpeg
import numpy as np
from moviepy import AudioFileClip, VideoClip
from PIL import Image

from config import LESSON_OUTPUT_DIR, TTS_CACHE_DIR
from core.lesson.importers import lesson_to_json
from core.lesson.schema import Lesson
from core.render.canvas import apply_logo as cv_apply_logo
from core.render.config import RenderConfig
from core.render.segments import (
    Ctx,
    build_dialogue,
    build_exercises,
    build_intro,
    build_outro,
    build_vocab,
    draw_dialogue,
    draw_exercise,
    draw_intro,
    draw_recap,
    draw_vocab,
)
from core.render.subtitles import TimedCue, write_srt
from core.render.timeline import Shot, TTSFn, make_tick_wav
from core.tts_service import synthesize_cached
from core.utils import is_within, resolve_output_path, safe_filename, slugify

ProgressFn = Callable[[str, int, int], None]  # (stage, done, total)

SAMPLE_RATE = 44100


@dataclass
class LessonRenderResult:
    video_path: str
    srt_en_path: str
    srt_vi_path: str
    thumbnail_path: str
    manifest_path: str
    lesson_dir: str
    duration: float
    segments: list[dict]
    tts_fallbacks: list[dict]
    speech: list[dict]          # [{start, end, voice, text}] – who says what, when


class EdgeTTSWithFallback:
    """Edge TTS (cached, retried); falls back to gTTS for a single line if Edge keeps failing.

    The free Edge endpoint is unofficial and intermittently returns
    ``NoAudioReceived``.  Rather than failing a whole render, the line is voiced
    by gTTS (different voice) and recorded in :attr:`fallbacks` so a reviewer
    can decide to re-render.  gTTS output is cached under its own key, so the
    next render tries Edge again first.
    """

    def __init__(self, cache_dir: str = TTS_CACHE_DIR, allow_fallback: bool = True):
        self.cache_dir = cache_dir
        self.allow_fallback = allow_fallback
        self.fallbacks: list[dict] = []

    def __call__(self, text: str, voice: str) -> str:
        try:
            return synthesize_cached(text, voice, cache_dir=self.cache_dir)
        except RuntimeError:
            if not self.allow_fallback:
                raise
            lang = voice.split("-")[0] if "-" in voice else "en"
            path = synthesize_cached(text, lang, cache_dir=self.cache_dir, engine="gtts")
            self.fallbacks.append({"text": text, "voice": voice, "fallback": f"gtts:{lang}"})
            return path


def default_tts(cache_dir: str = TTS_CACHE_DIR) -> TTSFn:
    return EdgeTTSWithFallback(cache_dir)


# ---------------------------------------------------------------------------
# TTS prefetch
# ---------------------------------------------------------------------------
def collect_speech(lesson: Lesson, cfg: RenderConfig) -> list[tuple[str, str]]:
    """Every unique (text, voice) the render will request, in order (dry run, no network)."""
    needed: list[tuple[str, str]] = []
    silent = os.path.join(tempfile.mkdtemp(prefix="dry_"), "silence.wav")
    with wave.open(silent, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)

    def _record(text: str, voice: str) -> str:
        needed.append((text, voice))
        return silent

    ctx = Ctx(lesson, cfg)
    for build in (build_intro, build_dialogue, build_vocab, build_outro):
        build(ctx, _record)
    build_exercises(ctx, _record, None)
    shutil.rmtree(os.path.dirname(silent), ignore_errors=True)
    return list(dict.fromkeys(needed))


def prefetch_tts(items: list[tuple[str, str]], tts: TTSFn, progress_cb: ProgressFn | None = None,
                 workers: int = 4) -> None:
    """Synthesize all lines concurrently so the frame pass only hits the cache."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not items:
        return
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(tts, text, voice) for text, voice in items]
        for fut in as_completed(futures):
            fut.result()  # re-raise if even the fallback failed
            done += 1
            if progress_cb:
                progress_cb("tts", done, len(items))


# ---------------------------------------------------------------------------
# Shots
# ---------------------------------------------------------------------------
def build_shots(lesson: Lesson, cfg: RenderConfig, tts: TTSFn, tick_path: str | None,
                progress_cb: ProgressFn | None = None) -> list[Shot]:
    ctx = Ctx(lesson, cfg)
    builders = [
        ("intro", lambda: build_intro(ctx, tts)),
        ("dialogue", lambda: build_dialogue(ctx, tts)),
        ("vocabulary", lambda: build_vocab(ctx, tts)),
        ("exercises", lambda: build_exercises(ctx, tts, tick_path)),
        ("recap", lambda: build_outro(ctx, tts)),
    ]
    shots: list[Shot] = []
    for i, (_name, build) in enumerate(builders):
        shots.extend(build())
        if progress_cb:
            progress_cb("frames", i + 1, len(builders))
    return shots


def render_preview_frames(lesson: Lesson, cfg: RenderConfig) -> dict[str, Image.Image]:
    """Representative still frames (no TTS / no encoding) for UI previews."""
    ctx = Ctx(lesson, cfg)
    frames = {"Intro": draw_intro(ctx)}
    if lesson.dialogue:
        frames["Hội thoại"] = draw_dialogue(ctx, min(2, len(lesson.dialogue) - 1))
    if lesson.vocabulary:
        frames["Từ vựng"] = draw_vocab(ctx, 0)
    if lesson.exercises:
        frames["Bài tập – câu hỏi"] = draw_exercise(ctx, 0, "countdown", lesson.exercises[0].think_seconds)
        frames["Bài tập – đáp án"] = draw_exercise(ctx, 0, "answer")
    frames["Ôn tập"] = draw_recap(ctx)
    return {k: cv_apply_logo(v, cfg).convert("RGB") for k, v in frames.items()}


# ---------------------------------------------------------------------------
# Audio mix
# ---------------------------------------------------------------------------
def _load_audio(path: str) -> np.ndarray:
    """Decode *path* to float32 stereo at SAMPLE_RATE using the bundled ffmpeg.

    (MoviePy's ``to_soundarray`` fails on very short clips such as the tick.)
    """
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", path,
        "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "2", "-ar", str(SAMPLE_RATE), "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Không giải mã được audio {path}: {proc.stderr.decode(errors='ignore')[:300]}")
    pcm = np.frombuffer(proc.stdout, dtype=np.int16).reshape(-1, 2)
    return pcm.astype(np.float32) / 32768.0


def mix_audio(placed: list[tuple[str, float]], total: float, out_path: str) -> str:
    """Mix ``(path, start_sec)`` cues into one 16-bit stereo WAV."""
    buf = np.zeros((int(np.ceil(total * SAMPLE_RATE)) + 1, 2), dtype=np.float32)
    cache: dict[str, np.ndarray] = {}
    for path, start in placed:
        if path not in cache:
            cache[path] = _load_audio(path)
        data = cache[path]
        i0 = int(start * SAMPLE_RATE)
        i1 = min(len(buf), i0 + len(data))
        if i1 > i0:
            buf[i0:i1] += data[: i1 - i0]
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0.99:  # avoid clipping when cues overlap
        buf *= 0.99 / peak
    pcm = (buf * 32767).astype(np.int16)
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return out_path


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------
class _FrameSource:
    """Frame function for MoviePy: returns the still covering time *t*."""

    def __init__(self, paths: list[str], starts: list[float]):
        self.paths = paths
        self.starts = starts
        self._idx = -1
        self._frame: np.ndarray | None = None

    def __call__(self, t: float) -> np.ndarray:
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        if i != self._idx:
            with Image.open(self.paths[i]) as im:
                self._frame = np.asarray(im.convert("RGB"))
            self._idx = i
        return self._frame  # type: ignore[return-value]


def _make_logger(progress_cb: ProgressFn | None):
    if progress_cb is None:
        return None
    from proglog import ProgressBarLogger

    class _Logger(ProgressBarLogger):
        def bars_callback(self, bar, attr, value, old_value=None):
            if bar == "frame_index" and attr == "index":
                total = self.bars[bar].get("total") or 1
                if value % 30 == 0 or value >= total - 1:
                    progress_cb("encode", int(value) + 1, int(total))

    return _Logger()


@dataclass
class EncodedTimeline:
    duration: float
    segments: list[dict]
    speech: list[dict]
    cues_en: list[TimedCue]
    cues_vi: list[TimedCue]
    shots: int


def encode_shots(shots: list[Shot], cfg: RenderConfig, video_path: str, work: str,
                 progress_cb: ProgressFn | None = None) -> EncodedTimeline:
    """Lay *shots* on one timeline, mix their audio and encode H.264/AAC to *video_path*.

    *work* is a scratch directory (frames + audio mix) owned by the caller.
    """
    # ── Global timeline ────────────────────────────────────────────
    starts: list[float] = []
    placed_audio: list[tuple[str, float]] = []
    cues_en: list[TimedCue] = []
    cues_vi: list[TimedCue] = []
    segments: list[dict] = []
    speech: list[dict] = []
    t = 0.0
    for shot in shots:
        starts.append(t)
        placed_audio.extend((a.path, t + a.start) for a in shot.audio)
        speech.extend(
            {"start": round(t + a.start, 2), "end": round(t + a.start + a.duration, 2),
             "segment": shot.segment, "voice": a.voice, "text": a.text}
            for a in shot.audio if a.text
        )
        for s in shot.subs:
            cues_en.append(TimedCue(t + s.start, t + s.end, s.en))
            cues_vi.append(TimedCue(t + s.start, t + s.end, s.vi))
        if segments and segments[-1]["name"] == shot.segment:
            segments[-1]["end"] = round(t + shot.duration, 3)
        else:
            segments.append({"name": shot.segment, "start": round(t, 3), "end": round(t + shot.duration, 3)})
        t += shot.duration
    total = t

    # ── Frames → PNG (memory stays flat) ───────────────────────────
    frame_paths = []
    for i, shot in enumerate(shots):
        p = os.path.join(work, f"frame_{i:04d}.png")
        cv_apply_logo(shot.image, cfg).convert("RGB").save(p, compress_level=1)
        frame_paths.append(p)

    # ── Audio mix ──────────────────────────────────────────────────
    if progress_cb:
        progress_cb("audio", 0, 1)
    mix_path = mix_audio(placed_audio, total, os.path.join(work, "mix.wav"))
    if progress_cb:
        progress_cb("audio", 1, 1)

    # ── Encode ─────────────────────────────────────────────────────
    audio = AudioFileClip(mix_path)
    clip = VideoClip(_FrameSource(frame_paths, starts), duration=total).with_fps(cfg.fps).with_audio(audio)
    try:
        clip.write_videofile(
            video_path,
            fps=cfg.fps,
            codec="libx264",
            audio_codec="aac",
            preset=cfg.preset,
            threads=os.cpu_count() or 2,
            pixel_format="yuv420p",          # widest player compatibility
            ffmpeg_params=["-movflags", "+faststart"],  # progressive playback
            logger=_make_logger(progress_cb),
        )
    finally:
        clip.close()
        audio.close()
    return EncodedTimeline(total, segments, speech, cues_en, cues_vi, len(frame_paths))


def _copy_assets(lesson: Lesson, lesson_dir: str) -> None:
    """Copy referenced images next to the exported lesson.json (same relative paths)."""
    for _, rel in lesson.asset_refs():
        src = lesson.asset_path(rel)
        dst = os.path.normpath(os.path.join(lesson_dir, rel))
        if src and os.path.isfile(src) and is_within(dst, lesson_dir) and os.path.abspath(src) != dst:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def render_lesson_video(
    lesson: Lesson,
    cfg: RenderConfig | None = None,
    *,
    video_name: str | None = None,
    output_root: str = LESSON_OUTPUT_DIR,
    tts: TTSFn | None = None,
    progress_cb: ProgressFn | None = None,
) -> LessonRenderResult:
    cfg = cfg or RenderConfig()
    tts = tts or default_tts()
    started = time.monotonic()

    lesson_dir = os.path.join(output_root, slugify(lesson.lesson_id, default="lesson"))
    os.makedirs(lesson_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="lesson_")
    try:
        tick = make_tick_wav(os.path.join(work, "tick.wav")) if cfg.tick_sound else None
        prefetch_tts(collect_speech(lesson, cfg), tts, progress_cb)
        shots = build_shots(lesson, cfg, tts, tick, progress_cb)
        if not shots:
            raise ValueError("Bài học không có nội dung để dựng video.")

        thumb_path = os.path.join(lesson_dir, "thumbnail.png")
        shots[0].image.convert("RGB").save(thumb_path)
        base_name = safe_filename(video_name or lesson.meta.title_en, default=lesson.lesson_id)
        video_path = resolve_output_path(base_name, "mp4", lesson_dir, overwrite=True)
        tl = encode_shots(shots, cfg, video_path, work, progress_cb)
        del shots
        total, segments, speech, cues_en, cues_vi = tl.duration, tl.segments, tl.speech, tl.cues_en, tl.cues_vi

        # ── Side artefacts ─────────────────────────────────────────────
        srt_en = write_srt(cues_en, os.path.join(lesson_dir, "subtitles.en.srt"))
        srt_vi = write_srt(cues_vi, os.path.join(lesson_dir, "subtitles.vi.srt"))
        with open(os.path.join(lesson_dir, "lesson.json"), "w", encoding="utf-8") as fh:
            fh.write(lesson_to_json(lesson))
        _copy_assets(lesson, lesson_dir)
        manifest = {
            "lesson_id": lesson.lesson_id,
            "title_en": lesson.meta.title_en,
            "title_vi": lesson.meta.title_vi,
            "rendered_at": datetime.now().isoformat(timespec="seconds"),
            "render_seconds": round(time.monotonic() - started, 1),
            "duration": round(total, 3),
            "video": os.path.basename(video_path),
            "subtitles": {"en": os.path.basename(srt_en), "vi": os.path.basename(srt_vi)},
            "thumbnail": os.path.basename(thumb_path),
            "segments": segments,
            "shots": tl.shots,
            "tts_fallbacks": getattr(tts, "fallbacks", []),
            "speech": speech,
            "render_config": cfg.to_dict(),
        }
        manifest_path = os.path.join(lesson_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)

        return LessonRenderResult(
            video_path=video_path,
            srt_en_path=srt_en,
            srt_vi_path=srt_vi,
            thumbnail_path=thumb_path,
            manifest_path=manifest_path,
            lesson_dir=lesson_dir,
            duration=total,
            segments=segments,
            tts_fallbacks=list(getattr(tts, "fallbacks", [])),
            speech=speech,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
