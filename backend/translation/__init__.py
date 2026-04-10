"""Translation Pipeline — unified interface for text translation engines."""
from abc import ABC, abstractmethod
from typing import TypedDict, List, Dict, Optional


class TranslatedSegment(TypedDict):
    start: float
    end: float
    en_text: str
    zh_text: str


class TranslationEngine(ABC):
    @abstractmethod
    def translate(self, segments: List[dict], glossary: Optional[List[dict]] = None, style: str = "formal", batch_size: Optional[int] = None, temperature: Optional[float] = None) -> List[TranslatedSegment]:
        """Translate English segments to Chinese."""

    @abstractmethod
    def get_info(self) -> dict:
        """Return engine metadata."""

    @abstractmethod
    def get_params_schema(self) -> dict:
        """Return JSON schema describing configurable parameters for this engine."""

    @abstractmethod
    def get_models(self) -> List[dict]:
        """Return list of available models for this engine."""


def create_translation_engine(translation_config: dict) -> TranslationEngine:
    engine_name = translation_config.get("engine", "")
    if engine_name == "mock":
        from .mock_engine import MockTranslationEngine
        return MockTranslationEngine(translation_config)
    elif engine_name in {"qwen3-235b", "qwen2.5-72b", "qwen2.5-7b", "qwen2.5-3b"}:
        from .ollama_engine import OllamaTranslationEngine
        return OllamaTranslationEngine(translation_config)
    else:
        raise ValueError(f"Unknown translation engine: {engine_name}")
