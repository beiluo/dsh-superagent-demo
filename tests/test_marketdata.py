"""Unit tests for the public A-share data adapter (no network access)."""

from __future__ import annotations

import httpx
import pytest

from server.marketdata import EastmoneyProvider, MarketDataError

SHANGHAI_TS = 1793607097  # 2026-11-02 in Asia/Shanghai


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "searchapi.eastmoney.com":
        return httpx.Response(
            200,
            json={
                "QuotationCodeTable": {
                    "Data": [
                        {
                            "Code": "600519",
                            "Name": "贵州茅台",
                            "Classify": "AStock",
                            "SecurityTypeName": "沪A",
                            "QuoteID": "1.600519",
                            "MktNum": "1",
                        }
                    ]
                }
            },
        )
    if host == "push2.eastmoney.com":
        return httpx.Response(
            200,
            json={
                "data": {
                    "f43": 143910,
                    "f47": 82691,
                    "f57": "600519",
                    "f58": "贵州茅台",
                    "f60": 139205,
                    "f86": SHANGHAI_TS,
                    "f116": 1798992431999.0999,
                    "f162": 2093,
                    "f163": 2185,
                    "f164": 2190,
                    "f167": 663,
                    "f168": 66,
                    "f170": 338,
                    "f173": 24.47,
                }
            },
        )
    if host == "datacenter-web.eastmoney.com":
        return httpx.Response(
            200,
            json={
                "result": {
                    "data": [
                        {
                            "REPORTDATE": "2026-09-30 00:00:00",
                            "TOTAL_OPERATE_INCOME": 133283652508.95,
                            "PARENT_NETPROFIT": 64467425981.95,
                            "WEIGHTAVG_ROE": 24.47,
                            "BASIC_EPS": 51.53,
                            "YSTZ": 1.8,
                            "SJLTZ": -0.25,
                            "PUBLISHNAME": "白酒Ⅱ",
                        },
                        {
                            "REPORTDATE": "2025-12-31 00:00:00",
                            "TOTAL_OPERATE_INCOME": 172054171890.91,
                            "PARENT_NETPROFIT": 82320067101.68,
                            "WEIGHTAVG_ROE": 32.53,
                            "BASIC_EPS": 65.66,
                            "YSTZ": -1.2,
                            "SJLTZ": -4.53,
                            "PUBLISHNAME": "白酒Ⅱ",
                        },
                    ]
                },
                "success": True,
            },
        )
    if host == "datacenter.eastmoney.com":
        return httpx.Response(
            200,
            json={
                "result": {
                    "data": [
                        {
                            "REPORT_DATE": "2026-09-30 00:00:00",
                            "ZCFZL": 11.9,
                            "ZZCJLL": 21.4,
                            "INTEREST_COVERAGE_RATIO": None,
                            "NETCASH_OPERATE_PK": 84058979832.29,
                        },
                        {
                            "REPORT_DATE": "2025-12-31 00:00:00",
                            "ZCFZL": 16.42,
                            "ZZCJLL": 28.31,
                            "INTEREST_COVERAGE_RATIO": 2141.02,
                            "NETCASH_OPERATE_PK": 61522204989.0,
                        },
                    ]
                }
            },
        )
    return httpx.Response(404, json={})


@pytest.fixture
def provider() -> EastmoneyProvider:
    provider = EastmoneyProvider(
        timeout_seconds=3,
        transport=httpx.MockTransport(_handler),
    )
    yield provider
    provider.close()


def test_resolve_and_fetch_real_company(provider):
    snapshot = provider.fetch("贵州茅台")
    assert snapshot is not None
    assert snapshot.security.code == "600519"
    assert snapshot.security.name == "贵州茅台"
    assert snapshot.security.exchange_code == "SSE"
    assert snapshot.security.segment_code == "main"
    assert snapshot.quote["lastPrice"] == 1439.1
    assert snapshot.quote["volume"] == 8_269_100
    assert snapshot.quote["marketCap"] == 1_798_992_431_999
    assert snapshot.quote["asOf"] == "2026-11-02"
    assert snapshot.valuation["peTtm"] == 21.9
    assert snapshot.valuation["pb"] == 6.63
    assert snapshot.financials is not None
    assert snapshot.financials["period"] == "2025"
    assert snapshot.financials["roe"] == 32.53
    assert snapshot.financials["debtRatio"] == 16.42
    assert snapshot.financials["interestCoverage"] == 2141.02
    assert snapshot.financials["revenueGrowth"] == -1.2
    assert snapshot.industry == "白酒Ⅱ"
    assert snapshot.notes == []


def test_code_query_uses_search_result(provider):
    snapshot = provider.fetch("600519")
    assert snapshot is not None
    assert snapshot.security.code == "600519"


def test_quote_and_financials_are_cached(provider):
    calls = {"quote": 0, "report": 0}

    def counting_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "push2.eastmoney.com":
            calls["quote"] += 1
        if request.url.host == "datacenter-web.eastmoney.com":
            calls["report"] += 1
        return _handler(request)

    cached = EastmoneyProvider(timeout_seconds=3, transport=httpx.MockTransport(counting_handler))
    try:
        first = cached.fetch("600519")
        second = cached.fetch("贵州茅台")
    finally:
        cached.close()
    assert first and second
    assert calls == {"quote": 1, "report": 1}


def test_unknown_query_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"QuotationCodeTable": {"Data": []}})

    provider = EastmoneyProvider(timeout_seconds=3, transport=httpx.MockTransport(handler))
    try:
        assert provider.fetch("不存在的公司") is None
    finally:
        provider.close()


def test_empty_quote_raises_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "searchapi.eastmoney.com":
            return _handler(request)
        return httpx.Response(200, json={"data": None})

    provider = EastmoneyProvider(timeout_seconds=3, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(MarketDataError) as captured:
            provider.fetch("600519")
    finally:
        provider.close()
    assert captured.value.code == "market_data_no_quote"
    assert "600519" in captured.value.message


def test_timeout_is_reported_as_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom", request=request)

    provider = EastmoneyProvider(timeout_seconds=3, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(MarketDataError) as captured:
            provider.fetch("600519")
    finally:
        provider.close()
    assert captured.value.code == "market_data_timeout"


def test_annual_report_failure_is_partial_not_fatal():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "datacenter-web.eastmoney.com":
            return httpx.Response(500, json={})
        return _handler(request)

    provider = EastmoneyProvider(timeout_seconds=3, transport=httpx.MockTransport(handler))
    try:
        snapshot = provider.fetch("600519")
    finally:
        provider.close()
    assert snapshot is not None
    assert snapshot.financials is None
    assert snapshot.quote["lastPrice"] == 1439.1
    assert snapshot.notes


def test_eastmoney_screen_reads_quote_page():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "data": {
                    "total": 2,
                    "diff": [
                        {
                            "f12": "600036",
                            "f14": "招商银行",
                            "f2": 38.5,
                            "f3": 1.2,
                            "f8": 0.6,
                            "f9": 6.1,
                            "f20": 972_000_000_000,
                            "f23": 0.9,
                            "f100": "银行",
                        },
                        {
                            "f12": "000001",
                            "f14": "平安银行",
                            "f2": 11.2,
                            "f3": -0.4,
                            "f8": 0.8,
                            "f9": -3.0,
                            "f20": 217_000_000_000,
                            "f23": 0.5,
                            "f100": "银行",
                        },
                    ],
                }
            },
        )

    provider = EastmoneyProvider(timeout_seconds=3, transport=httpx.MockTransport(handler))
    try:
        snapshots = provider.screen(limit=2, sort="+peTtm")
    finally:
        provider.close()

    assert seen["path"].endswith("/api/qt/clist/get")
    assert seen["params"]["fid"] == "f9"
    assert seen["params"]["po"] == "0"
    assert seen["params"]["pz"] == "2"
    assert [item.security.code for item in snapshots] == ["600036", "000001"]
    assert snapshots[0].valuation["peTtm"] == 6.1
    assert snapshots[1].valuation["peTtm"] is None  # negative PE is not meaningful
    assert snapshots[0].industry == "银行"
    assert snapshots[0].financials is None
    assert snapshots[0].quote["marketCap"] == 972_000_000_000
    assert snapshots[0].notes
