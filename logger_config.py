"""Central logging configuration for the desktop application."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: str | Path = "logs", level: int = logging.INFO) -> Path:
    """Configure console and rotating file logging.

    The function is idempotent enough to call more than once: it creates a
    root logger with the application name so callers can retrieve it through
    ``logging.getLogger("CETWritingStudio")``.
    """
    log_dir = Path(log_dir)

    logger = logging.getLogger("CETWritingStudio")
    if logger.handlers:
        return log_dir

    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # An existing log may belong to another Windows account. Keep startup
    # available and use a per-user location when the project log is read-only.
    user_root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    candidates = (log_dir, user_root / "CETWritingStudio" / "logs",
                  Path(tempfile.gettempdir()) / "CETWritingStudio" / "logs")
    for candidate in dict.fromkeys(candidates):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                candidate / "app.log", maxBytes=2_000_000,
                backupCount=5, encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Log location unavailable (%s): %s", candidate, exc)
            continue
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
        return candidate

    logger.warning("File logging unavailable; using console logging only")

    return log_dir


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application namespace."""
    return logging.getLogger(f"CETWritingStudio.{name}")
