"""Provider balance and quota checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class BalanceResult:
    success: bool
    message: str


def query_balance(provider: str, api_key: str) -> BalanceResult:
    provider = provider.lower()
    if provider == "deepseek":
        return _query_deepseek(api_key)
    if provider == "glm":
        return _query_glm_quota(api_key)
    if provider == "openai":
        return BalanceResult(
            False,
            "OpenAI 普通 API Key 不提供公开的余额查询接口。"
            "请在 OpenAI 平台账单页面查看余额。",
        )
    return BalanceResult(False, f"暂不支持 {provider} 的余额查询。")


def _query_deepseek(api_key: str) -> BalanceResult:
    try:
        response = requests.get(
            "https://api.deepseek.com/user/balance",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return BalanceResult(False, f"DeepSeek 网络请求失败: {exc}")
    if response.status_code != 200:
        return BalanceResult(
            False,
            f"DeepSeek 余额查询失败 {response.status_code}: "
            f"{_error_text(response)}",
        )
    try:
        data = response.json()
    except ValueError as exc:
        return BalanceResult(False, f"DeepSeek 返回格式异常: {exc}")

    available = bool(data.get("is_available", True))
    lines: list[str] = []
    for item in data.get("balance_infos", []) or []:
        if not isinstance(item, dict):
            continue
        currency = str(item.get("currency", "CNY"))
        total = item.get("total_balance", "0")
        granted = item.get("granted_balance", "0")
        topped_up = item.get("topped_up_balance", "0")
        lines.append(
            f"{currency} 总余额 {total}（赠送 {granted}，充值 {topped_up}）"
        )
    if not lines:
        lines.append("接口未返回余额明细")
    status = "账户可用" if available else "账户余额不足或不可用"
    return BalanceResult(True, f"DeepSeek {status}\n" + "\n".join(lines))


def _query_glm_quota(api_key: str) -> BalanceResult:
    try:
        response = requests.get(
            "https://open.bigmodel.cn/api/monitor/usage/quota/limit",
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
                "Accept-Language": "zh-CN,zh",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return BalanceResult(False, f"智谱额度查询失败: {exc}")
    if response.status_code != 200:
        return BalanceResult(
            False,
            f"智谱额度查询失败 {response.status_code}: "
            f"{_error_text(response)}",
        )
    try:
        body: dict[str, Any] = response.json()
    except ValueError as exc:
        return BalanceResult(False, f"智谱返回格式异常: {exc}")
    if body.get("success") is False:
        return BalanceResult(
            False,
            f"智谱额度查询失败: {body.get('msg', '未知错误')}",
        )

    data = body.get("data") or {}
    limits = data.get("limits") or []
    token_limits = [
        item
        for item in limits
        if isinstance(item, dict)
        and str(item.get("type", "")).upper() == "TOKENS_LIMIT"
    ]
    if not token_limits:
        level = data.get("level")
        suffix = f"，套餐：{level}" if level else ""
        return BalanceResult(
            True,
            f"智谱 API Key 有效{suffix}，当前响应未提供 Token 套餐额度。",
        )

    lines: list[str] = []
    for item in token_limits:
        percentage = _as_float(item.get("percentage"))
        remaining = max(0.0, 100.0 - percentage)
        lines.append(f"Token 额度：已用 {percentage:.1f}%，剩余 {remaining:.1f}%")
    level = data.get("level")
    suffix = f"\n套餐：{level}" if level else ""
    return BalanceResult(True, "智谱额度查询成功" + suffix + "\n" + "\n".join(lines))


def _error_text(response: requests.Response) -> str:
    try:
        data = response.json()
        error = data.get("error", {})
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if data.get("message"):
            return str(data["message"])
        if data.get("msg"):
            return str(data["msg"])
    except (AttributeError, ValueError, TypeError):
        pass
    return response.text[:500]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
