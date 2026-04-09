import pytest


def test_no_splitting_needed():
    from asr.segment_utils import split_segments
    segments = [{"start": 0.0, "end": 3.0, "text": "Hello world this is a test."}]
    result = split_segments(segments, max_words=40, max_duration=10.0)
    assert len(result) == 1
    assert result[0]["text"] == "Hello world this is a test."


def test_split_by_word_count():
    from asr.segment_utils import split_segments
    segments = [{"start": 0.0, "end": 6.0, "text": "one two three four five six seven eight nine ten eleven twelve"}]
    result = split_segments(segments, max_words=5, max_duration=60.0)
    assert len(result) >= 2
    for seg in result:
        assert len(seg["text"].split()) <= 5


def test_split_by_duration():
    from asr.segment_utils import split_segments
    segments = [{"start": 0.0, "end": 10.0, "text": "one two three four five six seven eight nine ten"}]
    result = split_segments(segments, max_words=200, max_duration=3.0)
    assert len(result) >= 3
    for seg in result:
        duration = seg["end"] - seg["start"]
        assert duration <= 3.5


def test_split_preserves_timing():
    from asr.segment_utils import split_segments
    segments = [{"start": 10.0, "end": 20.0, "text": "one two three four five six seven eight nine ten"}]
    result = split_segments(segments, max_words=5, max_duration=60.0)
    assert result[0]["start"] == 10.0
    assert result[-1]["end"] == 20.0
    for i in range(len(result) - 1):
        assert abs(result[i]["end"] - result[i + 1]["start"]) < 0.01


def test_empty_segments():
    from asr.segment_utils import split_segments
    assert split_segments([], max_words=40, max_duration=10.0) == []


def test_single_word_segment():
    from asr.segment_utils import split_segments
    segments = [{"start": 0.0, "end": 1.0, "text": "Hello"}]
    result = split_segments(segments, max_words=40, max_duration=10.0)
    assert len(result) == 1


def test_multiple_segments_mixed():
    from asr.segment_utils import split_segments
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Short sentence."},
        {"start": 2.0, "end": 12.0, "text": "This is a very long sentence that has way too many words for a single subtitle segment to display properly on screen"},
    ]
    result = split_segments(segments, max_words=10, max_duration=10.0)
    assert len(result) >= 3
    assert result[0]["text"] == "Short sentence."


def test_sentence_boundary_splitting():
    from asr.segment_utils import split_segments
    segments = [{"start": 0.0, "end": 8.0, "text": "Hello world. This is great. And more text here for testing."}]
    result = split_segments(segments, max_words=5, max_duration=60.0)
    assert len(result) >= 2
    for seg in result:
        assert len(seg["text"].split()) <= 5
