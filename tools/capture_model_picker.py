"""Preview the model picker using GLM's real public docs, no API credentials."""
import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from config_manager import ConfigManager
from database.sqlite import Database
from gui.main_window import MainWindow
from gui.styles import get_app_style
from memory.manager import MemoryManager
from ocr.trocr_engine import TrOCREngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(prefix="model-picker-", dir=ROOT / "work") as temp:
        config = ConfigManager(temp, resource_root=ROOT)
        config.set("app.reduce_motion", True)
        config.set("ai.provider", "glm")
        config.set("ocr.mode", "online")
        config.set("ocr.online_provider", "glm")
        # This preview accesses public documentation only.
        config.get_api_key = lambda provider=None: None
        config.get_ocr_api_key = lambda provider=None, fallback=True: None
        db = Database(config.resolve_path("paths.database"))
        db.connect()
        window = MainWindow(config, db, MemoryManager(config.resolve_path("paths.memory")), TrOCREngine(config.get_ocr_config()))
        window.resize(1280, 900)
        window.show()
        window._open_settings()
        page = window.settings_page
        page.models_btn.click()
        page.ocr_models_btn.click()
        for _ in range(600):
            QTest.qWait(50)
            if not any(page._model_pending.values()):
                break
        if not page._model_catalogs.get(page._model_context("scoring")):
            window.close()
            raise RuntimeError(page.models_status.text())
        for theme in ("light", "dark"):
            app.setStyleSheet(get_app_style(theme))
            app.processEvents()
            QTest.qWait(100)
            window.grab().save(str(args.output / f"settings-models-{theme}.png"))
            page.model_combo.showPopup()
            QTest.qWait(100)
            page.model_combo.view().window().grab().save(str(args.output / f"models-dropdown-{theme}.png"))
            page.model_combo.hidePopup()
        print(page.models_status.text())
        print(page.ocr_models_status.text())
        window.close()


if __name__ == "__main__":
    main()
