"""Early Windows DLL setup for PyTorch in frozen applications."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path


log = logging.getLogger("FJEnglishAIGrader.ocr.torch_preload")


def preload_torch_dlls() -> None:
    """Preload PyTorch's Windows DLLs before Qt and other native modules."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not bundle_root:
        return

    torch_lib = Path(bundle_root) / "torch" / "lib"
    if not torch_lib.exists():
        log.warning("Torch DLL directory not found: %s", torch_lib)
        return

    for search_dir in (Path(bundle_root), torch_lib):
        if search_dir.exists():
            os.add_dll_directory(str(search_dir))
    for dll_path in sorted(torch_lib.glob("*.dll")):
        try:
            ctypes.CDLL(str(dll_path))
            log.info("Preloaded %s", dll_path.name)
        except OSError:
            log.exception("Could not preload %s", dll_path.name)
