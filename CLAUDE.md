# CLAUDE.md — Broadcast Subtitle Pipeline

This file is the authoritative development reference for Claude Code.
**Update this file whenever a new feature is completed.**

---

## Project Overview

A browser-based broadcast subtitle production pipeline that converts English video content into Traditional Chinese (Cantonese or formal) subtitles. The pipeline: English ASR → Translation → Proof-reading → Burnt-in subtitle output (MP4/MXF).

**Tech stack:**
- Backend: Python 3.8+, Flask, Flask-SocketIO, faster-whisper/openai-whisper, Ollama (local LLM)
- Frontend: Vanilla HTML/CSS/JS (no build step), Socket.IO client
- ASR: Whisper (via faster-whisper or openai-whisper), Qwen3-ASR and FLG-ASR stubs for production
- Translation: Ollama + Qwen2.5 (local), Mock engine for dev/testing
- Rendering: FFmpeg (ASS subtitle burn-in)
- Audio extraction: FFmpeg (system dependency)

---

## Repository Structure

```
whisper-subtitle-ai/
├── backend/
│   ├── app.py                  # Flask server — REST API + WebSocket events
│   ├── profiles.py             # Profile management (ASR + Translation model routing)
│   ├── glossary.py             # Glossary management (EN→ZH term mappings)
│   ├── renderer.py             # Subtitle renderer (ASS generation + FFmpeg burn-in)
│   ├── asr/                    # ASR engine abstraction
│   │   ├── __init__.py         # ASREngine ABC + factory
│   │   ├── whisper_engine.py   # Whisper implementation
│   │   ├── qwen3_engine.py     # Qwen3-ASR stub
│   │   └── flg_engine.py       # FLG-ASR stub
│   ├── translation/            # Translation engine abstraction
│   │   ├── __init__.py         # TranslationEngine ABC + factory
│   │   ├── ollama_engine.py    # Ollama/Qwen implementation
│   │   └── mock_engine.py      # Mock engine for dev/testing
│   ├── config/                 # Configuration files
│   │   ├── settings.json       # Active profile pointer
│   │   ├── profiles/           # Profile JSON files
│   │   └── glossaries/         # Glossary JSON files
│   ├── tests/                  # Test suite (109 tests)
│   ├── data/                   # Runtime: uploads, registry, renders (gitignored)
│   └── requirements.txt        # Python dependencies
├── frontend/
│   ├── index.html              # Main dashboard — upload, transcribe, translate
│   └── proofread.html          # Proof-reading editor — review, edit, approve, render
├── docs/superpowers/           # Design specs and implementation plans
├── setup.sh                    # One-shot environment setup
├── start.sh                    # Start backend + open browser
├── CLAUDE.md                   # This file
└── README.md                   # User-facing documentation (Traditional Chinese)
```

---

## Architecture

### Pipeline Flow

```
English Video (MP4/MXF)
    │
    ▼ FFmpeg audio extraction
English Audio (16kHz WAV)
    │
    ▼ ASR Engine (Whisper / Qwen3-ASR / FLG-ASR)
English Transcript [{start, end, text}]
    │
    ▼ Translation Engine (Ollama Qwen / Mock) + Glossary
Chinese Translation [{start, end, en_text, zh_text}]
    │
    ▼ Proof-reading Editor (human review + edit + approve)
Approved Translations
    │
    ▼ Subtitle Renderer (ASS + FFmpeg burn-in)
Output Video with burnt-in Chinese subtitles (MP4 / MXF ProRes)
```

### Backend Modules

**`app.py`** — Flask server, REST API, WebSocket events, file registry, orchestration

**`profiles.py`** — Profile CRUD. Each profile defines ASR engine + Translation engine + Font config. JSON file storage in `config/profiles/`. One profile is active at a time.

**`glossary.py`** — Glossary CRUD. EN→ZH term mappings injected into translation prompts. JSON file storage in `config/glossaries/`. CSV import/export supported.

**`renderer.py`** — Generates ASS subtitle files from approved translations + font config, then invokes FFmpeg to burn subtitles into video. Supports MP4 (H.264) and MXF (ProRes 422 HQ) output.

**`asr/`** — Unified ASR interface. `ASREngine` ABC with `transcribe(audio_path, language)` method. Factory function creates the correct engine from profile config. WhisperEngine is fully implemented; Qwen3 and FLG are stubs.

**`translation/`** — Unified translation interface. `TranslationEngine` ABC with `translate(segments, glossary, style)` method. OllamaTranslationEngine calls local Ollama API with batch prompts. MockTranslationEngine for dev/testing.

### Backend (`app.py`)

**Model loading (`get_model`)** — Legacy path for direct Whisper model loading. Maintains dual caches for faster-whisper and openai-whisper. Used when active profile doesn't specify a whisper ASR engine.

**Transcription pipeline (`transcribe_with_segments`)** — Extracts audio from video via FFmpeg, then delegates to ASR engine from active profile. Reads language from profile config. Emits `subtitle_segment` WebSocket events per segment. After transcription completes, auto-triggers translation via `_auto_translate()`.

**Auto-translation (`_auto_translate`)** — Called after transcription. Reads active profile's translation config, loads glossary if configured, calls translation engine, stores results in file registry.

**WebSocket events (server → client)**
| Event | Payload | When |
|---|---|---|
| `connected` | `{sid}` | On connect |
| `model_loading` | `{model, status}` | Model load started |
| `model_ready` | `{model, status}` | Model load complete |
| `model_error` | `{error}` | Model load failed |
| `transcription_status` | `{status, message}` | Extraction/transcription phase |
| `subtitle_segment` | `{id, start, end, text, words[], progress, eta_seconds, total_duration}` | Each segment as it's ready |
| `transcription_complete` | `{text, language, segment_count}` | Transcription done |
| `transcription_error` | `{error}` | Any failure |
| `file_added` | `{id, original_name, ...}` | New file uploaded |
| `file_updated` | `{id, status, translation_status, ...}` | File status changed |

**WebSocket events (client → server)**
| Event | Payload |
|---|---|
| `load_model` | `{model}` |

**REST endpoints**
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Server status, loaded models |
| GET | `/api/models` | Available Whisper model list |
| POST | `/api/transcribe` | Upload + async transcription → auto-translate |
| GET | `/api/files` | List all uploaded files with status |
| GET | `/api/files/<id>/media` | Serve original media file |
| GET | `/api/files/<id>/subtitle.<fmt>` | Download subtitle (srt/vtt/txt) |
| GET | `/api/files/<id>/segments` | Get transcription segments |
| PATCH | `/api/files/<id>/segments/<seg_id>` | Update segment text |
| DELETE | `/api/files/<id>` | Delete file |
| GET | `/api/profiles` | List all profiles |
| POST | `/api/profiles` | Create profile |
| GET | `/api/profiles/active` | Get active profile |
| GET | `/api/profiles/<id>` | Get profile |
| PATCH | `/api/profiles/<id>` | Update profile |
| DELETE | `/api/profiles/<id>` | Delete profile |
| POST | `/api/profiles/<id>/activate` | Set active profile |
| GET | `/api/asr/engines` | List ASR engines with availability |
| POST | `/api/translate` | Translate a file's segments |
| GET | `/api/translation/engines` | List translation engines with availability |
| GET | `/api/glossaries` | List all glossaries |
| POST | `/api/glossaries` | Create glossary |
| GET | `/api/glossaries/<id>` | Get glossary with entries |
| PATCH | `/api/glossaries/<id>` | Update glossary |
| DELETE | `/api/glossaries/<id>` | Delete glossary |
| POST | `/api/glossaries/<id>/entries` | Add glossary entry |
| PATCH | `/api/glossaries/<id>/entries/<eid>` | Update entry |
| DELETE | `/api/glossaries/<id>/entries/<eid>` | Delete entry |
| POST | `/api/glossaries/<id>/import` | Import CSV |
| GET | `/api/glossaries/<id>/export` | Export CSV |
| GET | `/api/files/<id>/translations` | Get translations with approval status |
| PATCH | `/api/files/<id>/translations/<idx>` | Update translation text (auto-approve) |
| POST | `/api/files/<id>/translations/<idx>/approve` | Approve single translation |
| POST | `/api/files/<id>/translations/approve-all` | Approve all pending |
| GET | `/api/files/<id>/translations/status` | Get approval progress |
| POST | `/api/render` | Start subtitle burn-in render job |
| GET | `/api/renders/<id>` | Check render job status |
| GET | `/api/renders/<id>/download` | Download rendered file |

### Frontend

**`index.html`** — Main dashboard. File upload, transcription with progress, auto-translation, profile selector, transcript display (auto-switches to Chinese when translations available), subtitle overlay on video playback.

**`proofread.html`** — Standalone proof-reading editor. Side-by-side layout: video player (left) + segment table (right). Inline editing of Chinese translations, per-segment and bulk approval, keyboard shortcuts, format picker (MP4/MXF), render with progress polling and download.

---

## Development Guidelines

- Do not add a build system unless the frontend grows to multiple files requiring it
- All new backend routes must handle errors and return JSON `{error: "..."}` with appropriate HTTP status
- The `get_model()` function is the legacy model loading path; new code should use `asr/` engines via profiles
- Test both faster-whisper and openai-whisper code paths when modifying transcription logic
- Profiles control which ASR + Translation engines are used; always read from active profile
- Glossary entries are injected into translation prompts as few-shot examples

### Mandatory documentation updates on every feature change

Whenever a new feature is completed or existing functionality is modified, you **must** update:

1. **CLAUDE.md** (this file) — Architecture, REST endpoints, version history
2. **README.md** (user-facing, **must be written in Traditional Chinese**)

---

## Completed Features

### v2.0 — Broadcast Subtitle Pipeline
- **Complete pipeline rewrite**: English video → ASR → Translation → Proof-reading → Burnt-in subtitle output
- **Profile system**: Configurable ASR + Translation engine combinations with environment-aware defaults
- **Multi-engine ASR**: Unified interface supporting Whisper (full), Qwen3-ASR (stub), FLG-ASR (stub)
- **Translation pipeline**: Ollama + Qwen2.5 for local EN→ZH translation, Mock engine for dev
- **Glossary manager**: EN→ZH term mappings with CRUD, CSV import/export, auto-injection into translation prompts
- **Proof-reading editor**: Standalone page with side-by-side video + segment table, inline editing, per-segment and bulk approval, keyboard shortcuts
- **Subtitle renderer**: ASS generation with configurable font, FFmpeg burn-in, MP4 (H.264) and MXF (ProRes 422 HQ) output
- **Auto-translate**: Transcription completion automatically triggers translation
- **Removed live recording mode**: Camera/screen capture, VAD, chunk transcription, streaming mode all removed — project refocused on file-based broadcast pipeline
- **109 automated tests** across profiles, ASR, translation, glossary, proofreading, and rendering

### v1.0–v1.5 — Original Whisper Subtitle App
- File upload with drag-and-drop, persistent file management
- Whisper ASR with faster-whisper support (4–8× faster)
- Transcription progress bar with ETA
- Inline transcript editing
- SRT/VTT/TXT export
- Subtitle delay, duration, and font size controls
