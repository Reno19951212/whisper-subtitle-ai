# Proof-reading Editor Design (Phase 5)

## Purpose

A dedicated UI page for broadcast operators to review, edit, and approve translated subtitles before rendering them into the final video output. This is the human QA layer between machine translation and burnt-in subtitle delivery.

## File Structure

```
frontend/
├── proofread.html              # Standalone proof-reading editor page
backend/
├── app.py                      # Modified: approval API endpoints + proofread entry link
frontend/
├── index.html                  # Modified: add "校對" button on file cards
```

## Layout: Side-by-Side (Video + Table)

```
┌──────────────────────────────────────────────────────────┐
│  Proof-reading Editor                    [Approve All ✓] │
├──────────────────────┬───────────────────────────────────┤
│                      │  #  │ English     │ 中文翻譯    │ ○ │
│   Video Player       │  1  │ Good eve..  │ 各位晚..    │ ✓ │
│                      │  2  │ The Chief.. │ 行政長..    │ ✎ │
│   [subtitle overlay] │  3  │ Police...   │ 警方...     │ ○ │
│                      │  4  │ Typhoon...  │ 颱風...     │ ○ │
│                      │  5  │ ...         │ ...         │ ○ │
├──────────────────────┴───────────────────────────────────┤
│  Progress: 1/24 approved    [Approve All Unchanged] [Render →] │
└──────────────────────────────────────────────────────────┘
```

- Left panel: Video player with subtitle overlay showing the currently active segment
- Right panel: Scrollable table of all translated segments
- Bottom bar: Progress indicator + bulk actions

## Segment Status

Each translated segment has a `status` field:

| Status | Icon | Meaning |
|---|---|---|
| `pending` | ○ | Not reviewed yet |
| `approved` | ✓ | Approved (original or edited) |
| `editing` | ✎ | Currently being edited (transient, frontend-only) |

## Features

### Video Sync

- Click any segment row → video seeks to `segment.start`
- As video plays, the current segment is highlighted in the table
- Subtitle overlay shows the `zh_text` of the active segment

### Inline Editing

- Click the Chinese text cell → becomes an editable textarea
- Enter → save edit via `PATCH /api/files/:id/translations/:idx`, auto-approve the segment
- Escape → cancel edit, revert to original text
- The edited text is saved to the backend and persists

### Per-Segment Approval

- Click the status icon (○) → toggles to approved (✓)
- Calls `POST /api/files/:id/translations/:idx/approve`
- Can also approve by pressing Enter on a selected row

### Bulk Approval

- "Approve All Unchanged" button → approves all segments still in `pending` status that have not been manually edited
- Calls `POST /api/files/:id/translations/approve-all`
- Shows confirmation: "Approve 22 unchanged segments?"

### Render Button

- "Render →" button → only enabled when ALL segments are `approved`
- Disabled state shows tooltip: "Approve all segments before rendering"
- When clicked, triggers Phase 6 burn-in flow (future — for now shows "Coming in Phase 6" toast)

### Keyboard Shortcuts

| Key | Action |
|---|---|
| ↓ / Tab | Next segment |
| ↑ / Shift+Tab | Previous segment |
| Enter | Approve current segment (or save if editing) |
| E | Start editing current segment's Chinese text |
| Escape | Cancel editing |
| Space | Play/pause video |

## Backend API

### New Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/files/:id/translations` | Get all translated segments with status |
| PATCH | `/api/files/:id/translations/:idx` | Update zh_text of segment at index, auto-approve |
| POST | `/api/files/:id/translations/:idx/approve` | Approve single segment |
| POST | `/api/files/:id/translations/approve-all` | Approve all pending (unchanged) segments |
| GET | `/api/files/:id/translations/status` | Get approval progress: {total, approved, pending} |

### Data Model Change

The `translations` array in `_file_registry[file_id]` stores `TranslatedSegment` dicts. Each gets an added `status` field:

```json
{
  "start": 0.0,
  "end": 2.5,
  "en_text": "Good evening everyone.",
  "zh_text": "各位晚上好。",
  "status": "pending"
}
```

When `POST /api/translate` stores translations, all segments start with `status: "pending"`.

When `PATCH /api/files/:id/translations/:idx` updates `zh_text`, the segment is auto-set to `status: "approved"`.

### Modify existing POST /api/translate

After translations are stored, ensure each segment has `status: "pending"`:

```python
for t in translated:
    t["status"] = "pending"
_update_file(file_id, translations=translated, translation_status='done')
```

## Frontend: proofread.html

### Page Structure

Standalone HTML file (no build step, same as index.html pattern). Reads `file_id` from URL query parameter.

```
proofread.html?file_id=abc123
```

### Initialization

1. Fetch `/api/files/:id/translations` → populate segment table
2. Fetch `/api/files/:id/media` → load video player
3. Set up keyboard event listeners
4. Set up video `timeupdate` listener for active segment highlighting

### CSS

Follows the same dark theme as `index.html`. Key elements:

- `.segment-row` — table row, clickable
- `.segment-row.active` — currently playing segment (highlighted border)
- `.segment-row.approved` — green left border
- `.segment-row.pending` — no special border
- `.zh-cell.editing` — textarea with purple border
- `.status-icon` — clickable status toggle
- `.progress-bar` — approval progress at bottom

### Video Subtitle Overlay

Same approach as `index.html` — a positioned `<div>` over the video element showing the active segment's `zh_text`.

## Entry Point from index.html

Add a "校對" (Proofread) button on file cards in `index.html`. The button:

- Appears only when `translation_status === 'done'`
- Links to `proofread.html?file_id={id}`
- Styled as a secondary button next to existing download buttons

## Testing

### Backend

- API tests for all 5 new endpoints
- Test approval status tracking
- Test bulk approve only affects pending segments
- Test PATCH auto-approves on edit

### Frontend

- Manual testing (no automated frontend tests for this single-file app):
  - Load proofread page with a translated file
  - Click segments → video seeks
  - Edit Chinese text → saves and approves
  - Approve individual segments
  - Approve all unchanged
  - Keyboard navigation works
  - Render button enables only when all approved

## What Does NOT Change

- ASR pipeline
- Translation pipeline
- Glossary manager
- Profile system
- Existing index.html functionality (file upload, transcription, live mode)
