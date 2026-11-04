"""Tests for agent-driven data acquisition (no live network access)."""

from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from server.acquisition import (
    AcquisitionError,
    AcquisitionService,
    _as_time,
    _check_public_url,
    _walk,
)
from server.marketdata import RealCompanySnapshot, SecurityRef
from server.ontology import OntologyStore
from server.tools import call_tool

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = timezone(timedelta(hours=8))

SOURCES = [
    {
        "id": "fake-billboard",
        "label": "测试龙虎榜",
        "attribution": "测试数据源",
        "requests": [
            {
                "url": "https://example.test/billboard",
                "params": {"code": "{code}"},
                "select": {"path": "rows", "match": {"code": "{code}"}},
                "asOfPath": "date",
                "fields": {
                    "dragonTigerNetBuy": {"path": "net", "type": "float"},
                },
            }
        ],
    },
    {
        "id": "fake-seats",
        "label": "测试席位",
        "attribution": "测试数据源",
        "requests": [
            {
                "url": "https://example.test/seats",
                "params": {"code": "{code}"},
                "asOfPath": "$.rows[0].date",
                "fields": {
                    "seats": {
                        "type": "rows",
                        "path": "rows",
                        "item": {"name": "name", "netBuy": "net"},
                    }
                },
            }
        ],
    },
    {
        "id": "fake-limit-pool",
        "label": "测试涨停池",
        "attribution": "测试数据源",
        "requests": [
            {
                "url": "https://example.test/pool",
                "params": {"code": "{code}", "date": "{yyyymmdd}"},
                "select": {"path": "pool", "match": {"code": "{code}"}},
                "asOfPath": "date",
                "fields": {
                    "limitUpDays": {"path": "days", "type": "int"},
                    "brokenBoardCount": {"path": "broken", "type": "int"},
                    "sealAmount": {"path": "seal", "type": "float"},
                    "firstLimitUpTime": {"path": "first", "type": "time"},
                },
            }
        ],
    },
]


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/billboard":
        return httpx.Response(
            200,
            json={
                "rows": [
                    {"code": "600519", "date": "2026-11-03", "net": 62_000_000},
                    {"code": "000001", "date": "2026-11-03", "net": 1},
                ]
            },
        )
    if path == "/seats":
        return httpx.Response(
            200,
            json={
                "rows": [
                    {"date": "2026-11-03", "name": "某证券杭州营业部", "net": 20_000_000},
                    {"date": "2026-11-03", "name": "某证券机构专用", "net": 10_000_000},
                    {"date": "2026-11-03", "name": "某证券宁波营业部", "net": 8_000_000},
                ]
            },
        )
    if path == "/pool":
        return httpx.Response(
            200,
            json={
                "pool": [
                    {
                        "code": "600519",
                        "date": "2026-11-04",
                        "days": 3,
                        "broken": 0,
                        "seal": 88_000_000,
                        "first": 92500,
                    }
                ]
            },
        )
    return httpx.Response(404, text="not found")


def _client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler), trust_env=False)


def _service(**kwargs) -> AcquisitionService:
    return AcquisitionService(
        sources=SOURCES,
        allowed_hosts=("example.test",),
        client=_client(),
        **kwargs,
    )


def _snapshot() -> RealCompanySnapshot:
    return RealCompanySnapshot(
        security=SecurityRef(
            code="600519",
            name="贵州茅台",
            secid="1.600519",
            exchange_code="SSE",
            exchange_label="上海证券交易所",
            segment_code="main",
            segment_label="主板",
        ),
        quote={
            "code": "600519",
            "name": "贵州茅台",
            "lastPrice": 1439.1,
            "changePct": 3.38,
            "volume": 8_269_100,
            "turnoverRate": 0.66,
            "marketCap": 1_798_992_431_999,
            "asOf": "2026-11-02",
            "source": "测试行情",
            "quality": "public-api",
        },
        valuation={"peTtm": 21.9, "pb": 6.63, "asOf": "2026-11-02"},
        financials={
            "period": "2025",
            "fiscalYearEnd": "2025-12-31",
            "revenue": 172_054_171_891,
            "netProfit": 82_320_067_102,
            "roe": 32.53,
            "roa": 28.31,
            "debtRatio": 16.42,
            "interestCoverage": 2141.02,
            "operatingCashFlow": 61_522_204_989,
            "revenueGrowth": -1.2,
            "profitGrowth": -4.53,
            "eps": 65.66,
        },
        industry="白酒Ⅱ",
        fetched_at=datetime(2026, 11, 2, tzinfo=SHANGHAI),
        short_term=None,
        notes=[],
    )


class FakeProvider:
    source_label = "测试行情"
    source_url = "https://example.test/quote"

    def __init__(self, snapshot: RealCompanySnapshot):
        self.snapshot = snapshot
        self.calls = 0

    def fetch(self, query: str) -> RealCompanySnapshot:
        self.calls += 1
        return self.snapshot

    def screen(self, *, limit: int = 120, sort: str = "marketCap") -> list[RealCompanySnapshot]:
        return []


def _store(provider: FakeProvider, service: AcquisitionService) -> OntologyStore:
    store = OntologyStore(ROOT, market_data=provider)
    store.acquisition = service
    store.acquisition_enabled = True
    return store


def _patch_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def test_walk_and_time_format():
    payload = {"a": {"b": [{"c": 7}]}, "rows": [{"x": 1}, {"x": 2}]}
    assert _walk(payload, "a.b[0].c") == 7
    assert _walk(payload, "rows[1].x") == 2
    assert _walk(payload, "a.b[5].c") is None
    assert _as_time(92500) == "09:25:00"
    assert _as_time("14:57") == "14:57"


def test_default_sources_load():
    service = AcquisitionService()
    assert {"eastmoney-billboard", "eastmoney-billboard-seats", "eastmoney-limit-pool"} <= set(
        service.sources
    )


def test_fetch_extracts_selects_and_rows(monkeypatch):
    _patch_public_dns(monkeypatch)
    service = _service()
    dataset = service.fetch("fake-billboard", {"code": "600519"})
    assert dataset.values["dragonTigerNetBuy"] == 62_000_000
    assert dataset.as_of == "2026-11-03"

    seats = service.fetch("fake-seats", {"code": "600519"})
    assert len(seats.values["seats"]) == 3
    assert seats.values["seats"][0]["name"].startswith("某证券杭州")

    pool = service.fetch("fake-limit-pool", {"code": "600519", "base_date": "2026-11-04"})
    assert pool.values["limitUpDays"] == 3
    assert pool.values["firstLimitUpTime"] == "09:25:00"
    assert pool.as_of == "2026-11-04"


def test_fetch_is_cached_for_the_process(monkeypatch):
    _patch_public_dns(monkeypatch)
    calls = {"count": 0}

    def counting_handler(request):
        calls["count"] += 1
        return _handler(request)

    service = AcquisitionService(
        sources=SOURCES,
        allowed_hosts=("example.test",),
        client=httpx.Client(transport=httpx.MockTransport(counting_handler), trust_env=False),
    )
    service.fetch("fake-billboard", {"code": "600519"})
    service.fetch("fake-billboard", {"code": "600519"})
    assert calls["count"] == 1


def test_no_matching_row_is_no_data(monkeypatch):
    _patch_public_dns(monkeypatch)
    service = _service()
    with pytest.raises(AcquisitionError) as info:
        service.fetch("fake-billboard", {"code": "000002"})
    assert info.value.code == "no_data"


def test_unsafe_urls_are_rejected(monkeypatch):
    with pytest.raises(AcquisitionError) as info:
        _check_public_url("http://example.test/x", ("example.test",))
    assert info.value.code == "unsafe_source"

    with pytest.raises(AcquisitionError) as info:
        _check_public_url("https://evil.test/x", ("example.test",))
    assert info.value.code == "host_not_allowed"

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(AcquisitionError) as info:
        _check_public_url("https://example.test/x", ("example.test",))
    assert info.value.code == "unsafe_source"


def test_redirects_and_invalid_json_are_rejected(monkeypatch):
    _patch_public_dns(monkeypatch)
    source = {
        "id": "redirect",
        "requests": [{"url": "https://example.test/redirect", "fields": {"sentimentScore": {"path": "x"}}}],
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": "/x"})),
        trust_env=False,
    )
    service = AcquisitionService(
        sources=[source], allowed_hosts=("example.test",), client=client
    )
    with pytest.raises(AcquisitionError) as info:
        service.fetch("redirect", {"code": "600519"})
    assert info.value.code == "unsafe_redirect"

    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html>")),
        trust_env=False,
    )
    service = AcquisitionService(
        sources=[{"id": "bad", "requests": [{"url": "https://example.test/bad", "fields": {"sentimentScore": {"path": "x"}}}]}],
        allowed_hosts=("example.test",),
        client=client,
    )
    with pytest.raises(AcquisitionError) as info:
        service.fetch("bad", {"code": "600519"})
    assert info.value.code == "bad_response"


# ---------------------------------------------------------------------------
# Ontology integration and agent tool
# ---------------------------------------------------------------------------


def test_acquire_data_merges_facts_rules_and_survives_refresh(monkeypatch):
    _patch_public_dns(monkeypatch)
    provider = FakeProvider(_snapshot())
    store = _store(provider, _service())

    before = call_tool(store, "get_company_analysis", {"company": "600519"})
    assert before["ok"] is True
    fields = {item["field"] for item in before["data"]["missingData"]}
    assert {"dragonTigerNetBuy", "hotMoneySeatCount", "sealAmount"} <= fields

    result = call_tool(
        store,
        "acquire_data",
        {
            "company": "600519",
            "fields": [
                "dragonTigerNetBuy",
                "hotMoneySeatCount",
                "sealAmount",
                "limitUpDays",
                "brokenBoardCount",
                "firstLimitUpTime",
            ],
            "sources": ["fake-billboard", "fake-seats", "fake-limit-pool"],
        },
    )
    assert result["ok"] is True, result
    data = result["data"]
    assert data["acquired"]["dragonTigerNetBuy"] == 62_000_000
    assert data["acquired"]["hotMoneySeatCount"] == 2
    assert data["acquired"]["sealAmount"] == 88_000_000
    assert data["acquired"]["seats"][0]["type"] == "hot-money"
    assert any(item["ruleId"] == "R16" and item["after"] == "triggered" for item in data["ruleChanges"])
    signals = {item["ruleId"]: item["status"] for item in data["signals"]}
    assert signals["R16"] == "triggered"
    assert signals["R17"] == "triggered"
    assert data["shortTerm"]["agentAcquired"] is True
    assert "Agent" in data["dataNote"]

    # A later quote/analysis refresh must not wipe the acquired facts.
    refreshed = call_tool(store, "get_company_analysis", {"company": "600519"})
    assert refreshed["ok"] is True
    assert refreshed["data"]["shortTerm"]["dragonTigerNetBuy"] == 62_000_000
    assert refreshed["data"]["shortTerm"]["hotMoneySeatCount"] == 2
    assert refreshed["data"]["shortTerm"]["agentAcquired"] is True


def test_acquired_facts_expire_after_the_overlay_ttl(monkeypatch):
    _patch_public_dns(monkeypatch)
    provider = FakeProvider(_snapshot())
    store = _store(provider, _service())
    result = call_tool(
        store,
        "acquire_data",
        {
            "company": "600519",
            "fields": ["dragonTigerNetBuy", "hotMoneySeatCount"],
            "sources": ["fake-billboard", "fake-seats"],
        },
    )
    assert result["ok"] is True
    assert result["data"]["shortTerm"]["dragonTigerNetBuy"] == 62_000_000

    import server.ontology as ontology_module

    monkeypatch.setattr(ontology_module.time, "time", lambda: 9_999_999_999.0)
    refreshed = call_tool(store, "get_company_analysis", {"company": "600519"})
    assert refreshed["ok"] is True
    assert refreshed["data"]["shortTerm"]["dragonTigerNetBuy"] is None
    assert refreshed["data"]["shortTerm"]["agentAcquired"] is False


def test_agent_supplied_source_is_registered_and_reused(monkeypatch):
    _patch_public_dns(monkeypatch)
    provider = FakeProvider(_snapshot())
    service = _service()
    store = _store(provider, service)
    custom = {
        "id": "custom-billboard",
        "label": "自定义龙虎榜",
        "url": "https://example.test/billboard",
        "params": {"code": "{code}"},
        "select": {"path": "rows", "match": {"code": "{code}"}},
        "asOfPath": "date",
        "fields": {"dragonTigerNetBuy": {"path": "net", "type": "float"}},
    }
    result = call_tool(
        store,
        "acquire_data",
        {"company": "600519", "fields": ["dragonTigerNetBuy"], "source": custom},
    )
    assert result["ok"] is True, result
    assert service.get_source("custom-billboard").label == "自定义龙虎榜"
    assert result["data"]["acquired"]["dragonTigerNetBuy"] == 62_000_000


def test_acquire_data_rejects_example_companies():
    provider = FakeProvider(_snapshot())
    store = _store(provider, _service())
    result = call_tool(store, "acquire_data", {"company": "华辰智造"})
    assert result["ok"] is False
    assert result["error"]["code"] == "not_real_company"


def test_acquire_data_disabled_returns_clear_error(monkeypatch):
    _patch_public_dns(monkeypatch)
    provider = FakeProvider(_snapshot())
    store = _store(provider, _service())
    store.acquisition_enabled = False
    result = call_tool(store, "acquire_data", {"company": "600519"})
    assert result["ok"] is False
    assert result["error"]["code"] == "acquisition_disabled"


def test_agent_loop_can_call_acquire_data(monkeypatch):
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.settings import Settings
    from tests.conftest import FakeLLM, final_response, tool_response

    _patch_public_dns(monkeypatch)
    provider = FakeProvider(_snapshot())
    store = _store(provider, _service())
    settings = Settings(
        root=ROOT,
        llm_api_key="unit-test",
        rate_limit_per_minute=100,
        rate_limit_per_hour=100,
        daily_request_budget=100,
        market_data_enabled=True,
        agent_max_steps=4,
    )
    llm = FakeLLM(
        responses=[
            tool_response("load_company_data", {"company": "600519"}),
            tool_response(
                "acquire_data",
                {
                    "company": "600519",
                    "fields": ["dragonTigerNetBuy", "hotMoneySeatCount"],
                    "sources": ["fake-billboard", "fake-seats"],
                },
            ),
            final_response("Agent 已获取龙虎榜数据。"),
        ]
    )
    app = create_app(settings=settings, store=store, llm=llm)
    app.state.store.acquisition = _service()
    client = TestClient(app)
    response = client.post("/api/agent/analyze", json={"question": "分析贵州茅台的龙虎榜"})
    assert response.status_code == 200
    payload = response.json()
    assert [item["tool"] for item in payload["steps"]] == [
        "load_company_data",
        "acquire_data",
    ]
    assert payload["dataMode"] == "real"
    tool_messages = [
        item
        for item in payload["execution"]["messages"]
        if item.get("role") == "tool" and item.get("name") == "acquire_data"
    ]
    assert tool_messages and tool_messages[0]["ok"] is True

