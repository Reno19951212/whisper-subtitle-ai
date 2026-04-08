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


def test_add_entry(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create({"name": "Test", "entries": []})
    updated = mgr.add_entry(created["id"], {"en": "hello", "zh": "你好"})
    assert len(updated["entries"]) == 1
    assert updated["entries"][0]["en"] == "hello"

def test_add_entry_invalid_raises(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create({"name": "Test"})
    with pytest.raises(ValueError):
        mgr.add_entry(created["id"], {"en": "", "zh": "你好"})

def test_add_entry_nonexistent_glossary(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert mgr.add_entry("nonexistent", {"en": "hi", "zh": "嗨"}) is None

def test_update_entry(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    # Use add_entry so the entry gets a UUID id assigned
    created = mgr.create({"name": "Test", "entries": []})
    with_entry = mgr.add_entry(created["id"], {"en": "Legislative Council", "zh": "立法會"})
    first_entry_id = with_entry["entries"][0]["id"]
    updated = mgr.update_entry(created["id"], first_entry_id, {"en": "LegCo", "zh": "立法會"})
    assert updated["entries"][0]["en"] == "LegCo"
    assert updated["entries"][0]["zh"] == "立法會"

def test_update_entry_out_of_range(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create(VALID_GLOSSARY)
    assert mgr.update_entry(created["id"], "nonexistent-entry-id", {"en": "x", "zh": "y"}) is None

def test_delete_entry(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    # Use add_entry so entries have UUID ids assigned
    created = mgr.create({"name": "Test", "entries": []})
    mgr.add_entry(created["id"], {"en": "Legislative Council", "zh": "立法會"})
    with_two = mgr.add_entry(created["id"], {"en": "Chief Executive", "zh": "行政長官"})
    first_entry_id = with_two["entries"][0]["id"]
    updated = mgr.delete_entry(created["id"], first_entry_id)
    assert len(updated["entries"]) == 1
    assert updated["entries"][0]["en"] == "Chief Executive"

def test_delete_entry_out_of_range(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create(VALID_GLOSSARY)
    # delete_entry with unknown id returns glossary unchanged (not None)
    result = mgr.delete_entry(created["id"], "nonexistent-entry-id")
    assert result is not None
    assert len(result["entries"]) == 2

def test_import_csv(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create({"name": "CSV Test", "entries": []})
    csv_content = "en,zh\nhello,你好\nworld,世界\n,skip_empty\n"
    result = mgr.import_csv(created["id"], csv_content)
    assert result is not None
    assert len(result["entries"]) == 2
    assert result["entries"][0]["en"] == "hello"

def test_import_csv_appends(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create(VALID_GLOSSARY)
    csv_content = "en,zh\nnew term,新詞\n"
    result = mgr.import_csv(created["id"], csv_content)
    assert result is not None
    assert len(result["entries"]) == 3

def test_import_csv_nonexistent_raises(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    # import_csv returns None when glossary not found (does not raise)
    assert mgr.import_csv("nonexistent", "en,zh\nhello,你好\n") is None

def test_export_csv(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    created = mgr.create(VALID_GLOSSARY)
    csv_str = mgr.export_csv(created["id"])
    assert "en,zh" in csv_str
    assert "Legislative Council" in csv_str
    assert "立法會" in csv_str

def test_export_csv_nonexistent(glossary_dir):
    from glossary import GlossaryManager
    mgr = GlossaryManager(glossary_dir)
    assert mgr.export_csv("nonexistent") is None
