"""Credential storage with keyring and a user-bound encrypted fallback."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
from typing import Callable

import keyring

try:
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover - optional dependency guard
    Fernet = None


SERVICE_NAME = "CETWritingStudio"
_DPAPI_HEADER = b"DPAPI1\n"
_FERNET_HEADER = b"FERNET1\n"


def _default_user_key_dir() -> Path:
    """Return a per-user location outside the portable application folder."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / SERVICE_NAME
    return Path.home() / ".local" / "share" / SERVICE_NAME


def _dpapi_transform(data: bytes, *, protect: bool) -> bytes:
    """Protect or unprotect bytes with Windows DPAPI for the current user."""
    if os.name != "nt":
        raise OSError("Windows DPAPI is unavailable on this platform")

    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    buffer = ctypes.create_string_buffer(data, len(data))
    input_blob = DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = DataBlob()
    crypt32 = ctypes.windll.crypt32
    function = (
        crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    )
    ok = function(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def protect_for_current_user(data: bytes) -> bytes:
    return _dpapi_transform(data, protect=True)


def unprotect_for_current_user(data: bytes) -> bytes:
    return _dpapi_transform(data, protect=False)


class SecretStore:
    """Use keyring first, with DPAPI or an external-key file fallback."""

    def __init__(
        self,
        config_dir: str | Path = "config",
        *,
        user_key_dir: str | Path | None = None,
        protect: Callable[[bytes], bytes] | None = None,
        unprotect: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self.config_dir = Path(config_dir)
        self._fallback_path = self.config_dir / "secrets.dpapi"
        self._legacy_encrypted_path = self.config_dir / "secrets.enc"
        self._legacy_key_path = self.config_dir / ".secret_key"
        self._user_key_dir = Path(user_key_dir or _default_user_key_dir())
        self._user_key_path = self._user_key_dir / "fallback.key"
        self._protect = protect or protect_for_current_user
        self._unprotect = unprotect or unprotect_for_current_user

    def get_secret(self, key: str) -> str | None:
        """Read a secret and opportunistically migrate legacy local copies."""
        keyring_available = True
        try:
            value = keyring.get_password(SERVICE_NAME, key)
        except Exception:
            keyring_available = False
            value = None
        if value is not None:
            self._remove_local_secret(key)
            return value

        local_value = self._get_local_secret(key)
        if local_value is None:
            return None
        if keyring_available:
            try:
                keyring.set_password(SERVICE_NAME, key, local_value)
            except Exception:
                pass
            else:
                self._remove_local_secret(key)
        return local_value

    def set_secret(self, key: str, value: str) -> None:
        """Store in keyring; create a local fallback only when that fails."""
        if not value:
            raise ValueError("Secret value must not be empty")
        try:
            keyring.set_password(SERVICE_NAME, key, value)
        except Exception:
            self._write_to_fallback(key, value)
            return
        self._remove_local_secret(key)

    def delete_secret(self, key: str) -> None:
        """Delete a secret from keyring and every old or current fallback."""
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except Exception:
            pass
        self._remove_local_secret(key)

    def _get_local_secret(self, key: str) -> str | None:
        current = self._read_fallback_payload()
        if current is not None and key in current:
            return current[key]
        legacy = self._read_legacy_payload()
        return None if legacy is None else legacy.get(key)

    def _write_to_fallback(self, key: str, value: str) -> None:
        data = self._read_fallback_payload() or {}
        data[key] = value
        self._save_fallback_payload(data)

    def _read_fallback_payload(self) -> dict[str, str] | None:
        if not self._fallback_path.exists():
            return None
        try:
            payload = self._fallback_path.read_bytes()
            if payload.startswith(_DPAPI_HEADER):
                plaintext = self._unprotect(payload[len(_DPAPI_HEADER) :])
            elif payload.startswith(_FERNET_HEADER):
                if Fernet is None or not self._user_key_path.exists():
                    return None
                plaintext = Fernet(self._user_key_path.read_bytes()).decrypt(
                    payload[len(_FERNET_HEADER) :]
                )
            else:
                return None
            decoded = json.loads(plaintext.decode("utf-8"))
            return decoded if isinstance(decoded, dict) else None
        except Exception:
            return None

    def _save_fallback_payload(self, data: dict[str, str]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            protected = self._protect(plaintext)
            payload = _DPAPI_HEADER + protected
        except Exception:
            if Fernet is None:
                raise RuntimeError("没有可用的本地密钥保护后端") from None
            key = self._load_or_create_user_key()
            payload = _FERNET_HEADER + Fernet(key).encrypt(plaintext)
        self._fallback_path.write_bytes(payload)

    def _load_or_create_user_key(self) -> bytes:
        if self._user_key_path.exists():
            return self._user_key_path.read_bytes()
        self._user_key_dir.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        self._user_key_path.write_bytes(key)
        try:
            self._user_key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def _read_legacy_payload(self) -> dict[str, str] | None:
        if (
            Fernet is None
            or not self._legacy_encrypted_path.exists()
            or not self._legacy_key_path.exists()
        ):
            return None
        try:
            token = self._legacy_encrypted_path.read_bytes().strip()
            plaintext = Fernet(self._legacy_key_path.read_bytes()).decrypt(token)
            decoded = json.loads(plaintext.decode("utf-8"))
            return decoded if isinstance(decoded, dict) else None
        except Exception:
            return None

    def _save_legacy_payload(self, data: dict[str, str]) -> None:
        if not data:
            self._unlink(self._legacy_encrypted_path)
            self._unlink(self._legacy_key_path)
            return
        if Fernet is None or not self._legacy_key_path.exists():
            return
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        token = Fernet(self._legacy_key_path.read_bytes()).encrypt(plaintext)
        self._legacy_encrypted_path.write_bytes(token)

    def _remove_local_secret(self, key: str) -> None:
        current = self._read_fallback_payload()
        if current is not None and key in current:
            current.pop(key, None)
            if current:
                self._save_fallback_payload(current)
            else:
                self._unlink(self._fallback_path)

        legacy = self._read_legacy_payload()
        if legacy is not None and key in legacy:
            legacy.pop(key, None)
            self._save_legacy_payload(legacy)

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
