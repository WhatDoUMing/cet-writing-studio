"""Backward-compatible GLM facade over the shared chat-completion client."""

from __future__ import annotations

from typing import Any

from ai.chat_api import ChatAPIError, ChatCompletionClient


GLMAPIError = ChatAPIError


class GLMClient(ChatCompletionClient):
    """Compatibility wrapper that always selects the GLM provider."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__("glm", config, api_key)
