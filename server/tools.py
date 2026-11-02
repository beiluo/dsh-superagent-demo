"""Tool surface exposed to the ontology agent.

Every tool is read-only and returns a compact JSON payload plus citations that
point back into the static ontology explorer.
"""

from __future__ import annotations

import re
from typing import Any

from .ontology import CompanyKnowledge, OntologyStore, local_name
from .rules import evaluate_company

TOOL_LABELS = {
    "list_companies": "列出本体公司",
    "get_company_analysis": "读取企业画像与决策链",
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
            "description": "列出本体中的所有合成示例公司，以及每家公司当前的示例决策。适合回答“有哪些公司/标的”。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_analysis",
            "description": "读取一家公司的完整本体画像：证券、年报财务、行情估值、风险、示例决策、证据、合规检查与规则信号。分析具体公司时优先调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名称、证券简称或代码，例如 华辰智造、宁源新能源、600000、300000。",
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
            "description": "对全部合成公司执行 SWRL 筛选，返回触发/未触发/无法评估的规则信号和关键指标。适合回答“哪些公司符合某条件/有哪些候选”。",
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
    return {
        "title": knowledge.company.get("label"),
        "subtitle": " · ".join(
            part
            for part in [
                (knowledge.security or {}).get("code"),
                (knowledge.company.get("industry") or {}).get("label"),
            ]
            if part
        ),
        "recommendation": recommendation.get("label") or "无示例决策",
        "confidence": decision.get("confidence"),
        "targetPrice": decision.get("targetPrice"),
        "stopLoss": decision.get("stopLoss"),
        "riskLevel": (risk.get("level") or {}).get("label"),
        "riskScore": risk.get("score"),
        "triggeredRules": [item["ruleId"] for item in signals if item["status"] == "triggered"],
    }


def _company_analysis(store: OntologyStore, query: str) -> dict[str, Any]:
    subject = store.find_company(query)
    if not subject:
        names = store.company_names()
        return _error(
            "get_company_analysis",
            "company_not_found",
            f"本体中没有找到“{query}”。",
            available=[item["label"] for item in names],
        )
    knowledge = store.company_knowledge(subject)
    data = knowledge.to_dict()
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
                "分析华辰智造",
                "哪些公司是价值候选？",
                "组合的集中度风险如何？",
                "R02 是什么规则？",
            ],
            "dataNote": "本体只包含 4 家合成示例公司，不支持真实证券或实时行情。",
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
