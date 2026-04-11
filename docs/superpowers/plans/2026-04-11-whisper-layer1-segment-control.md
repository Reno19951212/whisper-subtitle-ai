# Whisper Layer 1 Segment Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose three faster-whisper native segmentation parameters (`max_new_tokens`, `condition_on_previous_text`, `vad_filter`) through the WhisperEngine schema and wire them into the Profile form's dynamic ASR params panel.

**Architecture:** Backend adds the three params to `WhisperEngine.get_params_schema()` and passes them into `model.transcribe()` in `_transcribe_faster()`. The existing dynamic params system in the frontend automatically surfaces schema fields — the only frontend changes needed are adding boolean type support to `renderParamField()` and making the ASR/translation param collection in `saveProfile()` schema-aware (to handle boolean and nullable integer correctly).

**Tech Stack:** Python 3.9+, faster-whisper, openai-whisper (fallback), Vanilla JS, pytest, unittest.mock

---

## File Structure

| File | Change |
|------|--------|
| `backend/asr/whisper_engine.py` | Add 3 params to `get_params_schema()`; pass them in `_transcribe_faster()`; pass `condition_on_previous_text` in `_transcribe_openai()` |
| `backend/tests/test_asr.py` | Add tests for new schema params and transcription call args |
| `frontend/index.html` | Add boolean branch to `renderParamField()`; fix nullable integer placeholder; update both param collection loops in `saveProfile()` |

---

## Context for agentic workers

**Codebase location:** The project root is `whisper-subtitle-ai/`. Backend is in `backend/`, frontend is a single file `frontend/index.html`.

**How the dynamic params panel works:**
1. `WhisperEngine.get_params_schema()` returns a dict `{ engine, params: { name: { type, description, default, ... } } }`
2. This is served by `GET /api/asr/engines/whisper/params`
3. `renderParamField(name, idPrefix, paramSchema, currentValue)` in `frontend/index.html` renders one form field per schema entry
4. `saveProfile()` collects values using `document.getElementById('pf-asr-{name}')` and sends them in the PATCH/POST body

**Existing `renderParamField` handles:** `enum` → `<select>`, `number`/`integer` → `<input type="number">`, `string` → `<input type="text">`. Missing: `boolean`.

**Existing `saveProfile` param collection (lines ~2211–2217):**
```js
for (const paramName of Object.keys(currentAsrSchema.params || {})) {
    if (EXCLUDED_ASR_PARAMS.includes(paramName)) continue;
    const el = document.getElementById(`pf-asr-${paramName}`);
    if (el) {
        asrParams[paramName] = (el.type === 'number') ? Number(el.value) : el.value;
    }
}
```
This is broken for booleans (returns `"true"`/`"false"` strings instead of booleans) and for nullable integers (returns `0` instead of `null` for empty input). Both loops (ASR and translation) need the same fix.

**Run tests from `backend/` directory with venv active:**
```bash
cd backend && source venv/bin/activate
pytest tests/test_asr.py -v
```

---

## Task 1: Add Layer 1 params to WhisperEngine schema

**Files:**
- Modify: `backend/asr/whisper_engine.py` (lines 99–122, `get_params_schema` method)
- Test: `backend/tests/test_asr.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_asr.py`:

```python
def test_whisper_engine_params_schema_includes_layer1():
    from asr.whisper_engine import WhisperEngine
    engine = WhisperEngine({"engine": "whisper", "model_size": "tiny"})
    schema = engine.get_params_schema()
    params = schema["params"]

    assert "max_new_tokens" in params
    assert params["max_new_tokens"]["type"] == "integer"
    assert params["max_new_tokens"]["default"] is None
    assert params["max_new_tokens"]["minimum"] == 1

    assert "condition_on_previous_text" in params
    assert params["condition_on_previous_text"]["type"] == "boolean"
    assert params["condition_on_previous_text"]["default"] is True

    assert "vad_filter" in params
    assert params["vad_filter"]["type"] == "boolean"
    assert params["vad_filter"]["default"] is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && source venv/bin/activate
pytest tests/test_asr.py::test_whisper_engine_params_schema_includes_layer1 -v
```

Expected: FAIL — `AssertionError: 'max_new_tokens' not in params`

- [ ] **Step 3: Add the three params to `get_params_schema()`**

In `backend/asr/whisper_engine.py`, replace the `get_params_schema` method (currently lines 99–122) with:

```python
def get_params_schema(self) -> dict:
    return {
        "engine": "whisper",
        "params": {
            "model_size": {
                "type": "string",
                "description": "Whisper model size",
                "enum": ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
                "default": "small",
            },
            "language": {
                "type": "string",
                "description": "Source language code (ISO 639-1)",
                "enum": ["en", "zh", "ja", "ko", "fr", "de", "es"],
                "default": "en",
            },
            "device": {
                "type": "string",
                "description": "Computation device",
                "enum": ["auto", "cpu", "cuda"],
                "default": "auto",
            },
            "max_new_tokens": {
                "type": "integer",
                "description": "每句字幕長度上限（Token）。留空 = 無限制。約 1 token ≈ 0.75 個英文字",
                "minimum": 1,
                "default": None,
            },
            "condition_on_previous_text": {
                "type": "boolean",
                "description": "用上句文本做 context（true = 更連貫；false = 每句獨立更短）",
                "default": True,
            },
            "vad_filter": {
                "type": "boolean",
                "description": "語音活動偵測 — 在靜音位置自動切割 segment",
                "default": False,
            },
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_asr.py::test_whisper_engine_params_schema_includes_layer1 -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
pytest tests/test_asr.py -v
```

Expected: All existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/asr/whisper_engine.py backend/tests/test_asr.py
git commit -m "feat: add Layer 1 segment params to WhisperEngine schema"
```

---

## Task 2: Wire Layer 1 params into transcription calls

**Files:**
- Modify: `backend/asr/whisper_engine.py` (lines 59–89, `_transcribe_faster` and `_transcribe_openai`)
- Test: `backend/tests/test_asr.py`

- [ ] **Step 1: Write failing tests for faster-whisper path**

Add to `backend/tests/test_asr.py`:

```python
def test_whisper_faster_passes_layer1_params():
    """Layer 1 params are forwarded to model.transcribe()."""
    from asr.whisper_engine import WhisperEngine
    from unittest.mock import patch, MagicMock
    from collections import namedtuple

    engine = WhisperEngine({
        "engine": "whisper",
        "model_size": "tiny",
        "max_new_tokens": 30,
        "condition_on_previous_text": False,
        "vad_filter": True,
    })

    MockSeg = namedtuple("MockSeg", ["start", "end", "text", "words"])
    MockInfo = namedtuple("MockInfo", ["language"])
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([]), MockInfo(language="en"))

    with patch.object(engine, '_get_model', return_value=(mock_model, 'faster')):
        engine.transcribe("/tmp/test.wav", language="en")

    mock_model.transcribe.assert_called_once_with(
        "/tmp/test.wav",
        language="en",
        task="transcribe",
        max_new_tokens=30,
        condition_on_previous_text=False,
        vad_filter=True,
    )


def test_whisper_faster_null_and_zero_max_tokens_become_none():
    """max_new_tokens of None or 0 both map to None (unlimited)."""
    from asr.whisper_engine import WhisperEngine
    from unittest.mock import patch, MagicMock
    from collections import namedtuple

    MockInfo = namedtuple("MockInfo", ["language"])

    for val in (None, 0):
        engine = WhisperEngine({
            "engine": "whisper", "model_size": "tiny", "max_new_tokens": val,
        })
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([]), MockInfo(language="en"))

        with patch.object(engine, '_get_model', return_value=(mock_model, 'faster')):
            engine.transcribe("/tmp/test.wav", language="en")

        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["max_new_tokens"] is None, f"Expected None for val={val}"


def test_whisper_openai_passes_condition_on_previous_text():
    """openai-whisper path passes condition_on_previous_text; ignores the others."""
    from asr.whisper_engine import WhisperEngine
    from unittest.mock import patch, MagicMock

    engine = WhisperEngine({
        "engine": "whisper", "model_size": "tiny",
        "condition_on_previous_text": False,
        "max_new_tokens": 30,
        "vad_filter": True,
    })

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"text": "", "language": "en", "segments": []}

    with patch.object(engine, '_get_model', return_value=(mock_model, 'openai')):
        engine.transcribe("/tmp/test.wav", language="en")

    call_kwargs = mock_model.transcribe.call_args.kwargs
    assert call_kwargs["condition_on_previous_text"] is False
    assert "max_new_tokens" not in call_kwargs
    assert "vad_filter" not in call_kwargs
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_asr.py::test_whisper_faster_passes_layer1_params tests/test_asr.py::test_whisper_faster_null_and_zero_max_tokens_become_none tests/test_asr.py::test_whisper_openai_passes_condition_on_previous_text -v
```

Expected: All three FAIL — `assert_called_once_with` mismatch (current code doesn't pass the new params).

- [ ] **Step 3: Update `_transcribe_faster` to pass Layer 1 params**

In `backend/asr/whisper_engine.py`, replace `_transcribe_faster` (currently lines 59–72):

```python
def _transcribe_faster(self, model, audio_path: str, language: str) -> list[Segment]:
    max_new_tokens = self._config.get("max_new_tokens") or None  # 0 or None → None
    seg_iter, _info = model.transcribe(
        audio_path,
        language=language,
        task="transcribe",
        max_new_tokens=max_new_tokens,
        condition_on_previous_text=self._config.get("condition_on_previous_text", True),
        vad_filter=self._config.get("vad_filter", False),
    )
    segments = []
    for seg in seg_iter:
        segments.append(Segment(
            start=seg.start,
            end=seg.end,
            text=seg.text.strip(),
        ))
    return segments
```

- [ ] **Step 4: Update `_transcribe_openai` to pass `condition_on_previous_text`**

In `backend/asr/whisper_engine.py`, replace `_transcribe_openai` (currently lines 74–89):

```python
def _transcribe_openai(self, model, audio_path: str, language: str) -> list[Segment]:
    result = model.transcribe(
        audio_path,
        language=language,
        task="transcribe",
        verbose=False,
        fp16=False,
        condition_on_previous_text=self._config.get("condition_on_previous_text", True),
    )
    segments = []
    for seg in result.get("segments", []):
        segments.append(Segment(
            start=seg["start"],
            end=seg["end"],
            text=seg["text"].strip(),
        ))
    return segments
```

- [ ] **Step 5: Run new tests to verify they pass**

```bash
pytest tests/test_asr.py::test_whisper_faster_passes_layer1_params tests/test_asr.py::test_whisper_faster_null_and_zero_max_tokens_become_none tests/test_asr.py::test_whisper_openai_passes_condition_on_previous_text -v
```

Expected: All three PASS.

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/test_asr.py -v
```

Expected: All tests PASS (including the existing `test_whisper_engine_transcribe_faster` and `test_whisper_engine_transcribe_openai` tests — verify these still pass since `_transcribe_faster` mock call signature changed).

> **Note:** The existing `test_whisper_engine_transcribe_faster` uses `mock_model.transcribe.return_value = (iter(mock_segments), mock_info)` and only checks the return value, not the call args. It will still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/asr/whisper_engine.py backend/tests/test_asr.py
git commit -m "feat: wire Layer 1 params into WhisperEngine transcription calls"
```

---

## Task 3: Frontend — boolean support and nullable integer in renderParamField

**Files:**
- Modify: `frontend/index.html` (lines 1697–1723, `renderParamField` function)

No automated test framework for frontend JS. Verification is manual via the running backend.

- [ ] **Step 1: Replace the `renderParamField` function**

In `frontend/index.html`, replace lines 1697–1723 (the full `renderParamField` function) with:

```js
function renderParamField(name, idPrefix, paramSchema, currentValue) {
  const id = `${idPrefix}-${name}`;
  const value = currentValue !== undefined ? currentValue : (paramSchema.default ?? '');
  const label = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  const tooltip = paramSchema.description ? ` title="${escapeHtml(paramSchema.description)}"` : '';

  let input;
  if (paramSchema.enum) {
    const options = paramSchema.enum.map(opt =>
      `<option value="${escapeHtml(String(opt))}" ${String(value) === String(opt) ? 'selected' : ''}>${escapeHtml(String(opt))}</option>`
    ).join('');
    input = `<select id="${id}">${options}</select>`;
  } else if (paramSchema.type === 'boolean') {
    const trueSelected  = String(value) === 'true'  ? 'selected' : '';
    const falseSelected = String(value) === 'false' ? 'selected' : '';
    input = `<select id="${id}">
      <option value="true"  ${trueSelected}>true</option>
      <option value="false" ${falseSelected}>false</option>
    </select>`;
  } else if (paramSchema.type === 'number' || paramSchema.type === 'integer') {
    const min = paramSchema.minimum !== undefined ? ` min="${paramSchema.minimum}"` : '';
    const max = paramSchema.maximum !== undefined ? ` max="${paramSchema.maximum}"` : '';
    const step = paramSchema.type === 'number' ? ' step="0.1"' : '';
    const displayValue = (value === null || value === undefined || value === '') ? '' : String(value);
    const placeholder = paramSchema.default === null ? ' placeholder="留空 = 無限制"' : '';
    input = `<input type="number" id="${id}" value="${escapeHtml(displayValue)}"${min}${max}${step}${placeholder}>`;
  } else {
    input = `<input type="text" id="${id}" value="${escapeHtml(String(value))}">`;
  }

  return `
    <div class="profile-form-row">
      <label${tooltip}>${escapeHtml(label)}</label>
      ${input}
    </div>`;
}
```

- [ ] **Step 2: Manual verification**

With the backend running (`./start.sh` from project root):

1. Open `http://localhost:5001` in browser
2. Open any Profile's edit form (or create a new one)
3. Expand "ASR 設定"
4. Select engine "whisper" — the params panel should appear with:
   - **Model Size** — dropdown (enum, existing)
   - **Language** — dropdown (enum, existing)
   - **Device** — dropdown (enum, existing)
   - **Max New Tokens** — number input with placeholder "留空 = 無限制"
   - **Condition On Prev** — dropdown with `true` / `false` options
   - **Vad Filter** — dropdown with `false` / `true` options (false pre-selected)
5. Hover over the labels to verify tooltips appear

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add boolean and nullable integer support to renderParamField"
```

---

## Task 4: Frontend — schema-aware param collection in saveProfile

**Files:**
- Modify: `frontend/index.html` (lines ~2211–2227, two param collection loops in `saveProfile`)

- [ ] **Step 1: Replace both param collection loops in `saveProfile`**

In `frontend/index.html`, find and replace the **ASR params collection loop** (currently lines ~2210–2217):

```js
  // Collect dynamic ASR params from schema keys
  const asrParams = {};
  for (const paramName of Object.keys(currentAsrSchema.params || {})) {
    if (EXCLUDED_ASR_PARAMS.includes(paramName)) continue;
    const el = document.getElementById(`pf-asr-${paramName}`);
    if (el) {
      asrParams[paramName] = (el.type === 'number') ? Number(el.value) : el.value;
    }
  }
```

Replace with:

```js
  // Collect dynamic ASR params from schema keys (schema-aware: handles boolean + nullable integer)
  const asrParams = {};
  for (const [paramName, schema] of Object.entries(currentAsrSchema.params || {})) {
    if (EXCLUDED_ASR_PARAMS.includes(paramName)) continue;
    const el = document.getElementById(`pf-asr-${paramName}`);
    if (!el) continue;
    if (schema.type === 'boolean') {
      asrParams[paramName] = el.value === 'true';
    } else if (schema.type === 'number' || schema.type === 'integer') {
      asrParams[paramName] = el.value === '' ? null : Number(el.value);
    } else {
      asrParams[paramName] = el.value;
    }
  }
```

Find and replace the **translation params collection loop** (currently lines ~2220–2227):

```js
  // Collect dynamic translation params from schema keys
  const trParams = {};
  for (const paramName of Object.keys(currentTranslationSchema.params || {})) {
    if (EXCLUDED_TRANSLATION_PARAMS.includes(paramName)) continue;
    const el = document.getElementById(`pf-tr-${paramName}`);
    if (el) {
      trParams[paramName] = (el.type === 'number') ? Number(el.value) : el.value;
    }
  }
```

Replace with:

```js
  // Collect dynamic translation params from schema keys (schema-aware: handles boolean + nullable integer)
  const trParams = {};
  for (const [paramName, schema] of Object.entries(currentTranslationSchema.params || {})) {
    if (EXCLUDED_TRANSLATION_PARAMS.includes(paramName)) continue;
    const el = document.getElementById(`pf-tr-${paramName}`);
    if (!el) continue;
    if (schema.type === 'boolean') {
      trParams[paramName] = el.value === 'true';
    } else if (schema.type === 'number' || schema.type === 'integer') {
      trParams[paramName] = el.value === '' ? null : Number(el.value);
    } else {
      trParams[paramName] = el.value;
    }
  }
```

- [ ] **Step 2: Manual end-to-end verification**

With the backend running:

1. Open a Profile edit form, select whisper engine
2. Set **Max New Tokens** to `30`, **Condition On Prev** to `false`, **VAD Filter** to `true`
3. Click Save
4. Immediately reopen that profile's edit form
5. Verify:
   - Max New Tokens shows `30`
   - Condition On Prev shows `false`
   - VAD Filter shows `true`
6. Clear Max New Tokens (leave blank), save again
7. Reopen — Max New Tokens should be blank (null stored, not 0)

Verify via API:
```bash
curl http://localhost:5001/api/profiles | python3 -m json.tool
```
The saved profile should show:
```json
"asr": {
    "engine": "whisper",
    "max_new_tokens": null,
    "condition_on_previous_text": false,
    "vad_filter": true,
    ...
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: schema-aware param collection in saveProfile (boolean + nullable integer)"
```

---

## Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, under the `### v3.0 — Modular Engine Selection` section, add a bullet for this feature after the existing Engine Selector bullet:

```
- **Whisper Layer 1 Segment Control**: ASR 引擎 schema 加入三個 faster-whisper 原生分段參數（`max_new_tokens`／每句字幕長度上限、`condition_on_previous_text`、`vad_filter`），透過 Profile 表單動態參數面板控制；前端新增 boolean 類型欄位支援同 nullable integer placeholder
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for Whisper Layer 1 segment control"
```
