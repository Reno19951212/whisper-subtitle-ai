"""Whisper ASR engine — full implementation using faster-whisper or openai-whisper."""

import threading

from . import ASREngine, Segment

try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False

try:
    import whisper as openai_whisper
    OPENAI_WHISPER_AVAILABLE = True
except ImportError:
    OPENAI_WHISPER_AVAILABLE = False

_faster_model_cache: dict = {}
_openai_model_cache: dict = {}
_model_lock = threading.Lock()


class WhisperEngine(ASREngine):
    def __init__(self, config: dict):
        self._config = config
        self._model_size = config.get("model_size", "small")
        self._device = config.get("device", "auto")

    def _get_model(self):
        """Load and cache the Whisper model. Returns (model, backend_name)."""
        with _model_lock:
            if FASTER_WHISPER_AVAILABLE:
                if self._model_size not in _faster_model_cache:
                    print(f"Loading faster-whisper model: {self._model_size}")
                    _faster_model_cache[self._model_size] = FasterWhisperModel(
                        self._model_size, device=self._device, compute_type="int8"
                    )
                    print(f"faster-whisper model {self._model_size} loaded")
                return _faster_model_cache[self._model_size], "faster"
            elif OPENAI_WHISPER_AVAILABLE:
                if self._model_size not in _openai_model_cache:
                    print(f"Loading openai-whisper model: {self._model_size}")
                    _openai_model_cache[self._model_size] = openai_whisper.load_model(
                        self._model_size
                    )
                    print(f"openai-whisper model {self._model_size} loaded")
                return _openai_model_cache[self._model_size], "openai"
            else:
                raise RuntimeError("Neither faster-whisper nor openai-whisper is installed")

    def transcribe(self, audio_path: str, language: str = "en") -> list[Segment]:
        model, backend = self._get_model()
        if backend == "faster":
            return self._transcribe_faster(model, audio_path, language)
        else:
            return self._transcribe_openai(model, audio_path, language)

    def _transcribe_faster(self, model, audio_path: str, language: str) -> list[Segment]:
        seg_iter, _info = model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
        )
        segments = []
        for seg in seg_iter:
            segments.append(Segment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
            ))
        return segments

    def _transcribe_openai(self, model, audio_path: str, language: str) -> list[Segment]:
        result = model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
            verbose=False,
            fp16=False,
        )
        segments = []
        for seg in result.get("segments", []):
            segments.append(Segment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            ))
        return segments

    def get_info(self) -> dict:
        return {
            "engine": "whisper",
            "model_size": self._model_size,
            "languages": ["en", "zh", "ja", "ko", "fr", "de", "es"],
            "available": True,
        }

    def get_params_schema(self) -> dict:
        return {
            "engine": "whisper",
            "params": {
                "model_size": {
                    "type": "string",
                    "description": "Whisper model size",
                    "enum": ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
                    "default": "small",
                },
                "language": {
                    "type": "string",
                    "description": "Source language code (ISO 639-1)",
                    "enum": ["en", "zh", "ja", "ko", "fr", "de", "es"],
                    "default": "en",
                },
                "device": {
                    "type": "string",
                    "description": "Computation device",
                    "enum": ["auto", "cpu", "cuda"],
                    "default": "auto",
                },
            },
        }
