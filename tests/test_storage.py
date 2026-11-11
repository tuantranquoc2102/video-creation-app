import os

from core import state, storage


def test_add_list_delete_roundtrip(tmp_db, tmp_path):
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    video_file = out_dir / "v.mp4"
    video_file.write_bytes(b"x")

    rec = storage.add_video({"name": "v", "status": "Hoàn thành", "created_at": "2026-11-08 10:00:00",
                             "output_path": str(video_file), "fps": 30})
    assert rec["id"] > 0
    rows = storage.list_videos()
    assert len(rows) == 1 and rows[0]["fps"] == 30 and rows[0]["name"] == "v"

    storage.delete_video(rec["id"], output_dir=str(out_dir))
    assert storage.list_videos() == []
    assert not video_file.exists()


def test_delete_never_removes_files_outside_output(tmp_db, tmp_path):
    outside = tmp_path / "precious.mp4"
    outside.write_bytes(b"keep")
    rec = storage.add_video({"name": "x", "status": "Lỗi", "created_at": "t", "output_path": str(outside)})
    storage.delete_video(rec["id"], output_dir=str(tmp_path / "output"))
    assert outside.exists()


def test_state_api_persists_and_counts(tmp_db):
    state.init()
    state.add_video({"name": "a", "status": state.STATUS_DONE, "created_at": "2026-11-08 09:00:00"})
    state.add_video({"name": "b", "status": state.STATUS_ERROR, "created_at": "2026-11-08 10:00:00"})
    assert state.get_stats() == {"total": 2, "done": 1, "processing": 0, "error": 1}
    assert [v["name"] for v in state.get_videos()] == ["b", "a"]  # newest first
    assert state.remove_videos_by_status(state.STATUS_ERROR) == 1
    assert state.get_stats()["total"] == 1
    assert os.path.isfile(tmp_db)
