"""Tests for mapping real A-share snapshots into the ontology agent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app
from server.marketdata import SOURCE_LABEL, MarketDataError, RealCompanySnapshot, SecurityRef
from server.namespaces import ASH
from server.ontology import OntologyStore
from server.settings import Settings
from server.tools import call_tool
from tests.conftest import FakeLLM, final_response, tool_response

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = timezone(timedelta(hours=8))


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
            "source": SOURCE_LABEL,
            "quality": "public-api",
        },
        valuation={
            "peTtm": 21.9,
            "pb": 6.63,
            "asOf": "2026-11-02",
            "source": SOURCE_LABEL,
            "quality": "public-api",
        },
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
            "asOf": "2025-12-31",
            "source": SOURCE_LABEL,
            "quality": "public-api",
        },
        industry="白酒Ⅱ",
        fetched_at=datetime(2026, 11, 2, tzinfo=SHANGHAI),
        notes=[],
    )


class FakeProvider:
    source_label = "测试公开行情源"
    source_url = "https://example.test/quote"

    def __init__(self, snapshot: RealCompanySnapshot | None = None, error: Exception | None = None):
        self.snapshot = snapshot
        self.error = error
        self.queries: list[str] = []

    def fetch(self, query: str) -> RealCompanySnapshot | None:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.snapshot


def _store(provider: FakeProvider) -> OntologyStore:
    return OntologyStore(ROOT, market_data=provider)


def _settings(**overrides) -> Settings:
    values = {
        "root": ROOT,
        "llm_api_key": "",
        "rate_limit_per_minute": 100,
        "rate_limit_per_hour": 100,
        "daily_request_budget": 100,
        "market_data_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_real_company_maps_into_ontology():
    store = _store(FakeProvider(_snapshot()))
    result = call_tool(store, "get_company_analysis", {"company": "贵州茅台"})

    assert result["ok"] is True
    data = result["data"]
    assert data["dataMode"] == "real"
    assert data["company"]["label"] == "贵州茅台"
    assert data["company"]["companyCode"] == "600519"
    assert data["company"]["industry"]["label"] == "白酒"
    assert data["security"]["exchange"]["label"] == "上海证券交易所"
    assert data["financials"]["roe"] == 32.53
    assert data["financials"]["interestCoverage"] == 2141.02
    assert data["quote"]["lastPrice"] == 1439.1
    assert result["summary"]["mode"] == "real"
    assert result["summary"]["price"] == 1439.1
    real_kinds = {item["kind"] for item in result["citations"]}
    assert "real" in real_kinds
    assert "concept" in real_kinds
    assert "individual" not in real_kinds
    # The real company is not added to the synthetic screening pool.
    assert len(store._company_subjects) >= 4


def test_real_company_api_rules_mode():
    provider = FakeProvider(_snapshot())
    store = _store(provider)
    client = TestClient(create_app(settings=_settings(), store=store, market_data=provider))
    response = client.post("/api/agent/analyze", json={"question": "分析贵州茅台"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["dataMode"] == "real"
    assert payload["summary"]["mode"] == "real"
    assert "贵州茅台" in payload["answer"]
    assert "真实数据" in payload["answer"]
    assert "东方财富" in payload["answer"]
    assert "2025" in payload["answer"]
    assert "不构成投资建议" in payload["answer"]
    assert "全部为本体中的合成示例数据" not in payload["answer"]
    assert payload["steps"][0]["tool"] == "get_company_analysis"
    assert any(item["kind"] == "real" for item in payload["citations"])


def test_real_company_refresh_replaces_runtime_entities():
    provider = FakeProvider(_snapshot())
    store = _store(provider)
    first = call_tool(store, "get_company_analysis", {"company": "贵州茅台"})
    second = call_tool(store, "get_company_analysis", {"company": "贵州茅台"})
    assert first["ok"] and second["ok"]
    assert len(store._real_companies) == 1
    company = store.find_company("600519")
    security = next(store.graph.objects(company, ASH.hasSecurity))
    quotes = list(store.graph.objects(security, ASH.hasMarketQuote))
    assert len(quotes) == 1
    assert provider.queries[0] == "贵州茅台"
    assert provider.queries[1] == "600519"


def test_unknown_company_keeps_examples_available():
    store = _store(FakeProvider(None))
    result = call_tool(store, "get_company_analysis", {"company": "不存在的公司"})
    assert result["ok"] is False
    assert result["error"]["code"] == "company_not_found"
    assert "华辰智造" in result["error"]["available"]
    assert "600519" in result["error"]["hint"]


def test_market_data_failure_is_a_safe_tool_error():
    provider = FakeProvider(error=MarketDataError("market_data_timeout", "真实行情数据源响应超时，请稍后重试。"))
    store = _store(provider)
    result = call_tool(store, "get_company_analysis", {"company": "贵州茅台"})
    assert result["ok"] is False
    assert result["error"]["code"] == "market_data_timeout"
    assert "示例公司仍可分析" in result["error"]["message"]


def test_screen_still_only_covers_examples_after_real_lookup():
    store = _store(FakeProvider(_snapshot()))
    call_tool(store, "get_company_analysis", {"company": "贵州茅台"})
    result = call_tool(store, "screen_companies", {})
    labels = [item["label"] for item in result["data"]["companies"]]
    assert len(labels) >= 4
    assert "贵州茅台" not in labels
    assert "华辰智造" in labels
    assert "游资科技" in labels


def test_list_companies_mentions_real_data_support():
    store = _store(FakeProvider(_snapshot()))
    result = call_tool(store, "list_companies", {})
    assert result["data"]["realData"]["enabled"] is True
    assert result["data"]["realData"]["provider"] == "测试公开行情源"
    assert "真实 A 股" in result["data"]["dataNote"]


def test_llm_path_uses_real_boundary():
    provider = FakeProvider(_snapshot())
    store = _store(provider)
    fake = FakeLLM(
        [
            tool_response("get_company_analysis", {"company": "贵州茅台"}),
            final_response("### 贵州茅台（600519）\n真实数据来自公开接口。"),
        ]
    )
    client = TestClient(
        create_app(
            settings=_settings(llm_api_key="unit-test-only-value"),
            store=store,
            llm=fake,
            market_data=provider,
        )
    )
    response = client.post("/api/agent/analyze", json={"question": "分析贵州茅台"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "llm"
    assert payload["dataMode"] == "real"
    assert "公开行情" in payload["answer"]
    assert "合成示例" not in payload["answer"]


def test_bare_company_name_routes_to_real_data():
    provider = FakeProvider(_snapshot())
    store = _store(provider)
    client = TestClient(create_app(settings=_settings(), store=store, market_data=provider))
    response = client.post("/api/agent/analyze", json={"question": "贵州茅台"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["dataMode"] == "real"
    assert payload["steps"][0]["tool"] == "get_company_analysis"


def test_disabled_market_data_explains_scope():
    store = OntologyStore(ROOT)
    result = call_tool(store, "get_company_analysis", {"company": "贵州茅台"})
    assert result["ok"] is False
    assert result["error"]["code"] == "company_not_found"
    assert "未启用真实 A 股数据源" in result["error"]["message"]
    assert "华辰智造" in result["error"]["available"]


def test_app_can_disable_market_data():
    client = TestClient(create_app(settings=_settings(market_data_enabled=False)))
    status = client.get("/api/agent/status").json()
    assert status["marketData"]["enabled"] is False
    response = client.post("/api/agent/analyze", json={"question": "分析贵州茅台"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["dataMode"] == "example"
    assert "未启用真实 A 股数据源" in payload["answer"]


def test_buy_advice_question_leaves_only_the_company_name():
    provider = FakeProvider(_snapshot())
    store = _store(provider)
    client = TestClient(create_app(settings=_settings(), store=store, market_data=provider))
    response = client.post("/api/agent/analyze", json={"question": "分析贵州茅台适合买入吗？"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["dataMode"] == "real"
    assert provider.queries[0] == "贵州茅台"
    assert "不构成投资建议" in payload["answer"]
