"""
Profile management module for the broadcast subtitle pipeline.

Profiles store ASR + translation engine configurations so users can
switch between model combinations without reconfiguring manually.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Valid option sets
# ---------------------------------------------------------------------------

VALID_ASR_ENGINES = {"whisper", "qwen3-asr", "flg-asr"}
VALID_TRANSLATION_ENGINES = {"qwen3-235b", "qwen2.5-72b", "qwen2.5-7b", "qwen2.5-3b"}
VALID_DEVICES = {"cpu", "cuda", "mps", "auto"}

SETTINGS_FILENAME = "settings.json"
PROFILES_DIRNAME = "profiles"


class ProfileManager:
    """
    Manages profile CRUD, validation, and active-profile tracking.

    All mutating operations return new data structures rather than
    modifying in place, keeping the persistence layer as the single
    source of truth.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = Path(config_dir)
        self._profiles_dir = self._config_dir / PROFILES_DIRNAME
        self._settings_path = self._config_dir / SETTINGS_FILENAME

        self._profiles_dir.mkdir(parents=True, exist_ok=True)

        if not self._settings_path.exists():
            self._write_settings({"active_profile": None})

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, data: dict) -> list:
        """
        Validate a profile data dict against the schema.

        Returns a list of human-readable error strings.
        An empty list means the data is valid.
        """
        errors = []

        # name
        name = data.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            errors.append("name is required")

        # asr block
        asr = data.get("asr")
        if asr is None:
            errors.append("asr is required")
        elif not isinstance(asr, dict):
            errors.append("asr must be an object")
        else:
            asr_errors = _validate_asr(asr)
            errors.extend(asr_errors)

        # translation block
        translation = data.get("translation")
        if translation is None:
            errors.append("translation is required")
        elif not isinstance(translation, dict):
            errors.append("translation must be an object")
        else:
            translation_errors = _validate_translation(translation)
            errors.extend(translation_errors)

        return errors

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, data: dict) -> dict:
        """
        Create a new profile from validated data.

        Returns the stored profile dict (with `id` field set).
        Raises ValueError if data is invalid.
        """
        errors = self.validate(data)
        if errors:
            raise ValueError(f"Invalid profile data: {errors}")

        profile_id = str(uuid.uuid4())
        profile = {**data, "id": profile_id, "created_at": time.time()}
        self._write_profile(profile_id, profile)
        return profile

    def get(self, profile_id: str) -> Optional[dict]:
        """
        Read a profile by id.

        Returns the profile dict, or None if not found.
        """
        profile_path = self._profile_path(profile_id)
        if not profile_path.exists():
            return None
        return self._read_profile(profile_path)

    def list_all(self) -> list:
        """
        Return all profiles sorted ascending by name.
        """
        profiles = []
        for path in self._profiles_dir.glob("*.json"):
            try:
                profile = self._read_profile(path)
                profiles.append(profile)
            except (json.JSONDecodeError, OSError):
                # Skip corrupted files rather than crashing
                continue
        return sorted(profiles, key=lambda p: (p.get("name") or "").lower())

    def update(self, profile_id: str, data: dict) -> Optional[dict]:
        """
        Merge `data` into an existing profile, validate, then persist.

        The merge is a **shallow (top-level) merge**: each key in `data`
        replaces the corresponding top-level key in the existing profile.
        Nested blocks such as ``asr`` and ``translation`` are replaced in
        their entirety, so callers must supply the complete nested object
        if any of their inner fields change — partial nested updates are
        not supported.

        Returns the updated profile, or None if profile_id is not found.
        Raises ValueError if the merged data is invalid.
        """
        existing = self.get(profile_id)
        if existing is None:
            return None

        merged = {**existing, **data, "id": profile_id}
        errors = self.validate(merged)
        if errors:
            raise ValueError(f"Invalid profile data: {errors}")

        self._write_profile(profile_id, merged)
        return merged

    def delete(self, profile_id: str) -> bool:
        """
        Delete a profile by id.

        Clears the active profile if it matched.
        Returns True if deleted, False if not found.
        """
        profile_path = self._profile_path(profile_id)
        if not profile_path.exists():
            return False

        profile_path.unlink()

        settings = self._read_settings()
        if settings.get("active_profile") == profile_id:
            self._write_settings({**settings, "active_profile": None})

        return True

    # ------------------------------------------------------------------
    # Active profile
    # ------------------------------------------------------------------

    def get_active(self) -> Optional[dict]:
        """
        Return the currently active profile, or None if none is set
        or the referenced profile no longer exists.
        """
        settings = self._read_settings()
        active_id = settings.get("active_profile")
        if not active_id:
            return None
        return self.get(active_id)

    def set_active(self, profile_id: str) -> Optional[dict]:
        """
        Set the active profile by id.

        Returns the profile dict, or None if profile_id is not found.
        """
        profile = self.get(profile_id)
        if profile is None:
            return None

        settings = self._read_settings()
        self._write_settings({**settings, "active_profile": profile_id})
        return profile

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _profile_path(self, profile_id: str) -> Path:
        return self._profiles_dir / f"{profile_id}.json"

    def _read_profile(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_profile(self, profile_id: str, profile: dict) -> None:
        path = self._profile_path(profile_id)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)

    def _read_settings(self) -> dict:
        try:
            return json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"active_profile": None}

    def _write_settings(self, settings: dict) -> None:
        tmp_path = self._settings_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._settings_path)


# ---------------------------------------------------------------------------
# Internal validation helpers (pure functions, no mutation)
# ---------------------------------------------------------------------------

def _validate_asr(asr: dict) -> list:
    errors = []

    engine = asr.get("engine")
    if not engine:
        errors.append("asr.engine is required")
    elif engine not in VALID_ASR_ENGINES:
        errors.append(
            f"asr.engine '{engine}' is not valid; must be one of {sorted(VALID_ASR_ENGINES)}"
        )

    if not asr.get("language"):
        errors.append("asr.language is required")

    device = asr.get("device")
    if device is not None and device not in VALID_DEVICES:
        errors.append(
            f"asr.device '{device}' is not valid; must be one of {sorted(VALID_DEVICES)}"
        )

    return errors


def _validate_translation(translation: dict) -> list:
    errors = []

    engine = translation.get("engine")
    if not engine:
        errors.append("translation.engine is required")
    elif engine not in VALID_TRANSLATION_ENGINES:
        errors.append(
            f"translation.engine '{engine}' is not valid; "
            f"must be one of {sorted(VALID_TRANSLATION_ENGINES)}"
        )

    return errors
