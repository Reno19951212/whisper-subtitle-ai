"""Ollama-based translation engine using local LLMs."""

import json
import re
import urllib.request
import urllib.error
from typing import Optional, List

from . import TranslationEngine, TranslatedSegment

ENGINE_TO_MODEL = {
    "qwen2.5-3b": "qwen2.5:3b",
    "qwen2.5-7b": "qwen2.5:7b",
    "qwen2.5-72b": "qwen2.5:72b",
    "qwen3-235b": "qwen3:235b",
}

BATCH_SIZE = 10

SYSTEM_PROMPT_FORMAL = (
    "You are a professional translator. Translate the following English text "
    "into formal Traditional Chinese (繁體中文書面語). Maintain the meaning and tone. "
    "Output ONLY the translations, numbered to match the input."
)

SYSTEM_PROMPT_CANTONESE = (
    "You are a professional translator. Translate the following English text "
    "into Cantonese Traditional Chinese (繁體中文粵語口語). Use natural spoken "
    "Cantonese expressions. Output ONLY the translations, numbered to match the input."
)


class OllamaTranslationEngine(TranslationEngine):
    """Translation engine that calls Ollama's local HTTP API."""

    def __init__(self, config: dict):
        self._config = config
        self._engine_name = config.get("engine", "qwen2.5-3b")
        self._model = ENGINE_TO_MODEL.get(self._engine_name, "qwen2.5:3b")
        self._temperature = config.get("temperature", 0.1)
        self._base_url = config.get("ollama_url", "http://localhost:11434")

    def translate(
        self,
        segments: List[dict],
        glossary: Optional[List[dict]] = None,
        style: str = "formal",
        batch_size: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> List[TranslatedSegment]:
        if not segments:
            return []

        glossary = glossary or []
        all_translated = []
        effective_batch = batch_size if batch_size is not None else BATCH_SIZE
        effective_temp = temperature if temperature is not None else self._temperature

        for i in range(0, len(segments), effective_batch):
            batch = segments[i : i + effective_batch]
            translated_batch = self._translate_batch(batch, glossary, style, effective_temp)
            all_translated.extend(translated_batch)

        return all_translated

    def _translate_batch(
        self, segments: List[dict], glossary: List[dict], style: str, temperature: float
    ) -> List[TranslatedSegment]:
        system_prompt = self._build_system_prompt(style, glossary)
        user_message = self._build_user_message(segments)
        response_text = self._call_ollama(system_prompt, user_message, temperature)
        return self._parse_response(response_text, segments)

    def _build_system_prompt(self, style: str, glossary: List[dict]) -> str:
        if style == "cantonese":
            prompt = SYSTEM_PROMPT_CANTONESE
        else:
            prompt = SYSTEM_PROMPT_FORMAL

        if glossary:
            terms = "\n".join(
                f'- "{entry["en"]}" → "{entry["zh"]}"' for entry in glossary
            )
            prompt += (
                f"\n\nIMPORTANT — Use these specific translations for "
                f"the following terms:\n{terms}"
            )

        return prompt

    def _build_user_message(self, segments: List[dict]) -> str:
        lines = []
        for i, seg in enumerate(segments, 1):
            lines.append(f"{i}. {seg['text']}")
        return "\n".join(lines)

    def _call_ollama(self, system_prompt: str, user_message: str, temperature: float) -> str:
        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get("message", {}).get("content", "")
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self._base_url}. "
                f"Is Ollama running? Error: {e}"
            )

    def _parse_response(
        self, response_text: str, segments: List[dict]
    ) -> List[TranslatedSegment]:
        lines = [ln.strip() for ln in response_text.strip().split("\n") if ln.strip()]

        numbered = {}
        for line in lines:
            match = re.match(r"^(\d+)[.)]\s*(.+)", line)
            if match:
                idx = int(match.group(1))
                numbered[idx] = match.group(2).strip()

        if len(numbered) == len(segments):
            return [
                TranslatedSegment(
                    start=seg["start"],
                    end=seg["end"],
                    en_text=seg["text"],
                    zh_text=numbered[i + 1],
                )
                for i, seg in enumerate(segments)
            ]

        clean_lines = []
        for line in lines:
            cleaned = re.sub(r"^\d+[.)]\s*", "", line).strip()
            if cleaned:
                clean_lines.append(cleaned)

        results = []
        for i, seg in enumerate(segments):
            zh = clean_lines[i] if i < len(clean_lines) else f"[TRANSLATION MISSING] {seg['text']}"
            results.append(
                TranslatedSegment(
                    start=seg["start"],
                    end=seg["end"],
                    en_text=seg["text"],
                    zh_text=zh,
                )
            )
        return results

    def get_info(self) -> dict:
        return {
            "engine": self._engine_name,
            "model": self._model,
            "available": self._check_available(),
            "styles": ["formal", "cantonese"],
        }

    def get_params_schema(self) -> dict:
        return {
            "engine": self._engine_name,
            "params": {
                "model": {
                    "type": "string",
                    "description": "Ollama model to use for translation",
                    "enum": list(ENGINE_TO_MODEL.values()),
                    "default": self._model,
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature (lower = more deterministic)",
                    "minimum": 0.0,
                    "maximum": 2.0,
                    "default": 0.1,
                },
                "batch_size": {
                    "type": "integer",
                    "description": "Number of segments per translation batch",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
                "style": {
                    "type": "string",
                    "description": "Translation style",
                    "enum": ["formal", "cantonese"],
                    "default": "formal",
                },
            },
        }

    def get_models(self) -> list:
        models = []
        for engine_key, model_tag in ENGINE_TO_MODEL.items():
            models.append({
                "engine": engine_key,
                "model": model_tag,
                "available": self._check_model_available(model_tag),
            })
        return models

    def _check_model_available(self, model_tag: str) -> bool:
        try:
            req = urllib.request.Request(f"{self._base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                installed = [m.get("name", "") for m in data.get("models", [])]
                return model_tag in installed
        except Exception:
            return False

    def _check_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                return self._model in models
        except Exception:
            return False
