"""Tool surface exposed to the ontology agent.

Every tool is read-only and returns a compact JSON payload plus citations that
point back into the static ontology explorer.
"""

from __future__ import annotations

import re
from typing import Any

from .marketdata import MarketDataError
from .ontology import CompanyKnowledge, OntologyStore, local_name
from .query import (
    COMPARISON_FIELDS,
    METRIC_FIELDS,
    QueryError,
    check_constraints,
    compare_companies,
    run_query,
    simulate_scenario,
    trace_evidence,
)
from .rules import evaluate_company

TOOL_LABELS = {
    "list_companies": "列出本体公司",
    "get_company_analysis": "读取企业画像与规则信号",
    "compare_companies": "本体同口径多股对比",
    "screen_companies": "执行本体规则筛选",
    "get_portfolio_analysis": "检查组合与集中度",
    "get_rule": "解释 SWRL 规则",
    "get_policies": "读取 ODRL 政策",
    "search_ontology": "检索本体词汇",
    "query_ontology": "问题驱动的本体查询",
    "trace_evidence": "追踪决策证据链",
    "check_constraints": "检查组合与政策约束",
    "simulate_scenario": "模拟情景下的规则变化",
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_companies",
            "description": "列出本体中的合成示例公司，以及每家公司当前的示例决策。真实 A 股请改用 get_company_analysis 或 query_ontology。",
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
            "name": "compare_companies",
            "description": (
                "对 2–5 只股票做本体同口径对比：统一读取 ROE、PE/PB、负债率、增速、市值、换手率、"
                "MA20/MA60、连板/炸板，执行同一套 R01–R21 规则，并返回 RDF 属性路径与证据。"
                "多股对比、哪个更好、横向比较优先使用本工具，不要逐只调用 get_company_analysis 超过 2 只。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "companies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 5,
                        "description": "2–5 只股票，名称或 6 位代码，例如 贵州茅台、600519、中国平安。",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(COMPARISON_FIELDS)},
                        "description": "可选，只对比这些本体字段；默认使用核心财务/估值/中短期字段。",
                    },
                },
                "required": ["companies"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_companies",
            "description": "对本体中的合成示例公司执行 SWRL 规则筛选，返回触发/未触发/无法评估的规则信号和关键指标。只覆盖本体中已有的公司；按业务指标筛选或跨真实 A 股样本筛选请用 query_ontology。",
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
    {
        "type": "function",
        "function": {
            "name": "query_ontology",
            "description": (
                "问题驱动的本体查询：按业务条件跨公司筛选、横向比较。filters 把 ROE、PE、负债率、"
                "营收增速、风险分数、市值、换手率、组合权重映射到本体属性路径，返回命中公司、"
                "命中依据的 RDF 路径、命中的 SWRL 规则和引用。universe=ontology 覆盖本体示例公司及"
                "本次运行已加载的真实 A 股；universe=real 扫描真实 A 股行情单页样本，仅支持行情/估值字段，"
                "年报指标需要先缩小范围再逐只分析。筛选类问题优先使用本工具，可替代固定规则筛选。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "universe": {
                        "type": "string",
                        "enum": ["ontology", "real"],
                        "description": "ontology（默认）查本体已有公司；real 扫真实 A 股行情样本。",
                    },
                    "filters": {
                        "type": "array",
                        "description": "多个条件按 AND 组合。positionWeight 用 0-1 小数（0.12 = 12%）。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string", "enum": list(METRIC_FIELDS)},
                                "op": {
                                    "type": "string",
                                    "enum": ["gte", "lte", "gt", "lt", "eq", "between"],
                                },
                                "value": {"type": "number"},
                                "value2": {"type": "number"},
                            },
                            "required": ["field", "op", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "industry": {"type": "string", "description": "行业标签，例如 半导体、银行、新能源。"},
                    "rules_any": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "任一规则触发才保留，例如 R01。",
                    },
                    "rules_all": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "全部规则触发才保留。",
                    },
                    "rules_exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "这些规则均未触发才保留。",
                    },
                    "sort": {
                        "type": "string",
                        "description": "排序字段，前缀 - 表示降序，例如 -roe、peTtm。",
                    },
                    "limit": {"type": "integer", "description": "最多返回多少家公司，默认 10。"},
                    "sample": {
                        "type": "integer",
                        "description": "universe=real 时读取的行情样本数，默认 120，最大 200。",
                    },
                    "include_evidence": {
                        "type": "boolean",
                        "description": "是否返回每条命中事实的 RDF 属性路径，默认 true。",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trace_evidence",
            "description": (
                "从公司、决策、规则或政策出发，沿本体中显式建模的证据谓词（aboutCompany、basedOn、"
                "governedBy、hasRationale、hasRiskAssessment、hasSource、dataSource 等）逐层遍历，"
                "返回证据链节点、边、数据来源/日期/版本。适合“为什么”“证据”“溯源”“审计”类问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "公司名、决策编号（DEC-...）、规则编号（R01）或政策 uid。",
                    },
                    "depth": {"type": "integer", "description": "遍历深度 1-4，默认 3。"},
                    "limit": {"type": "integer", "description": "节点上限，默认 40，最大 60。"},
                    "rule_id": {
                        "type": "string",
                        "description": "可选，把某条规则的解释节点附到证据链上。",
                    },
                },
                "required": ["subject"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_constraints",
            "description": (
                "检查一个拟议仓位或当前组合是否满足组合约束与 ODRL 政策：R06 单票集中度、R07 限制名单、"
                "R11 高风险买入复核，以及 trade-guard 的人工批准与合规检查双前置条件。适合“能不能买/加仓”"
                "“权重是否超限”“为什么被拦截”类问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "可选；不传则检查当前示例组合。"},
                    "weight": {
                        "type": "number",
                        "description": "拟议组合权重，0-1 小数（0.15 = 15%）；不传则用当前持仓权重。",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["buy", "sell", "hold"],
                        "description": "拟议动作，默认 buy。",
                    },
                    "human_approval": {
                        "type": "boolean",
                        "description": "是否已取得人工批准；不传表示未知。",
                    },
                    "compliance_passed": {
                        "type": "boolean",
                        "description": "合规检查是否通过；不传表示未知。",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_scenario",
            "description": (
                "what-if 情景模拟：在内存中的公司事实副本上修改财务、估值、风险或持仓指标，重新执行全部"
                "确定性 SWRL 规则并对比前后状态。支持 roe、debtRatio、interestCoverage、revenueGrowth、"
                "profitGrowth、peTtm、pb、riskScore、lastPrice、avgCost、positionWeight。不写回本体，也不是预测。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "公司名、证券简称或代码。"},
                    "changes": {
                        "type": "array",
                        "description": "假设变化列表。delta 是相对变化，value 是绝对设定；至少给一个。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {
                                    "type": "string",
                                    "enum": [
                                        "roe",
                                        "debtRatio",
                                        "interestCoverage",
                                        "revenueGrowth",
                                        "profitGrowth",
                                        "peTtm",
                                        "pb",
                                        "riskScore",
                                        "lastPrice",
                                        "avgCost",
                                        "positionWeight",
                                    ],
                                },
                                "delta": {"type": "number"},
                                "value": {"type": "number"},
                            },
                            "required": ["field"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["company", "changes"],
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


def _compare(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    companies = arguments.get("companies") or []
    if not isinstance(companies, list):
        return _error("compare_companies", "invalid_companies", "companies 必须是字符串数组。")
    fields = arguments.get("fields")
    if fields is not None and not isinstance(fields, list):
        return _error("compare_companies", "invalid_fields", "fields 必须是字段数组。")
    try:
        data = compare_companies(
            store,
            [str(item) for item in companies],
            fields=[str(item) for item in fields] if fields else None,
        )
    except QueryError as exc:
        return _error("compare_companies", exc.code, exc.message, **exc.extra)
    except MarketDataError as exc:
        return _error("compare_companies", exc.code, exc.message)
    return {
        "ok": True,
        "tool": "compare_companies",
        "data": data,
        "citations": data.get("citations", []),
        "queryPath": data.get("queryPath", []),
    }


def _query(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        data = run_query(store, arguments)
    except QueryError as exc:
        return _error("query_ontology", exc.code, exc.message, **exc.extra)
    except MarketDataError as exc:
        return _error("query_ontology", exc.code, exc.message)
    return {
        "ok": True,
        "tool": "query_ontology",
        "data": data,
        "citations": data.get("citations", []),
        "queryPath": data.get("queryPath", []),
    }


def _trace(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        data = trace_evidence(
            store,
            str(arguments.get("subject", "")),
            depth=int(arguments.get("depth") or 3),
            limit=int(arguments.get("limit") or 40),
            rule_id=(
                str(arguments.get("rule_id"))
                if arguments.get("rule_id")
                else None
            ),
        )
    except QueryError as exc:
        return _error("trace_evidence", exc.code, exc.message, **exc.extra)
    except (TypeError, ValueError):
        return _error("trace_evidence", "invalid_arguments", "depth/limit 必须是整数。")
    return {
        "ok": True,
        "tool": "trace_evidence",
        "data": data,
        "citations": data.get("citations", []),
        "queryPath": data.get("queryPath", []),
    }


def _constraints(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        data = check_constraints(
            store,
            company=(
                str(arguments.get("company"))
                if arguments.get("company")
                else None
            ),
            weight=arguments.get("weight"),
            action=str(arguments.get("action") or "buy"),
            human_approval=arguments.get("human_approval"),
            compliance_passed=arguments.get("compliance_passed"),
        )
    except QueryError as exc:
        return _error("check_constraints", exc.code, exc.message, **exc.extra)
    return {
        "ok": True,
        "tool": "check_constraints",
        "data": data,
        "citations": data.get("citations", []),
        "queryPath": data.get("queryPath", []),
    }


def _scenario(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    company = str(arguments.get("company", ""))
    changes = arguments.get("changes")
    if not company:
        return _error("simulate_scenario", "missing_company", "请提供要模拟的公司。")
    try:
        data = simulate_scenario(store, company=company, changes=changes)
    except QueryError as exc:
        return _error("simulate_scenario", exc.code, exc.message, **exc.extra)
    return {
        "ok": True,
        "tool": "simulate_scenario",
        "data": data,
        "citations": data.get("citations", []),
        "queryPath": data.get("queryPath", []),
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
                "PE 低于 20 且 ROE 高于 15 的公司",
                "华辰智造的决策证据链",
                "如果加仓华辰智造到 15%，组合约束允许吗？",
                "如果华辰智造 ROE 下降 5 个百分点会怎样？",
            ],
            "realData": {
                "enabled": store.market_data is not None,
                "provider": getattr(store.market_data, "source_label", ""),
                "note": (
                    "单只真实 A 股请在 get_company_analysis 中按 6 位代码或证券简称查询；"
                    "真实市场横截面样本可用 query_ontology 的 universe=real。"
                ),
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
        if name == "compare_companies":
            return _compare(store, arguments)
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
        if name == "query_ontology":
            return _query(store, arguments)
        if name == "trace_evidence":
            return _trace(store, arguments)
        if name == "check_constraints":
            return _constraints(store, arguments)
        if name == "simulate_scenario":
            return _scenario(store, arguments)
    except Exception as exc:  # noqa: BLE001 - tool boundary must not crash the agent
        return _error(name, "tool_failed", f"工具执行失败：{type(exc).__name__}")
    return _error(name, "unknown_tool", "未知工具。", available=list(TOOL_LABELS))


__all__ = ["TOOLS", "TOOL_LABELS", "call_tool"]
