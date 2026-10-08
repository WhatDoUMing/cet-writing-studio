"""Offline regression: prevent accidental real network calls and modal blocking."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtWidgets import QMessageBox

@pytest.fixture(autouse=True)
def offline_ui(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network must be replaced by a test double")
    monkeypatch.setattr("requests.post", blocked)
    monkeypatch.setattr("requests.get", blocked)
    for method in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, method, lambda *a, **k: QMessageBox.StandardButton.No)
