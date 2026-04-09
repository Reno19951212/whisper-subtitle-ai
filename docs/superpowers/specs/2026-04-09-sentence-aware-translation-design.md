# Sentence-Aware Translation Pipeline Design

## Purpose

Fix translation repetition caused by sending ASR sentence fragments to the LLM. Whisper produces 2-5 second segments that split mid-sentence. When these fragments are batched for translation, the LLM produces repeated or nonsensical output because each fragment lacks complete meaning.

## Scope

- New file: `backend/translation/sentence_pipeline.py`
- Modify: `backend/app.py` (2 call sites)
- Modify: `backend/translation/ollama_engine.py` (improved prompt)
- Modify: `backend/requirements.txt` (add pySBD)
- New test file: `backend/tests/test_sentence_pipeline.py`
- No frontend changes. No new API endpoints.

## Architecture

Three-phase pipeline wrapping the existing `TranslationEngine`:

```
ASR Segments (fragments, 2-5s each)
    |
    v  merge_to_sentences()
Sentence-level segments (complete English sentences)
    |
    v  engine.translate()  [existing TranslationEngine]
Sentence-level translations (complete Chinese sentences)
    |
    v  redistribute_to_segments()
    |
    v  validate_and_retry()
Final TranslatedSegment[] (matching original segment timestamps)
```

## Data Structures

### MergedSentence

```python
class MergedSentence(TypedDict):
    text: str                    # Complete English sentence
    seg_indices: List[int]       # Indices into original segments list
    seg_word_counts: Dict[int, int]  # seg_index -> word count from that segment
    start: float                 # Earliest segment start time
    end: float                   # Latest segment end time
```

## Changes

### 1. `merge_to_sentences(segments) -> list[MergedSentence]`

**Input:** List of ASR segments `[{start, end, text}, ...]`

**Process:**
1. Concatenate all segment texts into one string with single spaces
2. Build a word-to-segment index: for each word in the concatenated text, record which original segment it came from
3. Use `pysbd.Segmenter(language="en", clean=False)` to split the concatenated text into complete English sentences
4. For each sentence, map its words back to original segment indices using the word-to-segment index
5. Record each segment's word count contribution to the sentence

**Output:** List of MergedSentence, each containing a complete English sentence with its segment mapping

**Edge cases:**
- Single-segment sentence: maps to exactly one segment (no redistribution needed later)
- Sentence spanning many segments: all segment indices recorded with individual word counts
- Segments shared between sentences: a segment can appear in two MergedSentences (e.g., segment contains end of one sentence and start of another). Each MergedSentence records only the word count from that segment that belongs to it.

### 2. Improved Translation Prompt

The system prompt for OllamaTranslationEngine gains an additional instruction:

```
Each numbered line is a COMPLETE sentence. Translate each into exactly one
corresponding Traditional Chinese line. Do NOT merge or split lines.
```

This is appended to both `SYSTEM_PROMPT_FORMAL` and `SYSTEM_PROMPT_CANTONESE`.

No other changes to the engine interface or batching logic.

### 3. `redistribute_to_segments(merged_sentences, zh_sentences, original_segments) -> list[TranslatedSegment]`

**Input:**
- `merged_sentences`: list of MergedSentence from step 1
- `zh_sentences`: list of Chinese translation strings (one per merged sentence)
- `original_segments`: the original ASR segments

**Process:**

For each merged sentence and its Chinese translation:

1. Calculate each original segment's proportion: `seg_en_words / total_sentence_en_words`
2. Allocate Chinese characters proportionally: `round(total_zh_chars * proportion)`
3. Adjust allocation to break at natural Chinese boundaries:
   - Preferred break points: Chinese punctuation (`。，、！？；：`)
   - Fallback: any position (character-level split)
   - Search within +/- 3 characters of the target split point for a natural break
4. Last segment in each sentence gets all remaining characters (no rounding loss)
5. Build TranslatedSegment with the original segment's start/end timestamps

**Handling segments shared between sentences:**
- When a segment appears in two sentences, it produces two TranslatedSegment entries with the same start/end but different zh_text portions
- The orchestrator merges these into a single TranslatedSegment by concatenating the zh_text portions

**Output:** List of TranslatedSegment, one per original segment, preserving original timestamps

### 4. `validate_batch(results) -> list[int]`

**Input:** List of TranslatedSegment

**Checks and thresholds:**

| Check | Condition | Severity |
|-------|-----------|----------|
| Repetition | >= 3 consecutive segments with identical zh_text | retry |
| Missing | zh_text contains `[TRANSLATION MISSING]` | retry |
| Too long | zh_text > 32 Chinese characters | split at nearest punctuation |
| Hallucination | len(zh_text) > len(en_text) * 3 | mark `[NEEDS REVIEW]` |

**Output:** List of problematic segment indices. Empty list means all passed.

### 5. `translate_with_sentences(engine, segments, glossary, style, batch_size, temperature) -> list[TranslatedSegment]`

**Orchestrator function.** This replaces direct `engine.translate()` calls in app.py.

**Process:**
1. Call `merge_to_sentences(segments)` to get sentence-level data
2. Build sentence-level segment list for the engine
3. Call `engine.translate(sentence_segments, ...)` with the merged sentences
4. Call `redistribute_to_segments(...)` to map Chinese back to original timestamps
5. Call `validate_batch(results)` to check for problems
6. For any failed sentences: retry translation with `batch_size=1` (one sentence at a time)
7. Re-redistribute and re-validate the retried sentences
8. Segments that still fail after retry: mark zh_text as `[NEEDS REVIEW] {original_zh_text}`
9. Return final list of TranslatedSegment

**Retry strategy:**
- Only retry the specific merged sentences whose redistributed segments failed validation
- Retry uses `batch_size=1` to isolate each sentence
- Maximum 1 retry per sentence
- Retry does not change temperature or other parameters

### 6. Integration into app.py

Two call sites change:

**`api_translate_file()`** (line ~665):
```python
# Before:
translated = engine.translate(asr_segments, glossary=..., style=..., ...)

# After:
from translation.sentence_pipeline import translate_with_sentences
translated = translate_with_sentences(engine, asr_segments, glossary=..., style=..., ...)
```

**`_auto_translate()`** (line ~1082):
```python
# Same change as above
```

No changes to the TranslationEngine interface. The sentence pipeline wraps the engine, not replaces it.

### 7. New dependency

Add to `backend/requirements.txt`:
```
pysbd>=0.3.4
```

## Testing

### Unit tests (`backend/tests/test_sentence_pipeline.py`)

**merge_to_sentences:**
- Fragments forming 2 sentences -> returns 2 MergedSentences with correct mappings
- Single complete sentence in one segment -> returns 1 MergedSentence
- Empty segments -> returns empty list
- Segment shared between two sentences -> both sentences reference it with correct word counts

**redistribute_to_segments:**
- 1 sentence spanning 3 segments -> 3 TranslatedSegments with proportional zh_text
- Chinese text breaks at punctuation when available
- Last segment gets remainder characters
- Shared segment between 2 sentences -> merged into single TranslatedSegment

**validate_batch:**
- 3+ consecutive identical zh_text -> returns those indices
- `[TRANSLATION MISSING]` -> returns that index
- zh_text > 32 chars -> returns that index
- All valid -> returns empty list

**translate_with_sentences (integration):**
- Uses MockTranslationEngine to verify full pipeline flow
- Retry logic: mock engine returns duplicates on first call, good results on retry

### Manual verification

- Re-translate the FIFA video and compare segment 40-48 output
- Verify no repetition in the Chinese translations
- Check that timestamps still align with video playback

## What Does NOT Change

- TranslationEngine ABC interface
- MockTranslationEngine (still works for dev/testing, just wrapped by pipeline)
- Frontend (no changes)
- API endpoints (same request/response format)
- Proof-reading editor
- Subtitle renderer
- ASR pipeline
- segment_utils.py (split_segments is a separate concern — it splits oversized ASR output, while this pipeline merges fragments for translation)
