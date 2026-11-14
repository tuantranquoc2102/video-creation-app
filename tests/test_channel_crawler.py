"""Channel crawler – offline: yt-dlp is replaced by a fake ``_extract``."""

from __future__ import annotations

import csv
import io

import pytest

from core import channel_crawler as cc


def _yt_channel():
    return {
        "_type": "playlist",
        "id": "@demo",
        "webpage_url": "https://www.youtube.com/@demo",
        "entries": [
            {
                "_type": "playlist",
                "channel": "Demo",
                "channel_url": "https://www.youtube.com/channel/UC1",
                "webpage_url": "https://www.youtube.com/@demo/videos",
                "entries": [
                    {"_type": "url", "id": "a1", "title": "First", "url": "https://www.youtube.com/watch?v=a1",
                     "duration": 3725, "view_count": 10, "thumbnails": [{"url": "s.jpg"}, {"url": "l.jpg"}]},
                    {"_type": "url", "id": "a2", "title": "Second", "url": "https://www.youtube.com/watch?v=a2"},
                    None,
                ],
            },
            {
                "_type": "playlist",
                "channel": "Demo",
                "webpage_url": "https://www.youtube.com/@demo/shorts",
                "entries": [{"_type": "url", "id": "s1", "title": "Short", "url": "https://www.youtube.com/shorts/s1"}],
            },
            {
                "_type": "playlist",
                "channel": "Demo",
                "webpage_url": "https://www.youtube.com/@demo/streams",
                "entries": [{"_type": "url", "id": "l1", "title": "Live", "url": "https://www.youtube.com/watch?v=l1"}],
            },
        ],
    }


@pytest.fixture
def fake_extract(monkeypatch):
    calls: list[tuple[str, bool, int | None]] = []

    def _fake(url, *, flat, limit=None):
        calls.append((url, flat, limit))
        if flat:
            if "tiktok" in url:
                return {"_type": "playlist", "entries": [
                    {"_type": "url", "id": "t1", "title": "Hi #fun", "description": "Hi #fun #Việt",
                     "url": "https://www.tiktok.com/@u/video/t1", "timestamp": 1700000000, "channel": "u",
                     "view_count": 5, "repost_count": 2},
                ]}
            if "facebook" in url:
                raise RuntimeError("ERROR: Unsupported URL: " + url)
            return _yt_channel()
        if url.endswith("a2"):
            raise RuntimeError("\x1b[0;31mERROR:\x1b[0m Private video")
        vid = url.rsplit("=", 1)[-1].rsplit("/", 1)[-1]
        return {"id": vid, "title": f"Full {vid}", "description": "Line 1\nLine 2, \"quoted\"",
                "tags": ["english", "học"], "categories": ["Education"], "upload_date": "20260102",
                "webpage_url": url, "channel": "Demo", "like_count": 7, "comment_count": 3, "duration": 61}

    monkeypatch.setattr(cc, "_extract", _fake)
    _fake.calls = calls
    return _fake


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/@demo", "youtube"),
        ("https://youtu.be/abc", "youtube"),
        ("https://m.tiktok.com/@u", "tiktok"),
        ("https://www.facebook.com/watch/?v=1", "facebook"),
        ("https://fb.watch/x/", "facebook"),
        ("https://notyoutube.com/@demo", None),
        ("https://youtube.com.evil.io/x", None),
        ("file:///etc/passwd", None),
        ("http://localhost:8501", None),
        ("", None),
    ],
)
def test_detect_platform(url, expected):
    assert cc.detect_platform(url) == expected


def test_parse_urls_dedupes_and_adds_scheme():
    text = "youtube.com/@a\n\n https://www.tiktok.com/@b , youtube.com/@a"
    assert cc.parse_urls(text) == ["https://youtube.com/@a", "https://www.tiktok.com/@b"]


def test_youtube_channel_with_details(fake_extract):
    progress = []
    videos = cc.crawl_url("https://www.youtube.com/@demo", limit=5,
                          progress_cb=lambda d, t, m: progress.append((d, t)))
    assert [v.video_id for v in videos] == ["a1", "a2", "s1", "l1"]
    assert [v.kind for v in videos] == ["video", "video", "short", "live"]
    assert fake_extract.calls[0] == ("https://www.youtube.com/@demo", True, 5)

    a1 = videos[0]
    assert a1.title == "Full a1" and a1.tags == ["english", "học"] and a1.upload_date == "2026-01-02"
    assert a1.view_count == 10            # only known from the listing – kept
    assert a1.thumbnail == "l.jpg" and a1.like_count == 7 and a1.channel == "Demo"
    assert not a1.error

    a2 = videos[1]                        # detail failed → flat data kept, error recorded
    assert a2.title == "Second" and a2.error == "Private video"
    assert progress[0] == (0, 0) and progress[-1] == (4, 4)


def test_kind_filter_and_no_details(fake_extract):
    videos = cc.crawl_url("https://www.youtube.com/@demo", kinds=[cc.KIND_SHORT], details=False)
    assert [v.video_id for v in videos] == ["s1"]
    assert all(flat for _, flat, _ in fake_extract.calls)   # no per-video request


def test_tiktok_flat_is_complete_and_hashtags_become_tags(fake_extract):
    videos = cc.crawl_url("https://www.tiktok.com/@u")
    assert len(fake_extract.calls) == 1
    v = videos[0]
    assert v.tags == ["fun", "Việt"] and v.upload_date == "2023-11-14" and v.share_count == 2


def test_crawl_collects_errors_and_continues(fake_extract):
    result = cc.crawl(["https://www.facebook.com/TED/videos", "ftp://x", "https://www.tiktok.com/@u",
                       "https://www.tiktok.com/@u?again"])
    assert [v.video_id for v in result.videos] == ["t1"]     # deduped across links
    assert [u for u, _ in result.errors] == ["https://www.facebook.com/TED/videos", "ftp://x"]
    assert "từng video" in result.errors[0][1]


def test_csv_roundtrip(fake_extract):
    videos = cc.crawl_url("https://www.youtube.com/@demo")
    data = cc.videos_to_csv(videos)
    assert data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert len(rows) == 4 and list(rows[0]) == cc.CSV_COLUMNS
    assert rows[0]["description"] == 'Line 1\nLine 2, "quoted"'
    assert rows[0]["tags"] == "english, học" and rows[0]["duration"] == "1:01"
    assert cc.VideoMeta(duration_sec=3725).duration == "1:02:05"
