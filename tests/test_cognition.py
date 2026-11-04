"""Five-engine trading-cognition pipeline tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.cognition import CognitionError, assess_cognition, build_cognition_context
from server.ontology import OntologyStore
from server.tools import TOOLS, call_tool

ROOT = Path(__file__).resolve().parents[1]


def test_cognition_context_loads_non_position_case(store: OntologyStore):
    context = build_cognition_context(store, "游资科技")
    assert context["scenario"] == "non_position"
    assert context["scenarioLabel"] == "非持仓"
    assert context["case"]["caseId"] == "AC-YZ-20261103"
    assert context["case"]["version"] == 2
    assert [item["id"] for item in context["engines"]] == [
        "market",
        "stock",
        "event",
        "opportunity",
        "decision",
    ]
    assert context["judgment"]["decisionCode"] == "buy"
    assert context["judgment"]["version"] == 2
    assert context["riskReward"]["expectedRewardRiskRatio"] == 2.08
    assert context["revisions"][0]["fromVersion"] == 1
    assert context["revisions"][0]["toVersion"] == 2
    assert context["verification"]["resultCode"] == "logic_held"


def test_cognition_context_loads_held_case_and_position(store: OntologyStore):
    context = build_cognition_context(store, "华辰智造")
    assert context["scenario"] == "held"
    assert context["position"]["weight"] == 0.12
    assert context["judgment"]["decisionCode"] == "reduce"
    assert context["judgment"]["logicStillValid"] is True
    assert context["opportunity"]["stageCode"] == "decline"
    assert context["verification"]["resultCode"] == "logic_weakened"
    triggers = {
        item["id"]
        for item in context["revisions"][0]["triggerEvidence"]
    }
    assert "evidence-huachen-pm-breakdown" in triggers
    assert "evidence-huachen-weight" in triggers


def test_non_position_judgment_is_evidence_first_buy(store: OntologyStore):
    result = assess_cognition(store, "游资科技")
    assert result["decision"]["code"] == "buy"
    assert result["decision"]["consistent"] is True
    assert result["blockers"] == []
    assert all(item["status"] == "pass" for item in result["checks"])
    assert [item["stage"] for item in result["pipeline"]] == [
        "market",
        "opportunity",
        "judgment",
        "behavior",
        "verification",
    ]
    assert {item["actionCode"] for item in result["behaviorRules"]} >= {
        "enter",
        "add",
        "reduce",
        "stop",
        "watch",
    }
    assert result["behaviorPlan"]["primaryAction"] == "enter"


def test_held_judgment_reduces_on_concentration_breach(store: OntologyStore):
    result = assess_cognition(store, "华辰智造")
    assert result["decision"]["code"] == "reduce"
    assert result["decision"]["consistent"] is True
    reasons = " ".join(result["decision"]["reasons"])
    assert "12.0%" in reasons
    assert "10.0%" in reasons
    assert result["behaviorPlan"]["primaryAction"] == "reduce"
    assert result["position"]["weight"] == 0.12
    # The declining opportunity is a warning, not a hard buy-side veto.
    opportunity_stage = next(item for item in result["pipeline"] if item["stage"] == "opportunity")
    assert opportunity_stage["status"] == "warning"


def test_cognition_tool_is_exposed_and_returns_pipeline(store: OntologyStore):
    names = {item["function"]["name"] for item in TOOLS}
    assert "evaluate_cognition" in names
    result = call_tool(store, "evaluate_cognition", {"company": "华辰智造", "scenario": "held"})
    assert result["ok"] is True
    data = result["data"]
    assert data["decision"]["code"] == "reduce"
    assert data["summary"]
    assert data["judgmentModel"].startswith("opportunity_structure")
    assert data["scoring"] == "no_weighted_sum"
    assert len(data["queryPath"]) == 5


def test_cognition_tool_rejects_unknown_company(store: OntologyStore):
    result = call_tool(store, "evaluate_cognition", {"company": "不存在的公司"})
    assert result["ok"] is False
    assert result["error"]["code"] == "company_not_found"


def test_invalid_scenario_is_rejected(store: OntologyStore):
    with pytest.raises(CognitionError):
        build_cognition_context(store, "游资科技", scenario="short")


def test_cognition_intent_routes_to_five_engine_pipeline(client_factory):
    response = client_factory().post(
        "/api/agent/analyze",
        json={"question": "按市场认知→机会识别→交易判断→行为管理→结果验证的体系分析游资科技"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "evaluate_cognition"
    answer = data["answer"]
    assert "五引擎交易认知" in answer
    for marker in ("市场认知", "机会识别", "交易判断", "行为管理", "结果验证"):
        assert marker in answer
    assert "与 1.9 的差异" in answer


def test_holding_question_uses_held_flow(client_factory):
    response = client_factory().post(
        "/api/agent/analyze",
        json={"question": "华辰智造还值得继续持有吗？"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "evaluate_cognition"
    answer = data["answer"]
    assert "已持仓" in answer
    assert "减仓" in answer
    assert "判断版本变化" in answer


def test_cognition_rules_are_registered(store: OntologyStore):
    rules = {item["ruleId"]: item for item in store.rules()}
    for rule_id in ("R162", "R163", "R164", "R165", "R166", "R167", "R168", "R169"):
        assert rule_id in rules
        assert rules[rule_id]["status"] == "active"


def _youyan_snapshot():
    from dataclasses import replace

    from server.marketdata import SecurityRef
    from tests.test_real_data import _snapshot

    base = _snapshot()
    return replace(
        base,
        security=SecurityRef(
            code="600206",
            name="有研新材",
            secid="1.600206",
            exchange_code="SSE",
            exchange_label="上海证券交易所",
            segment_code="main",
            segment_label="主板",
        ),
        quote={
            "code": "600206",
            "name": "有研新材",
            "lastPrice": 34.9,
            "changePct": 9.99,
            "volume": 77_432_400,
            "turnoverRate": 9.15,
            "marketCap": 29_544_711_287,
            "asOf": "2026-11-04",
            "source": base.source_label,
            "quality": "public-api",
        },
        valuation={
            "peTtm": 104.5,
            "pb": 6.6,
            "asOf": "2026-11-04",
            "source": base.source_label,
            "quality": "public-api",
        },
        financials={
            "period": "2025",
            "fiscalYearEnd": "2025-12-31",
            "revenue": 9_542_126_754,
            "netProfit": 264_789_582,
            "roe": 6.5,
            "roa": 3.46,
            "debtRatio": 34.86,
            "interestCoverage": -1.99,
            "operatingCashFlow": -78_811_720,
            "revenueGrowth": 4.33,
            "profitGrowth": 79.29,
            "eps": 0.313,
            "asOf": "2025-12-31",
            "source": base.source_label,
            "quality": "public-api",
        },
        industry="半导体",
        short_term={
            "ma5": 33.18,
            "ma20": 38.97,
            "ma60": 46.4,
            "limitUpDays": 1,
            "brokenBoardCount": 0,
            "asOf": "2026-11-04",
            "source": base.source_label,
        },
    )


def test_real_company_cognition_fallback_marks_missing_dimensions():
    from tests.test_real_data import FakeProvider

    store = OntologyStore(ROOT, market_data=FakeProvider(_youyan_snapshot()))
    result = call_tool(store, "evaluate_cognition", {"company": "有研新材"})
    assert result["ok"] is True
    data = result["data"]
    assert data["dataMode"] == "real"
    assert data["scenario"] == "non_position"
    assert data["decision"]["code"] == "watch"
    assert data["market"] is None
    assert data["stock"]["trendDirection"] == "下降"
    assert data["stock"]["trendStage"] == "启动"
    assert data["stock"]["structure"] == "跌破 MA20 后单日反弹"
    assert data["opportunity"]["counterEvidenceReviewed"] is True
    assert data["opportunity"]["counterEvidenceCount"] >= 3
    assert data["riskReward"]["expectedRewardRiskRatio"] is None
    assert "历史判断记录" in " ".join(data["missingDimensions"])
    assert "真实数据模式" in data["dataNote"]


def test_real_company_test_phrase_routes_to_cognition():
    import asyncio

    from server.agent import AgentService
    from server.settings import Settings
    from tests.test_real_data import FakeProvider

    store = OntologyStore(ROOT, market_data=FakeProvider(_youyan_snapshot()))
    settings = Settings(
        root=ROOT,
        llm_api_key="",
        rate_limit_per_minute=100,
        rate_limit_per_hour=100,
        daily_request_budget=100,
        max_request_bytes=24_000,
        market_data_enabled=True,
    )
    result = asyncio.run(AgentService(store, settings, llm=None).analyze("用有研新材给我做一个测试"))
    assert result.steps[0]["tool"] == "evaluate_cognition"
    assert "有研新材" in result.answer
    assert "观望" in result.answer
    assert "真实公开行情" in result.answer
