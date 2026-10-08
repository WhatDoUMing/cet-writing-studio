import json
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from gui.styles import get_app_style
from tests.test_workflow_sessions import make_window


def assert_database_usable(database, label: str) -> None:
    essay_id = database.create_essay(label, "CET-4", label)
    assert database.get_essay(essay_id)["question"] == label


def configure_independent_runtime_changes(window, tmp_path: Path) -> None:
    window.config.set("app.theme", "dark")
    window.config.set("ocr.local_model_path", "models/reloaded")
    window.config.set("ocr.model_name", "models/reloaded")
    window.config.set("paths.database", str(tmp_path / "blocked" / "new.db"))


def assert_failed_switch_rolled_back(window, old_database) -> None:
    assert window.db is old_database
    assert window.config.get("paths.database") == "data/test.db"
    saved = json.loads(window.config.user_path.read_text(encoding="utf-8"))
    assert saved["paths"]["database"] == "data/test.db"
    assert_database_usable(old_database, "切换失败后仍可写")
    assert QApplication.instance().styleSheet() == get_app_style("dark")
    assert window.ocr_engine.local_model_path.endswith("models\\reloaded")


def test_database_constructor_permission_error_keeps_old_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, old_database = make_window(tmp_path)
    configure_independent_runtime_changes(window, tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )

    class PermissionDeniedDatabase:
        def __init__(self, _path) -> None:
            raise PermissionError("directory is read-only")

    monkeypatch.setattr(
        "gui.main_window.Database",
        PermissionDeniedDatabase,
    )
    window._apply_runtime_settings()

    assert_failed_switch_rolled_back(window, old_database)
    assert messages and "继续使用原数据库" in messages[0]
    window.close()


def test_partially_connected_replacement_is_closed_on_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, old_database = make_window(tmp_path)
    configure_independent_runtime_changes(window, tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    instances = []

    class PartialDatabase:
        def __init__(self, path) -> None:
            self.db_path = Path(path)
            self.opened = False
            self.closed = False
            instances.append(self)

        def connect(self):
            self.opened = True
            raise RuntimeError("schema migration failed")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("gui.main_window.Database", PartialDatabase)
    window._apply_runtime_settings()

    assert len(instances) == 1
    assert instances[0].opened is True
    assert instances[0].closed is True
    assert_failed_switch_rolled_back(window, old_database)
    window.close()


def test_database_path_resolution_failure_keeps_old_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, old_database = make_window(tmp_path)
    configure_independent_runtime_changes(window, tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    original_resolve = window.config.resolve_path

    def fail_database_resolution(key: str):
        if key == "paths.database":
            raise OSError("path resolution failed")
        return original_resolve(key)

    monkeypatch.setattr(window.config, "resolve_path", fail_database_resolution)
    window._apply_runtime_settings()

    assert_failed_switch_rolled_back(window, old_database)
    window.close()


def test_successful_switch_closes_old_database_only_after_connect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, old_database = make_window(tmp_path)
    requested = tmp_path / "data" / "replacement.db"
    window.config.set("paths.database", str(requested))
    events: list[tuple[str, bool]] = []
    instances = []

    class SuccessfulDatabase:
        def __init__(self, path) -> None:
            self.db_path = Path(path)
            self.closed = False
            instances.append(self)

        def connect(self):
            events.append(("connected", old_database._conn is not None))
            return object()

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("gui.main_window.Database", SuccessfulDatabase)
    window._apply_runtime_settings()

    assert events == [("connected", True)]
    assert window.db is instances[0]
    assert old_database._conn is None
    assert window.config.get("paths.database") == str(requested)
    window.close()
    assert instances[0].closed is True


def test_equivalent_database_path_does_not_reopen_connection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, old_database = make_window(tmp_path)
    window.config.set("paths.database", str(old_database.db_path).upper())

    class UnexpectedDatabase:
        def __init__(self, _path) -> None:
            raise AssertionError("equivalent path should not construct a database")

    monkeypatch.setattr("gui.main_window.Database", UnexpectedDatabase)
    window._apply_runtime_settings()

    assert window.db is old_database
    assert_database_usable(old_database, "等价路径")
    window.close()
