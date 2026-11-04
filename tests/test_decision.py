"""Decision-lifecycle context, trade checks and routing tests."""

from __future__ import annotations

from pathlib import Path

from server.decision import build_trade_context, evaluate_trade
from server.ontology import OntologyStore
from server.tools import TOOLS, call_tool

ROOT = Path(__file__).resolve().parents[1]


def test_trade_context_loads_account_budget_plan_and_review(store: OntologyStore):
    context = build_trade_context(store, "华辰智造")
    assert context["account"]["code"] == "ACC-2026-001"
    assert context["account"]["state"]["buyingPower"] == 850000
    assert context["riskBudget"]["utilization"] == 77.5
    assert context["riskBudget"]["maxSingleNameWeight"] == 0.10
    assert context["position"]["state"]["availableQuantity"] == 90000
    assert context["position"]["state"]["lastPrice"] == 36.80
    plan_ids = {item["planId"] for item in context["plans"]}
    assert {"TP-2026-HC-ADD", "TP-2026-HC-REDUCE", "TP-2026-HC-BRACKET"} <= plan_ids
    assert context["review"]["verdict"] == "PROCESS_IMPROVE"
    assert context["review"]["findings"][0]["occurrenceCount"] == 2
    assert context["review"]["revisions"][0]["id"] == "RR-2026-001"
    assert context["cycle"]["id"] == "DC-2026-HC-001"


def test_buy_is_blocked_by_weight_and_hard_limit(store: OntologyStore):
    result = evaluate_trade(store, "华辰智造", side="buy")
    assert result["buy"]["allowed"] is False
    checks = {item["id"]: item for item in result["checks"]}
    assert checks["R06"]["status"] == "fail"
    assert checks["R154"]["status"] == "fail"
    assert checks["R161"]["status"] == "fail"
    assert checks["R153"]["status"] == "pass"
    assert checks["R155"]["status"] == "pass"
    assert checks["R152"]["status"] == "pass"
    reasons = " ".join(result["buy"]["reasons"])
    assert "预计权重" in reasons
    assert "单票上限" in reasons


def test_sell_reduction_is_not_blocked_by_concentration(store: OntologyStore):
    result = evaluate_trade(store, "华辰智造", side="sell")
    checks = {item["id"]: item for item in result["checks"]}
    assert checks["R06"]["side"] == "buy"
    assert not any("当前权重" in reason for reason in result["sell"]["reasons"])
    assert checks["T1_AVAILABLE"]["status"] == "pass"
    assert checks["R07"]["status"] == "pass"
    # The demo approval is still pending, so the sell order cannot execute yet.
    assert checks["APPROVAL"]["status"] == "fail"
    assert result["sell"]["allowed"] is False
    assert "审批" in " ".join(result["sell"]["reasons"])


def test_trade_tool_is_exposed_and_returns_limits(store: OntologyStore):
    names = {item["function"]["name"] for item in TOOLS}
    assert "evaluate_trade" in names
    result = call_tool(store, "evaluate_trade", {"company": "华辰智造", "side": "both"})
    assert result["ok"] is True
    data = result["data"]
    assert data["limits"]["buy"]
    assert data["limits"]["sell"]
    assert data["outcome"]["status"] == "PROFIT"
    assert data["execution"]["quality"]["slippageBps"] == 12


def test_trade_intent_routes_to_evaluate_trade(client_factory):
    response = client_factory().post(
        "/api/agent/analyze",
        json={"question": "华辰智造的买点、卖点和仓位限制是什么？"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "evaluate_trade"
    assert "买卖决策检查" in data["answer"]
    assert "风险预算" in data["answer"]
    assert "R154" in data["answer"]
    assert "复盘" in data["answer"]


def test_portfolio_risk_budget_question_uses_portfolio_scope(client_factory):
    response = client_factory().post(
        "/api/agent/analyze",
        json={"question": "组合的风险预算还剩多少？"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "evaluate_trade"
    assert "组合风险预算与交易检查" in data["answer"]
    assert "77.5%" in data["answer"]


def test_lifecycle_rules_are_registered(store: OntologyStore):
    rules = {item["ruleId"]: item for item in store.rules()}
    for rule_id in ("R152", "R153", "R154", "R155", "R156", "R157", "R158", "R159", "R160", "R161"):
        assert rule_id in rules
        assert rules[rule_id]["status"] == "active"
