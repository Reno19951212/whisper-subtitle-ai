"""
Tests for GlossaryManager CRUD and validation.

Follows the same pattern as test_profiles.py.
"""

import pytest
import json
from pathlib import Path


@pytest.fixture
def glossary_dir(tmp_path):
    glossaries_dir = tmp_path / "glossaries"
    glossaries_dir.mkdir()
    return tmp_path


VALID_GLOSSARY = {
    "name": "Test Glossary",
    "description": "For testing",
    "entries": [
        {"en": "Legislative Council", "zh": "立法會"},
        {"en": "Chief Executive", "zh": "行政長官"},
    ],
}


def test_validate_valid(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert mgr.validate(VALID_GLOSSARY) == []


def test_validate_missing_name(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert "name is required" in mgr.validate({"description": "no name"})


def test_validate_entry_valid(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert mgr.validate_entry({"en": "hello", "zh": "你好"}) == []


def test_validate_entry_missing_en(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert any("en" in e for e in mgr.validate_entry({"zh": "你好"}))


def test_validate_entry_empty_zh(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert any("zh" in e for e in mgr.validate_entry({"en": "hello", "zh": ""}))


def test_create_glossary(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    result = mgr.create(VALID_GLOSSARY)
    assert result["id"]
    assert result["name"] == "Test Glossary"
    assert len(result["entries"]) == 2
    assert result["created_at"] > 0


def test_create_without_entries(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    result = mgr.create({"name": "Empty"})
    assert result["entries"] == []


def test_create_invalid_raises(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    with pytest.raises(ValueError):
        mgr.create({"name": ""})


def test_get_glossary(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create(VALID_GLOSSARY)
    fetched = mgr.get(created["id"])
    assert fetched["id"] == created["id"]
    assert len(fetched["entries"]) == 2


def test_get_nonexistent(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert mgr.get("nonexistent") is None


def test_list_all(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    mgr.create({**VALID_GLOSSARY, "name": "Bravo"})
    mgr.create({**VALID_GLOSSARY, "name": "Alpha"})
    result = mgr.list_all()
    assert len(result) == 2
    assert result[0]["name"] == "Alpha"
    assert result[1]["name"] == "Bravo"
    assert "entry_count" in result[0]
    assert "entries" not in result[0]


def test_update_glossary(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create(VALID_GLOSSARY)
    updated = mgr.update(created["id"], {"name": "Updated Name"})
    assert updated["name"] == "Updated Name"
    assert len(updated["entries"]) == 2


def test_update_nonexistent(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert mgr.update("nonexistent", {"name": "X"}) is None


def test_delete_glossary(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create(VALID_GLOSSARY)
    assert mgr.delete(created["id"]) is True
    assert mgr.get(created["id"]) is None


def test_delete_nonexistent(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert mgr.delete("nonexistent") is False
