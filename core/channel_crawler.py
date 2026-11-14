"""Crawl the public video list of a channel (YouTube / TikTok / Facebook) via yt-dlp.

Only metadata is read – nothing is downloaded.  No Streamlit dependency.

Platform coverage (limits of yt-dlp, verified 2026-11):

* YouTube  – channel, tab (``/videos``, ``/shorts``, ``/streams``), playlist and single video.
* TikTok   – user profile (``/@name``) and single video.  Listing is best effort: TikTok
  sometimes refuses anonymous requests.
* Facebook – **single video / reel links only**.  Listing all videos of a page is not
  supported by yt-dlp; such links raise :class:`CrawlError` with an explanation.
"""

from __future__ import annotations

import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import urlparse

PLATFORM_YOUTUBE = "youtube"
PLATFORM_TIKTOK = "tiktok"
PLATFORM_FACEBOOK = "facebook"

_HOSTS = {
    PLATFORM_YOUTUBE: ("youtube.com", "youtu.be"),
    PLATFORM_TIKTOK: ("tiktok.com",),
    PLATFORM_FACEBOOK: ("facebook.com", "fb.watch", "fb.com"),
}

KIND_VIDEO = "video"
KIND_SHORT = "short"
KIND_LIVE = "live"
ALL_KINDS = (KIND_VIDEO, KIND_SHORT, KIND_LIVE)

_DETAIL_WORKERS = 4
_SOCKET_TIMEOUT = 30
_HASHTAG_RE = re.compile(r"#([\w]+)", re.UNICODE)

# progress_cb(done, total, message)
ProgressCb = Callable[[int, int, str], None]


class CrawlError(Exception):
    """A link could not be crawled; the message is user-facing (Vietnamese)."""


@dataclass
class VideoMeta:
    platform: str = ""
    channel: str = ""
    channel_url: str = ""
    video_id: str = ""
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    kind: str = KIND_VIDEO
    url: str = ""
    upload_date: str = ""          # YYYY-MM-DD
    duration_sec: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    language: str = ""
    thumbnail: str = ""
    source_url: str = ""           # the link the user entered
    error: str = ""                # set when detailed metadata could not be fetched

    @property
    def duration(self) -> str:
        if self.duration_sec is None:
            return ""
        h, rem = divmod(int(self.duration_sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def to_row(self) -> dict:
        row = asdict(self)
        row["tags"] = ", ".join(self.tags)
        row["categories"] = ", ".join(self.categories)
        row["duration"] = self.duration
        return row


CSV_COLUMNS: list[str] = [f.name for f in fields(VideoMeta)]
CSV_COLUMNS.insert(CSV_COLUMNS.index("duration_sec") + 1, "duration")


@dataclass
class CrawlResult:
    videos: list[VideoMeta] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (source url, message)


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------
def detect_platform(url: str) -> str | None:
    """Return the platform for *url*, or ``None`` when the host is not supported."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    for platform, domains in _HOSTS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    return None


def parse_urls(text: str) -> list[str]:
    """Split free text (one link per line / whitespace separated) into unique links."""
    seen: dict[str, None] = {}
    for token in re.split(r"[\s,;]+", text or ""):
        token = token.strip()
        if not token:
            continue
        if "://" not in token:
            token = "https://" + token
        seen.setdefault(token)
    return list(seen)


# ---------------------------------------------------------------------------
# yt-dlp access (single seam – tests monkeypatch ``_extract``)
# ---------------------------------------------------------------------------
class _SilentLogger:
    def debug(self, msg):  # noqa: D102
        pass

    warning = error = debug


def _extract(url: str, *, flat: bool, limit: int | None = None) -> dict | None:
    """Run yt-dlp metadata extraction.  ``flat`` lists a channel without visiting each video."""
    import yt_dlp

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignore_no_formats_error": True,
        "socket_timeout": _SOCKET_TIMEOUT,
        "logger": _SilentLogger(),
    }
    if flat:
        opts["extract_flat"] = "in_playlist"
        if limit:
            opts["playlistend"] = limit
    with yt_dlp.YoutubeDL(opts) as ydl:
        # Detail calls skip format processing: only metadata is needed.
        return ydl.extract_info(url, download=False, process=flat)


def _clean_error(exc: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    return re.sub(r"^ERROR:\s*", "", msg).strip()


def _friendly_error(platform: str, exc: Exception) -> str:
    msg = _clean_error(exc)
    if platform == PLATFORM_FACEBOOK and "Unsupported URL" in msg:
        return (
            "Facebook không cho phép liệt kê toàn bộ video của một trang/kênh "
            "(công cụ yt-dlp không hỗ trợ). Hãy dán link từng video/reel của Facebook, mỗi link một dòng."
        )
    if platform == PLATFORM_TIKTOK and "secondary user ID" in msg:
        return "TikTok từ chối yêu cầu ẩn danh cho kênh này. Hãy thử lại sau ít phút hoặc dán link từng video."
    return msg


# ---------------------------------------------------------------------------
# Mapping yt-dlp info → VideoMeta
# ---------------------------------------------------------------------------
def _int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _upload_date(info: dict) -> str:
    raw = info.get("upload_date")
    if raw and len(str(raw)) == 8:
        raw = str(raw)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    ts = info.get("timestamp") or info.get("release_timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            return ""
    return ""


def _thumbnail(info: dict) -> str:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = [t.get("url") for t in info.get("thumbnails") or [] if t.get("url")]
    return thumbs[-1] if thumbs else ""


def _kind(info: dict, url: str, parent_url: str) -> str:
    if "/shorts/" in url:
        return KIND_SHORT
    live = info.get("live_status")
    if live in ("is_live", "was_live", "is_upcoming", "post_live") or parent_url.rstrip("/").endswith("/streams"):
        return KIND_LIVE
    return KIND_VIDEO


def _to_meta(info: dict, *, platform: str, source_url: str, parent: dict | None = None) -> VideoMeta:
    parent = parent or {}
    url = info.get("webpage_url") or info.get("original_url") or info.get("url") or ""
    description = info.get("description") or ""
    tags = [str(t) for t in info.get("tags") or [] if t]
    if not tags:  # TikTok / Facebook: tags live in the caption as #hashtags
        tags = list(dict.fromkeys(_HASHTAG_RE.findall(f"{info.get('title') or ''} {description}")))
    return VideoMeta(
        platform=platform,
        channel=info.get("channel") or info.get("uploader") or parent.get("channel") or parent.get("uploader") or "",
        channel_url=info.get("channel_url") or info.get("uploader_url") or parent.get("channel_url") or "",
        video_id=str(info.get("id") or ""),
        title=info.get("title") or "",
        description=description,
        tags=tags,
        categories=[str(c) for c in info.get("categories") or [] if c],
        kind=_kind(info, url, parent.get("webpage_url") or ""),
        url=url,
        upload_date=_upload_date(info),
        duration_sec=_int(info.get("duration")),
        view_count=_int(info.get("view_count")),
        like_count=_int(info.get("like_count")),
        comment_count=_int(info.get("comment_count")),
        share_count=_int(info.get("repost_count")),
        language=info.get("language") or "",
        thumbnail=_thumbnail(info),
        source_url=source_url,
    )


def _flatten(info: dict, parent: dict | None = None) -> Iterable[tuple[dict, dict]]:
    """Yield ``(entry, parent_playlist)`` for every video below *info* (channel → tabs → videos)."""
    if info.get("_type") == "playlist" or "entries" in info:
        for entry in info.get("entries") or []:
            if entry:
                yield from _flatten(entry, info)
    else:
        yield info, parent or {}


def _needs_detail(info: dict) -> bool:
    """Flat YouTube entries lack description/tags/date; TikTok's flat entries are already complete."""
    return not (info.get("description") and (info.get("timestamp") or info.get("upload_date")))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def crawl_url(
    url: str,
    *,
    limit: int | None = None,
    kinds: Iterable[str] = ALL_KINDS,
    details: bool = True,
    progress_cb: ProgressCb | None = None,
) -> list[VideoMeta]:
    """Crawl one channel / playlist / video link.

    ``limit`` caps the number of videos per list (per tab for a YouTube channel);
    ``details`` visits each video that lacks description / tags / upload date.
    Raises :class:`CrawlError` when the link itself cannot be read; a failure on one
    video only sets ``VideoMeta.error`` for that row.
    """
    platform = detect_platform(url)
    if platform is None:
        raise CrawlError("Link không hợp lệ hoặc không thuộc YouTube / TikTok / Facebook.")
    kinds = set(kinds)

    if progress_cb:
        progress_cb(0, 0, "Đang lấy danh sách video...")
    try:
        info = _extract(url, flat=True, limit=limit)
    except Exception as exc:
        raise CrawlError(_friendly_error(platform, exc)) from exc
    if not info:
        raise CrawlError("Không đọc được dữ liệu từ link này.")

    videos: list[VideoMeta] = []
    pending: list[int] = []
    seen: set[str] = set()
    for entry, parent in _flatten(info):
        meta = _to_meta(entry, platform=platform, source_url=url, parent=parent)
        if not meta.video_id or meta.video_id in seen or meta.kind not in kinds:
            continue
        seen.add(meta.video_id)
        if details and meta.url and _needs_detail(entry):
            pending.append(len(videos))
        videos.append(meta)

    if pending:
        _fill_details(videos, pending, platform, url, progress_cb)
    return videos


def _fill_details(
    videos: list[VideoMeta], pending: list[int], platform: str, source_url: str, progress_cb: ProgressCb | None
) -> None:
    def _one(idx: int) -> tuple[int, VideoMeta]:
        flat = videos[idx]
        try:
            info = _extract(flat.url, flat=False)
            if not info:
                raise CrawlError("không có dữ liệu")
        except Exception as exc:
            flat.error = _clean_error(exc)
            return idx, flat
        full = _to_meta(info, platform=platform, source_url=source_url)
        # Keep what only the listing knows (tab → kind) and never lose a value.
        full.kind = flat.kind if flat.kind != KIND_VIDEO else full.kind
        for f in fields(VideoMeta):
            if getattr(full, f.name) in ("", None, []):
                setattr(full, f.name, getattr(flat, f.name))
        return idx, full

    total = len(pending)
    with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
        futures = [pool.submit(_one, idx) for idx in pending]
        for done, fut in enumerate(as_completed(futures), start=1):
            idx, meta = fut.result()
            videos[idx] = meta
            if progress_cb:
                progress_cb(done, total, f"Đang lấy metadata chi tiết... {done}/{total}")


def crawl(
    urls: Iterable[str],
    *,
    limit: int | None = None,
    kinds: Iterable[str] = ALL_KINDS,
    details: bool = True,
    progress_cb: ProgressCb | None = None,
) -> CrawlResult:
    """Crawl several links; a failing link is reported in ``errors`` and does not stop the others."""
    result = CrawlResult()
    seen: set[tuple[str, str]] = set()
    for url in urls:
        try:
            videos = crawl_url(url, limit=limit, kinds=kinds, details=details, progress_cb=progress_cb)
        except CrawlError as exc:
            result.errors.append((url, str(exc)))
            continue
        for v in videos:
            key = (v.platform, v.video_id)
            if key not in seen:
                seen.add(key)
                result.videos.append(v)
    return result


def videos_to_csv(videos: Iterable[VideoMeta]) -> bytes:
    """CSV bytes (UTF-8 with BOM so Excel shows Vietnamese correctly)."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for v in videos:
        writer.writerow(v.to_row())
    return buf.getvalue().encode("utf-8-sig")
