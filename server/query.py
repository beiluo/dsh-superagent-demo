"""Question-driven ontology queries behind the agent tools.

The tools in :mod:`server.tools` are deliberately small, but the questions the
agent receives are not.  This module translates a question's business filters
into explicit ontology property paths, executes them over the in-memory RDF
graph, and returns the facts and paths that produced each match.

It also contains the prototypes for the other ontology-native scenarios:

* cross-company screening, including a bounded real A-share quote sample;
* evidence-chain tracing from a company or decision to sources and policies;
* portfolio / ODRL constraint checks for a proposed position; and
* what-if rule simulation on an in-memory copy of a company's facts.

Everything is read-only.  Real A-share screening is mapped into the runtime
graph only; no Turtle file is modified.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from rdflib import Literal, RDF, URIRef

from .namespaces import ASH, ODRL
from .ontology import OntologyStore, local_name, normalize_text
from .rules import RULE_THRESHOLDS, evaluate_company, fmt_money, fmt_num, fmt_weight

# ---------------------------------------------------------------------------
# Metric model
# ---------------------------------------------------------------------------

# Each metric is a small ontology property path, not a column in a fixed
# report.  ``real`` marks the fields available in the bounded quote sample.
METRIC_SPECS: dict[str, dict[str, Any]] = {
    "roe": {
        "label": "ROE",
        "section": "financials",
        "key": "roe",
        "predicate": ASH.roe,
        "unit": "%",
        "real": False,
    },
    "peTtm": {
        "label": "PE(TTM)",
        "section": "valuation",
        "key": "peTtm",
        "predicate": ASH.peTtm,
        "unit": "",
        "real": True,
    },
    "pb": {
        "label": "PB",
        "section": "valuation",
        "key": "pb",
        "predicate": ASH.pb,
        "unit": "",
        "real": True,
    },
    "debtRatio": {
        "label": "资产负债率",
        "section": "financials",
        "key": "debtRatio",
        "predicate": ASH.debtRatio,
        "unit": "%",
        "real": False,
    },
    "interestCoverage": {
        "label": "利息保障倍数",
        "section": "financials",
        "key": "interestCoverage",
        "predicate": ASH.interestCoverage,
        "unit": "×",
        "real": False,
    },
    "revenueGrowth": {
        "label": "营收增速",
        "section": "financials",
        "key": "revenueGrowth",
        "predicate": ASH.revenueGrowth,
        "unit": "%",
        "real": False,
    },
    "profitGrowth": {
        "label": "净利润增速",
        "section": "financials",
        "key": "profitGrowth",
        "predicate": ASH.profitGrowth,
        "unit": "%",
        "real": False,
    },
    "riskScore": {
        "label": "风险分数",
        "section": "risk",
        "key": "score",
        "predicate": ASH.riskScore,
        "unit": "/100",
        "real": False,
    },
    "marketCap": {
        "label": "总市值",
        "section": "quote",
        "key": "marketCap",
        "predicate": ASH.marketCap,
        "unit": "money",
        "real": True,
    },
    "turnoverRate": {
        "label": "换手率",
        "section": "quote",
        "key": "turnoverRate",
        "predicate": ASH.turnoverRate,
        "unit": "%",
        "real": True,
    },
    "changePct": {
        "label": "涨跌幅",
        "section": "quote",
        "key": "changePct",
        "predicate": ASH.changePct,
        "unit": "%",
        "real": True,
    },
    "positionWeight": {
        "label": "组合权重",
        "section": "position",
        "key": "weight",
        "predicate": ASH.positionWeight,
        "unit": "weight",
        "real": False,
    },
}

METRIC_FIELDS = tuple(METRIC_SPECS)

FIELD_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("roe", ("roe", "净资产收益率")),
    ("peTtm", ("pe(ttm)", "pe（ttm）", "pe", "市盈率")),
    ("pb", ("pb", "市净率")),
    ("debtRatio", ("资产负债率", "负债率")),
    ("interestCoverage", ("利息保障倍数", "利息保障")),
    ("revenueGrowth", ("营业收入增速", "营收增速", "收入增速")),
    ("profitGrowth", ("净利润增速", "净利增速", "利润增速")),
    ("riskScore", ("风险分数", "风险评分")),
    ("marketCap", ("总市值", "市值")),
    ("turnoverRate", ("换手率",)),
    ("changePct", ("涨跌幅", "涨幅")),
    ("positionWeight", ("组合权重", "持仓权重", "仓位", "权重")),
)

OPERATOR_ALIASES = {
    "不低于": "gte",
    "大于等于": "gte",
    "至少": "gte",
    ">=": "gte",
    "≥": "gte",
    "不超过": "lte",
    "小于等于": "lte",
    "至多": "lte",
    "<=": "lte",
    "≤": "lte",
    "大于": "gt",
    "高于": "gt",
    "超过": "gt",
    ">": "gt",
    "小于": "lt",
    "低于": "lt",
    "<": "lt",
    "等于": "eq",
    "=": "eq",
    "之间": "between",
    "介于": "between",
}

_OPERATOR_PATTERN = "|".join(
    re.escape(item) for item in sorted(OPERATOR_ALIASES, key=len, reverse=True)
)
_OPERATOR_LABELS = {
    "gte": "≥",
    "lte": "≤",
    "gt": ">",
    "lt": "<",
    "eq": "=",
    "between": "介于",
}
_NUMBER_PATTERN = r"-?\d+(?:\.\d+)?"

DECREASE_WORDS = ("下降", "下调", "减少", "降低", "下跌", "跌", "降")
INCREASE_WORDS = ("上升", "上调", "增加", "提高", "上涨", "涨", "升")
SET_WORDS = ("到", "至", "变成", "达到", "变为")


class QueryError(Exception):
    """A safe, user-facing query error."""

    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


@dataclass(frozen=True)
class FieldFilter:
    field: str
    op: str
    value: float
    value2: float | None = None

    def describe(self) -> str:
        spec = METRIC_SPECS[self.field]
        if self.op == "between":
            return (
                f"{spec['label']} 介于 {_format_metric(self.value, self.field)} 和 "
                f"{_format_metric(self.value2, self.field)} 之间"
            )
        return (
            f"{spec['label']} {_OPERATOR_LABELS[self.op]} "
            f"{_format_metric(self.value, self.field)}"
        )

    def matches(self, value: Any) -> bool:
        if value is None or isinstance(value, bool):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if self.op == "gte":
            return number >= self.value
        if self.op == "lte":
            return number <= self.value
        if self.op == "gt":
            return number > self.value
        if self.op == "lt":
            return number < self.value
        if self.op == "eq":
            return abs(number - self.value) < 1e-9
        if self.op == "between":
            low, high = sorted((self.value, self.value2 if self.value2 is not None else self.value))
            return low <= number <= high
        return False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _step(kind: str, label: str, detail: str, iris: Iterable[str] | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "detail": detail,
        "iris": [str(item) for item in (iris or []) if item],
    }


def _node(store: OntologyStore, term: Any) -> dict[str, Any]:
    if isinstance(term, URIRef):
        ref = store._ref(term) or {}
        return {
            "id": ref.get("id") or local_name(term),
            "iri": str(term),
            "label": ref.get("label") or store._label(term),
            "kind": ref.get("kind") or "individual",
        }
    return _literal_node(term)


def _literal_node(value: Any, unit: str = "") -> dict[str, Any]:
    return {
        "id": None,
        "iri": None,
        "label": _format_metric(value, unit) if unit else str(value),
        "value": value,
        "literal": True,
    }


def _edge(
    store: OntologyStore,
    source: Any,
    predicate: Any,
    target: Any,
    *,
    target_value: Any = None,
    target_unit: str = "",
) -> dict[str, Any]:
    from_node = source if isinstance(source, dict) else _node(store, source)
    if target_value is not None:
        to_node = _literal_node(target_value, target_unit)
    else:
        to_node = target if isinstance(target, dict) else _node(store, target)
    return {
        "from": from_node,
        "predicate": local_name(predicate),
        "predicateIri": str(predicate),
        "predicateLabel": store._label(predicate) or local_name(predicate),
        "to": to_node,
    }


def _format_metric(value: Any, field_or_unit: str) -> str:
    if value is None:
        return "—"
    spec = METRIC_SPECS.get(field_or_unit)
    unit = spec["unit"] if spec else field_or_unit
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "%":
        return f"{number:.1f}%"
    if unit == "weight":
        return f"{number * 100:.1f}%"
    if unit == "money":
        return fmt_money(number)
    if unit == "/100":
        return f"{fmt_num(number)}/100"
    if unit == "×":
        return f"{number:.1f}×"
    if unit == "price":
        return f"¥{number:,.2f}"
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}"
    return f"{number:,.2f}"


def _metric_value(knowledge: dict[str, Any], field: str) -> Any:
    spec = METRIC_SPECS[field]
    section = spec["section"]
    key = spec["key"]
    if section == "risk":
        return (knowledge.get("risk") or {}).get(key)
    if section == "position":
        return (knowledge.get("position") or {}).get(key)
    return (knowledge.get(section) or {}).get(key)


def _metric_display(knowledge: dict[str, Any], field: str) -> str:
    return _format_metric(_metric_value(knowledge, field), field)


def _latest_term(store: OntologyStore, subject: URIRef, predicate: Any, date_predicate: Any) -> Any:
    return store._latest(subject, predicate, date_predicate)


def _term_section(store: OntologyStore, subject: URIRef, section: str) -> tuple[Any, Any]:
    """Return ``(node, decision)`` for a metric section.

    ``node`` is the report/quote/valuation/risk/position individual and
    ``decision`` is the decision that owns a risk assessment, when relevant.
    """

    if section == "financials":
        return _latest_term(store, subject, ASH.hasFinancialReport, ASH.dataAsOf), None
    security = store._first(subject, ASH.hasSecurity)
    if not isinstance(security, URIRef):
        return None, None
    if section == "valuation":
        return store._first(security, ASH.hasValuation), None
    if section == "quote":
        return store._first(security, ASH.hasMarketQuote), None
    decision = store.company_decision(subject)
    if section == "risk":
        risk = store._first(decision, ASH.hasRiskAssessment) if isinstance(decision, URIRef) else None
        return risk, decision
    if section == "position":
        positions = store._all_positions(security)
        return (positions[0] if positions else None), decision
    return None, None


def _metric_fact(store: OntologyStore, subject: URIRef, field: str, knowledge: dict[str, Any]) -> dict[str, Any] | None:
    value = _metric_value(knowledge, field)
    if value is None:
        return None
    spec = METRIC_SPECS[field]
    section = spec["section"]
    node, decision = _term_section(store, subject, section)
    path: list[dict[str, Any]] = []
    company_node = _node(store, subject)

    if section == "financials" and isinstance(node, URIRef):
        path = [
            _edge(store, company_node, ASH.hasFinancialReport, node),
            _edge(store, node, spec["predicate"], None, target_value=value, target_unit=field),
        ]
    elif section in {"valuation", "quote"} and isinstance(node, URIRef):
        security = store._first(subject, ASH.hasSecurity)
        if isinstance(security, URIRef):
            predicate = ASH.hasValuation if section == "valuation" else ASH.hasMarketQuote
            path = [
                _edge(store, company_node, ASH.hasSecurity, security),
                _edge(store, security, predicate, node),
                _edge(store, node, spec["predicate"], None, target_value=value, target_unit=field),
            ]
    elif section == "risk" and isinstance(node, URIRef):
        path = [
            _edge(store, node, spec["predicate"], None, target_value=value, target_unit=field),
        ]
        if isinstance(decision, URIRef):
            path.insert(0, _edge(store, decision, ASH.hasRiskAssessment, node))
    elif section == "position" and isinstance(node, URIRef):
        security = store._first(subject, ASH.hasSecurity)
        if isinstance(security, URIRef):
            path = [
                _edge(store, node, ASH.positionIn, security),
                _edge(store, node, spec["predicate"], None, target_value=value, target_unit=field),
            ]

    as_of = store._date(node, ASH.dataAsOf) if isinstance(node, URIRef) else None
    source = store._text(node, ASH.dataSource) if isinstance(node, URIRef) else None
    citations = []
    for item in (subject, node):
        if isinstance(item, URIRef):
            ref = store._cite(item)
            if ref:
                citations.append(ref)
    return {
        "field": field,
        "label": spec["label"],
        "value": value,
        "display": _format_metric(value, field),
        "unit": spec["unit"],
        "propertyIri": str(spec["predicate"]),
        "propertyLabel": store._label(spec["predicate"]) or local_name(spec["predicate"]),
        "path": path,
        "asOf": as_of,
        "source": source,
        "citations": citations,
    }


def _path_text(path: list[dict[str, Any]]) -> str:
    if not path:
        return ""
    parts = [path[0]["from"].get("label") or ""]
    for edge in path:
        parts.append(f"—{edge.get('predicateLabel') or edge.get('predicate')}→")
        parts.append(edge["to"].get("label") or "")
    return " ".join(part for part in parts if part)


def _dedupe(values: Iterable[Any]) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_citations(items: Iterable[dict[str, Any] | None], limit: int = 24) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        if not item or not isinstance(item, dict):
            continue
        key = item.get("iri") or item.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _normalize_operator(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"gte", "lte", "gt", "lt", "eq", "between"}:
        return text
    for alias, operator in OPERATOR_ALIASES.items():
        if text == alias.lower():
            return operator
    raise QueryError("invalid_filter", f"未知比较运算：{value}。可用：>=、<=、>、<、=、between。")


def _coerce_filter(item: Any) -> FieldFilter:
    if isinstance(item, FieldFilter):
        return item
    if not isinstance(item, dict):
        raise QueryError("invalid_filter", "filters 必须是对象数组。")
    field = str(item.get("field") or "").strip()
    if field not in METRIC_SPECS:
        raise QueryError(
            "invalid_filter",
            f"不支持的筛选字段：{field or '（空）'}。",
            available=list(METRIC_FIELDS),
        )
    operator = _normalize_operator(item.get("op") or item.get("operator") or "gte")
    value = item.get("value")
    if value is None:
        raise QueryError("invalid_filter", f"{field} 需要 value。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise QueryError("invalid_filter", f"{field} 的 value 必须是数字。") from exc
    value2 = item.get("value2")
    if operator == "between" and value2 is None:
        raise QueryError("invalid_filter", f"{field} 的 between 条件需要 value2。")
    try:
        number2 = float(value2) if value2 is not None else None
    except (TypeError, ValueError) as exc:
        raise QueryError("invalid_filter", f"{field} 的 value2 必须是数字。") from exc
    return FieldFilter(field=field, op=operator, value=number, value2=number2)


def normalize_filters(raw: Any) -> list[FieldFilter]:
    if not raw:
        return []
    if isinstance(raw, dict):
        if {"field", "op", "value"} & set(raw):
            return [_coerce_filter(raw)]
        expanded = []
        for field, condition in raw.items():
            if isinstance(condition, dict):
                expanded.append({"field": field, **condition})
            else:
                expanded.append({"field": field, "op": "eq", "value": condition})
        raw = expanded
    if not isinstance(raw, list):
        raise QueryError("invalid_filter", "filters 必须是对象或对象数组。")
    return [_coerce_filter(item) for item in raw]


def _normalize_rule_ids(raw: Any) -> list[str]:
    if not raw:
        return []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    result = []
    for item in items:
        text = str(item or "").strip().upper()
        match = re.fullmatch(r"R?(\d{1,2})", text)
        if match:
            result.append(f"R{int(match.group(1)):02d}")
        elif text:
            result.append(text)
    return result


def _rule_status(signals: list[dict[str, Any]]) -> dict[str, str]:
    return {item["ruleId"]: item["status"] for item in signals}


def _criteria_text(
    filters: list[FieldFilter],
    industry: str | None,
    rules_any: list[str],
    rules_all: list[str],
    rules_exclude: list[str],
) -> list[str]:
    criteria = [item.describe() for item in filters]
    if industry:
        criteria.append(f"行业匹配“{industry}”")
    if rules_any:
        criteria.append(f"{'、'.join(rules_any)} 任一触发")
    if rules_all:
        criteria.append(f"{'、'.join(rules_all)} 全部触发")
    if rules_exclude:
        criteria.append(f"{'、'.join(rules_exclude)} 均未触发")
    return criteria


def _match_sort_value(item: dict[str, Any], field: str) -> float | None:
    value = (item.get("metrics") or {}).get(field)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _sort_matches(matches: list[dict[str, Any]], sort: str | None) -> list[dict[str, Any]]:
    if not sort:
        return sorted(matches, key=lambda item: item["company"]["label"])
    field = str(sort).strip()
    descending = field.startswith("-")
    field = field.lstrip("+-")
    if field not in METRIC_SPECS:
        return sorted(matches, key=lambda item: item["company"]["label"])
    with_value = [item for item in matches if _match_sort_value(item, field) is not None]
    without_value = [item for item in matches if _match_sort_value(item, field) is None]
    with_value.sort(
        key=lambda item: _match_sort_value(item, field) or 0.0,
        reverse=descending,
    )
    return with_value + without_value


def _base_query_path(
    universe: str,
    filters: list[FieldFilter],
    industry: str | None,
    rules_any: list[str],
    rules_all: list[str],
    rules_exclude: list[str],
) -> list[dict[str, Any]]:
    path = [
        _step(
            "select",
            "选择查询范围",
            "本体中的示例公司 + 本次运行已加载的真实 A 股"
            if universe == "ontology"
            else "真实 A 股行情单页样本",
        )
    ]
    if filters:
        paths = "；".join(
            f"{item.field} ← {_metric_property_path(item.field)}" for item in filters
        )
        path.append(_step("traverse", "把业务条件映射成属性路径", paths))
        path.append(_step("filter", "执行属性过滤", "；".join(item.describe() for item in filters)))
    if industry:
        path.append(_step("filter", "按行业概念过滤", f"行业标签包含“{industry}”"))
    if rules_any or rules_all or rules_exclude:
        parts = []
        if rules_any:
            parts.append(f"{'、'.join(rules_any)} 任一触发")
        if rules_all:
            parts.append(f"{'、'.join(rules_all)} 全部触发")
        if rules_exclude:
            parts.append(f"{'、'.join(rules_exclude)} 均未触发")
        path.append(_step("verify", "用 SWRL 规则复核", "；".join(parts)))
    return path


def _metric_property_path(field: str) -> str:
    spec = METRIC_SPECS[field]
    section = spec["section"]
    prop = local_name(spec["predicate"])
    if section == "financials":
        return f"company → hasFinancialReport → report → {prop}"
    if section == "valuation":
        return f"company → hasSecurity → security → hasValuation → valuation → {prop}"
    if section == "quote":
        return f"company → hasSecurity → security → hasMarketQuote → quote → {prop}"
    if section == "risk":
        return f"decision → hasRiskAssessment → risk → {prop}"
    if section == "position":
        return f"position → positionIn → security; position → {prop}"
    return prop


# ---------------------------------------------------------------------------
# Cross-company screening
# ---------------------------------------------------------------------------


def _evaluate_signals(store: OntologyStore, knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**store._enrich_signal(item), "label": (store.rule(item["ruleId"]) or {}).get("label", item["ruleId"])}
        for item in evaluate_company(knowledge)
    ]


def _company_metrics(knowledge: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {field: _metric_value(knowledge, field) for field in fields}


def _query_ontology(
    store: OntologyStore,
    *,
    filters: list[FieldFilter],
    industry: str | None,
    rules_any: list[str],
    rules_all: list[str],
    rules_exclude: list[str],
    limit: int,
    sort: str | None,
    include_evidence: bool,
) -> dict[str, Any]:
    subjects = store.all_company_subjects()
    matches: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    citations: list[dict[str, Any] | None] = []
    metric_fields = _dedupe([item.field for item in filters] + ["roe", "peTtm", "riskScore", "positionWeight", "debtRatio", "revenueGrowth"])

    for subject in subjects:
        knowledge = store.company_knowledge(subject)
        data = knowledge.to_dict()
        company = knowledge.company or {}
        industry_label = (company.get("industry") or {}).get("label") or ""
        signals = _evaluate_signals(store, data)
        statuses = _rule_status(signals)
        reasons: list[str] = []
        facts: list[dict[str, Any]] = []

        if industry and normalize_text(industry) not in normalize_text(industry_label):
            reasons.append(f"行业为“{industry_label or '未知'}”")

        for item in filters:
            value = _metric_value(data, item.field)
            if value is None:
                reasons.append(f"{METRIC_SPECS[item.field]['label']} 缺失")
                continue
            if not item.matches(value):
                reasons.append(
                    f"{item.describe()} 不满足（实际 {_format_metric(value, item.field)}）"
                )
                continue
            if include_evidence:
                fact = _metric_fact(store, subject, item.field, data)
                if fact:
                    facts.append(fact)
                    citations.extend(fact.get("citations") or [])

        if rules_any and not any(statuses.get(rule_id) == "triggered" for rule_id in rules_any):
            reasons.append(f"{'、'.join(rules_any)} 均未触发")
        if rules_all and not all(statuses.get(rule_id) == "triggered" for rule_id in rules_all):
            reasons.append(f"{'、'.join(rules_all)} 未全部触发")
        if rules_exclude and any(statuses.get(rule_id) == "triggered" for rule_id in rules_exclude):
            reasons.append(f"{'、'.join(rules_exclude)} 触发了")

        if reasons:
            excluded.append(
                {
                    "company": {
                        "id": company.get("id"),
                        "iri": company.get("iri"),
                        "label": company.get("label"),
                        "code": (knowledge.security or {}).get("code", ""),
                        "industry": industry_label,
                    },
                    "reasons": reasons[:4],
                }
            )
            continue

        citations.append(store._cite(subject))
        if knowledge.security:
            citations.append(store._cite(URIRef((knowledge.security or {}).get("iri") or "")) if (knowledge.security or {}).get("iri") else None)
        matches.append(
            {
                "company": {
                    "id": company.get("id"),
                    "iri": company.get("iri"),
                    "label": company.get("label"),
                    "code": (knowledge.security or {}).get("code", ""),
                    "industry": industry_label,
                    "dataMode": data.get("dataMode") or "example",
                },
                "metrics": _company_metrics(data, metric_fields),
                "matchedRules": [item["ruleId"] for item in signals if item["status"] == "triggered"],
                "facts": facts,
            }
        )
        for rule_id in [item["ruleId"] for item in signals if item["status"] == "triggered"]:
            rule = store.rule(rule_id)
            if rule:
                citations.append(store._cite(URIRef(rule["iri"])))

    matches = _sort_matches(matches, sort)
    total_matches = len(matches)
    matches = matches[:limit]
    path = _base_query_path("ontology", filters, industry, rules_any, rules_all, rules_exclude)
    path.append(
        _step(
            "result",
            "返回命中",
            f"{total_matches} / {len(subjects)} 家公司符合条件",
            [item["company"].get("iri") for item in matches],
        )
    )
    return {
        "universe": "ontology",
        "criteria": _criteria_text(filters, industry, rules_any, rules_all, rules_exclude),
        "filters": [
            {"field": item.field, "op": item.op, "value": item.value, "value2": item.value2}
            for item in filters
        ],
        "industry": industry,
        "rules": {"any": rules_any, "all": rules_all, "exclude": rules_exclude},
        "evaluatedCount": len(subjects),
        "totalMatches": total_matches,
        "matches": matches,
        "excluded": excluded[:6],
        "dataNote": (
            "筛选覆盖本体中的合成示例公司，以及本次运行中已经加载的真实 A 股；"
            "规则与阈值仍为示例常量。"
        ),
        "queryPath": path,
        "citations": _dedupe_citations(citations),
    }


def _query_real(
    store: OntologyStore,
    *,
    filters: list[FieldFilter],
    industry: str | None,
    rules_any: list[str],
    rules_all: list[str],
    rules_exclude: list[str],
    limit: int,
    sort: str | None,
    sample: int,
    include_evidence: bool,
) -> dict[str, Any]:
    unsupported = [item.field for item in filters if not METRIC_SPECS[item.field].get("real")]
    if unsupported:
        labels = "、".join(METRIC_SPECS[item]["label"] for item in unsupported)
        raise QueryError(
            "unsupported_filter",
            f"真实 A 股样本筛选暂时只支持行情/估值字段；{labels} 需要年报或决策数据。"
            "请先用行情条件缩小范围，再对候选调用 get_company_analysis。",
            supported=[field for field in METRIC_FIELDS if METRIC_SPECS[field].get("real")],
        )

    sort_field = "marketCap"
    direction = "-"
    if sort:
        candidate = str(sort).lstrip("+-")
        if candidate in METRIC_SPECS and METRIC_SPECS[candidate].get("real"):
            sort_field = candidate
            direction = "-" if str(sort).startswith("-") else "+"
    elif filters and METRIC_SPECS[filters[0].field].get("real"):
        sort_field = filters[0].field
        direction = "-" if filters[0].op in {"gte", "gt"} else "+"

    snapshots = store.market_candidates(
        limit=max(8, min(int(sample or 120), 200)),
        sort=f"{direction}{sort_field}",
    )
    if snapshots is None:
        raise QueryError(
            "market_data_disabled",
            "真实 A 股数据源未启用或不支持跨公司筛选；可改用 universe=ontology。",
        )

    candidates: list[dict[str, Any]] = []
    for snapshot in snapshots:
        metrics = {
            "peTtm": snapshot.valuation.get("peTtm"),
            "pb": snapshot.valuation.get("pb"),
            "marketCap": snapshot.quote.get("marketCap"),
            "turnoverRate": snapshot.quote.get("turnoverRate"),
            "changePct": snapshot.quote.get("changePct"),
            "lastPrice": snapshot.quote.get("lastPrice"),
        }
        if any(not item.matches(metrics.get(item.field)) for item in filters):
            continue
        if industry and normalize_text(industry) not in normalize_text(snapshot.industry or ""):
            continue
        candidates.append({"snapshot": snapshot, "metrics": metrics})

    reverse = direction == "-"
    sort_key = sort_field
    candidates.sort(
        key=lambda item: item["metrics"].get(sort_key) if item["metrics"].get(sort_key) is not None else float("-inf"),
        reverse=reverse,
    )

    selected = candidates[:limit]
    matches: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    citations: list[dict[str, Any] | None] = []
    for item in selected:
        snapshot = item["snapshot"]
        subject = store.register_real_company(snapshot)
        knowledge = store.company_knowledge(subject)
        data = knowledge.to_dict()
        signals = _evaluate_signals(store, data)
        statuses = _rule_status(signals)
        reasons = []
        if rules_any and not any(statuses.get(rule_id) == "triggered" for rule_id in rules_any):
            reasons.append(f"{'、'.join(rules_any)} 均未触发")
        if rules_all and not all(statuses.get(rule_id) == "triggered" for rule_id in rules_all):
            reasons.append(f"{'、'.join(rules_all)} 未全部触发")
        if rules_exclude and any(statuses.get(rule_id) == "triggered" for rule_id in rules_exclude):
            reasons.append(f"{'、'.join(rules_exclude)} 触发了")
        if reasons:
            excluded.append(
                {
                    "company": {
                        "id": knowledge.company.get("id"),
                        "label": knowledge.company.get("label"),
                        "code": (knowledge.security or {}).get("code", ""),
                    },
                    "reasons": reasons,
                }
            )
            continue
        facts = []
        if include_evidence:
            for field_filter in filters:
                fact = _metric_fact(store, subject, field_filter.field, data)
                if fact:
                    facts.append(fact)
                    citations.extend(fact.get("citations") or [])
        citations.append(store._cite(subject))
        matches.append(
            {
                "company": {
                    "id": knowledge.company.get("id"),
                    "iri": knowledge.company.get("iri"),
                    "label": knowledge.company.get("label"),
                    "code": (knowledge.security or {}).get("code", ""),
                    "industry": (knowledge.company.get("industry") or {}).get("label", snapshot.industry or ""),
                    "dataMode": "real",
                },
                "metrics": _company_metrics(data, _dedupe([item.field for item in filters] + ["peTtm", "pb", "marketCap", "turnoverRate"])),
                "matchedRules": [item["ruleId"] for item in signals if item["status"] == "triggered"],
                "facts": facts,
            }
        )

    path = _base_query_path("real", filters, industry, rules_any, rules_all, rules_exclude)
    path.insert(
        1,
        _step(
            "scan",
            "扫描真实 A 股行情样本",
            f"按{_sort_label(sort_field)}排序读取 {len(snapshots)} 只，应用行情/估值条件后剩 {len(candidates)} 只",
        ),
    )
    path.append(_step("result", "返回命中", f"{len(matches)} 只（样本 {len(snapshots)} 只）", [item["company"].get("iri") for item in matches]))
    return {
        "universe": "real",
        "criteria": _criteria_text(filters, industry, rules_any, rules_all, rules_exclude),
        "filters": [
            {"field": item.field, "op": item.op, "value": item.value, "value2": item.value2}
            for item in filters
        ],
        "industry": industry,
        "rules": {"any": rules_any, "all": rules_all, "exclude": rules_exclude},
        "evaluatedCount": len(snapshots),
        "totalMatches": len(matches),
        "candidateCount": len(candidates),
        "matches": matches,
        "excluded": excluded[:6],
        "dataNote": (
            "真实 A 股筛选读取东方财富公开行情接口的单页样本（最多 200 只），"
            "仅覆盖行情与估值字段，未拉取年报；行情接口的 PE 为动态口径，与年报 TTM 可能存在差异。"
            "结果映射到本次运行的 RDF 图，不写盘，可能延迟。"
        ),
        "queryPath": path,
        "citations": _dedupe_citations(citations),
    }


def _sort_label(field: str) -> str:
    labels = {
        "marketCap": "总市值",
        "peTtm": "PE(TTM)",
        "pb": "PB",
        "turnoverRate": "换手率",
        "changePct": "涨跌幅",
    }
    return labels.get(field, field)


def run_query(store: OntologyStore, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Execute a question-shaped query and return matches plus their paths."""

    spec = spec or {}
    filters = normalize_filters(spec.get("filters"))
    industry = str(spec.get("industry") or "").strip() or None
    rules_any = _normalize_rule_ids(spec.get("rules_any") or spec.get("rules"))
    rules_all = _normalize_rule_ids(spec.get("rules_all"))
    rules_exclude = _normalize_rule_ids(spec.get("rules_exclude"))
    try:
        limit = max(1, min(int(spec.get("limit") or 10), 25))
    except (TypeError, ValueError) as exc:
        raise QueryError("invalid_limit", "limit 必须是整数。") from exc
    try:
        sample = max(8, min(int(spec.get("sample") or 120), 200))
    except (TypeError, ValueError) as exc:
        raise QueryError("invalid_sample", "sample 必须是整数。") from exc
    sort = str(spec.get("sort") or "").strip() or None
    include_evidence = bool(spec.get("include_evidence", True))
    universe = str(spec.get("universe") or "ontology").strip().lower()
    if universe not in {"ontology", "real"}:
        raise QueryError("invalid_universe", "universe 只能是 ontology 或 real。")

    if universe == "real":
        return _query_real(
            store,
            filters=filters,
            industry=industry,
            rules_any=rules_any,
            rules_all=rules_all,
            rules_exclude=rules_exclude,
            limit=limit,
            sort=sort,
            sample=sample,
            include_evidence=include_evidence,
        )
    return _query_ontology(
        store,
        filters=filters,
        industry=industry,
        rules_any=rules_any,
        rules_all=rules_all,
        rules_exclude=rules_exclude,
        limit=limit,
        sort=sort,
        include_evidence=include_evidence,
    )


# ---------------------------------------------------------------------------
# Evidence-chain tracing
# ---------------------------------------------------------------------------

EVIDENCE_PREDICATES: tuple[tuple[Any, str], ...] = (
    (ASH.hasSecurity, "持有证券"),
    (ASH.hasFinancialReport, "披露年报"),
    (ASH.hasMarketQuote, "行情快照"),
    (ASH.hasValuation, "估值快照"),
    (ASH.aboutCompany, "关于公司"),
    (ASH.aboutSecurity, "关于证券"),
    (ASH.assessesSecurity, "评估证券"),
    (ASH.assessesDecision, "评估决策"),
    (ASH.checksDecision, "合规检查"),
    (ASH.basedOn, "依据证据"),
    (ASH.governedBy, "受政策约束"),
    (ASH.hasRationale, "决策理由"),
    (ASH.hasRiskAssessment, "风险评估"),
    (ASH.hasComplianceCheck, "合规检查"),
    (ASH.generatedBy, "生成服务"),
    (ASH.hasMacroContext, "宏观背景"),
    (ASH.hasSource, "数据来源"),
    (ASH.positionIn, "持仓证券"),
    (ASH.positionOf, "所属组合"),
    (ASH.holdsPosition, "持有仓位"),
    (ASH.appliesTo, "适用范围"),
    (ASH.ruleUses, "读取属性"),
    (ASH.hasPolicy, "关联政策"),
    (ODRL.hasPolicy, "关联政策"),
)

# Reverse traversal is only useful for the inverse-side relations below.  Walking
# every predicate backwards would pull unrelated decisions through shared
# policies or services and turn one company's evidence chain into the whole
# portfolio.
REVERSE_EVIDENCE_PREDICATES: frozenset[Any] = frozenset(
    {
        ASH.aboutCompany,
        ASH.aboutSecurity,
        ASH.assessesSecurity,
        ASH.assessesDecision,
        ASH.checksDecision,
    }
)

PROVENANCE_PREDICATES: tuple[Any, ...] = (
    ASH.dataAsOf,
    ASH.dataSource,
    ASH.dataQualityFlag,
    ASH.decisionId,
    ASH.decisionDate,
    ASH.validUntil,
    ASH.confidence,
    ASH.ruleId,
    ASH.ruleVersion,
    ASH.ruleStatus,
    ASH.ruleOwner,
    ASH.severity,
    ASH.policyVersion,
    ASH.policyStatus,
    ASH.reviewDate,
    ASH.riskScore,
    ASH.reportPeriod,
    ASH.securityCode,
)


def _resolve_subject(store: OntologyStore, query: str) -> tuple[URIRef | None, str | None]:
    text = str(query or "").strip()
    if not text:
        return None, None
    company = store.find_company(text)
    if company is not None:
        return company, "company"

    normalized = normalize_text(text)
    if text.startswith("http"):
        term = URIRef(text)
        if (term, None, None) in store.graph:
            kind = "decision" if (term, RDF.type, ASH.InvestmentDecision) in store.graph else "entity"
            return term, kind

    for decision in store.graph.subjects(RDF.type, ASH.InvestmentDecision):
        if not isinstance(decision, URIRef):
            continue
        values = (
            store._text(decision, ASH.decisionId),
            store._label(decision),
            local_name(decision),
        )
        if any(value and normalize_text(value) == normalized for value in values):
            return decision, "decision"

    rule = store.rule(text)
    if rule:
        return URIRef(rule["iri"]), "rule"

    for policy in store.policies():
        values = (policy.get("uid"), policy.get("id"), policy.get("label"))
        if any(value and normalize_text(value) == normalized for value in values):
            return URIRef(policy["iri"]), "policy"

    for security in store.graph.subjects(RDF.type, ASH.AShare):
        if not isinstance(security, URIRef):
            continue
        values = (
            store._text(security, ASH.securityCode),
            store._text(security, ASH.securityName),
            store._label(security),
        )
        if any(value and normalize_text(value) == normalized for value in values):
            return security, "security"
    return None, None


def _provenance(store: OntologyStore, subject: URIRef) -> list[dict[str, Any]]:
    facts = []
    for predicate in PROVENANCE_PREDICATES:
        value = store._literal(subject, predicate)
        if value in (None, ""):
            continue
        facts.append(
            {
                "property": local_name(predicate),
                "label": store._label(predicate) or local_name(predicate),
                "value": str(value),
            }
        )
    return facts


def trace_evidence(
    store: OntologyStore,
    subject: str,
    *,
    depth: int = 3,
    limit: int = 40,
    rule_id: str | None = None,
) -> dict[str, Any]:
    """Walk an evidence/provenance graph around a company, decision, rule or policy."""

    try:
        depth = max(1, min(int(depth or 3), 4))
    except (TypeError, ValueError) as exc:
        raise QueryError("invalid_depth", "depth 必须是 1-4 的整数。") from exc
    limit = max(5, min(int(limit or 40), 60))

    seed, seed_kind = _resolve_subject(store, subject)
    if seed is None:
        raise QueryError(
            "subject_not_found",
            f"没有找到“{subject}”对应的公司、决策、规则或政策。",
            hint="可以传公司名、决策编号（如 DEC-...）、规则编号（R01）或政策 uid。",
        )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[URIRef] = set()
    queue: list[tuple[URIRef, int]] = [(seed, 0)]
    seen.add(seed)

    while queue and len(nodes) < limit:
        current, level = queue.pop(0)
        node = _node(store, current)
        node["types"] = [local_name(item) for item in store.graph.objects(current, RDF.type) if isinstance(item, URIRef)]
        node["provenance"] = _provenance(store, current)
        nodes.append(node)
        if level >= depth:
            continue
        for predicate, label in EVIDENCE_PREDICATES:
            neighbours: list[tuple[URIRef, str]] = []
            for value in store.graph.objects(current, predicate):
                if isinstance(value, URIRef):
                    neighbours.append((value, "forward"))
            allow_reverse = predicate in REVERSE_EVIDENCE_PREDICATES or (
                seed_kind == "policy" and predicate in {ASH.governedBy, ASH.hasPolicy}
            )
            if allow_reverse:
                for value in store.graph.subjects(predicate, current):
                    if isinstance(value, URIRef):
                        neighbours.append((value, "reverse"))
            for neighbour, direction in neighbours:
                if len(edges) >= limit * 2:
                    break
                if direction == "forward":
                    edge = _edge(store, current, predicate, neighbour)
                else:
                    edge = _edge(store, neighbour, predicate, current)
                edges.append(
                    {
                        **edge,
                        "direction": direction,
                        "label": label,
                    }
                )
                if neighbour not in seen and len(seen) < limit:
                    seen.add(neighbour)
                    queue.append((neighbour, level + 1))

    extra_rule = None
    if rule_id:
        rule = store.rule(str(rule_id))
        if rule:
            extra_rule = rule
            rule_term = URIRef(rule["iri"])
            if rule_term not in seen and len(nodes) < limit:
                node = _node(store, rule_term)
                node["types"] = ["RuleArtifact"]
                node["provenance"] = _provenance(store, rule_term)
                nodes.append(node)
            edges.append(
                {
                    "from": _node(store, seed),
                    "predicate": "ruleCheck",
                    "predicateIri": "",
                    "predicateLabel": "规则复核",
                    "to": _node(store, rule_term),
                    "direction": "annotated",
                    "label": "规则复核",
                }
            )
        else:
            raise QueryError("rule_not_found", f"本体中没有规则 {rule_id}。")

    chain = []
    for edge in edges:
        chain.append(
            f"{edge['from'].get('label')} —{edge.get('predicateLabel') or edge.get('predicate')}→ "
            f"{edge['to'].get('label')}"
        )
    chain = list(dict.fromkeys(chain))[:limit]
    path = [
        _step("select", "定位本体实体", f"{seed_kind or 'entity'}：{store._label(seed)}", [str(seed)]),
        _step(
            "traverse",
            "按证据谓词逐层遍历",
            f"深度 {depth}，保留 {len(nodes)} 个节点、{len(edges)} 条边",
            [str(seed)],
        ),
        _step("verify", "保留数据来源、日期、规则与政策版本", f"{len(chain)} 条可读证据链"),
    ]
    if extra_rule:
        path.append(
            _step(
                "verify",
                "附加规则元数据",
                f"{extra_rule['ruleId']} · {extra_rule['label']}",
                [extra_rule["iri"]],
            )
        )
    citations = []
    for node in nodes:
        ref = store._ref(URIRef(node["iri"]))
        if ref:
            citations.append(ref)
    return {
        "subject": {
            "id": local_name(seed),
            "iri": str(seed),
            "label": store._label(seed),
            "kind": seed_kind or "entity",
        },
        "rule": extra_rule,
        "depth": depth,
        "nodes": nodes,
        "edges": edges,
        "chain": chain,
        "dataNote": (
            "证据链只遍历本体中显式建模的证据、理由、数据来源、规则与政策关系；"
            "不推断未建模的因果关系。"
        ),
        "queryPath": path,
        "citations": _dedupe_citations(citations),
    }


# ---------------------------------------------------------------------------
# Portfolio and ODRL constraint checks
# ---------------------------------------------------------------------------

ODRL_OPERATORS = {
    "eq": "eq",
    "neq": "neq",
    "lt": "lt",
    "lteq": "lte",
    "gt": "gt",
    "gteq": "gte",
    "isA": "isA",
    "isNoneOf": "isNoneOf",
}


def _local_context_value(context: dict[str, Any], left_operand: Any) -> tuple[bool, Any]:
    name = local_name(left_operand)
    for prefix in ("leftOperand-", "leftOperand_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    if name in context:
        return True, context[name]
    return False, None


def _constraint_check(
    store: OntologyStore,
    constraint: Any,
    context: dict[str, Any],
    *,
    policy_label: str,
) -> dict[str, Any] | None:
    left = store._first(constraint, ODRL.leftOperand)
    operator = local_name(store._first(constraint, ODRL.operator))
    right = store._first(constraint, ODRL.rightOperand)
    if left is None:
        return None
    present, actual = _local_context_value(context, left)
    name = local_name(left)
    for prefix in ("leftOperand-", "leftOperand_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    if not present:
        return None
    expected: Any
    if isinstance(right, Literal):
        expected = right.to_python() if hasattr(right, "to_python") else str(right)
    elif isinstance(right, URIRef):
        expected = store._label(right)
    else:
        expected = str(right)
    op = ODRL_OPERATORS.get(operator, operator)
    status = "pass"
    detail = ""
    if actual is None:
        status = "unknown"
        detail = f"{name} 未提供（政策要求 {op} {expected}）"
    elif op == "eq":
        status = "pass" if str(actual).lower() == str(expected).lower() else "fail"
        detail = f"{name}={actual}（政策要求 = {expected}）"
    elif op == "neq":
        status = "pass" if str(actual).lower() != str(expected).lower() else "fail"
        detail = f"{name}={actual}（政策要求 ≠ {expected}）"
    elif op in {"lt", "lte", "gt", "gte"}:
        try:
            left_number = float(actual)
            right_number = float(expected)
        except (TypeError, ValueError):
            status = "unknown"
            detail = f"{name} 无法与 {expected} 比较"
        else:
            checks = {
                "lt": left_number < right_number,
                "lte": left_number <= right_number,
                "gt": left_number > right_number,
                "gte": left_number >= right_number,
            }
            status = "pass" if checks[op] else "fail"
            detail = f"{name}={actual}（政策要求 {op} {expected}）"
    elif op in {"isA", "isNoneOf"}:
        status = "pass"
        detail = f"{name}={actual}（政策要求 {operator} {expected}）"
    else:
        status = "unknown"
        detail = f"{name} 的政策运算 {operator} 暂不自动判定"
    return {
        "id": f"ODRL:{name}",
        "label": f"{policy_label} · {name}",
        "status": status,
        "detail": detail,
        "policyIri": None,
    }


def _policy_checks(
    store: OntologyStore,
    policy_uid: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = next((item for item in store.policies() if item.get("uid") == policy_uid or item.get("id") == policy_uid), None)
    if policy is None:
        return [
            {
                "id": f"ODRL:{policy_uid}",
                "label": f"政策 {policy_uid}",
                "status": "unknown",
                "detail": "本体中没有找到该政策。",
                "policyIri": None,
            }
        ]
    subject = URIRef(policy["iri"])
    checks = []
    for permission in store.graph.objects(subject, ODRL.permission):
        for constraint in store.graph.objects(permission, ODRL.constraint):
            check = _constraint_check(store, constraint, context, policy_label=policy["label"])
            if check:
                check["policyIri"] = policy["iri"]
                check["id"] = f"ODRL:{policy['uid']}:{check['id'].split(':', 1)[-1]}"
                checks.append(check)
    if not checks:
        checks.append(
            {
                "id": f"ODRL:{policy['uid']}",
                "label": policy["label"],
                "status": "pass",
                "detail": "政策没有需要本次检查的上下文约束。",
                "policyIri": policy["iri"],
            }
        )
    return checks


def _policy_freshness(store: OntologyStore) -> dict[str, Any]:
    today = date.today().isoformat()
    stale = []
    inactive = []
    for policy in store.policies():
        status = str(policy.get("status") or "").lower()
        review = str(policy.get("reviewDate") or "")
        if status and status != "active":
            inactive.append(policy["label"])
        if review and review < today:
            stale.append(f"{policy['label']}（复核日 {review}）")
    if inactive or stale:
        detail = []
        if inactive:
            detail.append("非 active：" + "、".join(inactive))
        if stale:
            detail.append("已过复核日：" + "、".join(stale))
        return {
            "id": "ODRL:freshness",
            "label": "政策有效期与状态",
            "status": "fail",
            "detail": "；".join(detail),
            "policyIri": None,
        }
    return {
        "id": "ODRL:freshness",
        "label": "政策有效期与状态",
        "status": "pass",
        "detail": "所有 ODRL 政策均为 active，且未超过复核日期。",
        "policyIri": None,
    }


def check_constraints(
    store: OntologyStore,
    *,
    company: str | None = None,
    weight: float | None = None,
    action: str = "buy",
    human_approval: bool | None = None,
    compliance_passed: bool | None = None,
) -> dict[str, Any]:
    """Check a proposed position or the current portfolio against rules/ODRL."""

    action = str(action or "buy").strip().lower()
    checks: list[dict[str, Any]] = []
    citations: list[dict[str, Any] | None] = []
    target: dict[str, Any]
    proposed_weight: float | None = None

    if weight is not None:
        try:
            proposed_weight = float(weight)
        except (TypeError, ValueError) as exc:
            raise QueryError("invalid_weight", "weight 必须是数字。") from exc
        if proposed_weight > 1:
            proposed_weight = proposed_weight / 100.0

    if company:
        subject = store.find_company(company)
        if subject is None:
            raise QueryError("company_not_found", f"没有找到公司“{company}”。")
        knowledge = store.company_knowledge(subject)
        data = knowledge.to_dict()
        security = data.get("security") or {}
        position = data.get("position") or {}
        if proposed_weight is None and isinstance(position.get("weight"), (int, float)):
            proposed_weight = float(position["weight"])
        target = {
            "kind": "company",
            "id": knowledge.company.get("id"),
            "iri": knowledge.company.get("iri"),
            "label": knowledge.company.get("label"),
            "code": security.get("code") or "",
        }
        citations.append(store._cite(subject))
        if security.get("iri"):
            citations.append(store._cite(URIRef(security["iri"])))

        max_weight = float(RULE_THRESHOLDS["R06"]["max_weight"])
        if proposed_weight is None:
            checks.append(
                {
                    "id": "R06",
                    "label": "单票集中度",
                    "status": "unknown",
                    "detail": "没有当前持仓权重，也没有给出拟议权重；无法检查 R06。",
                }
            )
        else:
            passed = proposed_weight <= max_weight
            checks.append(
                {
                    "id": "R06",
                    "label": "单票集中度",
                    "status": "pass" if passed else "fail",
                    "detail": (
                        f"拟议权重 {fmt_weight(proposed_weight)} "
                        f"{'≤' if passed else '>'} 上限 {fmt_weight(max_weight)}"
                    ),
                }
            )
            rule = store.rule("R06")
            if rule:
                citations.append(store._cite(URIRef(rule["iri"])))

        restricted = bool(security.get("restricted"))
        checks.append(
            {
                "id": "R07",
                "label": "限制名单",
                "status": "fail" if restricted else "pass",
                "detail": f"证券 isRestricted = {'true' if restricted else 'false'}",
            }
        )
        rule = store.rule("R07")
        if rule:
            citations.append(store._cite(URIRef(rule["iri"])))

        risk = data.get("risk") or {}
        risk_score = risk.get("score")
        wants_buy = action in {"buy", "increase", "加仓", "买入", "增持"}
        if wants_buy and isinstance(risk_score, (int, float)):
            threshold = float(RULE_THRESHOLDS["R11"]["risk_score_min"])
            needs_review = float(risk_score) >= threshold
            checks.append(
                {
                    "id": "R11",
                    "label": "高风险买入复核",
                    "status": "fail" if needs_review else "pass",
                    "detail": (
                        f"风险分数 {fmt_num(risk_score)} {'≥' if needs_review else '<'} "
                        f"{fmt_num(threshold)}，{'需要' if needs_review else '不需要'}二次复核"
                    ),
                }
            )
            rule = store.rule("R11")
            if rule:
                citations.append(store._cite(URIRef(rule["iri"])))
        elif wants_buy:
            checks.append(
                {
                    "id": "R11",
                    "label": "高风险买入复核",
                    "status": "unknown",
                    "detail": "缺少风险评估分数，无法检查 R11。",
                }
            )

        context = {
            "humanApproval": human_approval,
            "compliancePassed": compliance_passed,
        }
        if action in {"buy", "sell"}:
            checks.extend(_policy_checks(store, "policy-trade-guard", context))
        else:
            checks.append(
                {
                    "id": "ODRL:policy-trade-guard",
                    "label": "订单意图交易护栏",
                    "status": "pass",
                    "detail": "当前动作不是订单意图（hold），trade-guard 前置条件不适用。",
                }
            )
        checks.append(_policy_freshness(store))
        for check in checks:
            if check.get("policyIri"):
                citations.append(store._cite(URIRef(check["policyIri"])))
        headings = [
            _step("select", "定位拟议标的", f"{target['label']}（{target['code'] or '示例'}）", [target.get("iri")]),
            _step(
                "traverse",
                "读取当前持仓与风险",
                f"权重 {fmt_weight(proposed_weight) if proposed_weight is not None else '—'}；风险分数 {fmt_num(risk_score)}",
                [target.get("iri")],
            ),
            _step("verify", "执行 R06/R07/R11 组合与风险规则", f"{sum(1 for item in checks if item['id'].startswith('R'))} 项"),
            _step("verify", "读取 ODRL trade-guard 约束", "人工批准 + 合规检查双前置条件", ["policy-trade-guard"]),
        ]
    else:
        portfolio = store.portfolio()
        target = {
            "kind": "portfolio",
            "id": (portfolio.get("portfolio") or {}).get("id"),
            "iri": (portfolio.get("portfolio") or {}).get("iri"),
            "label": (portfolio.get("portfolio") or {}).get("label") or "示例组合",
        }
        citations.append(store._cite(URIRef(target["iri"])) if target.get("iri") else None)
        max_weight = float(RULE_THRESHOLDS["R06"]["max_weight"])
        for item in portfolio.get("positions") or []:
            item_weight = item.get("weight")
            passed = isinstance(item_weight, (int, float)) and float(item_weight) <= max_weight
            checks.append(
                {
                    "id": f"R06:{item.get('id')}",
                    "label": f"单票集中度 · {item.get('company', {}).get('label') or item.get('label')}",
                    "status": "pass" if passed else "fail",
                    "detail": (
                        f"权重 {fmt_weight(item_weight)} "
                        f"{'≤' if passed else '>'} 上限 {fmt_weight(max_weight)}"
                    ),
                }
            )
            citations.append(store._cite(URIRef(item["iri"])) if item.get("iri") else None)
            company_subject = store.find_company(
                str(item.get("company", {}).get("label") or "")
            )
            if company_subject is not None:
                security = store.company_knowledge(company_subject).security or {}
                restricted = bool(security.get("restricted"))
                checks.append(
                    {
                        "id": f"R07:{item.get('id')}",
                        "label": f"限制名单 · {item.get('company', {}).get('label') or item.get('label')}",
                        "status": "fail" if restricted else "pass",
                        "detail": f"证券 isRestricted = {'true' if restricted else 'false'}",
                    }
                )
        rule = store.rule("R06")
        if rule:
            citations.append(store._cite(URIRef(rule["iri"])))
        checks.append(_policy_freshness(store))
        headings = [
            _step("select", "读取组合与持仓", f"{len(portfolio.get('positions') or [])} 个持仓", [target.get("iri")]),
            _step("verify", "逐仓检查 R06 集中度上限", f"上限 {fmt_weight(max_weight)}"),
            _step("verify", "检查政策有效期与状态", f"{len(store.policies())} 项 ODRL 政策"),
        ]

    blocking = [item for item in checks if item.get("status") != "pass"]
    unknown = [item for item in blocking if item.get("status") == "unknown"]
    allowed = not blocking
    summary = "允许" if allowed else ("需要补充信息" if unknown and len(unknown) == len(blocking) else "阻断")
    return {
        "target": target,
        "proposedWeight": proposed_weight,
        "action": action,
        "allowed": allowed,
        "summary": summary,
        "checks": checks,
        "blocking": blocking,
        "dataNote": (
            "约束检查只读取本体中的规则阈值、持仓与 ODRL 政策；不连接交易系统，"
            "人工批准与合规检查必须由真实流程提供。"
        ),
        "queryPath": headings,
        "citations": _dedupe_citations(citations),
    }


# ---------------------------------------------------------------------------
# What-if rule simulation
# ---------------------------------------------------------------------------

SIMULATABLE_LABELS = {
    "lastPrice": "最新价",
    "avgCost": "持仓成本",
}

SIMULATABLE_FIELDS = {
    "roe": ("financials", "roe", "%"),
    "debtRatio": ("financials", "debtRatio", "%"),
    "interestCoverage": ("financials", "interestCoverage", "×"),
    "revenueGrowth": ("financials", "revenueGrowth", "%"),
    "profitGrowth": ("financials", "profitGrowth", "%"),
    "peTtm": ("valuation", "peTtm", ""),
    "pb": ("valuation", "pb", ""),
    "riskScore": ("risk", "score", "/100"),
    "lastPrice": ("quote", "lastPrice", "price"),
    "avgCost": ("position", "avgCost", "price"),
    "positionWeight": ("position", "weight", "weight"),
}


def _apply_change(data: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    field = str(change.get("field") or "").strip()
    if field not in SIMULATABLE_FIELDS:
        raise QueryError(
            "invalid_change",
            f"不支持的情景字段：{field or '（空）'}。",
            available=sorted(SIMULATABLE_FIELDS),
        )
    section, key, _unit = SIMULATABLE_FIELDS[field]
    has_delta = "delta" in change and change.get("delta") is not None
    has_value = "value" in change and change.get("value") is not None
    if not has_delta and not has_value:
        raise QueryError("invalid_change", f"{field} 需要 delta 或 value。")
    try:
        base = (data.get(section) or {}).get(key)
        base_number = float(base) if base is not None else None
        if has_value:
            new_value = float(change["value"])
        else:
            if base_number is None:
                raise QueryError("missing_baseline", f"{field} 缺少基线值，请改用 value 指定绝对值。")
            new_value = base_number + float(change["delta"])
    except QueryError:
        raise
    except (TypeError, ValueError) as exc:
        raise QueryError("invalid_change", f"{field} 的变化量必须是数字。") from exc
    if section == "position" and key == "weight" and new_value > 1:
        new_value = new_value / 100.0
    if section not in data or not isinstance(data.get(section), dict):
        if section == "position":
            data[section] = {}
        else:
            raise QueryError("missing_section", f"{field} 所属的 {section} 数据不存在，无法模拟。")
    data[section][key] = new_value
    display_unit = field if field in METRIC_SPECS else SIMULATABLE_FIELDS[field][2]
    return {
        "field": field,
        "label": METRIC_SPECS.get(field, {}).get("label") or SIMULATABLE_LABELS.get(field) or field,
        "before": base_number,
        "displayBefore": _format_metric(base_number, display_unit),
        "after": new_value,
        "displayAfter": _format_metric(new_value, display_unit),
    }


def simulate_scenario(
    store: OntologyStore,
    *,
    company: str,
    changes: list[dict[str, Any]] | dict[str, Any],
) -> dict[str, Any]:
    """Re-evaluate SWRL signals after hypothetical metric changes."""

    subject = store.find_company(company)
    if subject is None:
        raise QueryError("company_not_found", f"没有找到公司“{company}”。")
    knowledge = store.company_knowledge(subject)
    data = knowledge.to_dict()
    before = evaluate_company(data)
    mutated = copy.deepcopy(data)
    if isinstance(changes, dict):
        changes = [
            {"field": key, "value": value} for key, value in changes.items()
        ]
    if not isinstance(changes, list) or not changes:
        raise QueryError("no_changes", "请至少提供一个假设变化，例如 ROE 下降 5 个百分点。")
    applied = [_apply_change(mutated, dict(item)) for item in changes if isinstance(item, dict)]
    if not applied:
        raise QueryError("no_changes", "请至少提供一个假设变化。")
    after = evaluate_company(mutated)
    before_map = {item["ruleId"]: item for item in before}
    after_map = {item["ruleId"]: item for item in after}
    changed = []
    for rule_id in sorted(set(before_map) | set(after_map)):
        old = before_map.get(rule_id) or {}
        new = after_map.get(rule_id) or {}
        if old.get("status") == new.get("status"):
            continue
        rule = store.rule(rule_id) or {}
        changed.append(
            {
                "ruleId": rule_id,
                "label": rule.get("label") or rule_id,
                "before": old.get("status"),
                "after": new.get("status"),
                "beforeDetail": old.get("detail"),
                "afterDetail": new.get("detail"),
                "severity": rule.get("severity"),
            }
        )
    citations = [store._cite(subject)]
    if knowledge.security and knowledge.security.get("iri"):
        citations.append(store._cite(URIRef(knowledge.security["iri"])))
    for item in changed:
        rule = store.rule(item["ruleId"])
        if rule:
            citations.append(store._cite(URIRef(rule["iri"])))
    scenario_text = "；".join(
        f"{item['label']} {item.get('displayBefore') or '—'} → {item['displayAfter']}"
        if item["before"] is not None
        else f"{item['label']} → {item['displayAfter']}"
        for item in applied
    )
    path = [
        _step("select", "读取基线画像", f"{knowledge.company.get('label')}（{knowledge.company.get('code') or (knowledge.security or {}).get('code', '')}）", [str(subject)]),
        _step("traverse", "应用假设变化", scenario_text),
        _step("verify", "在事实副本上重跑 SWRL 规则", f"{len(before)} 条规则，{len(changed)} 条状态变化"),
        _step("result", "对比情景前后信号", "不写回本体"),
    ]
    return {
        "company": {
            "id": knowledge.company.get("id"),
            "iri": knowledge.company.get("iri"),
            "label": knowledge.company.get("label"),
            "code": (knowledge.security or {}).get("code", ""),
        },
        "scenario": scenario_text,
        "applied": applied,
        "before": before,
        "after": after,
        "changed": changed,
        "dataNote": (
            "情景模拟只在内存中的公司事实副本上重算确定性 SWRL 信号，"
            "不写回 RDF 图；这是规则敏感性演示，不是市场预测。"
        ),
        "queryPath": path,
        "citations": _dedupe_citations(citations),
    }


# ---------------------------------------------------------------------------
# Deterministic question parsing for rules mode
# ---------------------------------------------------------------------------

_REAL_UNIVERSE_WORDS = (
    "全市场",
    "全部a股",
    "全部 a 股",
    "所有a股",
    "所有 a 股",
    "a股市场",
    "a 股市场",
    "真实市场",
    "真实a股",
    "真实 a 股",
    "跨市场",
)
_SCREEN_WORDS = ("哪些", "筛选", "候选", "机会", "池", "排名", "符合", "触发", "选出", "挑出")
_EVIDENCE_WORDS = ("证据链", "证据", "溯源", "数据来源", "审计", "依据是什么", "为什么")
_CONSTRAINT_WORDS = (
    "约束",
    "合规",
    "能不能买",
    "可以买吗",
    "允许吗",
    "人工批准",
    "交易护栏",
    "集中度上限",
    "超配",
    "加仓",
    "增持",
    "减仓",
)
_SCENARIO_WORDS = ("如果", "假如", "假设", "情景", "模拟", "what-if", "what if", "敏感性")


def detect_industry(store: OntologyStore, question: str) -> str | None:
    normalized = normalize_text(question)
    for label in store.industry_labels():
        key = normalize_text(label)
        if len(key) >= 2 and key in normalized:
            return label
    return None


def _scaled_value(field: str, number: float, unit: str | None) -> float:
    unit = unit or ""
    if field == "marketCap":
        if unit == "万亿":
            return number * 1_000_000_000_000
        if unit == "亿":
            return number * 100_000_000
        if unit == "万":
            return number * 10_000
        return number
    if field == "positionWeight":
        if unit == "%" or number > 1:
            return number / 100.0
        return number
    return number


def parse_question_filters(store: OntologyStore, question: str) -> dict[str, Any]:
    """Translate a Chinese screening question into a query spec."""

    text = str(question or "")
    lower = text.lower()
    filters: list[FieldFilter] = []
    for field, aliases in FIELD_ALIASES:
        matched = False
        for alias in sorted(aliases, key=len, reverse=True):
            if matched:
                break
            alias_pattern = re.escape(alias)
            between = re.search(
                alias_pattern
                + rf"\s*(?:在|介于)?\s*({_NUMBER_PATTERN})\s*(%|亿|万|万亿)?\s*(?:到|至|~|-)\s*"
                + rf"({_NUMBER_PATTERN})\s*(%|亿|万|万亿)?",
                text,
                re.IGNORECASE,
            )
            if between:
                value = _scaled_value(field, float(between.group(1)), between.group(2))
                value2 = _scaled_value(field, float(between.group(3)), between.group(4))
                filters.append(FieldFilter(field=field, op="between", value=value, value2=value2))
                matched = True
                break
            comparison = re.search(
                alias_pattern
                + rf"\s*({_OPERATOR_PATTERN})\s*({_NUMBER_PATTERN})\s*(%|亿|万|万亿)?",
                text,
                re.IGNORECASE,
            )
            if comparison:
                operator = _normalize_operator(comparison.group(1))
                value = _scaled_value(field, float(comparison.group(2)), comparison.group(3))
                filters.append(FieldFilter(field=field, op=operator, value=value))
                matched = True
                break

    industry = detect_industry(store, text)
    rules_any: list[str] = []
    rules_all: list[str] = []
    rules_exclude: list[str] = []
    rule_match = re.search(r"\bR\s?(\d{1,2})\b", text, re.IGNORECASE)
    if rule_match:
        rule_id = f"R{int(rule_match.group(1)):02d}"
        if "不触发" in text or "未触发" in text:
            rules_exclude.append(rule_id)
        elif any(word in lower for word in _SCREEN_WORDS):
            rules_any.append(rule_id)
    for phrase, rule_id in (
        ("价值候选", "R01"),
        ("成长候选", "R10"),
        ("高财务风险", "R02"),
        ("财务风险", "R02"),
        ("低流动性", "R09"),
        ("可审计", "R08"),
    ):
        if phrase in text and rule_id not in rules_any:
            rules_any.append(rule_id)

    universe = "ontology"
    if any(word in lower for word in _REAL_UNIVERSE_WORDS):
        universe = "real"

    sort = None
    for field, aliases in FIELD_ALIASES:
        for alias in aliases:
            if re.search(rf"{re.escape(alias)}.*(最高|最大|降序)", text, re.IGNORECASE):
                sort = f"-{field}"
                break
            if re.search(rf"{re.escape(alias)}.*(最低|最小|升序)", text, re.IGNORECASE):
                sort = field
                break
        if sort:
            break

    return {
        "universe": universe,
        "filters": [
            {"field": item.field, "op": item.op, "value": item.value, "value2": item.value2}
            for item in filters
        ],
        "industry": industry,
        "rules_any": rules_any,
        "rules_all": rules_all,
        "rules_exclude": rules_exclude,
        "sort": sort,
        "limit": 10,
    }


def _extract_weight(question: str) -> float | None:
    patterns = (
        rf"(?:加仓|增持|买入|配置)(?:[^，。；;]{{0,16}}?)(?:到|至|为)?\s*({_NUMBER_PATTERN})\s*%",
        rf"({_NUMBER_PATTERN})\s*%\s*(?:仓位|权重)",
        rf"(?:权重|仓位)(?:[^，。；;]{{0,8}}?)(?:为|是|到|至)?\s*({_NUMBER_PATTERN})\s*%?",
    )
    for pattern in patterns:
        match = re.search(pattern, question)
        if not match:
            continue
        value = float(match.group(1))
        return value / 100.0 if value > 1 else value
    return None


def _tri_state(question: str, yes_words: tuple[str, ...], no_words: tuple[str, ...]) -> bool | None:
    for word in no_words:
        if word in question:
            return False
    for word in yes_words:
        if word in question:
            return True
    return None


def parse_constraint_question(store: OntologyStore, question: str) -> dict[str, Any]:
    company = store.find_company(question)
    action = "buy"
    if any(word in question for word in ("卖出", "减持", "减仓", "清仓")):
        action = "sell"
    elif any(word in question for word in ("买入", "加仓", "增持", "配置", "提高")):
        action = "buy"
    else:
        action = "hold"
    weight = _extract_weight(question)
    if weight is not None and action == "hold":
        # A proposed allocation is an order intent even when the question does
        # not spell out "buy".
        action = "buy"
    return {
        "company": store._label(company) if company else None,
        "weight": weight,
        "action": action,
        "human_approval": _tri_state(
            question,
            ("已人工批准", "人工批准通过", "已经批准", "已批准"),
            ("未批准", "没有批准", "待批准", "尚未批准", "未经批准"),
        ),
        "compliance_passed": _tri_state(
            question,
            ("合规通过", "合规检查通过", "已通过合规"),
            ("合规未通过", "未通过合规", "没有通过合规"),
        ),
    }


def parse_scenario_question(store: OntologyStore, question: str) -> dict[str, Any]:
    company = store.find_company(question)
    changes = []
    verbs = "|".join(
        re.escape(item)
        for item in DECREASE_WORDS + INCREASE_WORDS + SET_WORDS
        if item
    )
    for field, aliases in FIELD_ALIASES:
        matched = False
        for alias in sorted(aliases, key=len, reverse=True):
            if matched:
                break
            pattern = (
                re.escape(alias)
                + rf"(?:\s*从\s*{_NUMBER_PATTERN}\s*)?"
                + rf"\s*({verbs})\s*(?:至|到)?\s*({_NUMBER_PATTERN})\s*(%|个百分点|个点|亿|万|万亿)?"
            )
            match = re.search(pattern, question, re.IGNORECASE)
            if not match:
                continue
            verb = match.group(1)
            number = float(match.group(2))
            unit = match.group(3)
            if any(word in verb for word in SET_WORDS) or "至" in match.group(0) or "到" in match.group(0):
                value = _scaled_value(field, number, unit)
                changes.append({"field": field, "value": value})
            elif any(word in verb for word in DECREASE_WORDS):
                changes.append({"field": field, "delta": -number})
            else:
                changes.append({"field": field, "delta": number})
            matched = True
    return {
        "company": store._label(company) if company else None,
        "changes": changes,
    }


def parse_evidence_question(store: OntologyStore, question: str) -> dict[str, Any]:
    company = store.find_company(question)
    rule_match = re.search(r"\bR\s?(\d{1,2})\b", question, re.IGNORECASE)
    decision_match = re.search(r"\bDEC[-_A-Za-z0-9]+\b", question, re.IGNORECASE)
    subject = None
    if company is not None:
        subject = store._label(company)
    elif decision_match:
        subject = decision_match.group(0)
    else:
        cleaned = question.strip()
        for prefix in ("请给出", "给出", "查看", "解释一下", "解释", "为什么"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()
        for suffix in ("的证据链", "证据链", "的依据", "为什么", "？", "?"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        subject = cleaned or question
    return {
        "subject": subject,
        "rule_id": f"R{int(rule_match.group(1)):02d}" if rule_match else None,
    }


def is_real_universe_question(question: str) -> bool:
    lower = str(question or "").lower()
    return any(word in lower for word in _REAL_UNIVERSE_WORDS)


__all__ = [
    "FieldFilter",
    "METRIC_FIELDS",
    "METRIC_SPECS",
    "QueryError",
    "check_constraints",
    "detect_industry",
    "is_real_universe_question",
    "normalize_filters",
    "parse_constraint_question",
    "parse_evidence_question",
    "parse_question_filters",
    "parse_scenario_question",
    "run_query",
    "simulate_scenario",
    "trace_evidence",
]
