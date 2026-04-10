"""FLG-ASR engine stub — not available in dev environment."""

from . import ASREngine, Segment


class FLGASREngine(ASREngine):
    def __init__(self, config: dict):
        self._config = config

    def transcribe(self, audio_path: str, language: str = "en") -> list[Segment]:
        raise NotImplementedError(
            "FLG-ASR is not available in this environment. "
            "Use the 'whisper' engine or deploy on production hardware."
        )

    def get_info(self) -> dict:
        return {
            "engine": "flg-asr",
            "model_size": self._config.get("model_size", "unknown"),
            "languages": ["en", "zh"],
            "available": False,
        }

    def get_params_schema(self) -> dict:
        return {
            "engine": "flg-asr",
            "params": {
                "model_size": {
                    "type": "string",
                    "description": "FLG-ASR model variant",
                    "enum": ["standard"],
                    "default": "standard",
                },
                "language": {
                    "type": "string",
                    "description": "Source language code (ISO 639-1)",
                    "enum": ["en", "zh"],
                    "default": "en",
                },
            },
        }
