"""Resolve optional, user-supplied assets without copying or fetching anything."""
from pathlib import Path
import os


def configured_asset_dir(section: str) -> Path | None:
    """Return one well-known child of the optional local asset pack."""
    root = os.environ.get("CET_LOCAL_ASSETS_DIR", "").strip()
    if not root:
        return None
    if section not in {"fonts", "companions", "ui-meme-assets", "startup-assets"}:
        raise ValueError("Unknown local asset section")
    return Path(root).expanduser() / section
