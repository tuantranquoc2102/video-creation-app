from core.video_service import csv_to_text, detect_csv_type, filter_videos, parse_csv


def test_parse_and_detect_dialogue():
    df = parse_csv("Speaker 1;Speaker 2\nHi!;Hello!\n".encode())
    assert list(df.columns) == ["speaker 1", "speaker 2"]
    assert detect_csv_type(df) == "dialogue"


def test_parse_falls_back_to_sniffer_for_commas():
    df = parse_csv("english,ipa,vietnam,example,translate\ncat,kæt,con mèo,A cat.,Một con mèo.\n".encode())
    assert detect_csv_type(df) == "vocabulary"


def test_vocab_text_does_not_double_slash_ipa():
    df = parse_csv("english;ipa;vietnam;example;translate\nabandon;/əˈbændən/;từ bỏ;Ex.;Dịch.\n".encode())
    text = csv_to_text(df, "vocabulary")
    assert "/əˈbændən/" in text and "//" not in text


def test_filter_by_exact_resolution_label():
    vids = [{"name": "a", "resolution": "9:16 (1080x1920)", "created_at": "1"},
            {"name": "b", "resolution": "16:9 (1920x1080)", "created_at": "2"}]
    out = filter_videos(vids, resolution="9:16 (1080x1920)")
    assert [v["name"] for v in out] == ["a"]
