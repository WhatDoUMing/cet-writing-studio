"""OpenAI-compatible chat-completion clients used by the grading service."""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from ai.prompt import (
    build_grading_prompt,
    build_question_summary_prompt,
    heuristic_question_summary,
    normalize_report,
    parse_ai_json,
    sanitize_question_summary,
)
from logger_config import get_logger


log = get_logger("ai.chat_api")


@dataclass(frozen=True)
class ProviderPreset:
    """Provider settings needed by an OpenAI-compatible chat endpoint."""

    key: str
    label: str
    api_base: str
    default_model: str
    max_tokens_field: str = "max_tokens"
    use_temperature: bool = True
    use_top_k: bool = False
    use_json_mode: bool = True


# Provider presets follow the reusable preset pattern used by cc-switch:
# endpoint, default model, and protocol-specific request options live together.
PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "glm": ProviderPreset(
        key="glm",
        label="智谱 GLM",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5.3-flash",
        use_top_k=True,
        use_json_mode=False,
    ),
    "openai": ProviderPreset(
        key="openai",
        label="OpenAI GPT",
        api_base="https://api.openai.com/v1",
        default_model="gpt-5-mini",
        max_tokens_field="max_completion_tokens",
        use_temperature=False,
    ),
    "deepseek": ProviderPreset(
        key="deepseek",
        label="DeepSeek",
        api_base="https://api.deepseek.com/v1",
        default_model="deepseek-v4-flash",
    ),
}


def get_provider_preset(provider: str | None) -> ProviderPreset:
    """Return a known provider preset, falling back to GLM."""
    return PROVIDER_PRESETS.get(
        str(provider or "glm").lower(),
        PROVIDER_PRESETS["glm"],
    )


class ChatAPIError(RuntimeError):
    """Raised for missing credentials, network failures, or API errors."""


from cet_scoring import validate_report as validate_report_scores


class ChatCompletionClient:
    """Blocking OpenAI-compatible Chat Completions client."""

    def __init__(
        self,
        provider: str,
        config: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> None:
        config = config or {}
        self.preset = get_provider_preset(provider)
        self.provider = self.preset.key
        self.api_base = str(
            config.get("api_base") or self.preset.api_base
        ).rstrip("/")
        self.model = str(
            config.get("model") or self.preset.default_model
        ).strip()
        self.temperature = float(config.get("temperature", 0.7))
        self.top_k = int(config.get("top_k", 10))
        self.max_tokens = int(config.get("max_tokens", 4096))
        self.timeout = float(config.get("timeout_seconds", 180))
        self.api_key = api_key
        self.last_finish_reason: str | None = None

    def grade_essay(
        self, *, essay_type: str, max_score: str, question: str, student_text: str,
        examples: list[dict[str, Any]] | None = None,
        memory_rules: list[dict[str, Any]] | None = None,
        minimum_words: int | None = None,
    ) -> dict[str, Any]:
        messages = build_grading_prompt(essay_type, max_score, question, student_text,
                                        examples, memory_rules, minimum_words)
        attempts: list[str] = []
        for attempt in range(2):
            content = self.chat(messages, max_tokens_override=(min(max(self.max_tokens * 2, 8192), 16384) if attempt else None))
            attempts.append(content)
            try:
                if self.last_finish_reason == "length":
                    raise ValueError("评分报告被截断")
                raw = parse_ai_json(content)
                report = validate_report_scores(raw, max_score, student_text)
                report["raw_ai_report"] = raw
                report["raw_ai_response"] = content
                report["ai_response_attempts"] = attempts
                return report
            except (ValueError, TypeError) as exc:
                if attempt:
                    raise ChatAPIError(f"报告校验失败，修正重试后仍无效：{exc}") from exc
                messages += [{"role": "assistant", "content": content}, {"role": "user", "content":
                    f"上次报告校验错误：{exc}。重新输出完整 JSON，score 为 0—15 整数；dimension_feedback 包含 content/language/structure 文字；overall_comment 为文字；四个诊断数组保持正确类型。采用整体评分，勿输出分项得分。"}]
        raise AssertionError("unreachable")

    def summarize_question(self, question: str) -> str:
        """Generate a concise group title for a writing question."""
        for strict in (False, True):
            content = self.chat(
                build_question_summary_prompt(question, strict=strict),
                max_tokens_override=64,
                json_mode=False,
                allow_reasoning_fallback=False,
            )
            summary = sanitize_question_summary(content, question)
            if summary:
                return summary
        return heuristic_question_summary(question)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens_override: int | None = None,
        json_mode: bool | None = None,
        allow_reasoning_fallback: bool = True,
    ) -> str:
        """Call the provider's chat-completions endpoint."""
        if not self.api_key:
            raise ChatAPIError(
                f"未配置 {self.preset.label} API Key，请在系统设置中填写。"
            )

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(
            messages,
            max_tokens_override,
            json_mode,
        )

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ChatAPIError(
                f"{self.preset.label} 网络请求失败: {exc}"
            ) from exc

        if response.status_code in (400, 422):
            retry_payload = self._build_retry_payload(response, payload)
            if retry_payload is not None:
                log.warning(
                    "%s rejected request parameters; retrying. body=%s",
                    self.preset.label,
                    response.text[:300],
                )
                response = self._post_with_retry(
                    url,
                    headers,
                    retry_payload,
                )

        if response.status_code != 200:
            detail = self._extract_error(response)
            raise ChatAPIError(
                f"{self.preset.label} API 返回错误 "
                f"{response.status_code}: {detail}"
            )

        content, finish_reason = self._extract_content(
            response,
            allow_reasoning_fallback=allow_reasoning_fallback,
        )
        self.last_finish_reason = finish_reason
        if not content and "response_format" in payload:
            retry_payload = copy.deepcopy(payload)
            retry_payload.pop("response_format", None)
            log.warning(
                "%s returned empty content; retrying without JSON mode",
                self.preset.label,
            )
            response = self._post_with_retry(url, headers, retry_payload)
            content, finish_reason = self._extract_content(
                response,
                allow_reasoning_fallback=allow_reasoning_fallback,
            )
            self.last_finish_reason = finish_reason

        if not content:
            raise ChatAPIError(
                f"{self.preset.label} API 返回空内容"
                f"（finish_reason={finish_reason or 'unknown'}）。"
            )
        log.info(
            "%s response received: chars=%d finish_reason=%s",
            self.preset.label,
            len(content),
            finish_reason or "unknown",
        )
        return content

    @staticmethod
    def _extract_content(
        response: requests.Response,
        *,
        allow_reasoning_fallback: bool = True,
    ) -> tuple[str, str | None]:
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict)
                )
            if not content and allow_reasoning_fallback:
                content = (
                    message.get("reasoning_content")
                    or message.get("reasoning")
                    or ""
                )
            return str(content).strip(), choice.get("finish_reason")
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ChatAPIError(
                f"API 返回格式异常: {exc}"
            ) from exc

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        max_tokens_override: int | None = None,
        json_mode: bool | None = None,
    ) -> dict[str, Any]:
        max_tokens = max_tokens_override or self.max_tokens
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            self.preset.max_tokens_field: max_tokens,
        }
        if self.preset.use_temperature:
            payload["temperature"] = self.temperature
        if self.preset.use_top_k:
            payload["top_k"] = self.top_k
        if self.preset.use_json_mode and json_mode is not False:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _build_retry_payload(
        self,
        response: requests.Response,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        text = response.text.lower()
        unsupported = (
            "unsupported" in text
            or "not supported" in text
            or "unknown parameter" in text
            or "unrecognized" in text
        )

        retry_payload = copy.deepcopy(payload)
        changed = False

        if self.provider == "glm" and "top_k" in retry_payload:
            retry_payload.pop("top_k", None)
            retry_payload["top_p"] = 0.7
            changed = True
        elif unsupported and "top_k" in retry_payload and "top_k" in text:
            retry_payload.pop("top_k", None)
            retry_payload["top_p"] = 0.7
            changed = True
        if (
            unsupported
            and "response_format" in retry_payload
            and "response_format" in text
        ):
            retry_payload.pop("response_format", None)
            changed = True
        if (
            unsupported
            and "temperature" in retry_payload
            and "temperature" in text
        ):
            retry_payload.pop("temperature", None)
            changed = True
        if (
            unsupported
            and self.preset.max_tokens_field == "max_completion_tokens"
            and "max_completion_tokens" in text
        ):
            retry_payload["max_tokens"] = retry_payload.pop(
                "max_completion_tokens",
                self.max_tokens,
            )
            changed = True
        elif (
            unsupported
            and "max_tokens" in retry_payload
            and "max_tokens" in text
        ):
            retry_payload["max_completion_tokens"] = retry_payload.pop(
                "max_tokens",
                self.max_tokens,
            )
            changed = True

        return retry_payload if changed else None

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

    def _post_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))
        assert last_exc is not None
        raise ChatAPIError(
            f"{self.preset.label} 网络请求失败: {last_exc}"
        ) from last_exc
