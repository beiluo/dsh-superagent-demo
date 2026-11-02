"""Rule parity and ontology-grounded evaluation tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef

from server.namespaces import ASH, ONTOLOGY_MODULES
from server.rules import RULE_THRESHOLDS, evaluate_company

ROOT = Path(__file__).resolve().parents[1]


def _reachable_literals(graph: Graph, head) -> list[Literal]:
    literals: list[Literal] = []
    seen = set()
    stack = [head]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if isinstance(node, Literal):
            literals.append(node)
            continue
        if isinstance(node, BNode):
            for _, value in graph.predicate_objects(node):
                stack.append(value)
    return literals


def _rules_by_id() -> tuple[Graph, dict[str, URIRef]]:
    graph = Graph()
    for module in ONTOLOGY_MODULES:
        graph.parse(ROOT / "ontology" / module, format="turtle")
    from rdflib.namespace import RDF

    rules: dict[str, URIRef] = {}
    for subject in graph.subjects(RDF.type, ASH.RuleArtifact):
        rule_id = graph.value(subject, ASH.ruleId)
        if rule_id:
            rules[str(rule_id)] = subject
    return graph, rules


def test_thresholds_match_swrl_literals():
    graph, rules = _rules_by_id()
    SWRL = Namespace("http://www.w3.org/2003/11/swrl#")

    for rule_id, thresholds in RULE_THRESHOLDS.items():
        body = graph.value(rules[rule_id], SWRL.body)
        assert body is not None, rule_id
        literals = set()
        for literal in _reachable_literals(graph, body):
            value = literal.toPython()
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float, Decimal)):
                literals.add(Decimal(str(value)))
        for value in thresholds.values():
            assert Decimal(str(value)) in literals, (rule_id, value, literals)


def test_company_signals(store):
    huachen = store.find_company("华辰智造")
    signals = {item["ruleId"]: item for item in evaluate_company(store.company_knowledge(huachen).to_dict())}
    assert signals["R01"]["status"] == "triggered"
    assert signals["R02"]["status"] == "clear"
    assert signals["R06"]["status"] == "triggered"
    assert signals["R08"]["status"] == "triggered"
    assert signals["R11"]["status"] == "clear"


def test_st_company_signals(store):
    st = store.find_company("示例 ST 公司")
    signals = {item["ruleId"]: item for item in evaluate_company(store.company_knowledge(st).to_dict())}
    assert signals["R02"]["status"] == "triggered"
    assert signals["R03"]["status"] == "triggered"
    assert signals["R04"]["status"] == "triggered"
    assert signals["R01"]["status"] == "unknown"


def test_portfolio_signals(store):
    portfolio = store.portfolio()
    assert portfolio["portfolio"]["label"] == "示例质量价值组合"
    assert portfolio["signals"]["R06"]["status"] == "triggered"
    assert portfolio["signals"]["R05"]["status"] == "clear"
    huachen = next(item for item in portfolio["positions"] if item["company"]["label"] == "华辰智造")
    assert huachen["weight"] == 0.12


def test_company_aliases(store):
    assert store.find_company("华辰智造") == store.find_company("600000")
    assert store.find_company("宁源") == store.find_company("300000")
    assert store.find_company("景康生物") == store.find_company("688000")
    assert store.find_company("贵州茅台") is None


def test_rule_catalog_and_policies(store):
    rules = store.rules()
    assert len(rules) >= 15
    assert {f"R{i:02d}" for i in range(1, 12)} <= {item["ruleId"] for item in rules}
    policies = store.policies()
    assert len(policies) >= 4
    assert {
        "policy-research-data",
        "policy-decision-use",
        "policy-trade-guard",
    } <= {item["uid"] for item in policies}
    for policy in policies:
        assert policy["permissions"]
        assert policy["prohibitions"]


def test_search_returns_class_and_rule(store):
    matches = store.search("价值候选")
    kinds = {item["kind"] for item in matches}
    assert "class" in kinds
    assert "rule" in kinds
