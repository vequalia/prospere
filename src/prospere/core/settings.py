import json
import logging
import os
from typing import Any, Final, cast

_SETTINGS_FILE: Final = os.path.expanduser("~/.prospere_settings.json")
logger = logging.getLogger(__name__)


class SettingsManager:
    """Manages global CLI preferences like last user and language."""

    def __init__(self) -> None:
        self.settings: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not os.path.exists(_SETTINGS_FILE):
            return {}
        try:
            with open(_SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return cast(dict[str, Any], data)
        except Exception:
            return {}

    def save(self) -> None:
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logger.debug(f"Failed to save settings: {e}")

    @property
    def last_user(self) -> str | None:
        return self.settings.get("last_user")

    @last_user.setter
    def last_user(self, value: str | None) -> None:
        self.settings["last_user"] = value
        self.save()

    @property
    def language(self) -> str | None:
        return self.settings.get("language")

    @language.setter
    def language(self, value: str) -> None:
        self.settings["language"] = value
        self.save()

    @property
    def ai_provider(self) -> str | None:
        return self.settings.get("ai_provider")

    @ai_provider.setter
    def ai_provider(self, value: str) -> None:
        self.settings["ai_provider"] = value
        self.save()

    @property
    def ai_base_url(self) -> str | None:
        return self.settings.get("ai_base_url")

    @ai_base_url.setter
    def ai_base_url(self, value: str) -> None:
        self.settings["ai_base_url"] = value
        self.save()

    @property
    def ai_api_key(self) -> str | None:
        return self.settings.get("ai_api_key")

    @ai_api_key.setter
    def ai_api_key(self, value: str) -> None:
        self.settings["ai_api_key"] = value
        self.save()

    @property
    def ai_model(self) -> str | None:
        return self.settings.get("ai_model")

    @ai_model.setter
    def ai_model(self, value: str) -> None:
        self.settings["ai_model"] = value
        self.save()


# Global instance
settings_manager = SettingsManager()
