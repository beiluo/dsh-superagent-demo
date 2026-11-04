"""Agent-generated, read-only SPARQL over the in-memory ontology graph.

The parameterised tools in :mod:`server.tools` are convenient shortcuts, not the
boundary of what the agent may ask the ontology.  This module lets the LLM write
its own graph queries, execute them against the same rdflib graph, and receive
the variable bindings plus a query path for the UI.

Safety rules:

* only ``SELECT`` and ``ASK`` are accepted;
* SPARQL Update, ``SERVICE`` and ``FROM`` (remote loading) are rejected;
* queries are length-limited, row-limited and read-only;
* errors are returned as safe messages, never as tracebacks.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable

from rdflib import BNode, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from .namespaces import (
    ASH,
    ASHD,
    ASHREAL,
    ASHS,
    GROUNDING,
    ODRL,
    PROCESS,
    PROFILE,
    SERVICE,
)
from .ontology import OntologyStore, normalize_text

MAX_QUERY_CHARS = 4_000
DEFAULT_ROW_LIMIT = 25
MAX_ROW_LIMIT = 50
MAX_CELL_CHARS = 240
MAX_COMMENT_CHARS = 180
MAX_QUERY_PATH_CHARS = 900
DEFAULT_SCHEMA_LIMIT = 30
MAX_SCHEMA_LIMIT = 40

PREFIXES: dict[str, Namespace] = {
    "ash": ASH,
    "ashd": ASHD,
    "ashs": ASHS,
    "real": ASHREAL,
    "odrl": ODRL,
    "owl": Namespace(str(OWL)),
    "rdf": Namespace(str(RDF)),
    "rdfs": Namespace(str(RDFS)),
    "skos": Namespace(str(SKOS)),
    "xsd": Namespace(str(XSD)),
    "dcterms": Namespace(str(DCTERMS)),
    "service": SERVICE,
    "profile": PROFILE,
    "process": PROCESS,
    "grounding": GROUNDING,
}

_PREFIX_TEXT = "\n".join(f"PREFIX {name}: <{namespace}>" for name, namespace in PREFIXES.items())

ALLOWED_FORMS = frozenset({"SELECT", "ASK"})
FORBIDDEN_KEYWORDS = frozenset(
    {
        "INSERT",
        "DELETE",
        "LOAD",
        "CLEAR",
        "DROP",
        "CREATE",
        "ADD",
        "MOVE",
        "COPY",
        "WITH",
        "SERVICE",
        "FROM",
        "USING",
    }
)

_DECLARATION_RE = re.compile(
    r"(?is)\b(?:PREFIX\s+(?:[A-Za-z_][\w.-]*)?\s*:\s*<[^<>]*>|BASE\s*<[^<>]*>)"
)
_ABSOLUTE_IRI_RE = re.compile(r"<[A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*>")
_STRING_RE = re.compile(
    r'"""(?:\\.|[^"\\])*"""'
    r"|'''(?:\\.|[^'\\])*'''"
    r'|"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'",
    re.S,
)
_COMMENT_RE = re.compile(r"#[^\n]*")
_TOKEN_RE = re.compile(r"(?<![?$:])\b([A-Za-z][A-Za-z0-9_]*)\b")

_CORE_ENTRIES: tuple[tuple[str, str], ...] = (
    ("class", "ash:ListedCompany"),
    ("class", "ash:Security"),
    ("class", "ash:AShare"),
    ("class", "ash:AnnualReport"),
    ("class", "ash:FinancialReport"),
    ("class", "ash:MarketQuote"),
    ("class", "ash:Valuation"),
    ("class", "ash:InvestmentDecision"),
    ("class", "ash:RiskAssessment"),
    ("class", "ash:DecisionRationale"),
    ("class", "ash:Evidence"),
    ("class", "ash:DataSource"),
    ("class", "ash:ComplianceCheck"),
    ("class", "ash:Portfolio"),
    ("class", "ash:Position"),
    ("class", "ash:RuleArtifact"),
    ("class", "ash:MacroIndicator"),
    ("class", "skos:Concept"),
    ("class", "odrl:Policy"),
    ("objectProperty", "ash:hasSecurity"),
    ("objectProperty", "ash:hasFinancialReport"),
    ("objectProperty", "ash:hasMarketQuote"),
    ("objectProperty", "ash:hasValuation"),
    ("objectProperty", "ash:aboutCompany"),
    ("objectProperty", "ash:aboutSecurity"),
    ("objectProperty", "ash:basedOn"),
    ("objectProperty", "ash:hasRationale"),
    ("objectProperty", "ash:hasRiskAssessment"),
    ("objectProperty", "ash:hasComplianceCheck"),
    ("objectProperty", "ash:governedBy"),
    ("objectProperty", "ash:hasSource"),
    ("objectProperty", "ash:positionIn"),
    ("objectProperty", "ash:positionOf"),
    ("objectProperty", "ash:holdsPosition"),
    ("objectProperty", "ash:primaryIndustry"),
    ("objectProperty", "ash:hasThemeExposure"),
    ("objectProperty", "ash:hasRecommendation"),
    ("dataProperty", "ash:decisionId"),
    ("dataProperty", "ash:decisionDate"),
    ("dataProperty", "ash:confidence"),
    ("dataProperty", "ash:targetPrice"),
    ("dataProperty", "ash:stopLoss"),
    ("dataProperty", "ash:roe"),
    ("dataProperty", "ash:peTtm"),
    ("dataProperty", "ash:pb"),
    ("dataProperty", "ash:debtRatio"),
    ("dataProperty", "ash:revenueGrowth"),
    ("dataProperty", "ash:profitGrowth"),
    ("dataProperty", "ash:riskScore"),
    ("dataProperty", "ash:marketCap"),
    ("dataProperty", "ash:turnoverRate"),
    ("dataProperty", "ash:changePct"),
    ("dataProperty", "ash:ma20"),
    ("dataProperty", "ash:ma60"),
    ("dataProperty", "ash:limitUpDays"),
    ("dataProperty", "ash:ruleId"),
    ("dataProperty", "ash:severity"),
    ("dataProperty", "ash:ruleIf"),
    ("dataProperty", "ash:ruleThen"),
)

_STARTER_QUERIES: tuple[dict[str, str], ...] = (
    {
        "label": "公司财务与估值（按 ROE 排序）",
        "sparql": (
            "SELECT ?company ?label ?roe ?pe WHERE {\n"
            "  ?company a ash:ListedCompany ; rdfs:label ?label .\n"
            '  FILTER(LANG(?label) = "zh")\n'
            "  OPTIONAL { ?company ash:hasFinancialReport ?report . ?report ash:roe ?roe }\n"
            "  OPTIONAL {\n"
            "    ?company ash:hasSecurity ?security .\n"
            "    ?security ash:hasValuation ?valuation . ?valuation ash:peTtm ?pe\n"
            "  }\n"
            "}\n"
            "ORDER BY DESC(?roe)\n"
            "LIMIT 10"
        ),
    },
    {
        "label": "决策及其证据",
        "sparql": (
            "SELECT ?decision ?decisionId ?company ?evidence WHERE {\n"
            "  ?decision a ash:InvestmentDecision ;\n"
            "            ash:decisionId ?decisionId ;\n"
            "            ash:aboutCompany ?company ;\n"
            "            ash:basedOn ?evidence .\n"
            "}\n"
            "LIMIT 20"
        ),
    },
    {
        "label": "缺少年报的示例公司（否定条件）",
        "sparql": (
            "SELECT ?company ?label WHERE {\n"
            "  ?company a ash:ListedCompany ; rdfs:label ?label .\n"
            '  FILTER(LANG(?label) = "zh")\n'
            "  FILTER NOT EXISTS {\n"
            "    ?company ash:hasFinancialReport ?report . ?report ash:roe ?roe\n"
            "  }\n"
            "}\n"
            "LIMIT 10"
        ),
    },
    {
        "label": "规则清单与阈值说明",
        "sparql": (
            "SELECT ?rule ?ruleId ?severity ?ruleIf WHERE {\n"
            "  ?rule a ash:RuleArtifact ; ash:ruleId ?ruleId ;\n"
            "        ash:severity ?severity ; ash:ruleIf ?ruleIf .\n"
            "}\n"
            "ORDER BY ?ruleId\n"
            "LIMIT 30"
        ),
    },
)


class SparqlError(Exception):
    """A safe, user-facing graph-query error."""

    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


# ---------------------------------------------------------------------------
# Query validation
# ---------------------------------------------------------------------------


def _strip_non_code(query: str) -> str:
    """Mask declarations, comments, strings and absolute IRIs before keyword checks."""

    masked = _DECLARATION_RE.sub(" ", query)
    masked = _ABSOLUTE_IRI_RE.sub(" ", masked)
    masked = _STRING_RE.sub(" ", masked)
    masked = _COMMENT_RE.sub(" ", masked)
    return masked


def _query_form(masked: str) -> str:
    match = re.match(r"\s*([A-Za-z]+)", masked)
    return match.group(1).upper() if match else ""


def validate_query(query: Any) -> str:
    text = str(query or "")
    if not text.strip():
        raise SparqlError("empty_query", "SPARQL 查询不能为空。")
    if len(text) > MAX_QUERY_CHARS:
        raise SparqlError(
            "query_too_long",
            f"SPARQL 查询最多 {MAX_QUERY_CHARS} 个字符。",
        )

    masked = _strip_non_code(text)
    form = _query_form(masked)
    if form not in ALLOWED_FORMS:
        raise SparqlError(
            "read_only_required",
            "只接受 SELECT 或 ASK 查询；SPARQL Update、LOAD、CONSTRUCT/DESCRIBE 等都不允许。",
            allowedForms=["SELECT", "ASK"],
        )

    for token in _TOKEN_RE.findall(masked):
        keyword = token.upper()
        if keyword in FORBIDDEN_KEYWORDS:
            raise SparqlError(
                "forbidden_operation",
                f"查询包含不允许的关键字 {keyword}：只读查询不能更新图谱或访问远程端点。",
                keyword=keyword,
            )
    return text


# ---------------------------------------------------------------------------
# Result conversion
# ---------------------------------------------------------------------------


def _qname(iri: str) -> str | None:
    best: tuple[int, str] | None = None
    for name, namespace in PREFIXES.items():
        value = str(namespace)
        if iri.startswith(value):
            candidate = f"{name}:{iri[len(value):]}"
            if best is None or len(value) > best[0]:
                best = (len(value), candidate)
    return best[1] if best else None


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _literal_value(term: Literal) -> Any:
    try:
        value = term.toPython()
    except Exception:  # noqa: BLE001 - malformed literals must not break the tool
        return _truncate(str(term), MAX_CELL_CHARS)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return _truncate(str(value), MAX_CELL_CHARS)


def _cell(store: OntologyStore, term: Any) -> Any:
    if term is None:
        return None
    if isinstance(term, URIRef):
        cell: dict[str, Any] = {"iri": str(term), "label": store._label(term)}
        qname = _qname(str(term))
        if qname:
            cell["qname"] = qname
        return cell
    if isinstance(term, BNode):
        return {"bnode": str(term)}
    if isinstance(term, Literal):
        return _literal_value(term)
    return _truncate(str(term), MAX_CELL_CHARS)


def _step(kind: str, label: str, detail: str, iris: Iterable[str] | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "detail": detail,
        "iris": [str(item) for item in (iris or []) if item],
    }


def _query_path(query: str, form: str, variables: list[str], rows: int, truncated: bool, limit: int) -> list[dict[str, Any]]:
    compact = " ".join(query.split())
    steps = [
        _step(
            "select",
            "执行 Agent 生成的只读 SPARQL",
            _truncate(compact, MAX_QUERY_PATH_CHARS),
        )
    ]
    if form == "ASK":
        steps.append(_step("verify", "检查图模式是否成立", "ASK 查询只返回布尔结果"))
        steps.append(
            _step(
                "result",
                "返回布尔结果",
                "图模式成立" if rows else "图模式不成立",
            )
        )
        return steps
    if variables:
        steps.append(
            _step("scan", "扫描图模式并绑定变量", "变量: " + "、".join(variables))
        )
    detail = f"返回 {rows} 行"
    if truncated:
        detail += f"，达到上限 {limit} 行，结果已截断"
    steps.append(_step("result", "返回查询结果", detail))
    return steps


def _citation(store: OntologyStore, term: Any, seen: set[str], citations: list[dict[str, str]]) -> None:
    if not isinstance(term, URIRef) or str(term) in seen or len(citations) >= 18:
        return
    ref = store._cite(term)
    if not ref:
        return
    seen.add(str(term))
    citations.append(ref)


def run_sparql(store: OntologyStore, query: Any, *, limit: Any = DEFAULT_ROW_LIMIT) -> dict[str, Any]:
    """Execute one agent-authored read-only query and return compact bindings."""

    text = validate_query(query)
    try:
        row_limit = int(limit)
    except (TypeError, ValueError):
        raise SparqlError("invalid_limit", "limit 必须是整数。") from None
    row_limit = max(1, min(row_limit, MAX_ROW_LIMIT))

    try:
        result = store.graph.query(text, initNs=PREFIXES)
    except Exception as exc:  # noqa: BLE001 - parser/runtime errors become safe tool errors
        message = re.sub(r"\s+", " ", str(exc)).strip()
        raise SparqlError(
            "invalid_sparql",
            f"SPARQL 解析或执行失败：{_truncate(message, 280)}",
            prefixes={name: str(namespace) for name, namespace in PREFIXES.items()},
            hint="可以先调用 describe_ontology 查看类、属性、前缀和示例查询。",
        ) from exc

    form = _query_form(_strip_non_code(text))
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    used_real = str(ASHREAL) in text

    if form == "ASK":
        answer = bool(result)
        data: dict[str, Any] = {
            "query": text,
            "form": "ASK",
            "boolean": answer,
            "dataMode": "real" if used_real else "example",
            "queryPath": _query_path(text, form, [], 1 if answer else 0, False, row_limit),
            "citations": citations,
        }
        return data

    variables = [str(item) for item in result.vars]
    rows: list[dict[str, Any]] = []
    truncated = False
    for index, row in enumerate(result):
        if index >= row_limit:
            truncated = True
            break
        item: dict[str, Any] = {}
        for variable in result.vars:
            value = row[variable]
            if isinstance(value, URIRef):
                if str(value).startswith(str(ASHREAL)):
                    used_real = True
                _citation(store, value, seen, citations)
            item[str(variable)] = _cell(store, value)
        rows.append(item)

    if any(item.get("kind") == "real" for item in citations):
        used_real = True

    data = {
        "query": text,
        "form": "SELECT",
        "variables": variables,
        "rows": rows,
        "rowCount": len(rows),
        "returned": len(rows),
        "limit": row_limit,
        "truncated": truncated,
        "dataMode": "real" if used_real else "example",
        "dataNote": (
            "查询在本体内存图上以只读方式执行；结果中的 real: 实体来自公开行情接口。"
            if used_real
            else "查询在本体示例图上以只读方式执行；结果为合成示例。"
        ),
        "queryPath": _query_path(text, form, variables, len(rows), truncated, row_limit),
        "citations": citations,
    }
    return data


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------


def _kind_order(kind: str) -> int:
    return {"class": 0, "objectProperty": 1, "dataProperty": 2}.get(kind, 3)


def _entry(
    store: OntologyStore,
    subject: URIRef,
    kind: str,
    *,
    domain: Any = None,
    range_: Any = None,
) -> dict[str, Any]:
    comment = store._comment(subject)
    entry: dict[str, Any] = {
        "qname": _qname(str(subject)) or str(subject),
        "iri": str(subject),
        "kind": kind,
        "label": store._label(subject),
    }
    if comment:
        entry["comment"] = _truncate(comment, MAX_COMMENT_CHARS)
    if domain is not None:
        entry["domain"] = _qname(str(domain)) or str(domain)
        entry["domainLabel"] = store._label(domain)
    if range_ is not None:
        entry["range"] = _qname(str(range_)) or str(range_)
        entry["rangeLabel"] = store._label(range_)
    return entry


def _entry_haystack(store: OntologyStore, entry: dict[str, Any]) -> str:
    return normalize_text(
        " ".join(
            str(entry.get(key) or "")
            for key in ("qname", "label", "comment", "domain", "domainLabel", "range", "rangeLabel")
        )
    )


def _schema_candidates(store: OntologyStore) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for subject in store.graph.subjects(RDF.type, OWL.Class):
        if isinstance(subject, URIRef):
            candidates.setdefault(
                str(subject),
                _entry(store, subject, "class"),
            )
    for subject in store.graph.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(subject, URIRef):
            candidates.setdefault(
                str(subject),
                _entry(
                    store,
                    subject,
                    "objectProperty",
                    domain=store._first(subject, RDFS.domain),
                    range_=store._first(subject, RDFS.range),
                ),
            )
    for subject in store.graph.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(subject, URIRef):
            candidates.setdefault(
                str(subject),
                _entry(
                    store,
                    subject,
                    "dataProperty",
                    domain=store._first(subject, RDFS.domain),
                    range_=store._first(subject, RDFS.range),
                ),
            )
    return list(candidates.values())


def _core_entries(store: OntologyStore) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for kind, qname in _CORE_ENTRIES:
        prefix, _, name = qname.partition(":")
        namespace = PREFIXES.get(prefix)
        if namespace is None:
            continue
        entry = _entry(store, namespace[name], kind)
        entries.append(entry)
    return entries


def _counts(store: OntologyStore) -> dict[str, int]:
    graph = store.graph
    return {
        "triples": len(graph),
        "classes": len(set(graph.subjects(RDF.type, OWL.Class))),
        "objectProperties": len(set(graph.subjects(RDF.type, OWL.ObjectProperty))),
        "dataProperties": len(set(graph.subjects(RDF.type, OWL.DatatypeProperty))),
        "individuals": len(set(graph.subjects(RDF.type, OWL.NamedIndividual))),
        "concepts": len(set(graph.subjects(RDF.type, SKOS.Concept))),
        "rules": len(set(graph.subjects(RDF.type, ASH.RuleArtifact))),
        "policies": len(set(graph.subjects(ODRL.uid, None))),
    }


def describe_ontology(
    store: OntologyStore,
    *,
    focus: Any = "",
    kind: Any = "all",
    limit: Any = DEFAULT_SCHEMA_LIMIT,
) -> dict[str, Any]:
    """Return a compact, filterable view of classes and properties for query writing."""

    kind_filter = str(kind or "all").strip()
    if kind_filter not in {"all", "class", "objectProperty", "dataProperty"}:
        raise SparqlError(
            "invalid_kind",
            "kind 只能是 all、class、objectProperty 或 dataProperty。",
        )
    try:
        entry_limit = int(limit)
    except (TypeError, ValueError):
        raise SparqlError("invalid_limit", "limit 必须是整数。") from None
    entry_limit = max(1, min(entry_limit, MAX_SCHEMA_LIMIT))

    text = str(focus or "").strip()
    normalized = normalize_text(text)
    candidates = _schema_candidates(store)
    if kind_filter != "all":
        candidates = [item for item in candidates if item["kind"] == kind_filter]

    if normalized:
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in candidates:
            haystack = _entry_haystack(store, item)
            label = normalize_text(item.get("label"))
            qname = normalize_text(item.get("qname"))
            if normalized == label or normalized == qname:
                score = 100
            elif label.startswith(normalized) or qname.startswith(normalized):
                score = 80
            elif normalized in label or normalized in qname:
                score = 65
            elif normalized in haystack:
                score = 35
            else:
                continue
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], _kind_order(pair[1]["kind"]), pair[1]["qname"]))
        entries = [item for _, item in scored[:entry_limit]]
        total = len(scored)
        truncated = total > len(entries)
    else:
        core_entries = _core_entries(store)
        entries = core_entries[:entry_limit]
        total = len(core_entries)
        truncated = total > len(entries)

    steps = [
        _step(
            "select",
            "读取本体图式",
            f"focus={text or '核心词汇'}；kind={kind_filter}；返回 {len(entries)} 项",
        ),
        _step(
            "result",
            "返回类、属性、前缀与示例查询",
            "可继续用 focus 检索其他词汇，或直接生成 SPARQL"
            + ("（结果已截断，可用 focus 缩小范围）" if truncated else ""),
        ),
    ]
    return {
        "prefixes": {name: str(namespace) for name, namespace in PREFIXES.items()},
        "prefixBlock": _PREFIX_TEXT,
        "counts": _counts(store),
        "focus": text or None,
        "kind": kind_filter,
        "entries": entries,
        "entryCount": len(entries),
        "matchedCount": total,
        "truncated": truncated,
        "starterQueries": [
            {
                "label": item["label"],
                "sparql": item["sparql"],
            }
            for item in _STARTER_QUERIES
        ],
        "hint": (
            "只读查询只接受 SELECT/ASK，必须写 LIMIT；"
            "可用 ash:/ashd:/ashs:/real:/odrl:/rdfs:/skos: 等前缀。"
        ),
        "queryPath": steps,
    }


__all__ = [
    "DEFAULT_ROW_LIMIT",
    "MAX_QUERY_CHARS",
    "MAX_ROW_LIMIT",
    "PREFIXES",
    "SparqlError",
    "describe_ontology",
    "run_sparql",
    "validate_query",
]
