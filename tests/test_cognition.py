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
