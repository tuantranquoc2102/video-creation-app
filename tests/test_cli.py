from core.render.__main__ import build_parser, config_from_args, main

from conftest import SAMPLE_LESSON


def test_args_map_to_render_config():
    args = build_parser().parse_args(["x.json", "--landscape", "--example-repeat", "1", "--no-vi", "--layout", "panel"])
    cfg = config_from_args(args)
    assert cfg.size == (1920, 1080) and cfg.example_repeat == 1
    assert cfg.vi_narration is False and cfg.scene_layout == "panel"


def test_check_only_on_valid_and_missing_files(capsys):
    assert main([SAMPLE_LESSON, "--check"]) == 0
    assert "Kiểm tra đạt" in capsys.readouterr().out
    assert main(["does-not-exist.json", "--check"]) == 2


def test_check_reports_errors(tmp_path, sample_dict, capsys):
    import json
    sample_dict["vocabulary"].pop()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(sample_dict, ensure_ascii=False), encoding="utf-8")
    assert main([str(bad), "--check"]) == 1
    assert "Cần đúng 10 từ vựng" in capsys.readouterr().out
