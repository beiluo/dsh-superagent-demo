"""OpenAI-compatible chat client used only by the server."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .settings import Settings

logger = logging.getLogger("ashare.agent.llm")

_TOKEN_PATTERN = re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_\-]{12,}\b")


def redact_secret(text: Any, secret: str = "") -> str:
    value = str(text or "")
    if secret:
        value = value.replace(secret, "[redacted]")
    return _TOKEN_PATTERN.sub("[redacted]", value)


class LLMError(Exception):
    def __init__(self, code: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable

    def safe_message(self) -> str:
        return f"LLM request failed ({self.code})"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return self.settings.configured

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: str | None = "auto",
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not self.enabled:
            raise LLMError("llm_not_configured")

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "max_tokens": max_tokens or self.settings.llm_max_output_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=10.0)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    self.settings.chat_completions_url,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMError("llm_timeout", retryable=True) from exc
        except httpx.RequestError as exc:
            raise LLMError("llm_unreachable", retryable=True) from exc

        if response.status_code >= 400:
            detail = redact_secret(response.text[:500], self.settings.llm_api_key)
            logger.warning(
                "llm http error status=%s model=%s detail=%s",
                response.status_code,
                self.settings.llm_model,
                detail[:300],
            )
            raise LLMError(
                f"llm_http_{response.status_code}",
                status_code=response.status_code,
                retryable=response.status_code >= 500 or response.status_code == 429,
            )

        try:
            payload_json = response.json()
            choice = payload_json["choices"][0]
            message = choice.get("message") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("llm_invalid_response", retryable=True) from exc

        content = message.get("content") or ""
        if not isinstance(content, str):
            content = str(content)

        tool_calls: list[ToolCall] = []
        for index, raw_call in enumerate(message.get("tool_calls") or []):
            function = raw_call.get("function") or {}
            name = function.get("name") or ""
            raw_arguments = function.get("arguments")
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
                except ValueError as exc:
                    raise LLMError("llm_invalid_tool_arguments", retryable=True) from exc
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                arguments = {}
            if not name:
                continue
            tool_calls.append(
                ToolCall(
                    id=str(raw_call.get("id") or f"call_{index}"),
                    name=name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )

        logger.info(
            "llm ok model=%s messages=%d tools=%d finish=%s",
            self.settings.llm_model,
            len(messages),
            len(tools or []),
            choice.get("finish_reason") or "",
        )
        return LLMResponse(
            content=content.strip(),
            tool_calls=tool_calls,
            finish_reason=str(choice.get("finish_reason") or ""),
            model=str(payload_json.get("model") or self.settings.llm_model),
            usage=payload_json.get("usage") or {},
        )


__all__ = ["LLMClient", "LLMError", "LLMResponse", "ToolCall", "redact_secret"]
