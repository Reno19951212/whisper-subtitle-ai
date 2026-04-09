"""Tests for sentence-aware translation pipeline."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_merge_empty_segments():
    from translation.sentence_pipeline import merge_to_sentences
    result = merge_to_sentences([])
    assert result == []


def test_merge_single_complete_sentence():
    from translation.sentence_pipeline import merge_to_sentences
    segments = [
        {"start": 0.0, "end": 3.0, "text": "Hello world."},
    ]
    result = merge_to_sentences(segments)
    assert len(result) == 1
    assert result[0]["text"] == "Hello world."
    assert result[0]["seg_indices"] == [0]
    assert result[0]["seg_word_counts"] == {0: 2}
    assert result[0]["start"] == 0.0
    assert result[0]["end"] == 3.0


def test_merge_fragments_into_two_sentences():
    from translation.sentence_pipeline import merge_to_sentences
    segments = [
        {"start": 0.0, "end": 2.0, "text": "The cat sat on"},
        {"start": 2.0, "end": 4.0, "text": "the mat. The dog"},
        {"start": 4.0, "end": 6.0, "text": "ran away quickly."},
    ]
    result = merge_to_sentences(segments)
    assert len(result) == 2
    assert "The cat sat on the mat." in result[0]["text"]
    assert 0 in result[0]["seg_indices"]
    assert 1 in result[0]["seg_indices"]
    assert result[0]["start"] == 0.0
    assert "The dog ran away quickly." in result[1]["text"]
    assert 1 in result[1]["seg_indices"]
    assert 2 in result[1]["seg_indices"]
    assert result[1]["end"] == 6.0


def test_merge_shared_segment():
    from translation.sentence_pipeline import merge_to_sentences
    segments = [
        {"start": 0.0, "end": 3.0, "text": "First sentence here."},
        {"start": 3.0, "end": 6.0, "text": "Second one. Third starts"},
        {"start": 6.0, "end": 9.0, "text": "and finishes here."},
    ]
    result = merge_to_sentences(segments)
    assert len(result) == 3
    total_seg1_words = sum(
        s["seg_word_counts"].get(1, 0) for s in result
    )
    assert total_seg1_words == 4


def test_redistribute_single_sentence_three_segments():
    from translation.sentence_pipeline import merge_to_sentences, redistribute_to_segments
    original_segments = [
        {"start": 0.0, "end": 2.0, "text": "The cat sat on"},
        {"start": 2.0, "end": 5.0, "text": "the mat and then"},
        {"start": 5.0, "end": 7.0, "text": "went to sleep."},
    ]
    merged = merge_to_sentences(original_segments)
    zh_sentences = ["貓坐在墊子上，然後去睡覺了。"]
    result = redistribute_to_segments(merged, zh_sentences, original_segments)
    assert len(result) == 3
    combined = "".join(r["zh_text"] for r in result)
    assert combined == "貓坐在墊子上，然後去睡覺了。"
    assert result[0]["start"] == 0.0
    assert result[0]["end"] == 2.0
    assert result[1]["start"] == 2.0
    assert result[1]["end"] == 5.0
    assert result[2]["start"] == 5.0
    assert result[2]["end"] == 7.0
    assert result[0]["en_text"] == "The cat sat on"
    assert result[2]["en_text"] == "went to sleep."


def test_redistribute_prefers_punctuation_break():
    from translation.sentence_pipeline import merge_to_sentences, redistribute_to_segments
    original_segments = [
        {"start": 0.0, "end": 3.0, "text": "Hello there my friend"},
        {"start": 3.0, "end": 6.0, "text": "how are you doing today."},
    ]
    merged = merge_to_sentences(original_segments)
    zh_sentences = ["你好啊，我的朋友你今天怎麼樣。"]
    result = redistribute_to_segments(merged, zh_sentences, original_segments)
    assert len(result) == 2
    assert result[0]["zh_text"].endswith("，") or "，" in result[0]["zh_text"]


def test_redistribute_shared_segment_merged():
    from translation.sentence_pipeline import merge_to_sentences, redistribute_to_segments
    original_segments = [
        {"start": 0.0, "end": 3.0, "text": "First sentence."},
        {"start": 3.0, "end": 6.0, "text": "Second sentence."},
    ]
    merged = merge_to_sentences(original_segments)
    zh_sentences = ["第一句話。", "第二句話。"]
    result = redistribute_to_segments(merged, zh_sentences, original_segments)
    assert len(result) == 2
    assert result[0]["zh_text"] == "第一句話。"
    assert result[1]["zh_text"] == "第二句話。"
    assert result[0]["start"] == 0.0
    assert result[1]["start"] == 3.0


def test_validate_all_valid():
    from translation.sentence_pipeline import validate_batch
    results = [
        {"start": 0.0, "end": 2.0, "en_text": "Hello.", "zh_text": "你好。"},
        {"start": 2.0, "end": 4.0, "en_text": "World.", "zh_text": "世界。"},
    ]
    assert validate_batch(results) == []


def test_validate_repetition():
    from translation.sentence_pipeline import validate_batch
    results = [
        {"start": 0.0, "end": 1.0, "en_text": "A", "zh_text": "重複"},
        {"start": 1.0, "end": 2.0, "en_text": "B", "zh_text": "重複"},
        {"start": 2.0, "end": 3.0, "en_text": "C", "zh_text": "重複"},
        {"start": 3.0, "end": 4.0, "en_text": "D", "zh_text": "正常"},
    ]
    bad = validate_batch(results)
    assert 0 in bad
    assert 1 in bad
    assert 2 in bad
    assert 3 not in bad


def test_validate_missing():
    from translation.sentence_pipeline import validate_batch
    results = [
        {"start": 0.0, "end": 2.0, "en_text": "Hello.", "zh_text": "你好。"},
        {"start": 2.0, "end": 4.0, "en_text": "World.", "zh_text": "[TRANSLATION MISSING] World."},
    ]
    bad = validate_batch(results)
    assert 1 in bad
    assert 0 not in bad


def test_validate_too_long():
    from translation.sentence_pipeline import validate_batch
    long_zh = "一" * 33
    results = [
        {"start": 0.0, "end": 2.0, "en_text": "Short.", "zh_text": long_zh},
    ]
    bad = validate_batch(results)
    assert 0 in bad


def test_validate_hallucination():
    from translation.sentence_pipeline import validate_batch
    results = [
        {"start": 0.0, "end": 2.0, "en_text": "Hi", "zh_text": "一二三四五六七"},
    ]
    bad = validate_batch(results)
    assert 0 in bad
