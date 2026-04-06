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
- Receives base64-encoded WebM audio blobs from browser every 3 seconds
- Saves to temp file, transcribes, emits `live_subtitle` events back to client
- Uses `tiny` model by default for lowest latency

**WebSocket events (server → client)**
| Event | Payload | When |
|---|---|---|
| `connected` | `{sid}` | On connect |
| `model_loading` | `{model, status}` | Model load started |
| `model_ready` | `{model, status}` | Model load complete |
| `model_error` | `{error}` | Model load failed |
| `transcription_status` | `{status, message}` | Extraction/transcription phase |
| `subtitle_segment` | `{id, start, end, text, words[]}` | Each segment as it's ready |
| `transcription_complete` | `{text, language, segment_count}` | All done |
| `transcription_error` | `{error}` | Any failure |
| `live_subtitle` | `{text, start, end, timestamp}` | Live mode subtitle |
| `file_added` | `{id, original_name, ...}` | New file uploaded |
| `file_updated` | `{id, status, ...}` | File status changed |

**WebSocket events (client → server)**
| Event | Payload |
|---|---|
| `load_model` | `{model}` |
| `live_audio_chunk` | `{audio: base64, model}` |

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
- Each blob is base64-encoded in chunks of 8192 bytes (avoids stack overflow on large buffers)
- Sent to server via `live_audio_chunk` WebSocket event
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
