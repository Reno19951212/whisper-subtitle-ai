"""Mock translation engine for development and testing."""
from typing import List, Optional
from . import TranslationEngine, TranslatedSegment


class MockTranslationEngine(TranslationEngine):
    def __init__(self, config: dict):
        self._config = config

    def translate(self, segments: List[dict], glossary: Optional[List[dict]] = None, style: str = "formal", batch_size: Optional[int] = None, temperature: Optional[float] = None) -> List[TranslatedSegment]:
        return [
            TranslatedSegment(start=seg["start"], end=seg["end"], en_text=seg["text"], zh_text=f"[EN\u2192ZH] {seg['text']}")
            for seg in segments
        ]

    def get_info(self) -> dict:
        return {"engine": "mock", "model": "mock", "available": True, "styles": ["formal", "cantonese"]}

    def get_params_schema(self) -> dict:
        return {
            "engine": "mock",
            "params": {
                "style": {
                    "type": "string",
                    "description": "Translation style",
                    "enum": ["formal", "cantonese"],
                    "default": "formal",
                },
            },
        }

    def get_models(self) -> list:
        return [{"engine": "mock", "model": "mock", "available": True}]
