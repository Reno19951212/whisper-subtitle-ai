# Engine Selector + Dynamic Params Panel — Design Spec

**Date:** 2026-04-11  
**Feature:** Dynamic Engine Selection with Schema-Driven Parameters  
**Scope:** `frontend/index.html` — Profile edit/create form (ASR 設定 + 翻譯設定 sections)

---

## 1. Overview

The backend exposes full engine discovery APIs (list engines with availability, per-engine param schemas, translation model lists), but the frontend profile form uses hardcoded engine dropdowns with **incorrect engine name values** ("qwen3" instead of "qwen3-asr"). This spec defines a schema-driven replacement where engine lists are fetched from the API and param fields are generated dynamically from each engine's schema.

**Only `frontend/index.html` is modified. No backend changes required.**

---

## 2. Layout & Components

The Profile form's **ASR 設定** and **翻譯設定** collapsible sections are replaced. **基本資訊** and **字型設定** are unchanged.

### ASR 設定 (new)

```
ASR 設定 ▼
┌────────────────────────────────────┐
│ 引擎:  [whisper ▼]  🟢 可用        │  ← dynamic from API, dot = availability
│                                    │
│  ── 引擎參數 ──                     │  ← dynamically generated from params schema
│ Model Size:  [small ▼]             │
│ Language:    [en ▼]                │
│ Device:      [auto ▼]              │
│                                    │
│ Language Config ID: [en      ]     │  ← static field (profile-specific, not in schema)
└────────────────────────────────────┘
```

### 翻譯設定 (new)

```
翻譯設定 ▼
┌────────────────────────────────────┐
│ 引擎:  [mock ▼]  🟢 可用           │  ← dynamic from API
│ Model: mock  ✓ 已載入              │  ← model name + availability from /models; e.g. "qwen2.5:72b ✗ 未載入"
│                                    │
│  ── 引擎參數 ──                     │  ← dynamically generated from params schema
│ Style: [formal ▼]                  │
│                                    │
│ 詞彙表: [無 ▼]                     │  ← static, from glossariesData (unchanged)
└────────────────────────────────────┘
```

### Availability Indicator

- Green dot (●) + label "可用" → `available: true`
- Grey dot (●) + label "不可用" → `available: false`
- Unavailable engines in dropdown: `disabled` attribute + `title="此引擎目前不可用"`

**Pre-select rule for existing profiles:** When opening an edit form for a profile whose `asr.engine` or `translation.engine` is currently unavailable, still pre-select that engine value (set `select.value` via JS). Do NOT disable that option — only options that the user has **not** already selected should be disabled if unavailable. This preserves the saved config without forcing an unwanted engine change.

---

## 3. Data Flow & State

### New JS State Variables

Add after existing `let asrEnginesData` (reuse if already declared), otherwise add new:

```js
let asrEnginesData = []         // [{ engine, available, description }, ...]
let translationEnginesData = [] // [{ engine, available, description }, ...]
let currentAsrSchema = null     // last-fetched ASR params schema ({ engine, params: {...} })
let currentTranslationSchema = null  // last-fetched translation params schema
```

`currentAsrSchema` and `currentTranslationSchema` are updated on every engine change and cleared to `null` when the form is cancelled or a new form is opened. Models data is fetched and rendered directly into the DOM without being stored.

### Page Load

At page load (`DOMContentLoaded`), fetch engine lists once alongside existing `loadProfiles()` and `loadGlossaries()`:

```js
async function loadAsrEngines() {
  const resp = await fetch(`${API_BASE}/api/asr/engines`);
  const data = await resp.json();
  asrEnginesData = data.engines || [];
}

async function loadTranslationEngines() {
  const resp = await fetch(`${API_BASE}/api/translation/engines`);
  const data = await resp.json();
  translationEnginesData = data.engines || [];
}
```

Both are called in parallel at startup. Engine lists do not change at runtime, so no re-fetch is needed.

### Form Open (edit or create)

`buildProfileFormHTML(profile)` remains a **synchronous** function returning an HTML string. It renders the skeleton only — engine dropdowns populated, params containers empty. After inserting the HTML into the DOM, a separate async function is called to populate the params areas:

```
Step 1 (sync): card.innerHTML = buildProfileFormHTML(profile)
               → renders engine dropdowns + empty <div class="pf-engine-params"> containers

Step 2 (async): await initEngineParamsForForm(profile)
               → fetches params schemas + (for translation) models
               → renders dynamic fields into the containers
               → pre-fills with profile values
```

`buildProfileFormHTML` responsibilities:
1. Render engine dropdown from `asrEnginesData` / `translationEnginesData`; mark options as `disabled` where `available: false` (except the currently pre-selected engine — see Pre-select rule above)
2. Pre-select `profile.asr.engine` / `profile.translation.engine` (for new profiles: first available engine; if none available, first in list)
3. Render empty `<div id="asr-params-container" class="pf-engine-params">` and `<div id="translation-params-container" class="pf-engine-params">` placeholders

`initEngineParamsForForm(profile)` responsibilities:
1. Show loading spinner in both params containers; disable Save button
2. Fetch `GET /api/asr/engines/<engine>/params` → set `currentAsrSchema` → render fields pre-filled from `profile.asr.*`
3. Fetch `GET /api/translation/engines/<engine>/params` + `GET /api/translation/engines/<engine>/models` (parallel) → set `currentTranslationSchema` → render fields; update model info row
4. Re-enable Save button (if no errors)

### Engine Change (onchange)

**To prevent race conditions from rapid switching, disable the engine dropdown for the duration of the fetch.**

When the ASR engine dropdown changes:
```
→ disable ASR engine dropdown + Save button
→ show loading spinner in params area
→ fetch GET /api/asr/engines/<new>/params → set currentAsrSchema
→ clear params area → render new fields with schema defaults
→ re-enable ASR engine dropdown + Save button
```

When the translation engine dropdown changes:
```
→ disable translation engine dropdown + Save button
→ show loading spinner in params area
→ fetch GET /api/translation/engines/<new>/params (parallel with models fetch)
→ fetch GET /api/translation/engines/<new>/models
→ set currentTranslationSchema
→ clear params area → render new fields with schema defaults
→ update model info row
→ re-enable translation engine dropdown + Save button
```

### API Calls Summary

| Action | API Call |
|--------|----------|
| Page load | `GET /api/asr/engines` + `GET /api/translation/engines` |
| Form open / engine pre-select | `GET /api/asr/engines/<engine>/params` |
| Form open (translation) | `GET /api/translation/engines/<engine>/params` + `GET /api/translation/engines/<engine>/models` |
| ASR engine changed | `GET /api/asr/engines/<new>/params` |
| Translation engine changed | `GET /api/translation/engines/<new>/params` + `GET /api/translation/engines/<new>/models` |

---

## 4. Schema → DOM Rendering

### Excluded Params

Some schema params must NOT be rendered as form fields:

```js
const EXCLUDED_TRANSLATION_PARAMS = ['model'];
// 'model' from Ollama schema is the Ollama model tag (e.g. "qwen2.5:72b").
// The engine dropdown already conveys model selection; rendering 'model' separately
// would allow user to create a mismatch (engine="qwen2.5-3b", model="qwen2.5:72b").
// It is shown informational-only in the Model info row instead.

const EXCLUDED_ASR_PARAMS = [];
```

Skip any param whose name appears in the relevant exclusion list before rendering.

### `renderParamField(name, paramSchema, currentValue)`

Render one form field from a param schema entry:

| Condition | Rendered element |
|-----------|-----------------|
| `paramSchema.enum` exists | `<select>` with all enum values as `<option>` |
| `paramSchema.type === "number"` or `"integer"` | `<input type="number">` |
| `paramSchema.type === "string"` (no enum) | `<input type="text">` |

**Value priority:** `currentValue` (from existing profile) → `paramSchema.default` → empty

**Label:** Use `name` (formatted as human-readable label). Show `paramSchema.description` as `title` tooltip on the label.

**Note on `temperature` with mock engine:** The mock engine schema does not include `temperature`. If an existing profile has `translation.temperature` set, opening and saving that profile with mock engine selected will drop `temperature` from the payload. This is **expected and correct** — the mock engine does not use temperature. Switching to an Ollama engine will restore the temperature field (defaulting to schema default `0.1`).

### Static Fields (always present, not schema-driven)

| Section | Field | Notes |
|---------|-------|-------|
| ASR 設定 | Language Config ID | text input, pre-fill from `profile.asr.language_config_id`, default `"en"` |
| 翻譯設定 | 詞彙表 | select from `glossariesData`, pre-fill from `profile.translation.glossary_id` |

Static fields are rendered **after** dynamic params fields in their respective sections.

### Engine Params Container Structure

```html
<div class="pf-engine-params" id="asr-params-container">
  <!-- loading spinner OR dynamically rendered fields -->
</div>
```

---

## 5. Save Payload

`saveProfile()` must always send **complete** `asr`, `translation`, and `font` blocks (backend PATCH does shallow top-level merge — partial nested objects replace the entire block).

**Guard against null schema before collecting:**

```js
async function saveProfile() {
  if (!currentAsrSchema || !currentTranslationSchema) {
    showToast('引擎參數未載入，請重試', 'error');
    return;
  }
  // ... proceed with save
}
```

**Collecting dynamic ASR params:**

```js
const asrParams = {};
for (const name of Object.keys(currentAsrSchema.params)) {
  if (EXCLUDED_ASR_PARAMS.includes(name)) continue;
  const el = document.getElementById(`pf-asr-${name}`);
  if (el) asrParams[name] = (el.type === 'number') ? Number(el.value) : el.value;
}
const asrBlock = {
  engine: document.getElementById('pf-asr-engine').value,
  language_config_id: document.getElementById('pf-asr-language_config_id').value,
  ...asrParams,
};
```

Same pattern for translation block (skip `EXCLUDED_TRANSLATION_PARAMS`; append `glossary_id` from the static glossary dropdown; set `glossary_id: null` if "無" selected).

**`currentAsrSchema` and `currentTranslationSchema`** are JS variables declared alongside the other state vars (`editingProfileId`, etc.), set each time a params fetch completes. They are updated on every engine change and cleared (`null`) when the form is cancelled or a new form is opened.

---

## 6. Error Handling

| Scenario | Handling |
|----------|----------|
| `GET /api/asr/engines` or `/translation/engines` fails on page load | Toast "無法載入引擎清單"; engine dropdown shows placeholder "-- 載入失敗 --"; Save disabled |
| `GET /api/.../params` fails | Params area shows "無法載入引擎參數，請重試"; Save button disabled until resolved |
| `GET /api/.../models` fails | Model info row shows "—"; does NOT block save |
| Engine `available: false` selected | Allowed (user may be preparing offline config); backend validate will catch runtime errors |
| Params fetch in progress | Spinner shown in params area; Save disabled during fetch |
| Duplicate submission | Save button disabled during API call (existing behaviour, unchanged) |

---

## 7. Files Changed

- `frontend/index.html` — modify Profile form's ASR 設定 and 翻譯設定 sections only

No new files. No backend changes.
