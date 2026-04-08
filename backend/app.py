#!/usr/bin/env python3
"""
Whisper AI Web Application - Backend Server
Supports video/audio file upload and live transcription to Traditional Chinese subtitles
"""

import os
import sys
import json
import base64
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

# Per-session live transcription state (context carry-over + overlap)
_live_session_state = {}   # sid -> {'last_text': str, 'prev_audio_tail': bytes|None, 'last_segments': list}
_session_state_lock = threading.Lock()

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
            seg_iter, info = model.transcribe(
                audio_path,
                language='zh',
                task='transcribe',
                word_timestamps=True,
                initial_prompt='請將音頻轉錄為繁體中文。',
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

            result = model.transcribe(
                audio_path,
                language='zh',
                task='transcribe',
                verbose=False,
                word_timestamps=True,
                initial_prompt='請將音頻轉錄為繁體中文。',
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


def _extract_audio_tail(audio_bytes: bytes, tail_seconds: float = 1.0) -> bytes:
    """Extract the last tail_seconds of audio using FFmpeg.
    Returns the tail audio bytes, or None on failure."""
    in_file = str(UPLOAD_DIR / f"tail_in_{int(time.time() * 1000)}.webm")
    out_file = str(UPLOAD_DIR / f"tail_out_{int(time.time() * 1000)}.webm")
    try:
        with open(in_file, 'wb') as f:
            f.write(audio_bytes)
        cmd = [
            'ffmpeg', '-y', '-sseof', f'-{tail_seconds}',
            '-i', in_file, '-c', 'copy', out_file
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0 and os.path.exists(out_file):
            with open(out_file, 'rb') as f:
                return f.read()
        return None
    except Exception as e:
        print(f"Error extracting audio tail: {e}")
        return None
    finally:
        for f in [in_file, out_file]:
            if os.path.exists(f):
                os.remove(f)


def _merge_audio_overlap(prev_tail: bytes, current: bytes) -> bytes:
    """Concatenate previous audio tail with current chunk using FFmpeg.
    Returns merged audio bytes, or current on failure."""
    tail_file = str(UPLOAD_DIR / f"merge_tail_{int(time.time() * 1000)}.webm")
    curr_file = str(UPLOAD_DIR / f"merge_curr_{int(time.time() * 1000)}.webm")
    out_file = str(UPLOAD_DIR / f"merge_out_{int(time.time() * 1000)}.webm")
    list_file = str(UPLOAD_DIR / f"merge_list_{int(time.time() * 1000)}.txt")
    try:
        with open(tail_file, 'wb') as f:
            f.write(prev_tail)
        with open(curr_file, 'wb') as f:
            f.write(current)
        # Create concat list file
        with open(list_file, 'w') as f:
            f.write(f"file '{tail_file}'\nfile '{curr_file}'\n")
        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', list_file, '-c', 'copy', out_file
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0 and os.path.exists(out_file):
            with open(out_file, 'rb') as f:
                return f.read()
        return current  # fallback: use current chunk only
    except Exception as e:
        print(f"Error merging audio overlap: {e}")
        return current
    finally:
        for f in [tail_file, curr_file, out_file, list_file]:
            if os.path.exists(f):
                os.remove(f)


def _deduplicate_segments(new_segments: list, prev_segment_texts: list) -> list:
    """Remove segments that overlap with previous chunk's segments.
    Uses character-level similarity for Chinese text."""
    if not prev_segment_texts or not new_segments:
        return new_segments

    def char_overlap_ratio(a: str, b: str) -> float:
        """Compute ratio of overlapping characters between two strings."""
        if not a or not b:
            return 0.0
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        # Check if shorter is contained in longer
        if shorter in longer:
            return 1.0
        # Check suffix-prefix overlap
        max_overlap = min(len(a), len(b))
        for k in range(max_overlap, 0, -1):
            if a[-k:] == b[:k] or b[-k:] == a[:k]:
                return k / max_overlap
        return 0.0

    result = []
    for seg in new_segments:
        text = seg.get('text', '').strip()
        if not text:
            continue
        is_dup = False
        for prev_text in prev_segment_texts:
            if char_overlap_ratio(text, prev_text) > 0.7:
                is_dup = True
                break
        if not is_dup:
            result.append(seg)
    return result


def transcribe_chunk(audio_data: bytes, model_size: str = 'tiny', context_prompt: str = None) -> list:
    """Transcribe a chunk of audio data for live streaming.
    Prefers faster-whisper (lower latency). Falls back to openai-whisper.
    context_prompt: previous transcript text for continuity."""
    model, backend = get_model(model_size, backend='auto')

    prompt = '請將音頻轉錄為繁體中文。'
    if context_prompt:
        prompt += context_prompt[-100:]  # keep last 100 chars to avoid overflow

    temp_file = str(UPLOAD_DIR / f"chunk_{int(time.time() * 1000)}.webm")

    try:
        with open(temp_file, 'wb') as f:
            f.write(audio_data)

        if backend == 'faster':
            seg_iter, _ = model.transcribe(
                temp_file,
                language='zh',
                task='transcribe',
                vad_filter=True,
                initial_prompt=prompt,
            )
            return [
                {'text': seg.text, 'start': seg.start, 'end': seg.end}
                for seg in seg_iter
            ]
        else:
            result = model.transcribe(
                temp_file,
                language='zh',
                task='transcribe',
                verbose=False,
                initial_prompt=prompt,
                fp16=False
            )
            return result.get('segments', [])

    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


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

        translated = engine.translate(asr_segments, glossary=glossary_entries, style=style)

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
    with _session_state_lock:
        _live_session_state[sid] = {
            'last_text': '',
            'prev_audio_tail': None,
            'last_segments': [],
        }
    emit('connected', {'sid': sid, 'message': '已連接到 Whisper 服務器'})


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"Client disconnected: {sid}")
    with _session_state_lock:
        _live_session_state.pop(sid, None)


@socketio.on('live_silence')
def handle_live_silence():
    """Clear overlap buffer when frontend VAD detects silence."""
    sid = request.sid
    with _session_state_lock:
        if sid in _live_session_state:
            _live_session_state[sid]['prev_audio_tail'] = None


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


@socketio.on('live_audio_chunk')
def handle_live_chunk(data):
    """Handle live audio chunk from browser (binary or base64).
    Supports context carry-over, chunk overlap, and deduplication."""
    sid = request.sid
    audio_data = data.get('audio')
    model_size = data.get('model', 'tiny')  # Use tiny for live for speed

    if not audio_data:
        return

    # Support both binary (bytes) and legacy base64 (str)
    if isinstance(audio_data, bytes):
        audio_bytes = audio_data
    else:
        audio_bytes = base64.b64decode(audio_data)

    # Read session state for context carry-over and overlap
    with _session_state_lock:
        state = _live_session_state.get(sid, {})
        context_text = state.get('last_text', '')
        prev_tail = state.get('prev_audio_tail')
        prev_segments = state.get('last_segments', [])

    def process_chunk():
        try:
            # Chunk overlap: prepend previous audio tail if available
            merged_audio = _merge_audio_overlap(prev_tail, audio_bytes) if prev_tail else audio_bytes

            segments = transcribe_chunk(merged_audio, model_size, context_prompt=context_text)

            # Deduplicate against previous chunk's segments
            new_segments = _deduplicate_segments(segments, prev_segments)

            # Emit new (non-duplicate) segments
            emitted_texts = []
            for seg in new_segments:
                text = seg.get('text', '').strip()
                if text:
                    socketio.emit('live_subtitle', {
                        'text': text,
                        'start': seg.get('start', 0),
                        'end': seg.get('end', 0),
                        'timestamp': time.time()
                    }, room=sid)
                    emitted_texts.append(text)

            # Update session state
            all_text = ' '.join(emitted_texts)
            new_tail = _extract_audio_tail(audio_bytes)
            with _session_state_lock:
                if sid in _live_session_state:
                    _live_session_state[sid]['last_text'] = all_text if all_text else context_text
                    _live_session_state[sid]['prev_audio_tail'] = new_tail
                    _live_session_state[sid]['last_segments'] = [
                        seg.get('text', '').strip() for seg in segments if seg.get('text', '').strip()
                    ]

        except Exception as e:
            print(f"Error processing live chunk: {e}")

    thread = threading.Thread(target=process_chunk)
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
