"""Tool surface exposed to the ontology agent.

Every tool is read-only and returns a compact JSON payload plus citations that
point back into the static ontology explorer.
"""

from __future__ import annotations

import re
from typing import Any

from .marketdata import MarketDataError
from .ontology import CompanyKnowledge, OntologyStore, local_name
from .rules import evaluate_company

TOOL_LABELS = {
    "list_companies": "列出本体公司",
    "get_company_analysis": "读取企业画像与规则信号",
    "screen_companies": "执行本体规则筛选",
    "get_portfolio_analysis": "检查组合与集中度",
    "get_rule": "解释 SWRL 规则",
    "get_policies": "读取 ODRL 政策",
    "search_ontology": "检索本体词汇",
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_companies",
            "description": "列出本体中的 4 家合成示例公司，以及每家公司当前的示例决策。真实 A 股请改用 get_company_analysis。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_analysis",
            "description": (
                "读取一家公司的画像：证券、年报财务、行情估值、风险、决策、证据、合规检查与规则信号。"
                "支持本体示例公司，也支持任意真实 A 股（6 位证券代码或证券简称，走公开行情与年报数据），"
                "分析具体公司时优先调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名称、证券简称或代码，例如 华辰智造、贵州茅台、600000、600519。",
                    }
                },
                "required": ["company"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_companies",
            "description": "对本体中的 4 家合成示例公司执行 SWRL 筛选，返回触发/未触发/无法评估的规则信号和关键指标。只覆盖示例公司，不做全市场筛选；真实 A 股请用 get_company_analysis 逐只分析。",
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_id": {
                        "type": "string",
                        "description": "可选，只保留某条规则，例如 R01、R02、R10。R05/R06 是组合级规则，请改用 get_portfolio_analysis。",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_analysis",
            "description": "读取示例组合的持仓、权重、成本、现价，并执行 R05 止损与 R06 单票集中度检查。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rule",
            "description": "解释一条 SWRL 规则的编号、IF/THEN、阈值、严重程度、责任人，并列出当前哪些公司或持仓触发了它。",
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_id": {
                        "type": "string",
                        "description": "规则编号，例如 R01、R02、R06。",
                    }
                },
                "required": ["rule_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policies",
            "description": "读取 ODRL 政策：权限、禁止、义务、约束、版本与复核日期。适合回答合规、数据使用或人工批准问题。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ontology",
            "description": "在本体的类、属性、个体、SKOS 概念、规则、政策和服务中按标签/定义检索。适合解释某个术语或概念。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要检索的词，例如 价值候选、peTtm、投资决策、R08。",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


def _error(name: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": name,
        "error": {"code": code, "message": message, **extra},
        "citations": [],
    }


def _rule_citation(store: OntologyStore, rule_id: str) -> list[dict[str, str]]:
    rule = store.rule(rule_id)
    if not rule:
        return []
    return [{"id": rule["id"], "iri": rule["iri"], "label": rule["label"], "kind": "rule"}]


def _summary(knowledge: CompanyKnowledge, signals: list[dict[str, Any]]) -> dict[str, Any]:
    decision = knowledge.decision or {}
    risk = knowledge.risk or {}
    recommendation = decision.get("recommendation") or {}
    subtitle = " · ".join(
        part
        for part in [
            (knowledge.security or {}).get("code"),
            (knowledge.company.get("industry") or {}).get("label"),
        ]
        if part
    )
    if knowledge.data_mode == "real":
        quote = knowledge.quote or {}
        financials = knowledge.financials or {}
        valuation = knowledge.valuation or {}
        return {
            "mode": "real",
            "title": knowledge.company.get("label"),
            "subtitle": subtitle,
            "price": quote.get("lastPrice"),
            "changePct": quote.get("changePct"),
            "asOf": quote.get("asOf"),
            "source": quote.get("source"),
            "peTtm": valuation.get("peTtm"),
            "pb": valuation.get("pb"),
            "roe": financials.get("roe"),
            "revenueGrowth": financials.get("revenueGrowth"),
            "triggeredRules": [item["ruleId"] for item in signals if item["status"] == "triggered"],
        }
    return {
        "mode": "example",
        "title": knowledge.company.get("label"),
        "subtitle": subtitle,
        "recommendation": recommendation.get("label") or "无示例决策",
        "confidence": decision.get("confidence"),
        "targetPrice": decision.get("targetPrice"),
        "stopLoss": decision.get("stopLoss"),
        "riskLevel": (risk.get("level") or {}).get("label"),
        "riskScore": risk.get("score"),
        "triggeredRules": [item["ruleId"] for item in signals if item["status"] == "triggered"],
    }


def _company_analysis(store: OntologyStore, query: str) -> dict[str, Any]:
    names = store.company_names()
    subject = store.find_company(query)
    refresh_error: MarketDataError | None = None

    if subject is not None and store.is_real_company(subject):
        code = ((store.company_knowledge(subject).security or {}).get("code")) or ""
        if code and store.market_data is not None:
            try:
                subject = store.real_company(code) or subject
            except MarketDataError as exc:
                refresh_error = exc

    if subject is None:
        try:
            subject = store.real_company(query)
        except MarketDataError as exc:
            return _error(
                "get_company_analysis",
                exc.code,
                f"{exc.message}本体中的示例公司仍可分析。",
                available=[item["label"] for item in names],
            )
        if subject is None:
            if store.market_data is None:
                message = f"本体中没有找到“{query}”，当前未启用真实 A 股数据源。"
            else:
                message = f"没有找到与“{query}”匹配的本体公司或真实 A 股证券。"
            return _error(
                "get_company_analysis",
                "company_not_found",
                message,
                available=[item["label"] for item in names],
                hint="可输入 6 位证券代码或证券简称，例如 600519、贵州茅台。",
            )

    knowledge = store.company_knowledge(subject)
    data = knowledge.to_dict()
    if refresh_error is not None:
        data["dataNote"] += f" 本次刷新失败（{refresh_error.message}），展示上次抓取结果。"
    signals = [
        {
            **store._enrich_signal(item),
            "label": (store.rule(item["ruleId"]) or {}).get("label", item["ruleId"]),
        }
        for item in evaluate_company(data)
    ]
    data["signals"] = signals
    data["ruleSummary"] = {
        "triggered": [item["ruleId"] for item in signals if item["status"] == "triggered"],
        "unknown": [item["ruleId"] for item in signals if item["status"] == "unknown"],
        "critical": [
            item["ruleId"]
            for item in signals
            if item["status"] == "triggered"
            and (store.rule(item["ruleId"]) or {}).get("severity") == "high"
        ],
    }
    citations = []
    for item in signals:
        if item["status"] == "triggered":
            citations.extend(_rule_citation(store, item["ruleId"]))
    citations.extend(knowledge.citations)
    return {
        "ok": True,
        "tool": "get_company_analysis",
        "data": data,
        "summary": _summary(knowledge, signals),
        "citations": _dedupe(citations),
    }


def _screen(store: OntologyStore, rule_id: str | None) -> dict[str, Any]:
    try:
        result = store.screen(rule_id)
    except ValueError as exc:
        return _error(
            "screen_companies",
            "invalid_rule",
            str(exc),
            available=[item["ruleId"] for item in store.rules()],
        )
    return {
        "ok": True,
        "tool": "screen_companies",
        "data": result,
        "citations": result.get("citations", []),
    }


def _portfolio(store: OntologyStore) -> dict[str, Any]:
    result = store.portfolio()
    return {
        "ok": True,
        "tool": "get_portfolio_analysis",
        "data": result,
        "citations": result.get("citations", []),
    }


def _get_rule(store: OntologyStore, rule_id: str) -> dict[str, Any]:
    match = re.search(r"R?\s*(\d{1,2})", str(rule_id or ""), re.IGNORECASE)
    if not match:
        return _error("get_rule", "invalid_rule", "请提供规则编号，例如 R01。")
    normalized = f"R{int(match.group(1)):02d}"
    try:
        result = store.rule_effects(normalized)
    except ValueError:
        return _error(
            "get_rule",
            "invalid_rule",
            f"本体中没有规则 {normalized}。",
            available=[item["ruleId"] for item in store.rules()],
        )
    return {
        "ok": True,
        "tool": "get_rule",
        "data": result,
        "citations": result.get("citations", []),
    }


def _policies(store: OntologyStore) -> dict[str, Any]:
    policies = store.policies()
    citations = []
    for policy in policies:
        citations.append(
            {
                "id": local_name(policy["iri"]),
                "iri": policy["iri"],
                "label": policy["label"],
                "kind": "policy",
            }
        )
    return {
        "ok": True,
        "tool": "get_policies",
        "data": {
            "policies": policies,
            "dataNote": "ODRL 政策为示例声明，不构成真实数据授权合同或法律意见。",
        },
        "citations": _dedupe(citations),
    }


def _search(store: OntologyStore, query: str) -> dict[str, Any]:
    if not str(query or "").strip():
        return _error("search_ontology", "empty_query", "请提供要检索的词。")
    matches = store.search(query)
    citations = [
        {"id": item["id"], "iri": item["iri"], "label": item["label"], "kind": item["kind"]}
        for item in matches
    ]
    return {
        "ok": True,
        "tool": "search_ontology",
        "data": {"query": query, "matches": matches},
        "citations": _dedupe(citations),
    }


def _list(store: OntologyStore) -> dict[str, Any]:
    companies = []
    citations = []
    for subject in store._company_subjects:
        knowledge = store.company_knowledge(subject)
        data = knowledge.to_dict()
        signals = evaluate_company(data)
        triggered = [item["ruleId"] for item in signals if item["status"] == "triggered"]
        decision = knowledge.decision or {}
        recommendation = decision.get("recommendation") or {}
        risk = knowledge.risk or {}
        companies.append(
            {
                "id": knowledge.company.get("id"),
                "iri": knowledge.company.get("iri"),
                "label": knowledge.company.get("label"),
                "code": (knowledge.security or {}).get("code", ""),
                "industry": (knowledge.company.get("industry") or {}).get("label", ""),
                "isST": knowledge.company.get("isST"),
                "recommendation": recommendation.get("label"),
                "confidence": decision.get("confidence"),
                "riskLevel": (risk.get("level") or {}).get("label"),
                "triggeredRules": triggered,
            }
        )
        citations.extend(knowledge.citations[:4])
    return {
        "ok": True,
        "tool": "list_companies",
        "data": {
            "companies": companies,
            "exampleQuestions": [
                "分析贵州茅台",
                "分析华辰智造",
                "哪些公司是价值候选？",
                "组合的集中度风险如何？",
            ],
            "realData": {
                "enabled": store.market_data is not None,
                "provider": getattr(store.market_data, "source_label", ""),
                "note": "真实 A 股请在 get_company_analysis 中按 6 位代码或证券简称查询。",
            },
            "dataNote": (
                "这里只列出本体中的 4 家合成示例公司；真实 A 股可按代码或简称单独查询，"
                "数据来自公开行情与年报接口，可能延迟。"
            ),
        },
        "citations": _dedupe(citations),
    }


def _dedupe(citations: list[dict[str, Any]] | None, limit: int = 18) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in citations or []:
        if not item or not isinstance(item, dict):
            continue
        iri = item.get("iri")
        if not iri or iri in seen:
            continue
        seen.add(iri)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def call_tool(store: OntologyStore, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Execute one tool call and always return a JSON-serialisable result."""

    arguments = arguments or {}
    try:
        if name == "list_companies":
            return _list(store)
        if name == "get_company_analysis":
            return _company_analysis(store, str(arguments.get("company", "")))
        if name == "screen_companies":
            rule_id = arguments.get("rule_id")
            return _screen(store, str(rule_id) if rule_id else None)
        if name == "get_portfolio_analysis":
            return _portfolio(store)
        if name == "get_rule":
            return _get_rule(store, str(arguments.get("rule_id", "")))
        if name == "get_policies":
            return _policies(store)
        if name == "search_ontology":
            return _search(store, str(arguments.get("query", "")))
    except Exception as exc:  # noqa: BLE001 - tool boundary must not crash the agent
        return _error(name, "tool_failed", f"工具执行失败：{type(exc).__name__}")
    return _error(name, "unknown_tool", "未知工具。", available=list(TOOL_LABELS))


__all__ = ["TOOLS", "TOOL_LABELS", "call_tool"]
