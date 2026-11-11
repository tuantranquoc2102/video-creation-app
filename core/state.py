"""Video-record state.

Historically this wrapped ``st.session_state`` (records were lost on reload).
It now delegates to the SQLite store in :mod:`core.storage`; the public
function names are unchanged so views did not need to change.
"""

from __future__ import annotations

from core import storage

STATUS_DONE = "Hoàn thành"
STATUS_PROCESSING = "Đang xử lý"
STATUS_ERROR = "Lỗi"


def init() -> None:
    """Ensure the database exists (idempotent)."""
    storage.init_db()


# ---------------------------------------------------------------------------
# Video helpers (read / write)
# ---------------------------------------------------------------------------
def get_videos() -> list[dict]:
    return storage.list_videos()


def add_video(entry: dict) -> dict:
    return storage.add_video(entry)


def remove_video(entry: dict) -> None:
    """Delete the record and its generated file (if inside ``output/``)."""
    if entry.get("id") is not None:
        storage.delete_video(entry["id"])


def remove_videos_by_status(status: str) -> int:
    return storage.delete_videos_by_status(status)


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------
def count_by_status(status: str) -> int:
    return sum(1 for v in get_videos() if v.get("status") == status)


def get_stats() -> dict[str, int]:
    videos = get_videos()
    return {
        "total": len(videos),
        "done": sum(1 for v in videos if v.get("status") == STATUS_DONE),
        "processing": sum(1 for v in videos if v.get("status") == STATUS_PROCESSING),
        "error": sum(1 for v in videos if v.get("status") == STATUS_ERROR),
    }
