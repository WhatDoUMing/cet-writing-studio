"""Runtime configuration loading and persistence."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from security import SecretStore


class ConfigManager:
    """Load defaults, overlay the user config, and expose typed helpers."""

    API_KEY_NAME = "cet_glm_api_key"
    PROVIDER_SECRET_NAMES = {
        "glm": "cet_glm_api_key",
        "openai": "cet_openai_api_key",
        "deepseek": "cet_deepseek_api_key",
    }
    OCR_PROVIDER_SECRET_NAMES = {
        "glm": "glm_cet_ocr_api_key",
        "openai": "openai_cet_ocr_api_key",
        "deepseek": "deepseek_cet_ocr_api_key",
    }

    def __init__(
        self,
        project_root: str | Path,
        resource_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.resource_root = Path(resource_root or project_root)
        self.default_path = (
            self.resource_root / "config" / "default_settings.json"
        )
        self.user_path = self.project_root / "config" / "settings.json"
        self._data: dict[str, Any] = {}
        self._secrets = SecretStore(self.project_root / "config" / "CETWritingStudio")
        self.load()

    def load(self) -> dict[str, Any]:
        defaults = self._read_json(self.default_path)
        user = self._read_json(self.user_path)
        self._migrate_legacy_ai_config(user)
        self._migrate_ocr_config(user)
        self._data = self._deep_merge(defaults, user)
        self._ensure_required_dirs()
        return self._data

    def save(self) -> None:
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        node = self._data
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def resolve_path(self, dotted_key: str) -> Path:
        raw = self.get(dotted_key, "")
        path = Path(raw)
        return path if path.is_absolute() else self.project_root / path

    def get_ai_provider(self) -> str:
        provider = str(self.get("ai.provider", "glm")).strip().lower()
        return provider if provider in self.PROVIDER_SECRET_NAMES else "glm"

    def get_ai_provider_config(
        self,
        provider: str | None = None,
    ) -> dict[str, Any]:
        provider = self.get_ai_provider() if provider is None else provider
        ai_config = self.get("ai", {}) or {}
        providers = ai_config.get("providers", {}) or {}
        result = dict(providers.get(provider, {}) or {})
        for key in (
            "temperature",
            "top_k",
            "max_tokens",
            "timeout_seconds",
        ):
            if key in ai_config:
                result.setdefault(key, ai_config[key])
        return result

    def get_ocr_config(self) -> dict[str, Any]:
        """Return OCR settings with a project-relative model path resolved."""
        result = dict(self.get("ocr", {}) or {})
        local_path = str(result.get("local_model_path", "")).strip()
        if local_path:
            path = Path(local_path)
            result["local_model_path"] = str(
                path if path.is_absolute() else self.project_root / path
            )
        return result

    def get_api_key(self, provider: str | None = None) -> str | None:
        provider = self.get_ai_provider() if provider is None else provider
        secret_name = self.PROVIDER_SECRET_NAMES.get(
            provider,
            f"{provider}_api_key",
        )
        return self._secrets.get_secret(secret_name)

    def set_api_key(self, value: str, provider: str | None = None) -> None:
        provider = self.get_ai_provider() if provider is None else provider
        secret_name = self.PROVIDER_SECRET_NAMES.get(
            provider,
            f"{provider}_api_key",
        )
        self._secrets.set_secret(secret_name, value)

    def delete_api_key(self, provider: str | None = None) -> None:
        provider = self.get_ai_provider() if provider is None else provider
        secret_name = self.PROVIDER_SECRET_NAMES.get(
            provider,
            f"{provider}_api_key",
        )
        self._secrets.delete_secret(secret_name)

    def get_ocr_api_key(
        self,
        provider: str | None = None,
        *,
        fallback: bool = True,
    ) -> str | None:
        provider = self.get_ai_provider() if provider is None else provider
        secret_name = self.OCR_PROVIDER_SECRET_NAMES.get(
            provider,
            f"{provider}_cet_ocr_api_key",
        )
        value = self._secrets.get_secret(secret_name)
        if value or not fallback:
            return value
        return self.get_api_key(provider)

    def set_ocr_api_key(
        self,
        value: str,
        provider: str | None = None,
    ) -> None:
        provider = self.get_ai_provider() if provider is None else provider
        secret_name = self.OCR_PROVIDER_SECRET_NAMES.get(
            provider,
            f"{provider}_cet_ocr_api_key",
        )
        self._secrets.set_secret(secret_name, value)

    def delete_ocr_api_key(self, provider: str | None = None) -> None:
        provider = self.get_ai_provider() if provider is None else provider
        secret_name = self.OCR_PROVIDER_SECRET_NAMES.get(
            provider,
            f"{provider}_cet_ocr_api_key",
        )
        self._secrets.delete_secret(secret_name)

    @staticmethod
    def _migrate_legacy_ai_config(user: dict[str, Any]) -> None:
        """Move pre-provider GLM settings into the provider map."""
        ai_config = user.setdefault("ai", {})
        if not isinstance(ai_config, dict):
            user["ai"] = {}
            ai_config = user["ai"]
        providers = ai_config.setdefault("providers", {})
        if not isinstance(providers, dict):
            ai_config["providers"] = {}
            providers = ai_config["providers"]
        glm_config = providers.setdefault("glm", {})
        if not isinstance(glm_config, dict):
            providers["glm"] = {}
            glm_config = providers["glm"]
        for legacy_key in ("api_base", "model"):
            if legacy_key in ai_config and legacy_key not in glm_config:
                glm_config[legacy_key] = ai_config[legacy_key]

    @staticmethod
    def _migrate_ocr_config(user: dict[str, Any]) -> None:
        ocr_config = user.setdefault("ocr", {})
        if not isinstance(ocr_config, dict):
            user["ocr"] = {}
            ocr_config = user["ocr"]
        if (
            str(ocr_config.get("online_provider", "glm")).lower() == "glm"
            and ocr_config.get("online_model") == "glm-4v-flash"
        ):
            ocr_config["online_model"] = "glm-ocr"

    def _ensure_required_dirs(self) -> None:
        for key in ("database", "models", "logs", "memory"):
            path = self.resolve_path(f"paths.{key}")
            if key in {"database", "memory"}:
                path.parent.mkdir(parents=True, exist_ok=True)
            else:
                path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result
