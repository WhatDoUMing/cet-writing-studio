"""Online vision-model OCR engine for deployments without local GPUs."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from logger_config import get_logger


log = get_logger("ocr.online_engine")


class OnlineOCRError(RuntimeError):
    """Raised when an online OCR request fails."""


@dataclass(frozen=True)
class OnlineOCRPreset:
    key: str
    label: str
    api_base: str
    default_model: str


ONLINE_OCR_PRESETS: dict[str, OnlineOCRPreset] = {
    "glm": OnlineOCRPreset(
        key="glm",
        label="智谱手写文本识别",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-ocr",
    ),
    "openai": OnlineOCRPreset(
        key="openai",
        label="OpenAI 视觉识别",
        api_base="https://api.openai.com/v1",
        default_model="gpt-5-mini",
    ),
    "deepseek": OnlineOCRPreset(
        key="deepseek",
        label="DeepSeek 视觉识别",
        api_base="https://api.deepseek.com/v1",
        default_model="deepseek-v4-flash",
    ),
}


def get_online_ocr_preset(provider: str | None) -> OnlineOCRPreset:
    return ONLINE_OCR_PRESETS.get(
        str(provider or "glm").lower(),
        ONLINE_OCR_PRESETS["glm"],
    )


class OnlineOCREngine:
    """Transcribe an image through a vision-capable chat-completions model."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> None:
        config = config or {}
        self.preset = get_online_ocr_preset(
            config.get("online_provider", "glm")
        )
        self.api_base = str(
            config.get("online_api_base") or self.preset.api_base
        ).rstrip("/")
        self.model = str(
            config.get("online_model") or self.preset.default_model
        ).strip()
        self.timeout = float(config.get("online_timeout_seconds", 120))
        self.max_dimension = int(config.get("online_max_dimension", 2000))
        self.jpeg_quality = int(config.get("online_jpeg_quality", 88))
        self.max_bytes = int(config.get("online_max_bytes", 1_500_000))
        self.api_key = api_key

    def recognize(
        self,
        image_path: str | Path,
        *,
        use_lines: bool = True,
    ) -> str:
        """Return plain transcription text from an online vision model."""
        del use_lines
        if not self.api_key:
            raise OnlineOCRError(
                f"未配置 {self.preset.label} API Key，"
                "请在系统设置中填写，或切换为手动粘贴模式。"
            )

        if self.preset.key == "glm":
            return self._recognize_glm(image_path)

        image_data = self._encode_image(image_path)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个严格的 OCR 引擎。你只负责转录图片中可见的英文"
                    "文字，不翻译、不纠错、不润色、不补充缺失内容。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请逐行转录图片中的全部英文手写内容。"
                            "只输出转录文本，保留自然换行。"
                            "无法辨认的词输出 [unclear]，不要解释。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data},
                    },
                ],
            },
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if self.preset.key == "openai":
            payload["max_completion_tokens"] = 4096
        else:
            payload["temperature"] = 0
            payload["max_tokens"] = 4096
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise OnlineOCRError(
                f"{self.preset.label} 网络请求失败: {exc}"
            ) from exc

        if response.status_code != 200:
            detail = self._extract_error(response)
            raise OnlineOCRError(
                f"{self.preset.label}返回错误 "
                f"{response.status_code}: {detail}"
            )

        content = self._extract_content(response)
        if not content:
            raise OnlineOCRError(
                f"{self.preset.label}返回空内容，请稍后重试或手动粘贴。"
            )
        log.info(
            "Online OCR complete: provider=%s model=%s chars=%d",
            self.preset.key,
            self.model,
            len(content),
        )
        return content

    def _recognize_glm(self, image_path: str | Path) -> str:
        image_data = self._encode_image(image_path)
        url = f"{self.api_base}/layout_parsing"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "file": image_data,
            "return_crop_images": False,
            "need_layout_visualization": False,
        }
        response = self._post_glm(url, headers, payload)
        if response.status_code == 400:
            raw_payload = dict(payload)
            raw_payload["file"] = image_data.split(",", 1)[-1]
            log.info("Retrying GLM OCR with raw Base64 file payload")
            response = self._post_glm(
                url,
                headers,
                raw_payload,
            )
        if response.status_code != 200:
            detail = self._extract_error(response)
            raise OnlineOCRError(
                f"{self.preset.label}返回错误 "
                f"{response.status_code}: {detail}"
            )
        try:
            data = response.json()
            content = str(data.get("md_results") or "").strip()
            if not content:
                layouts = data.get("layout_details") or []
                content = "\n".join(
                    str(item.get("content", ""))
                    for page in layouts
                    for item in page
                    if isinstance(item, dict) and item.get("content")
                ).strip()
        except (AttributeError, ValueError, TypeError) as exc:
            raise OnlineOCRError(
                f"手写文本识别返回格式异常: {exc}"
            ) from exc
        if not content:
            raise OnlineOCRError(
                f"{self.preset.label}返回空内容，请稍后重试或手动粘贴。"
            )
        log.info(
            "GLM OCR complete: model=%s chars=%d",
            self.model,
            len(content),
        )
        return content

    def _post_glm(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> requests.Response:
        try:
            return requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise OnlineOCRError(
                f"{self.preset.label} 网络请求失败: {exc}"
            ) from exc

    def _encode_image(
        self,
        image_path: str | Path,
        *,
        include_data_url: bool = True,
    ) -> str:
        encoded = self._encode_image_bytes(image_path)
        result = base64.b64encode(encoded).decode("ascii")
        if include_data_url:
            return f"data:image/jpeg;base64,{result}"
        return result

    def _encode_image_bytes(self, image_path: str | Path) -> bytes:
        try:
            with Image.open(image_path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail(
                    (self.max_dimension, self.max_dimension),
                    Image.Resampling.LANCZOS,
                )
                quality = self.jpeg_quality
                encoded = self._save_jpeg(image, quality)
                for _ in range(5):
                    if len(encoded) <= self.max_bytes:
                        break
                    ratio = (self.max_bytes / len(encoded)) ** 0.5 * 0.92
                    width = max(400, int(image.width * ratio))
                    height = max(400, int(image.height * ratio))
                    if (width, height) == image.size:
                        break
                    image = image.resize(
                        (width, height),
                        Image.Resampling.LANCZOS,
                    )
                    quality = max(55, quality - 8)
                    encoded = self._save_jpeg(image, quality)
        except (OSError, ValueError) as exc:
            raise OnlineOCRError(
                f"无法读取手写文本图片: {exc}"
            ) from exc
        log.info(
            "Online OCR image encoded: %dx%d bytes=%d quality=%d",
            image.width,
            image.height,
            len(encoded),
            quality,
        )
        return encoded

    @staticmethod
    def _save_jpeg(image: Image.Image, quality: int) -> bytes:
        buffer = io.BytesIO()
        image.save(
            buffer,
            format="JPEG",
            quality=quality,
            optimize=True,
        )
        return buffer.getvalue()

    @staticmethod
    def _extract_content(response: requests.Response) -> str:
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content") or message.get(
                "reasoning_content", ""
            )
            if isinstance(content, list):
                content = "".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict)
                )
            return str(content).strip()
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise OnlineOCRError(
                f"手写文本识别返回格式异常: {exc}"
            ) from exc

    @staticmethod
    def _extract_error(response: requests.Response) -> str:
        try:
            data = response.json()
            error = data.get("error", {})
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if data.get("message"):
                return str(data["message"])
        except (AttributeError, ValueError, TypeError):
            pass
        return response.text[:500]
