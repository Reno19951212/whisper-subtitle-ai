"""Utility functions for post-processing ASR output segments."""

import math
import re
from typing import List


_SENTENCE_END_PATTERN = re.compile(r"[.!?]")


def split_segments(
    segments: List[dict],
    max_words: int,
    max_duration: float,
) -> List[dict]:
    """Post-process ASR output by splitting segments that exceed limits.

    Args:
        segments: List of segment dicts with keys: start, end, text.
        max_words: Maximum number of words allowed per segment.
        max_duration: Maximum duration (seconds) allowed per segment.

    Returns:
        New list of segments, each within the specified limits.
        Original segments are never mutated.
    """
    if not segments:
        return []

    result = []
    for segment in segments:
        result.extend(_split_single_segment(segment, max_words, max_duration))
    return result


def _split_single_segment(
    segment: dict,
    max_words: int,
    max_duration: float,
) -> List[dict]:
    """Split a single segment if it exceeds word count or duration limits."""
    text = segment["text"]
    start = segment["start"]
    end = segment["end"]
    duration = end - start

    words = text.split()
    word_count = len(words)

    needs_word_split = word_count > max_words
    needs_duration_split = duration > max_duration

    if not needs_word_split and not needs_duration_split:
        return [{"start": start, "end": end, "text": text}]

    # Calculate number of chunks needed by each constraint
    chunks_by_words = math.ceil(word_count / max_words) if needs_word_split else 1
    chunks_by_duration = math.ceil(duration / max_duration) if needs_duration_split else 1
    num_chunks = max(chunks_by_words, chunks_by_duration)

    if num_chunks <= 1:
        return [{"start": start, "end": end, "text": text}]

    target_chunk_size = math.ceil(word_count / num_chunks)
    word_groups = _partition_words(words, target_chunk_size)

    return _assign_timings(word_groups, start, end, words)


def _partition_words(words: List[str], target_chunk_size: int) -> List[List[str]]:
    """Partition words into groups, preferring sentence boundaries.

    Each resulting group will never exceed target_chunk_size words.
    When at the target size, the algorithm tries to split at the nearest
    preceding sentence boundary; otherwise it splits at the target size.
    """
    if not words:
        return []

    groups: List[List[str]] = []
    current_group: List[str] = []

    for i, word in enumerate(words):
        current_group = [*current_group, word]
        at_target = len(current_group) >= target_chunk_size
        is_sentence_end = bool(_SENTENCE_END_PATTERN.search(word))
        words_remaining = len(words) - i - 1

        if at_target and words_remaining > 0:
            if is_sentence_end:
                # Clean sentence boundary at or before limit — split here
                groups = [*groups, current_group]
                current_group = []
            else:
                # Check if there's a sentence boundary inside the current group
                # (i.e., we overshot it). If so, split at that earlier boundary.
                split_at = None
                for k in range(len(current_group) - 2, -1, -1):
                    if _SENTENCE_END_PATTERN.search(current_group[k]):
                        split_at = k
                        break

                if split_at is not None:
                    # Split current group at the sentence boundary
                    before = current_group[: split_at + 1]
                    after = current_group[split_at + 1 :]
                    groups = [*groups, before]
                    current_group = after
                else:
                    # No sentence boundary found — hard split at word limit
                    groups = [*groups, current_group]
                    current_group = []

    if current_group:
        groups = [*groups, current_group]

    return groups


def _assign_timings(
    word_groups: List[List[str]],
    seg_start: float,
    seg_end: float,
    all_words: List[str],
) -> List[dict]:
    """Assign start/end timestamps to each word group proportionally by word index."""
    total_words = len(all_words)
    duration = seg_end - seg_start
    segments = []
    word_offset = 0

    for i, group in enumerate(word_groups):
        group_size = len(group)

        # Proportional timing based on word position
        chunk_start = seg_start + (word_offset / total_words) * duration
        chunk_end = seg_start + ((word_offset + group_size) / total_words) * duration

        # Clamp and round
        chunk_start = round(max(seg_start, chunk_start), 2)
        chunk_end = round(min(seg_end, chunk_end), 2)

        # Ensure contiguity: first chunk starts exactly at seg_start,
        # last chunk ends exactly at seg_end
        if i == 0:
            chunk_start = seg_start
        if i == len(word_groups) - 1:
            chunk_end = seg_end

        # Snap this chunk's start to the previous chunk's end to guarantee no gaps
        if segments:
            chunk_start = segments[-1]["end"]

        segments = [
            *segments,
            {
                "start": chunk_start,
                "end": chunk_end,
                "text": " ".join(group),
            },
        ]

        word_offset += group_size

    return segments
