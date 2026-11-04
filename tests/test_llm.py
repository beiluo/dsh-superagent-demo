"""LLM client and agent-loop tests with a fake upstream server."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from server.llm import LLMClient, LLMError
from tests.conftest import FAKE_KEY, FakeLLM, final_response, tool_response


def test_llm_client_uses_server_side_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "model": "fake-model",
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "get_rule",
                                        "arguments": '{"rule_id": "R01"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"total_tokens": 10},
            },
        )

    async def run():
        from server.settings import Settings

        settings = Settings(llm_api_key=FAKE_KEY)
        client = LLMClient(settings, transport=httpx.MockTransport(handler))
        return await client.chat([{"role": "user", "content": "hi"}])

    response = asyncio.run(run())
    assert seen["authorization"] == f"Bearer {FAKE_KEY}"
    assert response.content == "ok"
    assert response.tool_calls[0].name == "get_rule"
    assert response.tool_calls[0].arguments == {"rule_id": "R01"}


def test_llm_error_does_not_echo_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad key {FAKE_KEY}")

    async def run():
        from server.settings import Settings

        settings = Settings(llm_api_key=FAKE_KEY)
        client = LLMClient(settings, transport=httpx.MockTransport(handler))
        with pytest.raises(LLMError) as captured:
            await client.chat([{"role": "user", "content": "hi"}])
        return captured.value

    error = asyncio.run(run())
    assert error.code == "llm_http_401"
    assert FAKE_KEY not in error.safe_message()
    assert FAKE_KEY not in repr(error)


def test_llm_client_ignores_broken_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://[::1")
    monkeypatch.setenv("HTTPS_PROXY", "http://[::1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "fake-model",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            },
        )

    async def run():
        from server.settings import Settings

        settings = Settings(llm_api_key=FAKE_KEY)
        client = LLMClient(settings, transport=httpx.MockTransport(handler))
        return await client.chat([{"role": "user", "content": "hi"}])

    assert asyncio.run(run()).content == "ok"


def test_llm_timeout_is_retryable():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async def run():
        from server.settings import Settings

        settings = Settings(llm_api_key=FAKE_KEY)
        client = LLMClient(settings, transport=httpx.MockTransport(handler))
        with pytest.raises(LLMError) as captured:
            await client.chat([{"role": "user", "content": "hi"}])
        return captured.value

    error = asyncio.run(run())
    assert error.code == "llm_timeout"
    assert error.retryable is True


def test_agent_tool_loop(client_factory):
    fake = FakeLLM(
        [
            tool_response("get_company_analysis", {"company": "华辰智造"}),
            final_response("### 结论\n华辰智造触发 R01。"),
        ]
    )
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=fake)
    response = client.post("/api/agent/analyze", json={"question": "分析华辰智造"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "llm"
    assert data["model"] == "fake-model"
    assert data["steps"][0]["tool"] == "get_company_analysis"
    assert data["summary"]["recommendation"] == "增持"
    assert "华辰智造" in data["answer"]
    assert "不构成投资建议" in data["answer"]
    assert FAKE_KEY not in response.text


def test_agent_generates_and_chains_sparql_queries(client_factory):
    fake = FakeLLM(
        [
            tool_response("describe_ontology", {"focus": "公司"}),
            tool_response(
                "sparql_query",
                {
                    "query": (
                        "SELECT ?company ?label WHERE { "
                        '?company a ash:ListedCompany ; rdfs:label ?label . '
                        'FILTER(LANG(?label) = "zh") } LIMIT 5'
                    )
                },
            ),
            final_response("### 结论\n本体中有 5 家示例公司。"),
        ]
    )
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=fake)
    response = client.post("/api/agent/analyze", json={"question": "本体里有多少家公司？"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "llm"
    assert [item["tool"] for item in data["steps"]] == [
        "describe_ontology",
        "sparql_query",
    ]
    assert [item["tool"] for item in data["queryPath"]] == [
        "describe_ontology",
        "sparql_query",
    ]
    sparql_steps = data["queryPath"][1]["steps"]
    assert sparql_steps[0]["label"] == "执行 Agent 生成的只读 SPARQL"
    assert "ash:ListedCompany" in sparql_steps[0]["detail"]
    tool_message = [
        item
        for item in data["execution"]["messages"]
        if item.get("name") == "sparql_query"
    ][0]
    assert tool_message["ok"] is True
    assert '"rowCount": 5' in tool_message["content"]
    assert "华辰智造" in tool_message["content"]


def test_agent_execution_trace_records_raw_messages(client_factory):
    fake = FakeLLM(
        [
            tool_response("get_company_analysis", {"company": "华辰智造"}),
            final_response("### 结论\n华辰智造触发 R01。"),
        ]
    )
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=fake)
    response = client.post(
        "/api/agent/analyze",
        json={
            "question": "分析华辰智造",
            "history": [
                {"role": "user", "content": "之前的问题"},
                {"role": "assistant", "content": "之前的回答"},
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    execution = data["execution"]
    assert execution["mode"] == "llm"
    assert execution["model"] == "fake-model"
    assert execution["systemPrompt"]["hidden"] is True
    assert execution["systemPrompt"]["chars"] > 0
    assert "你是「ASHARE" not in response.text

    messages = execution["messages"]
    assert [item["role"] for item in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert messages[0]["content"] == "之前的问题"
    assert messages[0]["history"] is True
    assert messages[2]["content"] == "分析华辰智造"

    decision = messages[3]
    assert decision["round"] == 1
    assert decision["toolCalls"] == [
        {
            "id": "call-test",
            "name": "get_company_analysis",
            "arguments": {"company": "华辰智造"},
        }
    ]

    tool_message = messages[4]
    assert tool_message["name"] == "get_company_analysis"
    assert tool_message["label"] == "读取企业画像与规则信号"
    assert tool_message["arguments"] == {"company": "华辰智造"}
    assert tool_message["ok"] is True
    assert tool_message["elapsedMs"] >= 0
    assert json.loads(tool_message["content"])["ok"] is True
    assert "华辰智造" in tool_message["content"]

    assert messages[5]["content"].startswith("### 结论")
    assert FAKE_KEY not in response.text


def test_agent_requires_a_tool_call(client_factory):
    fake = FakeLLM([final_response("我直接给一个没有工具依据的答案。")])
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=fake)
    response = client.post("/api/agent/analyze", json={"question": "分析华辰智造"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "rules"
    assert "llm_no_tools" in (data["notice"] or "")


def test_agent_falls_back_when_llm_fails(client_factory):
    fake = FakeLLM(error=LLMError("llm_timeout", retryable=True))
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=fake)
    response = client.post("/api/agent/analyze", json={"question": "分析华辰智造"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "rules"
    assert data["notice"]
    assert "llm_timeout" in data["notice"]
    assert "华辰智造" in data["answer"]
    assert FAKE_KEY not in response.text


def test_agent_handles_tool_errors(client_factory):
    fake = FakeLLM(
        [
            tool_response("get_company_analysis", {"company": "不存在的公司"}),
            final_response("没有找到该公司，可用的公司有华辰智造、宁源新能源、景康生物、示例 ST 公司。"),
        ]
    )
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=fake)
    response = client.post("/api/agent/analyze", json={"question": "分析不存在的公司"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "llm"
    assert data["steps"][0]["status"] == "error"


def test_agent_step_limit_falls_back(client_factory):
    def always_tool():
        return tool_response("list_companies", {})

    fake = FakeLLM([always_tool for _ in range(10)])
    client = client_factory({"llm_api_key": FAKE_KEY, "agent_max_steps": 2}, llm=fake)
    response = client.post("/api/agent/analyze", json={"question": "分析华辰智造"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "rules"
    assert data["notice"]
