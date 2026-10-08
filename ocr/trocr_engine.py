"""Microsoft TrOCR handwritten-text recognition engine."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np

from logger_config import get_logger
from ocr.image_process import preprocess_for_ocr
from ocr.torch_preload import preload_torch_dlls


log = get_logger("ocr.trocr_engine")


class OCREngineNotReady(RuntimeError):
    """Raised when TrOCR dependencies or model files are unavailable."""


class TrOCREngine:
    """Lazy-loading TrOCR model with CPU and CUDA support."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.model_name = str(
            config.get("model_name", "microsoft/trocr-base-handwritten")
        )
        self.local_model_path = str(config.get("local_model_path", ""))
        self.device_mode = str(config.get("device", "auto")).lower()
        self.max_length = int(config.get("max_length", 2048))
        self.beam_width = int(config.get("beam_width", 4))
        self._processor = None
        self._model = None
        self._device = None
        self._recognition_lock = threading.RLock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    @property
    def device(self) -> str:
        return self._device or self._resolve_device()

    def load(self) -> None:
        """Import and load the Hugging Face TrOCR model."""
        with self._recognition_lock:
            if self.is_loaded:
                return
            self._load_components()

    def _load_components(self) -> None:
        """Load model components while the instance lock is held."""
        preload_torch_dlls()
        try:
            import torch
            from transformers import AutoProcessor, VisionEncoderDecoderModel
        except ImportError as exc:
            raise OCREngineNotReady(
                "未安装 transformers/torch，请安装 requirements-local-ocr.txt 中的可选依赖。"
            ) from exc

        device = self._resolve_device()
        model_path = self.local_model_path or self.model_name
        log.info("Loading TrOCR model=%s device=%s", model_path, device)
        try:
            self._processor = AutoProcessor.from_pretrained(model_path)
            self._model = VisionEncoderDecoderModel.from_pretrained(model_path)
            self._model.to(device)
            self._model.eval()
            self._device = device
        except Exception as exc:
            self._processor = None
            self._model = None
            raise OCREngineNotReady(
                f"TrOCR 模型加载失败: {exc}"
            ) from exc

    def recognize(
        self,
        image_path: str | Path,
        *,
        use_lines: bool = True,
    ) -> str:
        """Recognize handwritten text from an image path."""
        with self._recognition_lock:
            self.load()
            artifacts = preprocess_for_ocr(image_path)
            if not use_lines:
                return self._recognize_image(artifacts["gray"])

            line_boxes = artifacts["line_boxes"]
            if not line_boxes:
                return self._recognize_image(artifacts["gray"])

            lines: list[str] = []
            gray = artifacts["gray"]
            for x, y, w, h in line_boxes:
                crop = gray[y : y + h, x : x + w]
                if crop.size == 0:
                    continue
                text = self._recognize_image(crop).strip()
                if text:
                    lines.append(text)
            return " ".join(lines).strip()

    def _recognize_image(self, image: np.ndarray) -> str:
        import torch

        if image.ndim == 2:
            rgb = np.stack([image] * 3, axis=-1)
        elif image.shape[2] == 4:
            rgb = image[:, :, :3]
        else:
            rgb = image

        try:
            from PIL import Image
            pil_image = Image.fromarray(rgb)
        except Exception as exc:
            raise OCREngineNotReady(
                f"无法将图像转换为 PIL 格式: {exc}"
            ) from exc

        pixel_values = self._processor(
            images=pil_image, return_tensors="pt"
        ).pixel_values.to(self._device)
        with torch.no_grad():
            generated_ids = self._model.generate(
                pixel_values,
                max_new_tokens=self.max_length,
                num_beams=self.beam_width,
            )
        return self._processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0].strip()

    def _resolve_device(self) -> str:
        if self.device_mode == "cpu":
            return "cpu"
        try:
            import torch

            if self.device_mode == "cuda":
                if torch.cuda.is_available():
                    return "cuda"
                log.warning("CUDA requested but not available; falling back to CPU")
                return "cpu"
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
