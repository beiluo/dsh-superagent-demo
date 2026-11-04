"""Question-driven ontology query, evidence, constraint and scenario tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.marketdata import RealCompanySnapshot, SecurityRef, SOURCE_LABEL, SOURCE_URL
from server.ontology import OntologyStore
from server.query import (
    compare_companies,
    QueryError,
    check_constraints,
    parse_constraint_question,
    parse_evidence_question,
    parse_question_filters,
    parse_scenario_question,
    run_query,
    simulate_scenario,
    trace_evidence,
)
from server.tools import TOOLS, call_tool
from tests.conftest import FAKE_KEY, FakeLLM, final_response, tool_response

ROOT = Path(__file__).resolve().parents[1]


class FakeMarketProvider:
    source_label = SOURCE_LABEL
    source_url = SOURCE_URL

    def __init__(self, rows=None):
        self.rows = rows or [
            ("600036", "招商银行", 6.0, 1.0, "银行"),
            ("000001", "平安银行", 5.0, 0.8, "银行"),
            ("600519", "贵州茅台", 25.0, 8.0, "白酒"),
        ]

    def fetch(self, query: str):
        return None

    def screen(self, *, limit: int = 120, sort: str = "marketCap"):
        snapshots = []
        for code, name, pe, pb, industry in self.rows[:limit]:
            exchange_code, exchange_label = (
                ("SSE", "上海证券交易所")
                if code.startswith("6")
                else ("SZSE", "深圳证券交易所")
            )
            security = SecurityRef(
                code=code,
                name=name,
                secid=("1." if code.startswith("6") else "0.") + code,
                exchange_code=exchange_code,
                exchange_label=exchange_label,
                segment_code="main",
                segment_label="主板",
            )
            snapshots.append(
                RealCompanySnapshot(
                    security=security,
                    quote={
                        "lastPrice": 10.0,
                        "changePct": 1.0,
                        "turnoverRate": 0.5,
                        "marketCap": 100_000_000_000,
                        "asOf": "2026-11-03",
                        "source": SOURCE_LABEL,
                        "quality": "public-api",
                    },
                    valuation={
                        "peTtm": pe,
                        "pb": pb,
                        "asOf": "2026-11-03",
                        "source": SOURCE_LABEL,
                        "quality": "public-api",
                    },
                    financials=None,
                    industry=industry,
                    fetched_at=datetime.now(timezone.utc),
                )
            )
        return snapshots


def test_query_translates_filters_to_rdf_paths(store: OntologyStore):
    result = run_query(
        store,
        {
            "filters": [
                {"field": "roe", "op": "gt", "value": 15},
                {"field": "peTtm", "op": "lt", "value": 20},
            ]
        },
    )
    assert [item["company"]["label"] for item in result["matches"]] == ["华辰智造"]
    match = result["matches"][0]
    assert match["company"]["code"] == "600000"
    assert "R01" in match["matchedRules"]
    paths = {edge["predicate"] for fact in match["facts"] for edge in fact["path"]}
    assert "hasFinancialReport" in paths
    assert "roe" in paths
    assert "hasValuation" in paths
    assert "peTtm" in paths
    assert [step["kind"] for step in result["queryPath"]][0] == "select"
    assert result["evaluatedCount"] >= 5


def test_query_industry_uses_industry_scheme(store: OntologyStore):
    result = run_query(store, {"industry": "新能源"})
    assert [item["company"]["label"] for item in result["matches"]] == ["宁源新能源"]
    # "价值" is an investment style, not an industry; it must not turn a rule
    # screening question into an industry filter.
    spec = parse_question_filters(store, "哪些公司是价值候选？")
    assert spec["industry"] is None
    assert spec["rules_any"] == ["R01"]


def test_query_rule_filter_and_sort(store: OntologyStore):
    result = run_query(store, {"rules_any": ["R10"], "sort": "-roe"})
    assert [item["company"]["label"] for item in result["matches"]] == ["游资科技"]
    assert result["matches"][0]["metrics"]["roe"] == 14.8

    excluded = run_query(store, {"rules_exclude": ["R01"]})
    assert excluded["matches"]
    assert all("R01" not in item["matchedRules"] for item in excluded["matches"])


def test_question_parser_builds_query_spec(store: OntologyStore):
    spec = parse_question_filters(store, "PE 低于 20 且 ROE 高于 15 的公司")
    assert {item["field"] for item in spec["filters"]} == {"roe", "peTtm"}
    assert spec["universe"] == "ontology"

    real = parse_question_filters(store, "全市场 PE 低于 15 的银行股")
    assert real["universe"] == "real"
    assert real["industry"] == "银行"

    market_cap = parse_question_filters(store, "市值小于 50 亿的公司")
    assert market_cap["filters"][0]["value"] == 5_000_000_000


def test_real_screening_maps_sample_into_runtime_graph():
    store = OntologyStore(ROOT, market_data=FakeMarketProvider())
    result = run_query(
        store,
        {
            "universe": "real",
            "filters": [{"field": "peTtm", "op": "lt", "value": 10}],
            "industry": "银行",
        },
    )
    assert result["universe"] == "real"
    assert result["totalMatches"] == 2
    assert {item["company"]["label"] for item in result["matches"]} == {"招商银行", "平安银行"}
    assert all(item["company"]["dataMode"] == "real" for item in result["matches"])
    assert any(step["kind"] == "scan" for step in result["queryPath"])
    assert "非全市场" in result["dataNote"] or "单页" in result["dataNote"]


def test_real_screening_rejects_annual_report_filters():
    store = OntologyStore(ROOT, market_data=FakeMarketProvider())
    with pytest.raises(QueryError) as captured:
        run_query(
            store,
            {
                "universe": "real",
                "filters": [{"field": "roe", "op": "gt", "value": 15}],
            },
        )
    assert captured.value.code == "unsupported_filter"
    assert "年报" in captured.value.message


def test_evidence_chain_reaches_decision_and_sources(store: OntologyStore):
    result = trace_evidence(store, "华辰智造")
    assert result["subject"]["label"] == "华辰智造"
    predicates = {edge["predicate"] for edge in result["edges"]}
    assert "aboutCompany" in predicates
    assert "basedOn" in predicates
    assert "governedBy" in predicates
    assert "hasSource" in predicates
    assert any("决策" in node["label"] for node in result["nodes"])
    assert any("Evidence" in node["types"] for node in result["nodes"])
    decision_edge = next(edge for edge in result["edges"] if edge["predicate"] == "aboutCompany")
    assert "决策" in decision_edge["from"]["label"]
    assert decision_edge["to"]["label"] == "华辰智造"
    assert result["queryPath"]
    assert result["citations"]


def test_evidence_chain_accepts_rule_and_rejects_unknown(store: OntologyStore):
    result = trace_evidence(store, "R01", depth=1)
    assert result["subject"]["label"] == "价值候选筛选"
    with pytest.raises(QueryError):
        trace_evidence(store, "不存在的实体")


def test_constraint_gate_checks_weight_and_odrl(store: OntologyStore):
    blocked = check_constraints(store, company="华辰智造", weight=0.15, action="buy")
    assert blocked["allowed"] is False
    assert blocked["summary"] == "阻断"
    checks = {item["id"]: item for item in blocked["checks"]}
    assert checks["R06"]["status"] == "fail"
    assert checks["ODRL:policy-trade-guard:humanApproval"]["status"] == "unknown"
    assert any(item["id"] == "R06" for item in blocked["blocking"])

    allowed = check_constraints(
        store,
        company="华辰智造",
        weight=0.08,
        action="buy",
        human_approval=True,
        compliance_passed=True,
    )
    assert allowed["allowed"] is True
    checks = {item["id"]: item for item in allowed["checks"]}
    assert checks["R06"]["status"] == "pass"
    assert checks["ODRL:policy-trade-guard:humanApproval"]["status"] == "pass"
    assert checks["ODRL:policy-trade-guard:compliancePassed"]["status"] == "pass"


def test_constraint_gate_blocks_restricted_security(store: OntologyStore):
    result = check_constraints(
        store,
        company="示例 ST 公司",
        weight=0.05,
        action="buy",
        human_approval=True,
        compliance_passed=True,
    )
    checks = {item["id"]: item for item in result["checks"]}
    assert checks["R07"]["status"] == "fail"
    assert result["allowed"] is False


def test_constraint_question_parsing(store: OntologyStore):
    parsed = parse_constraint_question(store, "如果加仓华辰智造到 15%，组合约束允许吗？")
    assert parsed["company"] == "华辰智造"
    assert parsed["weight"] == pytest.approx(0.15)
    assert parsed["action"] == "buy"

    proposed = parse_constraint_question(store, "华辰智造仓位 15% 是否符合约束")
    assert proposed["weight"] == pytest.approx(0.15)
    assert proposed["action"] == "buy"


def test_hold_action_does_not_require_order_gate(store: OntologyStore):
    result = check_constraints(store, company="华辰智造", weight=0.08, action="hold")
    checks = {item["id"]: item for item in result["checks"]}
    assert checks["ODRL:policy-trade-guard"]["status"] == "pass"
    assert result["allowed"] is True


def test_simulate_scenario_changes_rule_status(store: OntologyStore):
    result = simulate_scenario(
        store,
        company="华辰智造",
        changes=[{"field": "roe", "delta": -5}],
    )
    assert result["company"]["label"] == "华辰智造"
    assert "ROE" in result["scenario"]
    changed = {item["ruleId"]: item for item in result["changed"]}
    assert changed["R01"]["before"] == "triggered"
    assert changed["R01"]["after"] == "clear"
    assert result["queryPath"]
    # The mutation is confined to the copy.
    assert store.company_knowledge(store.find_company("华辰智造")).financials["roe"] == 18.2


def test_scenario_question_parsing(store: OntologyStore):
    parsed = parse_scenario_question(store, "如果华辰智造 ROE 下降 5 个百分点会怎样？")
    assert parsed["company"] == "华辰智造"
    assert parsed["changes"] == [{"field": "roe", "delta": -5.0}]


def test_evidence_question_parsing(store: OntologyStore):
    parsed = parse_evidence_question(store, "华辰智造触发 R01 的证据链")
    assert parsed["subject"] == "华辰智造"
    assert parsed["rule_id"] == "R01"


def test_query_tool_returns_query_path(store: OntologyStore):
    result = call_tool(
        store,
        "query_ontology",
        {"filters": [{"field": "peTtm", "op": "lt", "value": 20}]},
    )
    assert result["ok"] is True
    assert result["queryPath"]
    assert result["citations"]


def test_tool_catalog_exposes_ontology_scenarios():
    names = {item["function"]["name"] for item in TOOLS}
    assert {
        "query_ontology",
        "trace_evidence",
        "check_constraints",
        "simulate_scenario",
    } <= names


def test_rules_mode_routes_question_to_its_query_path(client_factory):
    client = client_factory()
    response = client.post(
        "/api/agent/analyze",
        json={"question": "PE 低于 20 且 ROE 高于 15 的公司"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "query_ontology"
    assert data["queryPath"]
    assert data["queryPath"][0]["tool"] == "query_ontology"
    assert "华辰智造" in data["answer"]
    assert "本体查询" in data["answer"]


def test_rules_mode_evidence_constraint_and_scenario(client_factory):
    client = client_factory()

    evidence = client.post(
        "/api/agent/analyze", json={"question": "华辰智造的决策证据链"}
    ).json()
    assert evidence["steps"][0]["tool"] == "trace_evidence"
    assert "证据链" in evidence["answer"]

    constraint = client.post(
        "/api/agent/analyze",
        json={"question": "如果加仓华辰智造到 15%，组合约束允许吗？"},
    ).json()
    assert constraint["steps"][0]["tool"] == "check_constraints"
    assert "R06" in constraint["answer"]
    assert "未通过" in constraint["answer"]

    scenario = client.post(
        "/api/agent/analyze",
        json={"question": "如果华辰智造 ROE 下降 5 个百分点会怎样？"},
    ).json()
    assert scenario["steps"][0]["tool"] == "simulate_scenario"
    assert "R01" in scenario["answer"]


def test_real_screen_without_market_data_is_a_safe_error(client_factory):
    response = client_factory().post(
        "/api/agent/analyze",
        json={"question": "全市场 PE 低于 15 的银行股"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "query_ontology"
    assert data["steps"][0]["status"] == "error"
    assert "真实 A 股" in data["answer"] or "未启用" in data["answer"]


def test_status_reports_query_capabilities(client_factory):
    data = client_factory().get("/api/agent/status").json()
    assert data["query"]["realScreening"] is False
    assert "query_ontology" in data["query"]["tools"]
    assert "roe" in data["query"]["metrics"]


def test_llm_agent_can_chain_query_and_evidence(client_factory):
    fake = FakeLLM(
        [
            tool_response(
                "query_ontology",
                {
                    "filters": [
                        {"field": "roe", "op": "gt", "value": 15},
                        {"field": "peTtm", "op": "lt", "value": 20},
                    ]
                },
            ),
            tool_response("trace_evidence", {"subject": "华辰智造"}),
            final_response("### 结论\n华辰智造命中 R01，证据链见工具结果。"),
        ]
    )
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=fake)
    response = client.post(
        "/api/agent/analyze",
        json={"question": "找出 PE 低于 20、ROE 高于 15 的公司并给出证据链"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "llm"
    assert [item["tool"] for item in data["steps"]] == [
        "query_ontology",
        "trace_evidence",
    ]
    assert [group["tool"] for group in data["queryPath"]] == [
        "query_ontology",
        "trace_evidence",
    ]
    assert FAKE_KEY not in response.text


def test_compare_companies_uses_shared_ontology_fields(store):
    result = compare_companies(store, ["华辰智造", "游资科技"])
    assert len(result["companies"]) == 2
    labels = [item["company"]["label"] for item in result["companies"]]
    assert set(labels) == {"华辰智造", "游资科技"}
    youzi = next(item for item in result["companies"] if item["company"]["label"] == "游资科技")
    assert youzi["metrics"]["ma20"] == 17.2
    assert youzi["metrics"]["limitUpDays"] == 4
    assert {"R16", "R17", "R20", "R21"} <= {rule["ruleId"] for rule in youzi["triggeredRules"]}
    assert result["fields"]
    assert result["queryPath"]
