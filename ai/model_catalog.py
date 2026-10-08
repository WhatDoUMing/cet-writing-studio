"""Discover model IDs from the configured API or GLM's official public catalog."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from ai.chat_api import get_provider_preset

GLM_CATALOG_URL = "https://docs.bigmodel.cn/cn/guide/start/model-overview.md"


class ModelListError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[str, ...]
    source: str
    source_url: str


def _model_ids(values) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in values
                         if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value.strip())}, key=str.casefold))


def fetch_model_catalog(provider: str, api_base: str, api_key: str | None = None,
                        purpose: str = "scoring") -> ModelCatalog:
    """Blocking discovery; called only by a background worker or explicit tools.

    GLM's public directory is not an account permission list. No credentials
    are sent to documentation hosts. Custom endpoints use /models directly.
    """
    base = api_base.strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise ModelListError("API 地址格式有误，请检查服务商配置。")
    public_glm = provider == "glm" and base == get_provider_preset("glm").api_base
    if not public_glm and not api_key:
        raise ModelListError("请先填写或保存当前服务商的 API Key，再获取模型列表。")
    url = GLM_CATALOG_URL if public_glm else base + "/models"
    headers = {} if public_glm else {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(url, headers=headers, timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise ModelListError("获取模型列表时连接失败或超时，请检查网络后重试。") from None
    if response.status_code != 200:
        messages = {401: "API Key 无效，请检查后重试。", 403: "当前 Key 没有模型列表访问权限。",
                    404: "当前服务地址未开放模型列表，可继续手动填写。", 405: "当前服务地址未开放模型列表，可继续手动填写。",
                    429: "请求频繁或额度受限，请稍后重试。"}
        raise ModelListError(messages.get(response.status_code, f"模型列表请求失败（HTTP {response.status_code}），可稍后重试或手动填写。"))
    if public_glm:
        response.encoding = "utf-8"
        links = re.findall(r"\[([A-Za-z0-9._-]+)\]\(/cn/guide/models/(text|vlm|free)/[^)]+\)", response.text)
        ids = [name.lower() for name, _ in links if name.lower().startswith("glm-")]
        ids = [name for name in ids if name == "glm-ocr"] if purpose == "ocr" else [name for name in ids if name != "glm-ocr"]
        models = _model_ids(ids)
    else:
        try:
            payload = response.json()
        except ValueError:
            raise ModelListError("服务商返回的模型列表不是有效 JSON，可继续手动填写。") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ModelListError("服务商返回的模型列表格式有误，可继续手动填写。")
        models = _model_ids(item.get("id") for item in payload["data"] if isinstance(item, dict))
    if not models:
        raise ModelListError("本次没有获取到有效模型名称，已保留原值，可继续手动填写。")
    return ModelCatalog(models, "public_catalog" if public_glm else "api", url)
