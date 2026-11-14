"""Join several video files into one, optionally stamping a logo at the bottom centre.

Uses the ffmpeg binary bundled with ``imageio-ffmpeg`` in a single pass:

* every input is scaled to fit the target frame (letterboxed, aspect kept),
  normalised to the same fps / pixel format / SAR, so clips of different
  sizes or frame rates can be concatenated safely;
* inputs without an audio track get matching silence so ``concat`` stays in sync;
* the optional logo is overlaid on the concatenated stream (bottom centre).

No Streamlit imports.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Callable

import imageio_ffmpeg
from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos
from PIL import Image

from core.utils import codecs_for

AUDIO_RATE = 44100
SUPPORTED_VIDEO_FILES = ["mp4", "mov", "m4v", "avi", "webm", "mkv"]

ProgressFn = Callable[[float], None]  # fraction 0.0 … 1.0


@dataclass(frozen=True)
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


@dataclass(frozen=True)
class LogoOptions:
    path: str
    scale: float = 0.15          # logo width as a fraction of the frame's short side
    opacity: float = 1.0         # 0 = invisible … 1 = opaque
    bottom_margin: float = 0.04  # gap to the bottom edge, fraction of frame height


def _even(n: float) -> int:
    """libx264 + yuv420p need even dimensions."""
    return max(2, int(round(n / 2.0)) * 2)


def probe(path: str) -> VideoInfo:
    """Read size / fps / duration / audio presence of *path*."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Không tìm thấy file video: {path}")
    try:
        info = ffmpeg_parse_infos(path)
    except Exception as exc:  # moviepy raises IOError/KeyError on unreadable files
        raise ValueError(f"Không đọc được video {os.path.basename(path)!r}: {exc}") from exc
    size = info.get("video_size")
    if not info.get("video_found", bool(size)) or not size:
        raise ValueError(f"File {os.path.basename(path)!r} không có luồng video.")
    w, h = size
    # Phone recordings store portrait video as landscape + rotation metadata;
    # ffmpeg auto-rotates on decode, so report the displayed size.
    if int(info.get("video_rotation", 0) or 0) % 180 == 90:
        w, h = h, w
    return VideoInfo(
        path=path,
        width=int(w),
        height=int(h),
        fps=float(info.get("video_fps") or 30.0),
        duration=float(info.get("duration") or 0.0),
        has_audio=bool(info.get("audio_found")),
    )


def logo_geometry(frame_size: tuple[int, int], logo_size: tuple[int, int], opts: LogoOptions) -> tuple[int, int, int, int]:
    """Return ``(x, y, w, h)`` of the logo on a frame of *frame_size* (bottom centre)."""
    fw, fh = frame_size
    lw0, lh0 = logo_size
    lw = _even(max(16, min(fw, fh) * max(0.01, opts.scale)))
    lh = _even(lw * lh0 / max(1, lw0))
    x = (fw - lw) // 2
    y = max(0, fh - lh - int(fh * max(0.0, opts.bottom_margin)))
    return x, y, lw, lh


def build_ffmpeg_command(
    infos: list[VideoInfo],
    output_path: str,
    *,
    size: tuple[int, int],
    fps: float,
    fmt: str = "mp4",
    logo: LogoOptions | None = None,
    logo_size: tuple[int, int] | None = None,
) -> list[str]:
    """Assemble the single-pass ffmpeg command (exposed for testing)."""
    w, h = _even(size[0]), _even(size[1])
    vcodec, acodec = codecs_for(fmt)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-v", "error", "-nostdin"]
    for info in infos:
        cmd += ["-i", info.path]
    if logo:
        cmd += ["-i", logo.path]

    parts: list[str] = []
    pairs = ""
    for i, info in enumerate(infos):
        parts.append(
            f"[{i}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
            f"fps={fps:g},format=yuv420p[v{i}]"
        )
        if info.has_audio:
            parts.append(
                f"[{i}:a:0]aresample={AUDIO_RATE},"
                f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=stereo[a{i}]"
            )
        else:
            parts.append(
                f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=duration={info.duration:.3f},"
                f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=stereo[a{i}]"
            )
        pairs += f"[v{i}][a{i}]"
    parts.append(f"{pairs}concat=n={len(infos)}:v=1:a=1[vcat][aout]")

    if logo:
        x, y, lw, lh = logo_geometry((w, h), logo_size or (1, 1), logo)
        alpha = max(0.0, min(1.0, logo.opacity))
        parts.append(
            f"[{len(infos)}:v]scale={lw}:{lh},format=rgba,colorchannelmixer=aa={alpha:.3f}[logo]"
        )
        parts.append(f"[vcat][logo]overlay={x}:{y}:format=auto,format=yuv420p[vout]")
        vlabel = "[vout]"
    else:
        vlabel = "[vcat]"

    cmd += ["-filter_complex", ";".join(parts), "-map", vlabel, "-map", "[aout]"]
    cmd += ["-c:v", vcodec, "-c:a", acodec, "-r", f"{fps:g}"]
    if vcodec == "libx264":
        cmd += ["-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
    elif vcodec == "libvpx":
        cmd += ["-b:v", "4M", "-deadline", "good", "-cpu-used", "4"]
    else:
        cmd += ["-q:v", "3"]
    if fmt.lower() in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    cmd += ["-progress", "pipe:1", output_path]
    return cmd


_OUT_TIME = re.compile(r"^out_time_(?:us|ms)=(\d+)")


def join_videos(
    paths: list[str],
    output_path: str,
    *,
    size: tuple[int, int] | None = None,
    fps: float | None = None,
    fmt: str = "mp4",
    logo: LogoOptions | None = None,
    progress_cb: ProgressFn | None = None,
) -> str:
    """Concatenate *paths* (in order) into *output_path* and return it.

    *size* / *fps* default to those of the first video.
    """
    if len(paths) < 1:
        raise ValueError("Cần ít nhất 1 video để ghép.")
    infos = [probe(p) for p in paths]
    first = infos[0]
    size = size or (first.width, first.height)
    fps = fps or first.fps
    logo_size = None
    if logo:
        if not os.path.isfile(logo.path):
            raise FileNotFoundError(f"Không tìm thấy file logo: {logo.path}")
        with Image.open(logo.path) as im:
            logo_size = im.size

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cmd = build_ffmpeg_command(infos, output_path, size=size, fps=fps, fmt=fmt, logo=logo, logo_size=logo_size)
    total = sum(i.duration for i in infos) or 1.0

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        m = _OUT_TIME.match(line.strip())
        if m and progress_cb:
            # ffmpeg reports out_time_ms in microseconds too (historical quirk).
            progress_cb(min(1.0, int(m.group(1)) / 1_000_000 / total))
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError(f"ffmpeg lỗi khi ghép video: {stderr.strip()[-800:]}")
    if progress_cb:
        progress_cb(1.0)
    return output_path


def extract_frame(path: str, t: float = 0.5) -> Image.Image:
    """Grab one RGB frame of *path* at *t* seconds (for previews)."""
    info = probe(path)
    t = max(0.0, min(t, max(0.0, info.duration - 0.05)))
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", path,
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    expected = info.width * info.height * 3
    if proc.returncode != 0 or len(proc.stdout) < expected:
        raise ValueError(f"Không trích được khung hình từ {os.path.basename(path)!r}")
    return Image.frombytes("RGB", (info.width, info.height), proc.stdout[:expected])


def preview_with_logo(frame: Image.Image, size: tuple[int, int], logo: LogoOptions | None) -> Image.Image:
    """Mimic the ffmpeg pipeline on one frame: letterbox to *size*, then overlay the logo."""
    w, h = _even(size[0]), _even(size[1])
    ratio = min(w / frame.width, h / frame.height)
    fitted = frame.resize((max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    canvas.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    if logo and os.path.isfile(logo.path):
        with Image.open(logo.path) as src:
            layer = src.convert("RGBA")
        x, y, lw, lh = logo_geometry((w, h), layer.size, logo)
        layer = layer.resize((lw, lh), Image.Resampling.LANCZOS)
        alpha = max(0.0, min(1.0, logo.opacity))
        layer.putalpha(layer.getchannel("A").point(lambda a: int(a * alpha)))
        canvas.alpha_composite(layer, dest=(x, y))
    return canvas.convert("RGB")
