"""Agent-generated SPARQL and ontology schema tests."""

from __future__ import annotations

import pytest

from server.ontology import OntologyStore
from server.sparql import (
    MAX_ROW_LIMIT,
    SparqlError,
    describe_ontology,
    run_sparql,
    validate_query,
)
from server.tools import TOOLS, call_tool

COMPANIES_QUERY = """
SELECT ?company ?label ?roe WHERE {
  ?company a ash:ListedCompany ; rdfs:label ?label .
  FILTER(LANG(?label) = "zh")
  OPTIONAL { ?company ash:hasFinancialReport ?report . ?report ash:roe ?roe }
}
ORDER BY DESC(?roe)
LIMIT 10
"""


def test_sparql_select_returns_bindings_paths_and_citations(store: OntologyStore):
    result = run_sparql(store, COMPANIES_QUERY)
    assert result["form"] == "SELECT"
    assert result["rowCount"] >= 4
    assert result["variables"] == ["company", "label", "roe"]
    assert result["rows"][0]["company"]["qname"] == "ashd:company-huachen"
    assert result["rows"][0]["label"] == "华辰智造"
    assert isinstance(result["rows"][0]["roe"], float)
    assert result["truncated"] is False
    assert [step["kind"] for step in result["queryPath"]] == ["select", "scan", "result"]
    assert "ash:ListedCompany" in result["queryPath"][0]["detail"]
    assert any(item["kind"] == "individual" for item in result["citations"])


def test_sparql_ask_returns_boolean(store: OntologyStore):
    result = run_sparql(store, "ASK { ?company a ash:ListedCompany }")
    assert result["form"] == "ASK"
    assert result["boolean"] is True
    assert [step["kind"] for step in result["queryPath"]] == ["select", "verify", "result"]
    assert run_sparql(store, "ASK { ?company a ash:NoSuchClass }")["boolean"] is False


def test_sparql_caps_rows_and_marks_truncation(store: OntologyStore):
    result = run_sparql(
        store,
        "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 100",
        limit=3,
    )
    assert result["rowCount"] == 3
    assert result["truncated"] is True
    assert result["limit"] == 3
    assert any("截断" in step["detail"] for step in result["queryPath"])


def test_sparql_rejects_non_select_forms(store: OntologyStore):
    for query in (
        "INSERT DATA { <urn:x> <urn:p> <urn:o> }",
        "DELETE WHERE { ?s ?p ?o }",
        "LOAD <https://example.com/data.ttl>",
        "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "DESCRIBE <urn:x>",
        "CLEAR ALL",
    ):
        with pytest.raises(SparqlError) as captured:
            validate_query(query)
        assert captured.value.code == "read_only_required"


def test_sparql_rejects_remote_access_and_updates_inside_select(store: OntologyStore):
    for query in (
        "SELECT * WHERE { SERVICE <https://example.com/sparql> { ?s ?p ?o } }",
        "SELECT * FROM <https://example.com/data.ttl> WHERE { ?s ?p ?o }",
    ):
        with pytest.raises(SparqlError) as captured:
            validate_query(query)
        assert captured.value.code == "forbidden_operation"


def test_sparql_keyword_check_ignores_literals_and_prefixed_names(store: OntologyStore):
    validate_query(
        'PREFIX ex: <http://example.org/service#> '
        'SELECT ?from WHERE { ?from ex:from "DELETE FROM SERVICE" } LIMIT 1'
    )
    validate_query(
        'PREFIX : <http://example.org/> SELECT ?s WHERE { ?s :p ?o } LIMIT 1'
    )
    validate_query(
        'PREFIX _x: <http://example.org/> SELECT ?s WHERE { ?s _x:p ?o } LIMIT 1'
    )


def test_sparql_update_does_not_change_the_graph(store: OntologyStore):
    before = len(store.graph)
    with pytest.raises(SparqlError):
        run_sparql(store, "INSERT DATA { <urn:x> <urn:p> <urn:o> }")
    assert len(store.graph) == before


def test_sparql_invalid_syntax_is_a_safe_error(store: OntologyStore):
    with pytest.raises(SparqlError) as captured:
        run_sparql(store, "SELECT ?company WHERE { ?company a")
    error = captured.value
    assert error.code == "invalid_sparql"
    assert "SPARQL" in error.message
    assert "prefixes" in error.extra
    assert "describe_ontology" in error.extra["hint"]


def test_sparql_empty_and_oversized_queries_are_rejected(store: OntologyStore):
    with pytest.raises(SparqlError) as empty:
        run_sparql(store, "   ")
    assert empty.value.code == "empty_query"
    with pytest.raises(SparqlError) as oversized:
        run_sparql(store, "SELECT * WHERE { ?s ?p ?o } # " + "x" * 5_000)
    assert oversized.value.code == "query_too_long"


def test_sparql_limit_is_bounded(store: OntologyStore):
    result = run_sparql(store, "SELECT ?c WHERE { ?c a ash:ListedCompany }", limit=10_000)
    assert result["limit"] == MAX_ROW_LIMIT


def test_sparql_tool_wraps_errors_and_results(store: OntologyStore):
    ok = call_tool(
        store,
        "sparql_query",
        {"query": "SELECT ?c WHERE { ?c a ash:ListedCompany } LIMIT 5"},
    )
    assert ok["ok"] is True
    assert ok["queryPath"]
    error = call_tool(store, "sparql_query", {"query": "DELETE WHERE { ?s ?p ?o }"})
    assert error["ok"] is False
    assert error["error"]["code"] == "read_only_required"


def test_schema_tool_exposes_core_vocabulary_and_prefixes(store: OntologyStore):
    result = describe_ontology(store)
    assert result["prefixes"]["ash"].endswith("ontology/a-share#")
    assert result["counts"]["classes"] == 194
    assert result["counts"]["rules"] == 21
    assert result["entries"]
    assert len(result["starterQueries"]) >= 3
    assert "SELECT" in result["starterQueries"][0]["sparql"]
    assert "ash:ListedCompany" in result["starterQueries"][0]["sparql"]
    assert result["prefixBlock"].startswith("PREFIX ash:")
    assert result["queryPath"]


def test_schema_tool_focus_filters_properties(store: OntologyStore):
    result = describe_ontology(store, focus="roe")
    names = {entry["qname"] for entry in result["entries"]}
    assert "ash:roe" in names
    assert result["matchedCount"] >= 1
    classes = describe_ontology(store, kind="class", focus="Decision")
    assert classes["entries"]
    assert all(entry["kind"] == "class" for entry in classes["entries"])
    with pytest.raises(SparqlError):
        describe_ontology(store, kind="individual")


def test_schema_tool_is_registered(store: OntologyStore):
    result = call_tool(store, "describe_ontology", {"focus": "决策"})
    assert result["ok"] is True
    assert result["queryPath"]


def test_tool_catalog_exposes_free_query():
    names = {item["function"]["name"] for item in TOOLS}
    assert {"describe_ontology", "sparql_query"} <= names
