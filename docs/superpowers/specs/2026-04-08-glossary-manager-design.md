# Glossary Manager Design (Phase 4)

## Purpose

Manage terminology glossaries (English → Chinese term mappings) that are injected into translation prompts to ensure consistent, accurate translations of domain-specific terms.

## File Structure

```
backend/
├── glossary.py                          # GlossaryManager — CRUD, entry management, CSV import/export
├── config/glossaries/                   # One JSON file per glossary
│   └── broadcast-news.json              # Default glossary with common HK broadcast terms
├── app.py                               # Modified: glossary REST endpoints + translate integration
```

## Glossary Schema

```json
{
  "id": "broadcast-news",
  "name": "Broadcast News",
  "description": "Common terms for HK news broadcasting",
  "entries": [
    {"en": "Legislative Council", "zh": "立法會"},
    {"en": "Chief Executive", "zh": "行政長官"},
    {"en": "Hong Kong", "zh": "香港"}
  ],
  "created_at": 1712534400,
  "updated_at": 1712534400
}
```

Entry schema: `{"en": str, "zh": str}`. Both fields required, non-empty.

## GlossaryManager

Follows the same pattern as ProfileManager (JSON file storage, atomic writes).

### Methods

```python
class GlossaryManager:
    def __init__(self, config_dir: Path):
        """Sets up glossaries/ directory under config_dir."""

    def validate(self, data: dict) -> list[str]:
        """Validate glossary data. Returns error list."""

    def validate_entry(self, entry: dict) -> list[str]:
        """Validate a single entry. Returns error list."""

    def create(self, data: dict) -> dict:
        """Create glossary. data must have name; entries optional."""

    def get(self, glossary_id: str) -> dict | None:
        """Get glossary with all entries."""

    def list_all(self) -> list[dict]:
        """List all glossaries. Returns summary (id, name, description, entry_count) without entries."""

    def update(self, glossary_id: str, data: dict) -> dict | None:
        """Update glossary name/description. Does not replace entries."""

    def delete(self, glossary_id: str) -> bool:
        """Delete glossary file."""

    def add_entry(self, glossary_id: str, entry: dict) -> dict | None:
        """Add entry to glossary. Returns updated glossary or None if not found."""

    def update_entry(self, glossary_id: str, entry_index: int, entry: dict) -> dict | None:
        """Update entry at index. Returns updated glossary or None."""

    def delete_entry(self, glossary_id: str, entry_index: int) -> dict | None:
        """Delete entry at index. Returns updated glossary or None."""

    def import_csv(self, glossary_id: str, csv_content: str) -> int:
        """Import entries from CSV string. Appends to existing entries. Returns count imported."""

    def export_csv(self, glossary_id: str) -> str | None:
        """Export entries as CSV string. Returns None if glossary not found."""
```

### Validation Rules

- `name` is required (non-empty string)
- `entries` is optional on create (defaults to empty list)
- Each entry must have non-empty `en` and `zh` fields

### CSV Format

```csv
en,zh
Legislative Council,立法會
Chief Executive,行政長官
```

Import: Reads CSV with `en,zh` header. Skips rows with empty fields. Appends to existing entries (does not replace).

Export: Writes CSV with `en,zh` header followed by all entries.

## REST Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/glossaries` | List all (summary, no entries) |
| POST | `/api/glossaries` | Create new glossary |
| GET | `/api/glossaries/:id` | Get glossary with entries |
| PATCH | `/api/glossaries/:id` | Update name/description |
| DELETE | `/api/glossaries/:id` | Delete glossary |
| POST | `/api/glossaries/:id/entries` | Add entry |
| PATCH | `/api/glossaries/:id/entries/:idx` | Update entry at index |
| DELETE | `/api/glossaries/:id/entries/:idx` | Delete entry at index |
| POST | `/api/glossaries/:id/import` | Import CSV (body: raw CSV text or JSON with csv_content field) |
| GET | `/api/glossaries/:id/export` | Export CSV (returns text/csv) |

## Default Glossary

`config/glossaries/broadcast-news.json` — pre-loaded with common HK broadcast terms:

```json
{
  "id": "broadcast-news",
  "name": "Broadcast News",
  "description": "Common terms for Hong Kong news broadcasting",
  "entries": [
    {"en": "Legislative Council", "zh": "立法會"},
    {"en": "Chief Executive", "zh": "行政長官"},
    {"en": "Hong Kong", "zh": "香港"},
    {"en": "government", "zh": "政府"},
    {"en": "police", "zh": "警方"},
    {"en": "hospital", "zh": "醫院"},
    {"en": "district", "zh": "地區"},
    {"en": "typhoon", "zh": "颱風"},
    {"en": "stock market", "zh": "股市"},
    {"en": "inflation", "zh": "通脹"}
  ],
  "created_at": 1712534400,
  "updated_at": 1712534400
}
```

## Integration with Translation Pipeline

Modify `POST /api/translate` in app.py:

Before (current):
```python
translated = engine.translate(asr_segments, glossary=[], style=style)
```

After:
```python
glossary_entries = []
glossary_id = translation_config.get("glossary_id")
if glossary_id:
    glossary_data = _glossary_manager.get(glossary_id)
    if glossary_data:
        glossary_entries = glossary_data.get("entries", [])

translated = engine.translate(asr_segments, glossary=glossary_entries, style=style)
```

## Testing

- Unit tests for GlossaryManager: create, get, list, update, delete
- Unit tests for entry management: add, update, delete entries
- Unit tests for CSV import/export
- Unit tests for validation
- API tests for all REST endpoints
- Integration test: translate with glossary_id → verify glossary terms injected

## What Does NOT Change

- Translation engine interface (glossary parameter already exists)
- Profile system (glossary_id field already in profile schema)
- ASR pipeline
- Frontend (glossary management UI is not part of this phase)
