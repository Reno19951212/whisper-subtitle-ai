import pytest
from pathlib import Path

SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "zh_text": "各位晚上好。"},
    {"start": 2.5, "end": 5.0, "zh_text": "歡迎收看新聞。"},
    {"start": 65.5, "end": 68.25, "zh_text": "颱風正在逼近。"},
]

DEFAULT_FONT = {
    "family": "Noto Sans TC", "size": 48, "color": "#FFFFFF",
    "outline_color": "#000000", "outline_width": 2, "position": "bottom", "margin_bottom": 40,
}


def test_hex_to_ass_color_white():
    from renderer import hex_to_ass_color
    assert hex_to_ass_color("#FFFFFF") == "&H00FFFFFF"


def test_hex_to_ass_color_black():
    from renderer import hex_to_ass_color
    assert hex_to_ass_color("#000000") == "&H00000000"


def test_hex_to_ass_color_red():
    from renderer import hex_to_ass_color
    assert hex_to_ass_color("#FF0000") == "&H000000FF"


def test_hex_to_ass_color_blue():
    from renderer import hex_to_ass_color
    assert hex_to_ass_color("#0000FF") == "&H00FF0000"


def test_seconds_to_ass_time_zero():
    from renderer import seconds_to_ass_time
    assert seconds_to_ass_time(0.0) == "0:00:00.00"


def test_seconds_to_ass_time_simple():
    from renderer import seconds_to_ass_time
    assert seconds_to_ass_time(2.5) == "0:00:02.50"


def test_seconds_to_ass_time_minutes():
    from renderer import seconds_to_ass_time
    assert seconds_to_ass_time(65.5) == "0:01:05.50"


def test_seconds_to_ass_time_hours():
    from renderer import seconds_to_ass_time
    assert seconds_to_ass_time(3723.75) == "1:02:03.75"


def test_generate_ass_structure(tmp_path):
    from renderer import SubtitleRenderer
    renderer = SubtitleRenderer(tmp_path)
    ass = renderer.generate_ass(SAMPLE_SEGMENTS, DEFAULT_FONT)
    assert "[Script Info]" in ass
    assert "Title: Broadcast Subtitles" in ass
    assert "PlayResX: 1920" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass


def test_generate_ass_style_line(tmp_path):
    from renderer import SubtitleRenderer
    renderer = SubtitleRenderer(tmp_path)
    ass = renderer.generate_ass(SAMPLE_SEGMENTS, DEFAULT_FONT)
    assert "Noto Sans TC" in ass
    assert ",48," in ass
    assert "&H00FFFFFF" in ass
    assert "&H00000000" in ass


def test_generate_ass_dialogue_lines(tmp_path):
    from renderer import SubtitleRenderer
    renderer = SubtitleRenderer(tmp_path)
    ass = renderer.generate_ass(SAMPLE_SEGMENTS, DEFAULT_FONT)
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,各位晚上好。" in ass
    assert "Dialogue: 0,0:00:02.50,0:00:05.00,Default,,0,0,0,,歡迎收看新聞。" in ass
    assert "Dialogue: 0,0:01:05.50,0:01:08.25,Default,,0,0,0,,颱風正在逼近。" in ass


def test_generate_ass_empty_segments(tmp_path):
    from renderer import SubtitleRenderer
    renderer = SubtitleRenderer(tmp_path)
    ass = renderer.generate_ass([], DEFAULT_FONT)
    assert "[Script Info]" in ass
    assert "Dialogue" not in ass


def test_generate_ass_custom_font(tmp_path):
    from renderer import SubtitleRenderer
    renderer = SubtitleRenderer(tmp_path)
    custom_font = {
        "family": "Arial", "size": 36, "color": "#FF0000",
        "outline_color": "#0000FF", "outline_width": 3, "position": "bottom", "margin_bottom": 60,
    }
    ass = renderer.generate_ass(SAMPLE_SEGMENTS, custom_font)
    assert "Arial" in ass
    assert ",36," in ass
    assert "&H000000FF" in ass
    assert "&H00FF0000" in ass


def test_get_default_font_config(tmp_path):
    from renderer import DEFAULT_FONT_CONFIG
    assert DEFAULT_FONT_CONFIG["family"] == "Noto Sans TC"
    assert DEFAULT_FONT_CONFIG["size"] == 48
