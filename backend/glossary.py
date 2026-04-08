"""
Glossary management module for the broadcast subtitle pipeline.

Glossaries store bilingual term pairs (en/zh) used to guide ASR and
translation engines toward domain-specific vocabulary.
"""

import csv
import io
import json
import os
import time
import uuid
from pathlib import Path
from typing import List, Optional

GLOSSARIES_DIRNAME = "glossaries"


class GlossaryManager:
    """
    Manages glossary CRUD, entry management, and CSV import/export.

    All mutating operations return new data structures rather than
    modifying in place, keeping the persistence layer as the single
    source of truth.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = Path(config_dir)
        self._glossaries_dir = self._config_dir / GLOSSARIES_DIRNAME
        self._glossaries_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, data: dict) -> List[str]:
        """
        Validate a glossary data dict against the schema.

        Returns a list of human-readable error strings.
        An empty list means the data is valid.
        """
        errors = []

        name = data.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            errors.append("name is required")

        entries = data.get("entries")
        if entries is not None:
            if not isinstance(entries, list):
                errors.append("entries must be a list")
            else:
                for i, entry in enumerate(entries):
                    entry_errors = self.validate_entry(entry)
                    for err in entry_errors:
                        errors.append(f"entries[{i}]: {err}")

        return errors

    def validate_entry(self, entry: dict) -> List[str]:
        """
        Validate a single glossary entry.

        Returns a list of human-readable error strings.
        An empty list means the entry is valid.
        """
        errors = []

        en = entry.get("en")
        if en is None:
            errors.append("en is required")
        elif not isinstance(en, str) or not en.strip():
            errors.append("en must be a non-empty string")

        zh = entry.get("zh")
        if zh is None:
            errors.append("zh is required")
        elif not isinstance(zh, str) or not zh.strip():
            errors.append("zh must be a non-empty string")

        return errors

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, data: dict) -> dict:
        """
        Create a new glossary from validated data.

        Returns the stored glossary dict (with `id` field set).
        Raises ValueError if data is invalid.
        """
        errors = self.validate(data)
        if errors:
            raise ValueError(f"Invalid glossary data: {errors}")

        glossary_id = str(uuid.uuid4())
        glossary = {
            "id": glossary_id,
            "name": data["name"],
            "description": data.get("description", ""),
            "entries": list(data.get("entries") or []),
            "created_at": time.time(),
        }
        self._write_glossary(glossary_id, glossary)
        return glossary

    def get(self, glossary_id: str) -> Optional[dict]:
        """
        Read a glossary by id.

        Returns the glossary dict, or None if not found.
        """
        path = self._glossary_path(glossary_id)
        if not path.exists():
            return None
        return self._read_glossary(path)

    def list_all(self) -> list:
        """
        Return summaries of all glossaries sorted ascending by name.

        Each summary includes `entry_count` but omits the full `entries`
        list to keep the payload small.
        """
        summaries = []
        for path in self._glossaries_dir.glob("*.json"):
            try:
                glossary = self._read_glossary(path)
                summary = {k: v for k, v in glossary.items() if k != "entries"}
                summary["entry_count"] = len(glossary.get("entries") or [])
                summaries.append(summary)
            except (json.JSONDecodeError, OSError):
                continue
        return sorted(summaries, key=lambda g: (g.get("name") or "").lower())

    def update(self, glossary_id: str, data: dict) -> Optional[dict]:
        """
        Update name and/or description of an existing glossary.

        Entries are preserved from the stored glossary and cannot be
        updated through this method — use add_entry / update_entry /
        delete_entry for entry mutations.

        Returns the updated glossary, or None if glossary_id is not found.
        Raises ValueError if the merged data is invalid.
        """
        existing = self.get(glossary_id)
        if existing is None:
            return None

        merged = {
            **existing,
            "name": data.get("name", existing["name"]),
            "description": data.get("description", existing.get("description", "")),
            "id": glossary_id,
        }

        errors = self.validate(merged)
        if errors:
            raise ValueError(f"Invalid glossary data: {errors}")

        self._write_glossary(glossary_id, merged)
        return merged

    def delete(self, glossary_id: str) -> bool:
        """
        Delete a glossary by id.

        Returns True if deleted, False if not found.
        """
        path = self._glossary_path(glossary_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    # ------------------------------------------------------------------
    # Entry management
    # ------------------------------------------------------------------

    def add_entry(self, glossary_id: str, entry: dict) -> Optional[dict]:
        """
        Append a validated entry to a glossary.

        Returns the updated glossary, or None if glossary_id is not found.
        Raises ValueError if the entry is invalid.
        """
        glossary = self.get(glossary_id)
        if glossary is None:
            return None

        errors = self.validate_entry(entry)
        if errors:
            raise ValueError(f"Invalid entry: {errors}")

        new_entry = {**entry, "id": str(uuid.uuid4())}
        updated = {**glossary, "entries": [*glossary["entries"], new_entry]}
        self._write_glossary(glossary_id, updated)
        return updated

    def update_entry(
        self, glossary_id: str, entry_id: str, entry_data: dict
    ) -> Optional[dict]:
        """
        Update a single entry within a glossary.

        Returns the updated glossary, or None if glossary_id or entry_id
        is not found.
        Raises ValueError if the entry data is invalid.
        """
        glossary = self.get(glossary_id)
        if glossary is None:
            return None

        existing_entry = next(
            (e for e in glossary["entries"] if e.get("id") == entry_id), None
        )
        if existing_entry is None:
            return None

        merged_entry = {**existing_entry, **entry_data, "id": entry_id}
        errors = self.validate_entry(merged_entry)
        if errors:
            raise ValueError(f"Invalid entry: {errors}")

        new_entries = [
            merged_entry if e.get("id") == entry_id else e
            for e in glossary["entries"]
        ]
        updated = {**glossary, "entries": new_entries}
        self._write_glossary(glossary_id, updated)
        return updated

    def delete_entry(self, glossary_id: str, entry_id: str) -> Optional[dict]:
        """
        Remove a single entry from a glossary.

        Returns the updated glossary, or None if glossary_id is not found.
        If entry_id is not found the glossary is returned unchanged.
        """
        glossary = self.get(glossary_id)
        if glossary is None:
            return None

        new_entries = [e for e in glossary["entries"] if e.get("id") != entry_id]
        updated = {**glossary, "entries": new_entries}
        self._write_glossary(glossary_id, updated)
        return updated

    # ------------------------------------------------------------------
    # CSV import / export
    # ------------------------------------------------------------------

    def import_csv(self, glossary_id: str, csv_text: str) -> Optional[dict]:
        """
        Append entries from a CSV string (columns: en, zh) to a glossary.

        Rows with validation errors are skipped.
        Returns the updated glossary, or None if glossary_id is not found.
        """
        glossary = self.get(glossary_id)
        if glossary is None:
            return None

        reader = csv.DictReader(io.StringIO(csv_text))
        new_entries = []
        for row in reader:
            entry = {"en": (row.get("en") or "").strip(), "zh": (row.get("zh") or "").strip()}
            if self.validate_entry(entry):
                continue
            new_entries.append({**entry, "id": str(uuid.uuid4())})

        updated = {**glossary, "entries": [*glossary["entries"], *new_entries]}
        self._write_glossary(glossary_id, updated)
        return updated

    def export_csv(self, glossary_id: str) -> Optional[str]:
        """
        Export the entries of a glossary as a CSV string (columns: en, zh).

        Returns the CSV text, or None if glossary_id is not found.
        """
        glossary = self.get(glossary_id)
        if glossary is None:
            return None

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["en", "zh"])
        writer.writeheader()
        for entry in glossary.get("entries") or []:
            writer.writerow({"en": entry.get("en", ""), "zh": entry.get("zh", "")})
        return output.getvalue()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _glossary_path(self, glossary_id: str) -> Path:
        return self._glossaries_dir / f"{glossary_id}.json"

    def _read_glossary(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_glossary(self, glossary_id: str, glossary: dict) -> None:
        path = self._glossary_path(glossary_id)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, path)
