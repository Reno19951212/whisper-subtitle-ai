import pytest


def test_create_whisper_engine():
    from asr import create_asr_engine
    config = {"engine": "whisper", "model_size": "tiny", "language": "en", "device": "cpu"}
    engine = create_asr_engine(config)
    assert engine is not None
    info = engine.get_info()
    assert info["engine"] == "whisper"


def test_create_qwen3_engine():
    from asr import create_asr_engine
    config = {"engine": "qwen3-asr", "model_size": "large", "language": "en", "device": "cuda"}
    engine = create_asr_engine(config)
    info = engine.get_info()
    assert info["engine"] == "qwen3-asr"
    assert info["available"] is False


def test_create_flg_engine():
    from asr import create_asr_engine
    config = {"engine": "flg-asr", "model_size": "large", "language": "en", "device": "cuda"}
    engine = create_asr_engine(config)
    info = engine.get_info()
    assert info["engine"] == "flg-asr"
    assert info["available"] is False


def test_create_unknown_engine_raises():
    from asr import create_asr_engine
    with pytest.raises(ValueError, match="Unknown ASR engine"):
        create_asr_engine({"engine": "nonexistent"})


def test_stub_transcribe_raises():
    from asr import create_asr_engine
    engine = create_asr_engine({"engine": "qwen3-asr", "model_size": "large", "language": "en"})
    with pytest.raises(NotImplementedError):
        engine.transcribe("/tmp/test.wav", language="en")


def test_flg_stub_transcribe_raises():
    from asr import create_asr_engine
    engine = create_asr_engine({"engine": "flg-asr", "model_size": "large", "language": "en"})
    with pytest.raises(NotImplementedError):
        engine.transcribe("/tmp/test.wav", language="en")


from unittest.mock import patch, MagicMock
from collections import namedtuple


def test_whisper_engine_transcribe_faster():
    from asr.whisper_engine import WhisperEngine
    engine = WhisperEngine({"engine": "whisper", "model_size": "tiny", "language": "en", "device": "cpu"})

    MockSeg = namedtuple("MockSeg", ["start", "end", "text", "words"])
    mock_segments = [
        MockSeg(start=0.0, end=2.5, text=" Hello world", words=None),
        MockSeg(start=2.5, end=5.0, text=" Testing one two", words=None),
    ]
    MockInfo = namedtuple("MockInfo", ["language"])
    mock_info = MockInfo(language="en")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter(mock_segments), mock_info)

    with patch.object(engine, '_get_model', return_value=(mock_model, 'faster')):
        result = engine.transcribe("/tmp/test.wav", language="en")

    assert len(result) == 2
    assert result[0]["start"] == 0.0
    assert result[0]["end"] == 2.5
    assert result[0]["text"] == "Hello world"
    assert result[1]["text"] == "Testing one two"


def test_whisper_engine_transcribe_openai():
    from asr.whisper_engine import WhisperEngine
    engine = WhisperEngine({"engine": "whisper", "model_size": "tiny", "language": "en", "device": "cpu"})

    mock_result = {
        "text": "Hello world",
        "language": "en",
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.5, "text": " Hello world"},
            {"id": 1, "start": 2.5, "end": 5.0, "text": " Testing"},
        ]
    }

    mock_model = MagicMock()
    mock_model.transcribe.return_value = mock_result

    with patch.object(engine, '_get_model', return_value=(mock_model, 'openai')):
        result = engine.transcribe("/tmp/test.wav", language="en")

    assert len(result) == 2
    assert result[0]["text"] == "Hello world"
    assert result[1]["text"] == "Testing"


def test_whisper_engine_get_info():
    from asr.whisper_engine import WhisperEngine
    engine = WhisperEngine({"engine": "whisper", "model_size": "small", "language": "en", "device": "auto"})
    info = engine.get_info()
    assert info["engine"] == "whisper"
    assert info["model_size"] == "small"
    assert info["available"] is True
    assert "en" in info["languages"]


import json


def test_api_list_asr_engines():
    """Test the /api/asr/engines REST endpoint."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/api/asr/engines")
        assert resp.status_code == 200
        data = resp.get_json()
        engines = data["engines"]
        assert len(engines) == 3

        engine_names = [e["engine"] for e in engines]
        assert "whisper" in engine_names
        assert "qwen3-asr" in engine_names
        assert "flg-asr" in engine_names

        whisper_info = next(e for e in engines if e["engine"] == "whisper")
        assert whisper_info["available"] is True

        qwen_info = next(e for e in engines if e["engine"] == "qwen3-asr")
        assert qwen_info["available"] is False


def test_whisper_engine_params_schema():
    from asr.whisper_engine import WhisperEngine
    engine = WhisperEngine({"engine": "whisper", "model_size": "small", "device": "auto"})
    schema = engine.get_params_schema()
    assert schema["engine"] == "whisper"
    assert "model_size" in schema["params"]
    assert "language" in schema["params"]
    assert "device" in schema["params"]
    assert schema["params"]["model_size"]["type"] == "string"
    assert "small" in schema["params"]["model_size"]["enum"]
    assert schema["params"]["model_size"]["default"] == "small"


def test_qwen3_engine_params_schema():
    from asr import create_asr_engine
    engine = create_asr_engine({"engine": "qwen3-asr", "model_size": "large"})
    schema = engine.get_params_schema()
    assert schema["engine"] == "qwen3-asr"
    assert "model_size" in schema["params"]
    assert "language" in schema["params"]


def test_flg_engine_params_schema():
    from asr import create_asr_engine
    engine = create_asr_engine({"engine": "flg-asr", "model_size": "standard"})
    schema = engine.get_params_schema()
    assert schema["engine"] == "flg-asr"
    assert "model_size" in schema["params"]
    assert "language" in schema["params"]


def test_api_asr_engine_params_whisper():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/api/asr/engines/whisper/params")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["engine"] == "whisper"
        assert "params" in data
        assert "model_size" in data["params"]
        assert "language" in data["params"]
        assert "device" in data["params"]


def test_api_asr_engine_params_qwen3():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/api/asr/engines/qwen3-asr/params")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["engine"] == "qwen3-asr"


def test_api_asr_engine_params_unknown():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/api/asr/engines/nonexistent/params")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
