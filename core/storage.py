"""SQLite persistence for video records (replaces volatile session state).

Each record keeps a few indexed columns plus the full dict as JSON, so new
fields can be added without migrations.  No Streamlit imports.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import closing

import config
from core.utils import is_within

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    output_path TEXT,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);
"""


def _db_path(db_path: str | None) -> str:
    return db_path or config.DB_PATH


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = _db_path(db_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | None = None) -> None:
    with closing(_connect(db_path)) as conn, conn:
        conn.executescript(_SCHEMA)


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = json.loads(row["payload"])
    data.update(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        created_at=row["created_at"],
        output_path=row["output_path"],
    )
    return data


def add_video(entry: dict, db_path: str | None = None) -> dict:
    """Insert *entry*; return it with the generated ``id``."""
    init_db(db_path)
    payload = {k: v for k, v in entry.items() if k != "id"}
    with closing(_connect(db_path)) as conn, conn:
        cur = conn.execute(
            "INSERT INTO videos (name, status, created_at, output_path, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                entry.get("name", ""),
                entry.get("status", ""),
                entry.get("created_at", ""),
                entry.get("output_path"),
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        return {**payload, "id": cur.lastrowid}


def list_videos(db_path: str | None = None) -> list[dict]:
    init_db(db_path)
    with closing(_connect(db_path)) as conn:
        rows = conn.execute("SELECT * FROM videos ORDER BY created_at DESC, id DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_video(video_id: int, db_path: str | None = None) -> dict | None:
    init_db(db_path)
    with closing(_connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    return _row_to_dict(row) if row else None


def _delete_file(path: str | None, output_dir: str) -> None:
    """Delete a generated file – only if it lives inside *output_dir*."""
    if path and os.path.isfile(path) and is_within(path, output_dir):
        try:
            os.remove(path)
        except OSError as exc:  # keep DB consistent even if the file is locked
            log.warning("Không xoá được file %s: %s", path, exc)


def delete_video(
    video_id: int,
    *,
    delete_file: bool = True,
    db_path: str | None = None,
    output_dir: str | None = None,
) -> None:
    video = get_video(video_id, db_path)
    if not video:
        return
    if delete_file:
        _delete_file(video.get("output_path"), output_dir or config.OUTPUT_DIR)
    with closing(_connect(db_path)) as conn, conn:
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))


def delete_videos_by_status(
    status: str,
    *,
    delete_files: bool = True,
    db_path: str | None = None,
    output_dir: str | None = None,
) -> int:
    victims = [v for v in list_videos(db_path) if v.get("status") == status]
    for v in victims:
        delete_video(v["id"], delete_file=delete_files, db_path=db_path, output_dir=output_dir)
    return len(victims)
