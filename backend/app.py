#!/usr/bin/env python3
"""
Whisper AI Web Application - Backend Server
Supports video/audio file upload and live transcription to Traditional Chinese subtitles
"""

import os
import sys
import json
import time
import uuid
import threading
import tempfile
import subprocess
from pathlib import Path

import whisper
import numpy as np
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from profiles import ProfileManager
from glossary import GlossaryManager
from language_config import LanguageConfigManager, DEFAULT_ASR_CONFIG, DEFAULT_TRANSLATION_CONFIG
from renderer import SubtitleRenderer, DEFAULT_FONT_CONFIG

# Try to import faster-whisper for better performance
try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    FASTER_WHISPER_AVAILABLE = True
    print("faster-whisper available — will use for live transcription")
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    print("faster-whisper not available — using openai-whisper only")

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'whisper-secret-key'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

CORS(app, origins="*")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading',
                    max_http_buffer_size=100 * 1024 * 1024)

# Persistent storage directory (inside project, survives restarts)
DATA_DIR = Path(__file__).parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULTS_DIR = DATA_DIR / "results"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

RENDERS_DIR = DATA_DIR / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
_subtitle_renderer = SubtitleRenderer(RENDERS_DIR)
_render_jobs = {}

# Profile management
CONFIG_DIR = Path(__file__).parent / "config"
_profile_manager = ProfileManager(CONFIG_DIR)


def _init_profile_manager(config_dir):
    """Re-initialize profile manager (used by tests)."""
    global _profile_manager
    _profile_manager = ProfileManager(config_dir)


# Glossary management
_glossary_manager = GlossaryManager(CONFIG_DIR)


def _init_glossary_manager(config_dir):
    """Re-initialize glossary manager (used by tests)."""
    global _glossary_manager
    _glossary_manager = GlossaryManager(config_dir)


# Language config management
_language_config_manager = LanguageConfigManager(CONFIG_DIR)


def _init_language_config_manager(config_dir):
    global _language_config_manager
    _language_config_manager = LanguageConfigManager(config_dir)


# In-memory file registry: file_id -> metadata dict
_file_registry = {}
_registry_lock = threading.Lock()


def _load_registry():
    """Load file registry from disk on startup"""
    registry_path = DATA_DIR / "registry.json"
    if registry_path.exists():
        with open(registry_path) as f:
            return json.load(f)
    return {}


def _save_registry():
    """Persist file registry to disk"""
    registry_path = DATA_DIR / "registry.json"
    with open(registry_path, 'w') as f:
        json.dump(_file_registry, f, ensure_ascii=False, indent=2)


def _register_file(file_id, original_name, stored_name, size_bytes):
    """Register an uploaded file"""
    with _registry_lock:
        _file_registry[file_id] = {
            'id': file_id,
            'original_name': original_name,
            'stored_name': stored_name,
            'size': size_bytes,
            'status': 'uploaded',  # uploaded | transcribing | done | error
            'uploaded_at': time.time(),
            'segments': [],
            'text': '',
            'error': None,
            'model': None,       # whisper model used (e.g. 'small', 'tiny')
            'backend': None,     # 'openai-whisper' or 'faster-whisper'
        }
        _save_registry()
    return _file_registry[file_id]


def _update_file(file_id, **kwargs):
    """Update file metadata"""
    with _registry_lock:
        if file_id in _file_registry:
            _file_registry[file_id].update(kwargs)
            _save_registry()


def _delete_file_entry(file_id):
    """Delete a file from registry and disk"""
    with _registry_lock:
        entry = _file_registry.pop(file_id, None)
        _save_registry()
    if entry:
        media_path = UPLOAD_DIR / entry['stored_name']
        if media_path.exists():
            media_path.unlink()
    return entry is not None

# Global model cache — separate caches for each backend
_openai_model_cache = {}
_faster_model_cache = {}
_model_lock = threading.Lock()

ALLOWED_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}


def get_model(model_size='small', backend='auto'):
    """Load and cache Whisper model. backend: 'auto'|'openai'|'faster'"""
    use_faster = (
        backend == 'faster' or
        (backend == 'auto' and FASTER_WHISPER_AVAILABLE)
    )

    with _model_lock:
        if use_faster and FASTER_WHISPER_AVAILABLE:
            if model_size not in _faster_model_cache:
                print(f"Loading faster-whisper model: {model_size}")
                _faster_model_cache[model_size] = FasterWhisperModel(
                    model_size, device="auto", compute_type="int8"
                )
                print(f"faster-whisper model {model_size} loaded")
            return _faster_model_cache[model_size], 'faster'
        else:
            if model_size not in _openai_model_cache:
                print(f"Loading openai-whisper model: {model_size}")
                _openai_model_cache[model_size] = whisper.load_model(model_size)
                print(f"openai-whisper model {model_size} loaded")
            return _openai_model_cache[model_size], 'openai'


def get_media_duration(file_path: str) -> float:
    """Get media duration in seconds using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get('format', {}).get('duration', 0))
    except Exception as e:
        print(f"Error getting duration: {e}")
    return 0


def extract_audio(video_path: str, output_path: str) -> bool:
    """Extract audio from video file using ffmpeg"""
    try:
        cmd = [
            'ffmpeg', '-i', video_path,
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # PCM 16-bit
            '-ar', '16000',  # 16kHz sample rate (Whisper requirement)
            '-ac', '1',  # Mono
            '-y',  # Overwrite
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except Exception as e:
        print(f"Error extracting audio: {e}")
        return False


def transcribe_with_segments(file_path: str, model_size: str = 'small', sid: str = None):
    """
    Transcribe audio/video file and emit segments with timestamps.
    If an active profile exists with whisper engine, uses the profile's ASR engine.
    Otherwise falls back to legacy direct Whisper path.
    """
    profile = _profile_manager.get_active()
    use_profile_engine = (
        profile is not None
        and profile.get("asr", {}).get("engine") == "whisper"
    )

    # Read language from profile (default to 'zh' for backward compat)
    transcribe_language = 'zh'
    if profile:
        transcribe_language = profile.get("asr", {}).get("language", "zh")

    if not use_profile_engine:
        model, backend = get_model(model_size, backend='auto')

    # Check if it's a video file - extract audio first
    suffix = Path(file_path).suffix.lower()
    audio_path = file_path
    temp_audio = None

    if suffix in {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.mxf'}:
        temp_audio = str(UPLOAD_DIR / f"audio_{uuid.uuid4().hex}.wav")
        if sid:
            socketio.emit('transcription_status',
                         {'status': 'extracting', 'message': '正在提取音頻...'},
                         room=sid)

        if not extract_audio(file_path, temp_audio):
            if sid:
                socketio.emit('transcription_error',
                             {'error': '無法提取音頻，請確保 ffmpeg 已安裝'},
                             room=sid)
            return None
        audio_path = temp_audio

    try:
        # Get total media duration for progress tracking
        total_duration = get_media_duration(audio_path)
        transcribe_start_time = time.time()

        if sid:
            socketio.emit('transcription_status', {
                'status': 'transcribing',
                'message': '正在轉錄中...',
                'total_duration': total_duration,
            }, room=sid)

        segments = []

        def emit_segment_with_progress(segment, sid):
            """Emit a segment along with progress info"""
            if not sid:
                return
            progress = 0
            eta = None
            if total_duration > 0:
                progress = min(segment['end'] / total_duration, 1.0)
                elapsed = time.time() - transcribe_start_time
                if progress > 0.01:
                    total_est = elapsed / progress
                    eta = max(0, total_est - elapsed)
            socketio.emit('subtitle_segment', {
                **segment,
                'progress': round(progress, 4),
                'eta_seconds': round(eta, 1) if eta is not None else None,
                'total_duration': total_duration,
            }, room=sid)

        # === Profile-based ASR engine path ===
        if use_profile_engine:
            from asr import create_asr_engine
            engine = create_asr_engine(profile["asr"])
            language = profile["asr"].get("language", "en")
            raw_segments = engine.transcribe(audio_path, language=language)

            # Post-process segments with language config
            from asr.segment_utils import split_segments
            lang_config_id = profile["asr"].get("language_config_id", language)
            lang_config = _language_config_manager.get(lang_config_id)
            asr_params = lang_config["asr"] if lang_config else DEFAULT_ASR_CONFIG
            raw_segments = split_segments(
                raw_segments,
                max_words=asr_params["max_words_per_segment"],
                max_duration=asr_params["max_segment_duration"],
            )

            for i, seg in enumerate(raw_segments):
                segment = {
                    'id': i,
                    'start': seg['start'],
                    'end': seg['end'],
                    'text': seg['text'],
                    'words': [],
                }
                segments.append(segment)
                emit_segment_with_progress(segment, sid)

            return {
                'text': ' '.join(s['text'] for s in segments),
                'language': language,
                'segments': segments,
                'backend': engine.get_info().get('engine', 'whisper'),
            }

        # === Legacy path (no profile or non-whisper engine) ===
        if backend == 'faster':
            # faster-whisper returns a generator of Segment namedtuples
            initial_prompt = '請將音頻轉錄為繁體中文。' if transcribe_language == 'zh' else ''
            seg_iter, info = model.transcribe(
                audio_path,
                language=transcribe_language,
                task='transcribe',
                word_timestamps=True,
                initial_prompt=initial_prompt,
            )
            full_text_parts = []
            for i, seg in enumerate(seg_iter):
                segment = {
                    'id': i,
                    'start': seg.start,
                    'end': seg.end,
                    'text': seg.text.strip(),
                    'words': []
                }
                if seg.words:
                    for w in seg.words:
                        segment['words'].append({
                            'word': w.word,
                            'start': w.start,
                            'end': w.end,
                            'probability': w.probability
                        })
                full_text_parts.append(seg.text.strip())
                segments.append(segment)
                emit_segment_with_progress(segment, sid)

            return {
                'text': ' '.join(full_text_parts),
                'language': info.language,
                'segments': segments,
                'backend': 'faster-whisper'
            }

        else:
            # openai-whisper: model.transcribe() is blocking — all segments
            # come back at once. We run a heartbeat thread that sends estimated
            # progress to the client while we wait.
            heartbeat_stop = threading.Event()

            def heartbeat():
                """Send estimated progress every 2 seconds while transcription blocks."""
                # Whisper processes ~30-second chunks. Estimate speed from model size.
                while not heartbeat_stop.is_set():
                    heartbeat_stop.wait(2)
                    if heartbeat_stop.is_set():
                        break
                    elapsed = time.time() - transcribe_start_time
                    if total_duration > 0 and sid:
                        # Estimate: assume processing takes roughly
                        # (total_duration * speed_factor) seconds of wall time.
                        # We don't know speed_factor exactly, so we just report
                        # elapsed time and let the client show an indeterminate
                        # progress bar with elapsed time info.
                        socketio.emit('transcription_progress', {
                            'elapsed': round(elapsed, 1),
                            'total_duration': total_duration,
                            'status': 'transcribing',
                        }, room=sid)

            if sid and total_duration > 0:
                hb_thread = threading.Thread(target=heartbeat, daemon=True)
                hb_thread.start()

            initial_prompt_openai = '請將音頻轉錄為繁體中文。' if transcribe_language == 'zh' else ''
            result = model.transcribe(
                audio_path,
                language=transcribe_language,
                task='transcribe',
                verbose=False,
                word_timestamps=True,
                initial_prompt=initial_prompt_openai,
                fp16=False
            )

            heartbeat_stop.set()

            for seg in result.get('segments', []):
                segment = {
                    'id': seg['id'],
                    'start': seg['start'],
                    'end': seg['end'],
                    'text': seg['text'].strip(),
                    'words': []
                }
                if 'words' in seg:
                    for word in seg['words']:
                        segment['words'].append({
                            'word': word.get('word', ''),
                            'start': word.get('start', seg['start']),
                            'end': word.get('end', seg['end']),
                            'probability': word.get('probability', 1.0)
                        })
                segments.append(segment)
                emit_segment_with_progress(segment, sid)

            return {
                'text': result.get('text', ''),
                'language': result.get('language', 'zh'),
                'segments': segments,
                'backend': 'openai-whisper'
            }

    finally:
        if temp_audio and os.path.exists(temp_audio):
            os.remove(temp_audio)


# ============================================================
# REST API Routes
# ============================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'faster_whisper_available': FASTER_WHISPER_AVAILABLE,
        'openai_models_loaded': list(_openai_model_cache.keys()),
        'faster_models_loaded': list(_faster_model_cache.keys()),
        'upload_dir': str(UPLOAD_DIR)
    })


@app.route('/api/models', methods=['GET'])
def list_models():
    """List available Whisper models with download/loaded status"""
    # Check which models are downloaded on disk
    cache_dir = Path.home() / '.cache' / 'whisper'
    downloaded = set()
    if cache_dir.exists():
        for f in cache_dir.iterdir():
            if f.suffix == '.pt':
                downloaded.add(f.stem)  # e.g. 'small', 'tiny'

    # Check which models are loaded in memory
    loaded_openai = set(_openai_model_cache.keys())
    loaded_faster = set(_faster_model_cache.keys())
    loaded = loaded_openai | loaded_faster

    models_info = [
        {'id': 'tiny', 'name': 'Tiny', 'params': '39M', 'speed': '最快', 'quality': '基礎'},
        {'id': 'base', 'name': 'Base', 'params': '74M', 'speed': '快', 'quality': '良好'},
        {'id': 'small', 'name': 'Small', 'params': '244M', 'speed': '中等', 'quality': '優良'},
        {'id': 'medium', 'name': 'Medium', 'params': '769M', 'speed': '慢', 'quality': '出色'},
        {'id': 'large', 'name': 'Large', 'params': '1550M', 'speed': '最慢', 'quality': '最佳'},
        {'id': 'turbo', 'name': 'Turbo', 'params': '809M', 'speed': '快', 'quality': '優良'},
    ]

    for m in models_info:
        mid = m['id']
        if mid in loaded:
            m['status'] = 'loaded'       # in memory, ready to use
        elif mid in downloaded:
            m['status'] = 'downloaded'    # on disk, needs loading
        else:
            m['status'] = 'not_downloaded'  # needs download + loading

    return jsonify({'models': models_info})


# ============================================================
# Profile Management API
# ============================================================

@app.route('/api/profiles', methods=['GET'])
def api_list_profiles():
    return jsonify({"profiles": _profile_manager.list_all()})


@app.route('/api/profiles', methods=['POST'])
def api_create_profile():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400
    try:
        profile = _profile_manager.create(data)
        return jsonify({"profile": profile}), 201
    except ValueError as e:
        return jsonify({"errors": e.args[0]}), 400


@app.route('/api/profiles/active', methods=['GET'])
def api_get_active_profile():
    profile = _profile_manager.get_active()
    return jsonify({"profile": profile})


@app.route('/api/profiles/<profile_id>', methods=['GET'])
def api_get_profile(profile_id):
    profile = _profile_manager.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify({"profile": profile})


@app.route('/api/profiles/<profile_id>', methods=['PATCH'])
def api_update_profile(profile_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400
    try:
        profile = _profile_manager.update(profile_id, data)
        if not profile:
            return jsonify({"error": "Profile not found"}), 404
        return jsonify({"profile": profile})
    except ValueError as e:
        return jsonify({"errors": e.args[0]}), 400


@app.route('/api/profiles/<profile_id>', methods=['DELETE'])
def api_delete_profile(profile_id):
    if _profile_manager.delete(profile_id):
        return jsonify({"message": "Profile deleted"})
    return jsonify({"error": "Profile not found"}), 404


@app.route('/api/profiles/<profile_id>/activate', methods=['POST'])
def api_activate_profile(profile_id):
    profile = _profile_manager.set_active(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify({"profile": profile})


# ============================================================
# ASR Engine Info
# ============================================================

@app.route('/api/asr/engines', methods=['GET'])
def api_list_asr_engines():
    """List available ASR engines with status."""
    from asr import create_asr_engine
    engines_info = []
    for engine_name, desc in [
        ("whisper", "OpenAI Whisper (local)"),
        ("qwen3-asr", "Qwen3-ASR (stub — production only)"),
        ("flg-asr", "FLG-ASR (stub — production only)"),
    ]:
        try:
            engine = create_asr_engine({"engine": engine_name, "model_size": "unknown"})
            info = engine.get_info()
            engines_info.append({
                "engine": engine_name,
                "available": info.get("available", False),
                "description": desc,
            })
        except Exception:
            engines_info.append({
                "engine": engine_name,
                "available": False,
                "description": desc,
            })
    return jsonify({"engines": engines_info})


# ============================================================
# Translation Engine Info
# ============================================================

@app.route('/api/translation/engines', methods=['GET'])
def api_list_translation_engines():
    """List available translation engines with status."""
    from translation import create_translation_engine
    engines_info = []
    for engine_name, desc in [
        ("mock", "Mock translator (development)"),
        ("qwen2.5-3b", "Qwen 2.5 3B (Ollama)"),
        ("qwen2.5-7b", "Qwen 2.5 7B (Ollama)"),
        ("qwen2.5-72b", "Qwen 2.5 72B (Ollama)"),
        ("qwen3-235b", "Qwen3 235B MoE (Ollama)"),
    ]:
        try:
            engine = create_translation_engine({"engine": engine_name})
            info = engine.get_info()
            engines_info.append({
                "engine": engine_name,
                "available": info.get("available", False),
                "description": desc,
            })
        except Exception:
            engines_info.append({
                "engine": engine_name,
                "available": False,
                "description": desc,
            })
    return jsonify({"engines": engines_info})


@app.route('/api/translate', methods=['POST'])
def api_translate_file():
    """Translate a file's transcription segments using the active profile's translation engine."""
    data = request.get_json()
    if not data or not data.get('file_id'):
        return jsonify({"error": "file_id is required"}), 400

    file_id = data['file_id']
    style_override = data.get('style')

    entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({"error": "File not found"}), 404

    segments = entry.get('segments', [])
    if not segments:
        return jsonify({"error": "No segments to translate. Transcribe the file first."}), 400

    profile = _profile_manager.get_active()
    if not profile:
        return jsonify({"error": "No active profile. Set a profile first."}), 400

    translation_config = profile.get("translation", {})
    style = style_override or translation_config.get("style", "formal")

    _update_file(file_id, translation_status='translating')

    try:
        from translation import create_translation_engine
        engine = create_translation_engine(translation_config)

        asr_segments = [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in segments
        ]

        glossary_entries = []
        glossary_id = translation_config.get("glossary_id")
        if glossary_id:
            glossary_data = _glossary_manager.get(glossary_id)
            if glossary_data:
                glossary_entries = glossary_data.get("entries", [])

        lang_config_id = profile.get("asr", {}).get("language_config_id", profile.get("asr", {}).get("language", "en"))
        lang_config = _language_config_manager.get(lang_config_id)
        trans_params = lang_config["translation"] if lang_config else DEFAULT_TRANSLATION_CONFIG
        from translation.sentence_pipeline import translate_with_sentences
        translated = translate_with_sentences(
            engine, asr_segments, glossary=glossary_entries, style=style,
            batch_size=trans_params["batch_size"],
            temperature=trans_params["temperature"],
        )

        for t in translated:
            t["status"] = "pending"
        _update_file(file_id, translations=translated, translation_status='done')

        return jsonify({
            "file_id": file_id,
            "segment_count": len(translated),
            "style": style,
            "engine": engine.get_info().get("engine"),
            "translations": translated,
        })

    except NotImplementedError as e:
        return jsonify({"error": str(e)}), 501
    except ConnectionError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Translation failed: {str(e)}"}), 500


# ============================================================
# Glossary endpoints
# ============================================================

@app.route('/api/glossaries', methods=['GET'])
def api_list_glossaries():
    """List all glossaries (summaries, no entries)."""
    summaries = _glossary_manager.list_all()
    return jsonify({"glossaries": summaries})


@app.route('/api/glossaries', methods=['POST'])
def api_create_glossary():
    """Create a new glossary."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        glossary = _glossary_manager.create(data)
        return jsonify(glossary), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 422


@app.route('/api/glossaries/<glossary_id>', methods=['GET'])
def api_get_glossary(glossary_id):
    """Get a single glossary with all entries."""
    glossary = _glossary_manager.get(glossary_id)
    if glossary is None:
        return jsonify({"error": "Glossary not found"}), 404
    return jsonify(glossary)


@app.route('/api/glossaries/<glossary_id>', methods=['PATCH'])
def api_update_glossary(glossary_id):
    """Update glossary name and/or description."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        updated = _glossary_manager.update(glossary_id, data)
        if updated is None:
            return jsonify({"error": "Glossary not found"}), 404
        return jsonify(updated)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422


@app.route('/api/glossaries/<glossary_id>', methods=['DELETE'])
def api_delete_glossary(glossary_id):
    """Delete a glossary."""
    deleted = _glossary_manager.delete(glossary_id)
    if not deleted:
        return jsonify({"error": "Glossary not found"}), 404
    return jsonify({"deleted": True})


@app.route('/api/glossaries/<glossary_id>/entries', methods=['POST'])
def api_add_entry(glossary_id):
    """Add an entry to a glossary."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        updated = _glossary_manager.add_entry(glossary_id, data)
        if updated is None:
            return jsonify({"error": "Glossary not found"}), 404
        return jsonify(updated), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 422


@app.route('/api/glossaries/<glossary_id>/entries/<entry_id>', methods=['PATCH'])
def api_update_entry(glossary_id, entry_id):
    """Update a single entry within a glossary."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        updated = _glossary_manager.update_entry(glossary_id, entry_id, data)
        if updated is None:
            return jsonify({"error": "Glossary or entry not found"}), 404
        return jsonify(updated)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422


@app.route('/api/glossaries/<glossary_id>/entries/<entry_id>', methods=['DELETE'])
def api_delete_entry(glossary_id, entry_id):
    """Delete a single entry from a glossary."""
    updated = _glossary_manager.delete_entry(glossary_id, entry_id)
    if updated is None:
        return jsonify({"error": "Glossary not found"}), 404
    return jsonify(updated)


@app.route('/api/glossaries/<glossary_id>/import', methods=['POST'])
def api_import_glossary_csv(glossary_id):
    """Import entries from CSV text (JSON body with csv_content field)."""
    data = request.get_json(silent=True)
    if not data or "csv_content" not in data:
        return jsonify({"error": "Request body must include csv_content"}), 400
    updated = _glossary_manager.import_csv(glossary_id, data["csv_content"])
    if updated is None:
        return jsonify({"error": "Glossary not found"}), 404
    return jsonify(updated)


@app.route('/api/glossaries/<glossary_id>/export', methods=['GET'])
def api_export_glossary_csv(glossary_id):
    """Export glossary entries as CSV text."""
    csv_text = _glossary_manager.export_csv(glossary_id)
    if csv_text is None:
        return jsonify({"error": "Glossary not found"}), 404
    return csv_text, 200, {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f"attachment; filename={glossary_id}.csv",
    }


# ============================================================
# Language Configuration API
# ============================================================

@app.route('/api/languages', methods=['GET'])
def api_list_languages():
    return jsonify({"languages": _language_config_manager.list_all()})


@app.route('/api/languages/<lang_id>', methods=['GET'])
def api_get_language(lang_id):
    config = _language_config_manager.get(lang_id)
    if not config:
        return jsonify({"error": "Language config not found"}), 404
    return jsonify({"language": config})


@app.route('/api/languages/<lang_id>', methods=['PATCH'])
def api_update_language(lang_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400
    try:
        config = _language_config_manager.update(lang_id, data)
        if not config:
            return jsonify({"error": "Language config not found"}), 404
        return jsonify({"language": config})
    except ValueError as e:
        return jsonify({"errors": e.args[0]}), 400


# ============================================================
# Translation Approval API (Proof-reading)
# ============================================================

@app.route('/api/files/<file_id>/translations', methods=['GET'])
def api_get_translations(file_id):
    entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({"error": "File not found"}), 404
    translations = entry.get("translations", [])
    return jsonify({"translations": translations, "file_id": file_id})


@app.route('/api/files/<file_id>/translations/approve-all', methods=['POST'])
def api_approve_all_translations(file_id):
    entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({"error": "File not found"}), 404
    translations = entry.get("translations", [])
    count = 0
    new_translations = []
    for t in translations:
        if t.get("status") == "pending":
            new_translations.append({**t, "status": "approved"})
            count += 1
        else:
            new_translations.append(t)
    _update_file(file_id, translations=new_translations)
    return jsonify({"approved_count": count, "total": len(new_translations)})


@app.route('/api/files/<file_id>/translations/status', methods=['GET'])
def api_translation_status(file_id):
    entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({"error": "File not found"}), 404
    translations = entry.get("translations", [])
    approved = sum(1 for t in translations if t.get("status") == "approved")
    pending = sum(1 for t in translations if t.get("status") != "approved")
    return jsonify({"total": len(translations), "approved": approved, "pending": pending})


@app.route('/api/files/<file_id>/translations/<int:idx>', methods=['PATCH'])
def api_update_translation(file_id, idx):
    entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({"error": "File not found"}), 404
    translations = entry.get("translations", [])
    if idx < 0 or idx >= len(translations):
        return jsonify({"error": "Translation index out of range"}), 404
    data = request.get_json()
    if not data or "zh_text" not in data:
        return jsonify({"error": "zh_text is required"}), 400
    new_translations = list(translations)
    new_translations[idx] = {**translations[idx], "zh_text": data["zh_text"], "status": "approved"}
    _update_file(file_id, translations=new_translations)
    return jsonify({"translation": new_translations[idx]})


@app.route('/api/files/<file_id>/translations/<int:idx>/approve', methods=['POST'])
def api_approve_translation(file_id, idx):
    entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({"error": "File not found"}), 404
    translations = entry.get("translations", [])
    if idx < 0 or idx >= len(translations):
        return jsonify({"error": "Translation index out of range"}), 404
    new_translations = list(translations)
    new_translations[idx] = {**translations[idx], "status": "approved"}
    _update_file(file_id, translations=new_translations)
    return jsonify({"translation": new_translations[idx]})


# ============================================================
# Render Endpoints
# ============================================================

VALID_RENDER_FORMATS = {"mp4", "mxf"}


@app.route('/api/render', methods=['POST'])
def api_start_render():
    """Start a render job: burn approved translations into video as ASS subtitles."""
    data = request.get_json() or {}

    file_id = data.get("file_id")
    if not file_id:
        return jsonify({"error": "file_id is required"}), 400

    output_format = data.get("format", "mp4")
    if output_format not in VALID_RENDER_FORMATS:
        return jsonify({"error": f"Invalid format '{output_format}'. Must be one of: {sorted(VALID_RENDER_FORMATS)}"}), 400

    with _registry_lock:
        entry = _file_registry.get(file_id)

    if not entry:
        return jsonify({"error": "File not found"}), 404

    translations = entry.get("translations")
    if not translations:
        return jsonify({"error": "File has no translations to render"}), 400

    unapproved = [t for t in translations if t.get("status") != "approved"]
    if unapproved:
        return jsonify({"error": f"{len(unapproved)} segment(s) not yet approved. All translations must be approved before rendering."}), 400

    render_id = uuid.uuid4().hex[:12]
    video_path = str(UPLOAD_DIR / entry["stored_name"])
    output_filename = f"{render_id}.{output_format}"
    output_path = str(RENDERS_DIR / output_filename)

    _render_jobs[render_id] = {
        "render_id": render_id,
        "file_id": file_id,
        "format": output_format,
        "status": "processing",
        "output_path": output_path,
        "error": None,
        "created_at": time.time(),
    }

    # Load font config from active profile (fallback to DEFAULT_FONT_CONFIG)
    active_profile = _profile_manager.get_active()
    font_config = active_profile.get("font", DEFAULT_FONT_CONFIG) if active_profile else DEFAULT_FONT_CONFIG

    # Snapshot translations to pass into thread (immutable)
    translations_snapshot = list(translations)

    def do_render():
        try:
            ass_content = _subtitle_renderer.generate_ass(translations_snapshot, font_config)
            success = _subtitle_renderer.render(video_path, ass_content, output_path, output_format)
            if success:
                _render_jobs[render_id] = {**_render_jobs[render_id], "status": "done"}
            else:
                _render_jobs[render_id] = {**_render_jobs[render_id], "status": "error", "error": "FFmpeg render failed"}
        except Exception as exc:
            print(f"Render job {render_id} error: {exc}")
            _render_jobs[render_id] = {**_render_jobs[render_id], "status": "error", "error": str(exc)}

    thread = threading.Thread(target=do_render)
    thread.daemon = True
    thread.start()

    return jsonify({
        "render_id": render_id,
        "file_id": file_id,
        "format": output_format,
        "status": "processing",
    }), 202


@app.route('/api/renders/<render_id>', methods=['GET'])
def api_get_render_status(render_id):
    """Return the status of a render job."""
    job = _render_jobs.get(render_id)
    if not job:
        return jsonify({"error": "Render job not found"}), 404
    return jsonify(job)


@app.route('/api/renders/<render_id>/download', methods=['GET'])
def api_download_render(render_id):
    """Download the rendered video file when the job is done."""
    job = _render_jobs.get(render_id)
    if not job:
        return jsonify({"error": "Render job not found"}), 404

    if job["status"] != "done":
        return jsonify({"error": f"Render job is not done yet (status: {job['status']})"}), 400

    output_path = job["output_path"]
    if not os.path.exists(output_path):
        return jsonify({"error": "Rendered file not found on disk"}), 404

    return send_file(output_path, as_attachment=True)


@app.route('/api/transcribe', methods=['POST'])
def transcribe_file():
    """Upload and transcribe a video/audio file. File is kept until explicitly deleted."""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': '未選擇文件'}), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'不支持的文件格式: {suffix}'}), 400

    model_size = request.form.get('model', 'small')
    sid = request.form.get('sid', None)

    # Generate a unique file id and save
    file_id = uuid.uuid4().hex[:12]
    stored_name = f"{file_id}{suffix}"
    file_path = str(UPLOAD_DIR / stored_name)
    file.save(file_path)

    file_size = os.path.getsize(file_path)
    entry = _register_file(file_id, file.filename, stored_name, file_size)

    # Notify client about the new file
    if sid:
        socketio.emit('file_added', entry, room=sid)

    def _auto_translate(fid, segments, session_id):
        """Auto-translate segments after transcription using the active profile."""
        try:
            profile = _profile_manager.get_active()
            if not profile:
                return
            translation_config = profile.get("translation", {})
            engine_name = translation_config.get("engine", "")
            if not engine_name:
                return

            _update_file(fid, translation_status='translating')
            if session_id:
                socketio.emit('file_updated', {
                    'id': fid,
                    'translation_status': 'translating',
                }, room=session_id)

            from translation import create_translation_engine
            engine = create_translation_engine(translation_config)

            style = translation_config.get("style", "formal")
            glossary_entries = []
            glossary_id = translation_config.get("glossary_id")
            if glossary_id:
                glossary_data = _glossary_manager.get(glossary_id)
                if glossary_data:
                    glossary_entries = glossary_data.get("entries", [])

            asr_segments = [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in segments
            ]

            lang_config_id = profile.get("asr", {}).get("language_config_id", profile.get("asr", {}).get("language", "en"))
            lang_config = _language_config_manager.get(lang_config_id)
            trans_params = lang_config["translation"] if lang_config else DEFAULT_TRANSLATION_CONFIG
            from translation.sentence_pipeline import translate_with_sentences
            translated = translate_with_sentences(
                engine, asr_segments, glossary=glossary_entries, style=style,
                batch_size=trans_params["batch_size"],
                temperature=trans_params["temperature"],
            )
            for t in translated:
                t["status"] = "pending"
            _update_file(fid, translations=translated, translation_status='done')

            if session_id:
                socketio.emit('file_updated', {
                    'id': fid,
                    'translation_status': 'done',
                    'translation_count': len(translated),
                }, room=session_id)
        except Exception as e:
            print(f"Auto-translate failed for {fid}: {e}")
            _update_file(fid, translation_status=None)
            if session_id:
                socketio.emit('file_updated', {
                    'id': fid,
                    'translation_status': None,
                    'translation_error': str(e),
                }, room=session_id)

    # Start transcription in background thread
    def do_transcribe():
        _update_file(file_id, status='transcribing', model=model_size)
        if sid:
            socketio.emit('file_updated', {'id': file_id, 'status': 'transcribing', 'model': model_size}, room=sid)
        try:
            result = transcribe_with_segments(file_path, model_size, sid)
            if result:
                _update_file(
                    file_id,
                    status='done',
                    text=result['text'],
                    segments=result['segments'],
                    backend=result.get('backend'),
                )
                if sid:
                    socketio.emit('file_updated', {
                        'id': file_id,
                        'status': 'done',
                        'segment_count': len(result['segments']),
                    }, room=sid)
                    socketio.emit('transcription_complete', {
                        'file_id': file_id,
                        'text': result['text'],
                        'language': result['language'],
                        'segment_count': len(result['segments'])
                    }, room=sid)

                # Auto-translate if profile has a translation engine configured
                _auto_translate(file_id, result['segments'], sid)
        except Exception as e:
            _update_file(file_id, status='error', error=str(e))
            if sid:
                socketio.emit('file_updated', {'id': file_id, 'status': 'error', 'error': str(e)}, room=sid)
                socketio.emit('transcription_error', {'error': str(e)}, room=sid)

    thread = threading.Thread(target=do_transcribe)
    thread.daemon = True
    thread.start()

    return jsonify({
        'status': 'processing',
        'file_id': file_id,
        'message': '轉錄已開始',
        'filename': stored_name,
    })


@app.route('/api/transcribe/sync', methods=['POST'])
def transcribe_sync():
    """Synchronous transcription - waits for result (for smaller files)"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400

    file = request.files['file']
    suffix = Path(file.filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'不支持的文件格式: {suffix}'}), 400

    model_size = request.form.get('model', 'small')

    filename = f"upload_{int(time.time())}{suffix}"
    file_path = str(UPLOAD_DIR / filename)
    file.save(file_path)

    try:
        result = transcribe_with_segments(file_path, model_size)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.route('/api/files', methods=['GET'])
def list_files():
    """List all uploaded files with their status"""
    files = []
    with _registry_lock:
        for fid, entry in _file_registry.items():
            files.append({
                'id': entry['id'],
                'original_name': entry['original_name'],
                'size': entry['size'],
                'status': entry['status'],
                'uploaded_at': entry['uploaded_at'],
                'segment_count': len(entry.get('segments', [])),
                'error': entry.get('error'),
                'model': entry.get('model'),
                'backend': entry.get('backend'),
                'translation_status': entry.get('translation_status'),
            })
    # Newest first
    files.sort(key=lambda f: f['uploaded_at'], reverse=True)
    return jsonify({'files': files})


@app.route('/api/files/<file_id>/media')
def serve_media(file_id):
    """Serve the original uploaded media file"""
    with _registry_lock:
        entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({'error': '文件不存在'}), 404

    media_path = UPLOAD_DIR / entry['stored_name']
    if not media_path.exists():
        return jsonify({'error': '文件已丟失'}), 404

    return send_file(str(media_path), as_attachment=False)


@app.route('/api/files/<file_id>/subtitle.<fmt>')
def download_subtitle(file_id, fmt):
    """Download subtitles in SRT, VTT, or TXT format"""
    if fmt not in ('srt', 'vtt', 'txt'):
        return jsonify({'error': '不支持的格式'}), 400

    with _registry_lock:
        entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({'error': '文件不存在'}), 404
    if entry['status'] != 'done':
        return jsonify({'error': '轉錄尚未完成'}), 400

    segs = entry.get('segments', [])
    base_name = Path(entry['original_name']).stem

    if fmt == 'txt':
        content = '\n'.join(s['text'] for s in segs)
        mime = 'text/plain'
    elif fmt == 'srt':
        lines = []
        for i, s in enumerate(segs):
            lines.append(str(i + 1))
            lines.append(f"{_fmt_srt(s['start'])} --> {_fmt_srt(s['end'])}")
            lines.append(s['text'])
            lines.append('')
        content = '\n'.join(lines)
        mime = 'text/plain'
    else:  # vtt
        lines = ['WEBVTT', '']
        for i, s in enumerate(segs):
            lines.append(str(i + 1))
            lines.append(f"{_fmt_vtt(s['start'])} --> {_fmt_vtt(s['end'])}")
            lines.append(s['text'])
            lines.append('')
        content = '\n'.join(lines)
        mime = 'text/vtt'

    from io import BytesIO
    buf = BytesIO(content.encode('utf-8'))
    return send_file(buf, mimetype=mime, as_attachment=True,
                     download_name=f"{base_name}.{fmt}")


def _fmt_srt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _fmt_vtt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


@app.route('/api/files/<file_id>/segments')
def get_file_segments(file_id):
    """Return transcription segments for a file (used to load subtitles in player)"""
    with _registry_lock:
        entry = _file_registry.get(file_id)
    if not entry:
        return jsonify({'error': '文件不存在'}), 404
    return jsonify({
        'id': file_id,
        'status': entry['status'],
        'segments': entry.get('segments', []),
        'text': entry.get('text', ''),
    })


@app.route('/api/files/<file_id>/segments/<int:seg_id>', methods=['PATCH'])
def update_segment_text(file_id, seg_id):
    """Update the text of a single segment (inline editing)"""
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': '缺少 text 參數'}), 400

    new_text = data['text'].strip()
    with _registry_lock:
        entry = _file_registry.get(file_id)
        if not entry:
            return jsonify({'error': '文件不存在'}), 404
        segs = entry.get('segments', [])
        matched = [s for s in segs if s.get('id') == seg_id]
        if not matched:
            return jsonify({'error': '段落不存在'}), 404
        matched[0]['text'] = new_text
        # Also update the full text
        entry['text'] = ' '.join(s['text'] for s in segs)
        _save_registry()

    return jsonify({'status': 'ok', 'id': seg_id, 'text': new_text})


@app.route('/api/files/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    """Delete an uploaded file and its transcription data"""
    if _delete_file_entry(file_id):
        return jsonify({'status': 'deleted', 'id': file_id})
    return jsonify({'error': '文件不存在'}), 404


@app.route('/api/restart', methods=['POST'])
def restart_server():
    """Restart the server process"""
    _save_registry()  # persist state before restart

    def do_restart():
        time.sleep(1)  # let the response reach the client
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=do_restart, daemon=True).start()
    return jsonify({'status': 'restarting', 'message': '服務器正在重啟...'})


# ============================================================
# WebSocket Events
# ============================================================

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"Client connected: {sid}")
    emit('connected', {'sid': sid, 'message': '已連接到 Whisper 服務器'})


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"Client disconnected: {sid}")


@socketio.on('load_model')
def handle_load_model(data):
    """Pre-load a model on request"""
    model_size = data.get('model', 'small')
    sid = request.sid  # capture before entering thread

    socketio.emit('model_loading', {'model': model_size, 'status': 'loading'}, room=sid)

    def load_async():
        try:
            get_model(model_size)
            socketio.emit('model_ready', {'model': model_size, 'status': 'ready'}, room=sid)
        except Exception as e:
            socketio.emit('model_error', {'error': str(e)}, room=sid)

    thread = threading.Thread(target=load_async)
    thread.daemon = True
    thread.start()


if __name__ == '__main__':
    print("=" * 60)
    print("AI 字幕轉換 APP - 後端服務器")
    print("=" * 60)
    print(f"上傳目錄: {UPLOAD_DIR}")
    print(f"結果目錄: {RESULTS_DIR}")
    print("正在啟動服務器...")

    # Load persisted file registry
    _file_registry.update(_load_registry())
    print(f"已載入 {len(_file_registry)} 個已上傳文件")

    # Pre-load small model
    print("預加載模型 (small)...")
    try:
        get_model('small')
        print("模型加載完成!")
    except Exception as e:
        print(f"模型預加載失敗: {e}")

    socketio.run(app, host='0.0.0.0', port=5001, debug=False, allow_unsafe_werkzeug=True)
