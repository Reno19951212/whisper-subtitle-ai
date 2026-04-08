import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client_with_file(tmp_path):
    from app import app, _init_profile_manager, _init_glossary_manager, _file_registry, _registry_lock

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"active_profile": None}))
    _init_profile_manager(tmp_path)

    glossaries_dir = tmp_path / "glossaries"
    glossaries_dir.mkdir()
    _init_glossary_manager(tmp_path)

    test_file_id = "test-file-001"
    with _registry_lock:
        _file_registry[test_file_id] = {
            "id": test_file_id,
            "original_name": "test.mp4",
            "stored_name": "test.mp4",
            "size": 1000,
            "status": "done",
            "uploaded_at": 1700000000,
            "segments": [
                {"id": 0, "start": 0.0, "end": 2.5, "text": "Good evening."},
                {"id": 1, "start": 2.5, "end": 5.0, "text": "Welcome to the news."},
                {"id": 2, "start": 5.0, "end": 8.0, "text": "The typhoon is approaching."},
            ],
            "text": "Good evening. Welcome to the news. The typhoon is approaching.",
            "error": None,
            "model": "tiny",
            "backend": "faster-whisper",
            "translations": [
                {"start": 0.0, "end": 2.5, "en_text": "Good evening.", "zh_text": "各位晚上好。", "status": "pending"},
                {"start": 2.5, "end": 5.0, "en_text": "Welcome to the news.", "zh_text": "歡迎收看新聞。", "status": "pending"},
                {"start": 5.0, "end": 8.0, "en_text": "The typhoon is approaching.", "zh_text": "颱風正在逼近。", "status": "pending"},
            ],
            "translation_status": "done",
        }

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, test_file_id

    with _registry_lock:
        _file_registry.pop(test_file_id, None)


def test_get_translations(client_with_file):
    client, file_id = client_with_file
    resp = client.get(f"/api/files/{file_id}/translations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["translations"]) == 3
    assert data["translations"][0]["zh_text"] == "各位晚上好。"
    assert data["translations"][0]["status"] == "pending"


def test_get_translations_not_found(client_with_file):
    client, _ = client_with_file
    resp = client.get("/api/files/nonexistent/translations")
    assert resp.status_code == 404


def test_update_translation(client_with_file):
    client, file_id = client_with_file
    resp = client.patch(f"/api/files/{file_id}/translations/0", json={"zh_text": "大家好。"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["translation"]["zh_text"] == "大家好。"
    assert data["translation"]["status"] == "approved"


def test_update_translation_out_of_range(client_with_file):
    client, file_id = client_with_file
    resp = client.patch(f"/api/files/{file_id}/translations/99", json={"zh_text": "test"})
    assert resp.status_code == 404


def test_approve_single(client_with_file):
    client, file_id = client_with_file
    resp = client.post(f"/api/files/{file_id}/translations/1/approve")
    assert resp.status_code == 200
    resp2 = client.get(f"/api/files/{file_id}/translations")
    assert resp2.get_json()["translations"][1]["status"] == "approved"


def test_approve_all(client_with_file):
    client, file_id = client_with_file
    client.post(f"/api/files/{file_id}/translations/0/approve")
    resp = client.post(f"/api/files/{file_id}/translations/approve-all")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["approved_count"] == 2

    resp2 = client.get(f"/api/files/{file_id}/translations/status")
    status = resp2.get_json()
    assert status["approved"] == 3
    assert status["pending"] == 0


def test_get_translation_status(client_with_file):
    client, file_id = client_with_file
    resp = client.get(f"/api/files/{file_id}/translations/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 3
    assert data["approved"] == 0
    assert data["pending"] == 3


def test_get_translations_no_translations(client_with_file):
    client, _ = client_with_file
    from app import _file_registry, _registry_lock
    with _registry_lock:
        _file_registry["no-trans"] = {
            "id": "no-trans", "original_name": "x.mp4", "stored_name": "x.mp4",
            "size": 100, "status": "done", "uploaded_at": 1, "segments": [],
            "text": "", "error": None, "model": None, "backend": None,
        }
    resp = client.get("/api/files/no-trans/translations")
    assert resp.status_code == 200
    assert resp.get_json()["translations"] == []
    with _registry_lock:
        _file_registry.pop("no-trans", None)
