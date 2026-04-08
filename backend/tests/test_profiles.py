import pytest
import json
from pathlib import Path


@pytest.fixture
def config_dir(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"active_profile": None}))
    return tmp_path


def test_validate_profile_valid(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    profile_data = {
        "name": "Test Profile",
        "description": "For testing",
        "asr": {"engine": "whisper", "model_size": "tiny", "language": "en", "device": "cpu"},
        "translation": {"engine": "qwen2.5-3b", "quantization": "q4", "temperature": 0.1, "glossary_id": None}
    }
    errors = mgr.validate(profile_data)
    assert errors == []


def test_validate_profile_missing_name(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    profile_data = {
        "description": "No name",
        "asr": {"engine": "whisper", "model_size": "tiny", "language": "en", "device": "cpu"},
        "translation": {"engine": "qwen2.5-3b", "quantization": "q4", "temperature": 0.1, "glossary_id": None}
    }
    errors = mgr.validate(profile_data)
    assert "name is required" in errors


def test_validate_profile_invalid_asr_engine(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    profile_data = {
        "name": "Bad Engine",
        "description": "",
        "asr": {"engine": "nonexistent", "model_size": "tiny", "language": "en", "device": "cpu"},
        "translation": {"engine": "qwen2.5-3b", "quantization": "q4", "temperature": 0.1, "glossary_id": None}
    }
    errors = mgr.validate(profile_data)
    assert any("asr.engine" in e for e in errors)


def test_validate_profile_missing_asr(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    profile_data = {
        "name": "No ASR",
        "description": "",
        "translation": {"engine": "qwen2.5-3b", "quantization": "q4", "temperature": 0.1, "glossary_id": None}
    }
    errors = mgr.validate(profile_data)
    assert "asr is required" in errors


VALID_PROFILE = {
    "name": "Dev Default",
    "description": "Development testing profile",
    "asr": {
        "engine": "whisper",
        "model_size": "tiny",
        "language": "en",
        "device": "cpu"
    },
    "translation": {
        "engine": "qwen2.5-3b",
        "quantization": "q4",
        "temperature": 0.1,
        "glossary_id": None
    }
}


def test_create_profile(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    profile = mgr.create(VALID_PROFILE)
    assert profile["id"]
    assert profile["name"] == "Dev Default"
    assert profile["asr"]["engine"] == "whisper"
    assert profile["created_at"] > 0


def test_create_profile_invalid_raises(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    with pytest.raises(ValueError):
        mgr.create({"name": ""})


def test_get_profile(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    created = mgr.create(VALID_PROFILE)
    fetched = mgr.get(created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "Dev Default"


def test_get_nonexistent_returns_none(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    assert mgr.get("nonexistent") is None


def test_list_profiles(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    mgr.create({**VALID_PROFILE, "name": "Bravo"})
    mgr.create({**VALID_PROFILE, "name": "Alpha"})
    profiles = mgr.list_all()
    assert len(profiles) == 2
    assert profiles[0]["name"] == "Alpha"
    assert profiles[1]["name"] == "Bravo"


def test_update_profile(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    created = mgr.create(VALID_PROFILE)
    updated = mgr.update(created["id"], {
        "name": "Updated Name",
        "asr": {**VALID_PROFILE["asr"], "model_size": "base"},
        "translation": VALID_PROFILE["translation"],
    })
    assert updated["name"] == "Updated Name"
    assert updated["asr"]["model_size"] == "base"
    assert updated["id"] == created["id"]


def test_update_nonexistent_returns_none(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    assert mgr.update("nonexistent", VALID_PROFILE) is None


def test_delete_profile(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    created = mgr.create(VALID_PROFILE)
    assert mgr.delete(created["id"]) is True
    assert mgr.get(created["id"]) is None


def test_delete_nonexistent_returns_false(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    assert mgr.delete("nonexistent") is False


def test_set_and_get_active_profile(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    p1 = mgr.create({**VALID_PROFILE, "name": "Profile 1"})
    p2 = mgr.create({**VALID_PROFILE, "name": "Profile 2"})
    mgr.set_active(p1["id"])
    assert mgr.get_active()["id"] == p1["id"]
    mgr.set_active(p2["id"])
    assert mgr.get_active()["id"] == p2["id"]


def test_get_active_when_none_set(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    assert mgr.get_active() is None


def test_delete_active_profile_clears_active(config_dir):
    from profiles import ProfileManager
    mgr = ProfileManager(config_dir)
    created = mgr.create(VALID_PROFILE)
    mgr.set_active(created["id"])
    mgr.delete(created["id"])
    assert mgr.get_active() is None
