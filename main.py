"""Application entry point."""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import sys
from pathlib import Path

from ocr.torch_preload import preload_torch_dlls


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    """Return the directory containing bundled read-only resources."""
    if getattr(sys, "frozen", False):
        return Path(
            getattr(sys, "_MEIPASS", project_root() / "_internal")
        ).resolve()
    return Path(__file__).resolve().parent


def startup_audio_allowed(requested: bool, *, reduced: bool, platform: str, qt_platform: str) -> bool:
    """Only an explicit, interactive Windows session may prepare startup sound."""
    requested_qt = os.environ.get("QT_QPA_PLATFORM", "").split(";", 1)[0].split(":", 1)[0].strip().casefold()
    return (
        requested and not reduced and platform == "win32"
        and qt_platform.casefold() == "windows"
        and requested_qt not in {"offscreen", "minimal", "minimalegl", "vnc"}
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CET Writing Studio")
    sound = parser.add_mutually_exclusive_group()
    sound.add_argument("--with-startup-audio", action="store_true", help="Use the optional local startup soundtrack")
    sound.add_argument("--silent", action="store_true", help="Start without sound (the default)")
    options = parser.parse_args(argv)
    root = project_root()

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from config_manager import ConfigManager
    from database.sqlite import Database
    from gui.main_window import MainWindow
    from gui.startup_integration import attach_startup_splash, local_startup_assets
    from gui.styles import get_app_style, prepare_fonts
    from logger_config import setup_logging
    from memory.manager import MemoryManager
    from ocr.trocr_engine import TrOCREngine

    setup_logging(root / "logs" / "CETWritingStudio")
    config = ConfigManager(root, resource_root=resource_root())

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([sys.argv[0]])
    app.setApplicationName("CETWritingStudio")
    app.setOrganizationName("CETWritingStudio")
    prepare_fonts(app)
    app.setStyleSheet(get_app_style(str(config.get("app.theme", "light"))))

    database = Database(config.resolve_path("paths.database"))
    database.connect()
    memory = MemoryManager(config.resolve_path("paths.memory"))
    ocr_engine = TrOCREngine(config.get_ocr_config())

    window = MainWindow(config, database, memory, ocr_engine)
    assets = local_startup_assets(root)
    reduced = bool(config.get("app.reduce_motion", False))
    factory = None
    if startup_audio_allowed(options.with_startup_audio, reduced=reduced, platform=sys.platform,
                             qt_platform=app.platformName()):
        from gui.startup_audio import optional_sound_factory

        factory = optional_sound_factory(assets, assets.parent / "startup_audio_contract.json")
    attach_startup_splash(window, asset_dir=assets, reduced_motion=reduced, sound_factory=factory)
    window.show()
    return app.exec()


def run_ocr_selftest(image_path: str, output_path: str) -> int:
    """Run the packaged OCR pipeline without opening the GUI."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    crash_log = output.with_suffix(output.suffix + ".faulthandler")
    with crash_log.open("w", encoding="utf-8") as crash_stream:
        faulthandler.enable(file=crash_stream, all_threads=True)
        output.write_text(
            json.dumps(
                {"ok": False, "stage": "starting"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            root = project_root()
            preload_torch_dlls()
            from config_manager import ConfigManager
            from logger_config import setup_logging
            from ocr.trocr_engine import TrOCREngine

            setup_logging(root / "logs" / "CETWritingStudio")
            config = ConfigManager(root, resource_root=resource_root())
            engine = TrOCREngine(config.get("ocr", {}))
            text = engine.recognize(image_path, use_lines=True)
            result = {"ok": True, "stage": "complete", "text": text}
            exit_code = 0
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary
            result = {
                "ok": False,
                "stage": "failed",
                "error": repr(exc),
            }
            exit_code = 2
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return exit_code


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--ocr-selftest":
        raise SystemExit(run_ocr_selftest(sys.argv[2], sys.argv[3]))
    raise SystemExit(main())
