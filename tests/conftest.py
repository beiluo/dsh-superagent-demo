"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from server.app import create_app  # noqa: E402
from server.llm import LLMError, LLMResponse, ToolCall  # noqa: E402
from server.ontology import OntologyStore  # noqa: E402
from server.settings import Settings  # noqa: E402

FAKE_KEY = "unit-test-only-value"


class FakeLLM:
    enabled = True

    def __init__(self, responses=None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        if self.error:
            raise self.error
        if self.responses:
            response = self.responses.pop(0)
        else:
            response = LLMResponse(content="默认测试回答。", model="fake-model")
        if callable(response):
            return response()
        return response


@pytest.fixture(scope="session")
def store() -> OntologyStore:
    return OntologyStore(ROOT)


@pytest.fixture
def base_settings(store: OntologyStore) -> Settings:
    return Settings(
        root=ROOT,
        llm_api_key="",
        rate_limit_per_minute=100,
        rate_limit_per_hour=100,
        daily_request_budget=100,
        max_request_bytes=24_000,
    )


@pytest.fixture
def client_factory(store: OntologyStore, base_settings: Settings):
    def make(
        overrides: dict | None = None,
        *,
        llm=None,
        settings: Settings | None = None,
    ) -> TestClient:
        active = settings or replace(base_settings, **(overrides or {}))
        app = create_app(settings=active, store=store, llm=llm)
        return TestClient(app)

    return make


def tool_response(name: str, arguments: dict, *, call_id: str = "call-test") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
        model="fake-model",
    )


def final_response(text: str) -> LLMResponse:
    return LLMResponse(content=text, finish_reason="stop", model="fake-model")


__all__ = ["FAKE_KEY", "FakeLLM", "final_response", "tool_response", "LLMError"]
