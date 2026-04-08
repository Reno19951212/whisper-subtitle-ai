import pytest
import json
import shutil
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
