import json
from pathlib import Path

from cryptography.fernet import Fernet

from config_manager import ConfigManager
from security import SecretStore


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_get = False
        self.fail_set = False
        self.fail_delete = False

    def get_password(self, service: str, key: str) -> str | None:
        if self.fail_get:
            raise RuntimeError("keyring read failed")
        return self.values.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        if self.fail_set:
            raise RuntimeError("keyring write failed")
        self.values[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("keyring delete failed")
        self.values.pop((service, key), None)


def install_keyring(monkeypatch, backend: FakeKeyring) -> None:
    monkeypatch.setattr("security.keyring.get_password", backend.get_password)
    monkeypatch.setattr("security.keyring.set_password", backend.set_password)
    monkeypatch.setattr("security.keyring.delete_password", backend.delete_password)


def reversible_protector():
    prefix = b"protected:"
    return (
        lambda payload: prefix + payload,
        lambda payload: payload[len(prefix) :]
        if payload.startswith(prefix)
        else (_ for _ in ()).throw(ValueError("invalid payload")),
    )


def test_config_merges_defaults_and_creates_dirs(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "config").mkdir()
    (root / "config" / "default_settings.json").write_text(
        '{"app":{"name":"default"},"paths":{"database":"data/x.db",'
        '"models":"models","logs":"logs","memory":"memory/rules.md"}}',
        encoding="utf-8",
    )
    cfg = ConfigManager(root)
    assert cfg.get("app.name") == "default"
    assert (root / "data").exists()
    assert (root / "models").exists()
    assert (root / "memory").exists()


def test_relative_local_ocr_model_path_resolves_from_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default_settings.json").write_text(
        '{"paths":{"database":"data/x.db","models":"models",'
        '"logs":"logs","memory":"memory/rules.md"},'
        '"ocr":{"local_model_path":"models/local"}}',
        encoding="utf-8",
    )
    cfg = ConfigManager(tmp_path)
    assert cfg.get_ocr_config()["local_model_path"] == str(
        tmp_path / "models" / "local"
    )


def test_keyring_success_does_not_create_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    backend = FakeKeyring()
    install_keyring(monkeypatch, backend)
    protect, unprotect = reversible_protector()
    store = SecretStore(
        tmp_path,
        user_key_dir=tmp_path.parent / "user-keys",
        protect=protect,
        unprotect=unprotect,
    )

    store.set_secret("api_key", "test-secret")

    assert store.get_secret("api_key") == "test-secret"
    assert not (tmp_path / "secrets.dpapi").exists()
    assert not (tmp_path / "secrets.enc").exists()
    assert not (tmp_path / ".secret_key").exists()


def test_keyring_failure_uses_protected_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    backend = FakeKeyring()
    backend.fail_set = True
    install_keyring(monkeypatch, backend)
    protect, unprotect = reversible_protector()
    store = SecretStore(
        tmp_path,
        user_key_dir=tmp_path.parent / "user-keys",
        protect=protect,
        unprotect=unprotect,
    )

    store.set_secret("api_key", "test-secret")

    assert store.get_secret("api_key") == "test-secret"
    assert (tmp_path / "secrets.dpapi").exists()
    assert not (tmp_path / ".secret_key").exists()


def test_non_dpapi_fallback_keeps_key_outside_config_dir(
    tmp_path: Path, monkeypatch
) -> None:
    backend = FakeKeyring()
    backend.fail_set = True
    install_keyring(monkeypatch, backend)
    user_key_dir = tmp_path.parent / "separate-user-store"
    store = SecretStore(
        tmp_path,
        user_key_dir=user_key_dir,
        protect=lambda _payload: (_ for _ in ()).throw(OSError("no dpapi")),
    )

    store.set_secret("api_key", "test-secret")

    assert (tmp_path / "secrets.dpapi").exists()
    assert (user_key_dir / "fallback.key").exists()
    assert not (tmp_path / ".secret_key").exists()
    assert store.get_secret("api_key") == "test-secret"


def test_keyring_unavailable_and_read_exception_use_local_copy(
    tmp_path: Path, monkeypatch
) -> None:
    backend = FakeKeyring()
    backend.fail_set = True
    install_keyring(monkeypatch, backend)
    protect, unprotect = reversible_protector()
    store = SecretStore(tmp_path, protect=protect, unprotect=unprotect)
    store.set_secret("api_key", "test-secret")

    backend.fail_get = True
    assert store.get_secret("api_key") == "test-secret"
    assert SecretStore(
        tmp_path / "empty", protect=protect, unprotect=unprotect
    ).get_secret("missing") is None


def test_legacy_secret_migrates_to_keyring_and_cleans_files(
    tmp_path: Path, monkeypatch
) -> None:
    backend = FakeKeyring()
    install_keyring(monkeypatch, backend)
    key = Fernet.generate_key()
    (tmp_path / ".secret_key").write_bytes(key)
    payload = json.dumps({"api_key": "legacy-secret"}).encode("utf-8")
    (tmp_path / "secrets.enc").write_bytes(Fernet(key).encrypt(payload))
    store = SecretStore(tmp_path)

    assert store.get_secret("api_key") == "legacy-secret"
    assert backend.values
    assert not (tmp_path / "secrets.enc").exists()
    assert not (tmp_path / ".secret_key").exists()


def test_failed_legacy_migration_preserves_old_copy(
    tmp_path: Path, monkeypatch
) -> None:
    backend = FakeKeyring()
    backend.fail_set = True
    install_keyring(monkeypatch, backend)
    key = Fernet.generate_key()
    (tmp_path / ".secret_key").write_bytes(key)
    payload = json.dumps({"api_key": "legacy-secret"}).encode("utf-8")
    (tmp_path / "secrets.enc").write_bytes(Fernet(key).encrypt(payload))

    assert SecretStore(tmp_path).get_secret("api_key") == "legacy-secret"
    assert (tmp_path / "secrets.enc").exists()
    assert (tmp_path / ".secret_key").exists()


def test_delete_clears_current_and_legacy_copies(
    tmp_path: Path, monkeypatch
) -> None:
    backend = FakeKeyring()
    backend.fail_set = True
    install_keyring(monkeypatch, backend)
    protect, unprotect = reversible_protector()
    store = SecretStore(tmp_path, protect=protect, unprotect=unprotect)
    store.set_secret("api_key", "test-secret")

    legacy_key = Fernet.generate_key()
    (tmp_path / ".secret_key").write_bytes(legacy_key)
    legacy_payload = json.dumps({"api_key": "legacy-secret"}).encode()
    (tmp_path / "secrets.enc").write_bytes(
        Fernet(legacy_key).encrypt(legacy_payload)
    )
    store.delete_secret("api_key")

    assert not (tmp_path / "secrets.dpapi").exists()
    assert not (tmp_path / "secrets.enc").exists()
    assert not (tmp_path / ".secret_key").exists()


def test_provider_specific_api_keys(tmp_path: Path, monkeypatch) -> None:
    backend = FakeKeyring()
    install_keyring(monkeypatch, backend)
    cfg = ConfigManager(tmp_path)
    cfg.set_api_key("glm-secret", provider="glm")
    cfg.set_api_key("openai-secret", provider="openai")
    cfg.set_api_key("deepseek-secret", provider="deepseek")

    cfg.set("ai.provider", "openai")
    assert cfg.get_api_key() == "openai-secret"
    cfg.set("ai.provider", "deepseek")
    assert cfg.get_api_key() == "deepseek-secret"
    assert cfg.get_api_key(provider="glm") == "glm-secret"

    cfg.set_ocr_api_key("deepseek-ocr-secret", provider="deepseek")
    assert (
        cfg.get_ocr_api_key(provider="deepseek", fallback=False)
        == "deepseek-ocr-secret"
    )
    assert cfg.get_api_key(provider="deepseek") == "deepseek-secret"
    assert cfg.get_ocr_api_key(provider="openai") == "openai-secret"

    cfg.delete_ocr_api_key(provider="deepseek")
    assert (
        cfg.get_ocr_api_key(provider="deepseek", fallback=False) is None
    )
    assert cfg.get_ocr_api_key(provider="deepseek") == "deepseek-secret"


def test_defaults_can_load_from_separate_resource_root(tmp_path: Path) -> None:
    writable_root = tmp_path / "app"
    resource_root = tmp_path / "_internal"
    (resource_root / "config").mkdir(parents=True)
    (resource_root / "config" / "default_settings.json").write_text(
        '{"paths":{"database":"data/essay.db","models":"models",'
        '"logs":"logs","memory":"memory/rules.md"}}',
        encoding="utf-8",
    )
    (writable_root / "config").mkdir(parents=True)

    cfg = ConfigManager(writable_root, resource_root=resource_root)

    assert cfg.resolve_path("paths.database") == (
        writable_root / "data" / "essay.db"
    )
    assert (writable_root / "data").exists()
    assert not (resource_root / "data").exists()


def test_legacy_glm_vision_model_migrates_to_glm_ocr(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text(
        '{"ocr":{"online_provider":"glm","online_model":"glm-4v-flash"}}',
        encoding="utf-8",
    )
    cfg = ConfigManager(tmp_path)
    assert cfg.get("ocr.online_model") == "glm-ocr"
