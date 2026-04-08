# CLAUDE.md — Whisper AI Subtitle App

This file is the authoritative development reference for Claude Code.
**Update this file whenever a new feature is completed.**

---

## Project Overview

A browser-based web application that uses OpenAI Whisper for automatic speech recognition (ASR), converting spoken audio/video into Traditional Chinese subtitles in real time. The app supports both pre-recorded file upload and live camera/screen capture.

**Tech stack:**
- Backend: Python 3.8+, Flask, Flask-SocketIO, openai-whisper, faster-whisper (optional)
- Frontend: Vanilla HTML/CSS/JS (single file, no build step), Socket.IO client
- Audio extraction: FFmpeg (system dependency)

---

## Repository Structure

```
Whisper 開發/
├── backend/
│   ├── app.py              # Flask server — REST API + WebSocket events
│   ├── requirements.txt    # Python dependencies
│   └── data/               # Runtime: uploaded media + registry.json (gitignored)
├── frontend/
│   └── index.html          # Complete single-page web app
├── setup.sh                # One-shot environment setup
├── start.sh                # Start backend + open browser
├── CLAUDE.md               # This file
└── README.md               # User-facing documentation (Traditional Chinese)
```

---

## Architecture

### Backend (`backend/app.py`)

**Model loading (`get_model`)**
- Maintains two separate caches: `_openai_model_cache` and `_faster_model_cache`
- `backend='auto'` prefers `faster-whisper` when installed (int8 quantisation, 4–8× faster)
- Falls back to `openai-whisper` gracefully if `faster-whisper` is not installed
- Thread-safe via `_model_lock`

**Transcription pipeline (`transcribe_with_segments`)**
- For video files (mp4/mov/avi/mkv/webm): extracts 16kHz mono WAV via FFmpeg first
- Emits `subtitle_segment` WebSocket events per segment as they arrive (streaming UX)
- Supports both faster-whisper and openai-whisper output formats

**Live transcription (`transcribe_chunk`)**
- Receives binary WebM audio via WebSocket (with base64 fallback)
- VAD (Voice Activity Detection): frontend uses Web Audio API AnalyserNode to detect speech energy; silent chunks are skipped; backend uses faster-whisper's `vad_filter=True` as safety net
- Context carry-over: previous transcription text is passed as `initial_prompt` for continuity
- Chunk overlap: last 1s of each chunk is prepended to the next via FFmpeg concat, with dedup logic to remove repeated segments
- Per-session state stored in `_live_session_state` dict (keyed by sid): `last_text`, `prev_audio_tail`, `last_segments`
- Helper functions: `_extract_audio_tail()`, `_merge_audio_overlap()`, `_deduplicate_segments()`
- Uses `tiny` model by default for lowest latency

**WebSocket events (server → client)**
| Event | Payload | When |
|---|---|---|
| `connected` | `{sid}` | On connect |
| `model_loading` | `{model, status}` | Model load started |
| `model_ready` | `{model, status}` | Model load complete |
| `model_error` | `{error}` | Model load failed |
| `transcription_status` | `{status, message}` | Extraction/transcription phase |
| `subtitle_segment` | `{id, start, end, text, words[], progress, eta_seconds, total_duration}` | Each segment as it's ready (with progress %) |
| `transcription_complete` | `{text, language, segment_count}` | All done |
| `transcription_error` | `{error}` | Any failure |
| `live_subtitle` | `{text, start, end, timestamp}` | Live mode subtitle |
| `file_added` | `{id, original_name, ...}` | New file uploaded |
| `file_updated` | `{id, status, ...}` | File status changed |

**WebSocket events (client → server)**
| Event | Payload |
|---|---|
| `load_model` | `{model}` |
| `live_audio_chunk` | `{audio: ArrayBuffer (binary), model}` |
| `live_silence` | *(no payload)* |

**REST endpoints**
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Server status, loaded models |
| GET | `/api/models` | Available model list |
| POST | `/api/transcribe` | Upload + async transcription (streams via WS). Returns `file_id`. File is kept on disk until explicitly deleted. |
| POST | `/api/transcribe/sync` | Sync transcription (small files) |
| GET | `/api/files` | List all uploaded files with status |
| GET | `/api/files/<id>/media` | Serve the original uploaded media file |
| GET | `/api/files/<id>/subtitle.<fmt>` | Download subtitle in srt/vtt/txt format |
| GET | `/api/files/<id>/segments` | Get transcription segments for a file |
| PATCH | `/api/files/<id>/segments/<seg_id>` | Update a single segment's text (inline editing) |
| DELETE | `/api/files/<id>` | Delete file from disk and registry |

**File persistence**
- Uploaded files are stored in `backend/data/uploads/` with a unique ID filename
- Metadata (original name, status, segments) is persisted in `backend/data/registry.json`
- The registry is loaded at server startup, so files survive restarts
- Files are only deleted when the user explicitly clicks the delete button

**Important implementation notes**
- Always capture `request.sid` before spawning a background thread — Flask request context is not available inside threads
- `socketio.emit(..., room=sid)` must be used from threads, never bare `emit()`
- Temp files are cleaned up in `finally` blocks

### Frontend (`frontend/index.html`)

Single self-contained file. No build step required.

**Subtitle sync (file playback)**
- `timeupdate` event on `<video>` scans `segments[]` array each tick
- Display window: `videoTime >= segment.start + delay` AND `videoTime <= segment.end + delay + 0.3`
- `delay` is the user-controlled slider (0–5 s); positive delay shifts subtitles to appear later, compensating for processing lag

**Live audio capture**
- `MediaRecorder` records the audio track at 3-second intervals
- Audio sent as binary ArrayBuffer via `live_audio_chunk` WebSocket event (no base64 overhead)
- VAD via Web Audio API `AnalyserNode`: computes RMS energy every 100ms, skips silent chunks
- LIVE indicator turns green (`.speech-active`) when speech is detected
- Frontend dedup: `recentLiveTexts` array tracks last 5 subtitle texts, skips duplicates
- `live_silence` event sent when a chunk is skipped, clearing backend overlap buffer
- Received `live_subtitle` events are displayed after `subtitleDelay` ms

**Export formats**
- SRT: standard subtitle format, compatible with most video players
- VTT: WebVTT format, native HTML5 `<track>` element format
- TXT: plain transcript, one line per segment

---

## Development Guidelines

- Do not add a build system unless the frontend grows to multiple files requiring it
- Keep all frontend logic in `index.html` until complexity warrants splitting
- All new backend routes must handle errors and return JSON `{error: "..."}` with appropriate HTTP status
- New WebSocket events must be documented in the table above
- The `get_model()` function must remain the single entry point for model loading
- Test both faster-whisper and openai-whisper code paths when modifying transcription logic

### Mandatory documentation updates on every feature change

Whenever a new feature is completed or existing functionality is modified, you **must** update the following files before committing:

1. **CLAUDE.md** (this file):
   - Add or update the relevant section in Architecture if the system design changed
   - Update REST endpoint / WebSocket event tables if new routes or events were added
   - Append a new version entry under "Completed Features" describing what was added or changed

2. **README.md** (user-facing, **must be written in Traditional Chinese**):
   - Update the feature table at the top if a new capability was added
   - Update the usage instructions if the user workflow changed
   - Update the project structure section if new files/directories were introduced
   - Update the API reference table if new endpoints were added
   - Append a new version entry under "更新記錄" describing the changes
   - Ensure all text remains in Traditional Chinese (繁體中文)

---

## Completed Features

### v1.0 — Initial Build
- File upload mode: drag-and-drop or file picker, supports MP4/MOV/AVI/MKV/WebM/MP3/WAV/M4A/AAC/FLAC/OGG
- Live mode: camera or screen share via `getUserMedia` / `getDisplayMedia`
- Real-time Traditional Chinese subtitles overlaid on video
- Subtitle delay slider (0–5 s) for audio/subtitle sync compensation
- Subtitle display duration control (1–10 s)
- Subtitle font size control (14–48 px)
- Segment-by-segment transcript panel with timestamps
- Model selector: tiny / base / small / medium / large / turbo
- Model pre-load button
- SRT export
- TXT export

### v1.1 — Bug Fixes & Reliability
- Fixed subtitle sync direction: delay now correctly shifts subtitles *later* (was inverted)
- Removed duplicate `timeupdate` event listeners accumulating per segment
- Fixed `emit()` called from background thread without request context (captured `sid` before thread spawn)
- Fixed large audio buffer base64 conversion stack overflow (chunked loop, 8192 bytes per call)
- Moved `import base64` to module level

### v1.2 — faster-whisper & WebVTT
- Added optional `faster-whisper` backend (4–8× faster, int8 quantised, auto-selected when installed)
- Dual model cache: separate caches for openai-whisper and faster-whisper
- Fixed live chunk temp file extension (`.webm` instead of `.wav`)
- Fixed health endpoint referencing deleted `_model_cache` variable
- Added WebVTT (`.vtt`) export format

### v1.3 — Persistent File Management
- Uploaded files are now kept on disk until the user explicitly deletes them (no longer auto-deleted after transcription)
- File registry persisted in `backend/data/registry.json`; survives server restarts
- Frontend file list: each uploaded file appears as a card with status indicator (uploading/transcribing/done/error)
- Click a file card to load its media into the video player
- Per-file SRT/VTT/TXT download links appear directly on the card when transcription is done
- Delete button on each file card removes the file from disk and registry
- Backend: `async_mode` switched from `eventlet` (deprecated) to `threading`; server port changed to 5001 (macOS AirPlay conflict)
- New REST endpoints: `GET /api/files`, `GET /api/files/<id>/media`, `GET /api/files/<id>/subtitle.<fmt>`, `DELETE /api/files/<id>`
- New WebSocket events: `file_added`, `file_updated`

### v1.4 — Transcription Progress Bar with ETA
- Backend: `get_media_duration()` uses `ffprobe` to detect total audio/video duration before transcription
- Backend: each `subtitle_segment` event now includes `progress` (0–1), `eta_seconds`, and `total_duration`
- Frontend: file card shows a progress bar during transcription with percentage, timeline (processed/total), and estimated time remaining
- Progress is calculated as `segment.end / total_duration`; ETA is derived from elapsed wall-clock time vs progress ratio

### v1.5 — Model Info Display & Inline Transcript Editing
- File registry now stores `model` (e.g. 'small', 'tiny') and `backend` ('openai-whisper' or 'faster-whisper') per file
- File cards show a model badge (e.g. "small · openai") in the download actions row when transcription is done
- `GET /api/files` and `file_updated` events now include `model` and `backend` fields
- Transcript text is inline-editable: click any segment text to edit, press Enter to save, Escape to cancel
- Edits are persisted to the backend via `PATCH /api/files/<id>/segments/<seg_id>` and update `registry.json`
- Edited text syncs to: the `segments[]` array (subtitle overlay), and all export formats (SRT/VTT/TXT, served from the registry)
- Hover effect on transcript text to hint editability (subtle purple highlight)

### v1.6 — Enhanced Live Transcription
- **Binary WebSocket**: audio chunks sent as binary ArrayBuffer instead of base64, reducing transfer overhead by ~33%
- **VAD (Voice Activity Detection)**: frontend uses Web Audio API AnalyserNode to compute RMS energy; silent chunks are skipped entirely; backend uses faster-whisper `vad_filter=True` as safety net
- **Context carry-over**: previous transcription text passed as `initial_prompt` for next chunk, improving continuity across chunk boundaries
- **Chunk overlap**: last 1s of each audio chunk is stored and prepended to the next chunk via FFmpeg concat, preventing sentence truncation at boundaries
- **Deduplication**: backend `_deduplicate_segments()` uses character-level overlap ratio (>70% threshold); frontend tracks last 5 subtitle texts for additional dedup
- **Per-session state**: `_live_session_state` dict tracks `last_text`, `prev_audio_tail`, `last_segments` per WebSocket session; cleaned up on disconnect
- **Visual feedback**: LIVE indicator turns green when speech detected, red when silent
- New WebSocket event: `live_silence` (client → server) clears overlap buffer on silence
