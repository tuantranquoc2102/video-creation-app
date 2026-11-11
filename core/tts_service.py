"""Text-to-Speech service.

Wraps gTTS and Edge TTS to produce audio files from text.
No Streamlit imports – purely I/O.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import time

from gtts import gTTS
from moviepy import AudioFileClip

log = logging.getLogger(__name__)


def synthesize(
    text: str,
    *,
    lang: str = "vi",
    tld: str = "com",
    slow: bool = False,
    output_dir: str | None = None,
) -> str:
    """Generate an mp3 file from *text* using gTTS and return its absolute path."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=".mp3", dir=output_dir)
        os.close(fd)
    else:
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)

    tts = gTTS(text=text, lang=lang, tld=tld, slow=slow)
    tts.save(path)
    return path


def synthesize_edge(
    text: str,
    *,
    voice_id: str = "en-US-AndrewNeural",
    output_dir: str | None = None,
    timeout: float = 25.0,
) -> str:
    """Generate an mp3 file from *text* using Edge TTS and return its path.

    *timeout* is a hard limit for the whole request (the free endpoint can
    stall); on any failure the temporary file is removed and the error raised.

    Parameters
    ----------
    text : str
        The text to speak.
    voice_id : str
        Edge TTS voice short name (e.g. ``"en-US-AndrewNeural"``).
    output_dir : str | None
        Directory for the mp3. Uses a temp dir when None.
    """
    import edge_tts

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=".mp3", dir=output_dir)
        os.close(fd)
    else:
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)

    async def _generate() -> None:
        comm = edge_tts.Communicate(text, voice_id, connect_timeout=10, receive_timeout=int(timeout))
        await asyncio.wait_for(comm.save(path), timeout=timeout)

    # Handle case where event loop is already running (e.g. in Streamlit)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _generate()).result()
        else:
            asyncio.run(_generate())
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path


def get_audio_duration(path: str) -> float:
    """Return the duration of an audio file in seconds."""
    with AudioFileClip(path) as clip:
        return clip.duration


# ---------------------------------------------------------------------------
# Cached synthesis (used by the lesson pipeline)
# ---------------------------------------------------------------------------
def tts_cache_key(text: str, voice_id: str, engine: str = "edge") -> str:
    """Stable hash of (engine, voice, text) – identical input ⇒ identical file."""
    raw = f"{engine}\x1f{voice_id}\x1f{text.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def synthesize_cached(
    text: str,
    voice_id: str,
    *,
    cache_dir: str,
    engine: str = "edge",
    retries: int = 4,
    backoff_sec: float = 1.5,
) -> str:
    """Return a cached mp3 for (*text*, *voice_id*), synthesising it if needed.

    * Re-rendering a lesson does not call the TTS service again.
    * Transient network errors are retried with exponential backoff.
    * The file is written to a temp name and atomically renamed, so a crash
      never leaves a truncated mp3 in the cache.
    """
    if not text or not text.strip():
        raise ValueError("Không thể tạo giọng đọc cho chuỗi rỗng.")

    os.makedirs(cache_dir, exist_ok=True)
    final_path = os.path.join(cache_dir, f"{tts_cache_key(text, voice_id, engine)}.mp3")
    if os.path.isfile(final_path) and os.path.getsize(final_path) > 0:
        return final_path

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            if engine == "edge":
                tmp = synthesize_edge(text, voice_id=voice_id, output_dir=cache_dir)
            else:  # gTTS – voice_id is interpreted as a language code
                tmp = synthesize(text, lang=voice_id, output_dir=cache_dir)
            if os.path.getsize(tmp) == 0:
                os.remove(tmp)
                raise RuntimeError("TTS trả về file rỗng")
            os.replace(tmp, final_path)
            return final_path
        except Exception as exc:  # network / service errors are not typed by edge-tts
            last_exc = exc
            log.warning("TTS lỗi (lần %d/%d) cho %r: %s", attempt + 1, retries, text[:40], exc)
            if attempt < retries - 1:
                time.sleep(backoff_sec * (2 ** attempt))
    raise RuntimeError(f"TTS thất bại sau {retries} lần thử: {last_exc}") from last_exc
