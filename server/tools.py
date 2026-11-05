"""Tool surface exposed to the ontology agent.

Every tool is read-only except :func:`acquire_data`, which fetches a public
dataset and writes the resulting facts into the runtime (in-memory) ontology.
Results are compact JSON payloads plus citations that point back into the
static ontology explorer.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .acquisition import (
    SUPPORTED_FIELDS,
    AcquisitionError,
    AcquisitionService,
)
from .cognition import CognitionError, assess_cognition
from .decision import DecisionError, evaluate_trade
from .marketdata import MarketDataError
from .ontology import CompanyKnowledge, OntologyStore, SUPPORTED_MERGE_FIELDS, local_name
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
from .sparql import SparqlError, describe_ontology, run_sparql

TOOL_LABELS = {
    "list_companies": "列出本体公司",
    "get_company_analysis": "读取企业画像与规则信号",
    "compare_companies": "本体同口径多股对比",
    "screen_companies": "执行本体规则筛选",
    "acquire_data": "Agent 自取缺失数据并接入本体",
    "get_portfolio_analysis": "检查组合与集中度",
    "get_rule": "解释 SWRL 规则",
    "get_policies": "读取 ODRL 政策",
    "search_ontology": "检索本体词汇",
    "load_company_data": "加载公司事实到本体图",
    "describe_ontology": "读取本体图式与查询示例",
    "sparql_query": "执行 Agent 生成的只读 SPARQL",
    "query_ontology": "问题驱动的本体查询",
    "trace_evidence": "追踪决策证据链",
    "check_constraints": "检查组合与政策约束",
    "evaluate_trade": "检查买卖点、仓位与风险预算",
    "evaluate_cognition": "按五引擎认知流程形成交易判断",
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
            "name": "acquire_data",
            "description": (
                "当工具结果显示 missingData 或 ruleSummary.unknown（例如缺龙虎榜净买入、封单、连板、"
                "炸板、竞价、情绪数据）时，由 Agent 自己从公开数据源抓取、校验并写入本体，再返回更新后的"
                "规则信号。不要要求用户补数据源或预先写适配器。内置数据源覆盖东方财富龙虎榜、龙虎榜买方"
                "席位与涨停池；其他公开数据可通过 source 传入声明式数据源（url + fields JSONPath 映射）"
                "自行接入，注册后本次进程内复用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "真实 A 股的 6 位代码或证券简称，例如 000417、合百集团。",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(SUPPORTED_FIELDS)},
                        "description": "可选，要补齐的字段；省略则自动补齐该股当前缺失的字段。",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "可选，指定内置数据源 id：eastmoney-billboard、"
                            "eastmoney-billboard-seats、eastmoney-limit-pool。省略则按字段自动选择。"
                        ),
                    },
                    "source": {
                        "type": "object",
                        "description": (
                            "可选，Agent 自带的声明式数据源：{id,label,url,params,select:{path,match},"
                            "fields:{字段:{path,type,scale}},asOfPath,lookbackDays,attribution}。"
                            "仅允许 HTTPS 公开金融域名。"
                        ),
                        "additionalProperties": True,
                    },
                    "asOf": {
                        "type": "string",
                        "description": "可选，数据日期 YYYY-MM-DD，默认今天；历史复盘时使用。",
                    },
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
            "name": "load_company_data",
            "description": (
                "把一家公司的公开事实加载进本体运行时图：真实 A 股会读取行情、年报、估值与短线快照，"
                "示例公司已在本体中。只返回公司标识、数据来源与日期，不返回分析或规则结论；"
                "加载后用 describe_ontology / sparql_query 自己查询。真实个股分析的第一步调用本工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名称、证券简称或 6 位证券代码，例如 有研新材、600206、贵州茅台。",
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
            "name": "describe_ontology",
            "description": (
                "读取本体图式：类、对象属性、数据属性、命名空间前缀和只读 SPARQL 示例。"
                "写自定义查询前先调用本工具，用 focus 按公司、财务、估值、决策、证据、规则、"
                "政策、行业、组合等关键词缩小范围；不带 focus 时返回核心词汇与示例。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "可选，关键词，例如 公司、财务、估值、决策、规则、行业、组合、政策。",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["all", "class", "objectProperty", "dataProperty"],
                        "description": "只返回某一类词汇，默认 all。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少项，默认 30，最大 40。",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sparql_query",
            "description": (
                "直接对内存中的本体 RDF 图执行 Agent 自己生成的只读 SPARQL。参数化工具只是快捷方式，"
                "不是查询边界：任意关系、聚合、路径、否定/缺失条件、跨实体组合都可以用 SPARQL 表达。"
                "只接受 SELECT/ASK；禁止 INSERT/DELETE/LOAD 等更新、SERVICE/FROM 远程加载；"
                "查询必须写 LIMIT，单次最多返回 50 行。可以先 describe_ontology 确认词汇，"
                "再多次执行“生成→执行→按结果修正”，并与其他工具组合。结果含变量绑定、引用和查询路径。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "完整的只读 SPARQL。可以直接使用 ash:、ashd:、ashs:、real:、odrl:、"
                            "rdfs:、skos:、xsd: 等前缀，不必重复声明。"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少行，默认 25，最大 50。",
                    },
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
            "name": "evaluate_trade",
            "description": (
                "检查一只证券的买入/卖出计划是否可执行：账户现金与购买力、组合风险预算与使用率、"
                "单笔风险、预计单票权重、买点/止损/目标价、T+1 可卖数量、人工审批，以及执行质量、"
                "结果和复盘闭环。回答“买点是什么”“能不能买”“卖点是什么”“买多少”“仓位多少”"
                "“风险预算还剩多少”“执行复盘”类问题时优先使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名、证券简称或 6 位代码；不传则使用本体中第一个有交易计划的示例公司。",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["buy", "sell", "both"],
                        "description": "关注方向，默认 both。",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_cognition",
            "description": (
                "按「市场认知 → 机会识别 → 交易判断 → 行为管理 → 结果验证」五引擎流程判断一只证券："
                "先检查市场是否允许交易，再读取板块、个股趋势、量价、竞价、盘中与事件证据，审查反向证据，"
                "按非持仓或已持仓场景形成买入/持有/加仓/减仓/卖出/观望结论，并给出失效条件、行为规则、"
                "判断版本与结果验证。回答“这只股票为什么值得买”“买入后什么情况下继续持有或卖出”"
                "“按认知体系分析”“判断逻辑有没有变”类问题时优先使用。示例公司有完整分析案例；"
                "真实 A 股会读取公开行情/年报并明确标出缺失维度，不伪造胜率。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名、证券简称或 6 位代码；不传则使用本体中的默认分析案例。",
                    },
                    "scenario": {
                        "type": "string",
                        "enum": ["auto", "non_position", "held"],
                        "description": "auto 根据持仓自动判断；non_position 寻找买入机会；held 管理已有持仓。",
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


_SHORT_TERM_FIELDS = {
    "dragonTigerNetBuy",
    "hotMoneySeatCount",
    "sealAmount",
    "limitUpDays",
    "brokenBoardCount",
    "firstLimitUpTime",
    "auctionPriceChange",
    "auctionVolumeRatio",
    "sentimentScore",
    "themeHeatScore",
    "hasNewsCatalyst",
}

_SOURCE_PLANS: dict[str, list[str]] = {
    "dragonTigerNetBuy": ["eastmoney-billboard"],
    "hotMoneySeatCount": ["eastmoney-billboard-seats"],
    "sealAmount": ["eastmoney-limit-pool"],
    "limitUpDays": ["eastmoney-limit-pool"],
    "brokenBoardCount": ["eastmoney-limit-pool"],
    "firstLimitUpTime": ["eastmoney-limit-pool"],
}

_INSTITUTIONAL_MARKERS = (
    "机构专用",
    "沪股通",
    "深股通",
    "陆股通",
    "基金",
    "社保",
    "保险",
    "QFII",
    "券商自营",
    "交易单元",
)


def _missing_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    short = data.get("shortTerm") or {}
    missing: list[dict[str, Any]] = []
    for field, meta in SUPPORTED_FIELDS.items():
        if field not in _SHORT_TERM_FIELDS or short.get(field) is not None:
            continue
        missing.append(
            {
                "field": field,
                "label": meta["label"],
                "rules": meta["rules"],
                "acquirable": field in _SOURCE_PLANS,
                "sources": _SOURCE_PLANS.get(field, []),
                "hint": meta["hint"],
            }
        )
    return missing


def _acquisition_service(store: OntologyStore) -> AcquisitionService | None:
    if getattr(store, "acquisition_enabled", True) is False:
        return None
    service = getattr(store, "acquisition", None)
    if service is None:
        service = AcquisitionService()
        store.acquisition = service
    return service


def _classify_seats(rows: list[Any], *, limit: int = 20) -> list[dict[str, Any]]:
    """Split exchange-published seats into hot-money brokerages and institutions."""

    seats: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        seat_type = "institution" if any(marker in name for marker in _INSTITUTIONAL_MARKERS) else "hot-money"
        seat = {"name": name, "type": seat_type}
        for key in ("netBuy", "buy", "sell", "riseProbability3Day"):
            if row.get(key) is not None:
                seat[key] = row[key]
        seats.append(seat)
        if len(seats) >= limit:
            break
    return seats


def _context_for_company(data: dict[str, Any]) -> dict[str, Any]:
    security = data.get("security") or {}
    company = data.get("company") or {}
    code = str(security.get("code") or company.get("companyCode") or "")
    exchange_code = str((security.get("exchange") or {}).get("id") or "")
    market = "1" if exchange_code.endswith("sse") else "0"
    return {
        "code": code,
        "market": market,
        "secid": f"{market}.{code}",
        "exchange": exchange_code,
    }


def _rule_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before_map = {item.get("ruleId"): item for item in before}
    after_map = {item.get("ruleId"): item for item in after}
    changes: list[dict[str, Any]] = []
    for rule_id in sorted(set(before_map) | set(after_map)):
        old = before_map.get(rule_id) or {}
        new = after_map.get(rule_id) or {}
        if old.get("status") == new.get("status") and old.get("detail") == new.get("detail"):
            continue
        changes.append(
            {
                "ruleId": rule_id,
                "before": old.get("status") or "unknown",
                "after": new.get("status") or "unknown",
                "detail": new.get("detail") or "",
            }
        )
    return changes


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
    if data.get("dataMode") == "real":
        data["missingData"] = _missing_data(data)
    return {
        "ok": True,
        "tool": "get_company_analysis",
        "data": data,
        "summary": _summary(knowledge, signals),
        "citations": _dedupe(citations),
    }


def _load_company_data(store: OntologyStore, query: str) -> dict[str, Any]:
    """Load a company's facts into the graph without returning an analysis.

    The agent uses this only to acquire external facts (real A-shares); all
    ontology questions are then answered with self-generated SPARQL.
    """

    text = str(query or "").strip()
    if not text:
        return _error("load_company_data", "missing_company", "请提供公司名称、证券简称或 6 位证券代码。")
    names = store.company_names()
    subject = store.find_company(text)
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
            subject = store.real_company(text)
        except MarketDataError as exc:
            return _error(
                "load_company_data",
                exc.code,
                f"{exc.message}本体中的示例公司已加载，可直接用 sparql_query 查询。",
                available=[item["label"] for item in names],
            )
        if subject is None:
            message = (
                f"本体中没有找到“{text}”，当前未启用真实 A 股数据源。"
                if store.market_data is None
                else f"没有找到与“{text}”匹配的本体公司或真实 A 股证券。"
            )
            return _error(
                "load_company_data",
                "company_not_found",
                message,
                available=[item["label"] for item in names],
                hint="可输入 6 位证券代码或证券简称，例如 600519、贵州茅台。",
            )

    knowledge = store.company_knowledge(subject)
    company = knowledge.company or {}
    security = knowledge.security or {}
    quote = knowledge.quote or {}
    financials = knowledge.financials or {}
    data: dict[str, Any] = {
        "company": {
            "id": company.get("id"),
            "iri": company.get("iri"),
            "label": company.get("label"),
            "code": security.get("code") or company.get("companyCode"),
            "industry": (company.get("industry") or {}).get("label"),
        },
        "dataMode": knowledge.data_mode,
        "source": quote.get("source") or financials.get("source"),
        "asOf": quote.get("asOf") or financials.get("asOf") or financials.get("reportPeriod"),
        "dataNote": (
            "事实已写入本体内存图；请用 describe_ontology / sparql_query 查询，不要假设存在固定分析工具。"
        ),
        "hint": (
            "常用属性：ash:hasFinancialReport/ash:roe、ash:hasSecurity/ash:hasMarketQuote、"
            "ash:hasValuation/ash:peTtm、ash:hasLimitUpStreak；规则为 ash:RuleArtifact。"
        ),
    }
    if knowledge.data_mode == "real":
        data["missingData"] = _missing_data(knowledge.to_dict())
    if refresh_error is not None:
        data["dataNote"] += f" 本次刷新失败（{refresh_error.message}），使用上次抓取的事实。"
    return {
        "ok": True,
        "tool": "load_company_data",
        "data": data,
        "citations": _dedupe(knowledge.citations[:4]),
    }


def _acquire(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    """Fetch a public dataset and integrate the facts into the runtime graph."""

    company = str(arguments.get("company") or "").strip()
    if not company:
        return _error("acquire_data", "missing_company", "请提供要补齐数据的真实 A 股代码或简称。")

    before = _company_analysis(store, company)
    if not before.get("ok"):
        error = before.get("error") or {}
        extra = {key: value for key, value in error.items() if key not in {"code", "message"}}
        return _error(
            "acquire_data",
            error.get("code") or "company_not_found",
            error.get("message") or "没有找到该证券。",
            **extra,
        )
    data = before.get("data") or {}
    if data.get("dataMode") != "real":
        return _error(
            "acquire_data",
            "not_real_company",
            "只能为真实 A 股获取并接入公开数据；示例公司是合成示例，不能伪造真实数据。",
        )

    requested = arguments.get("fields")
    if requested is not None and not isinstance(requested, list):
        return _error("acquire_data", "invalid_fields", "fields 必须是字段名数组。")
    requested_fields = [str(item) for item in requested] if requested else []
    unknown = [item for item in requested_fields if item not in SUPPORTED_FIELDS]
    if unknown:
        return _error(
            "acquire_data",
            "unknown_field",
            "不支持的数据字段。",
            unknown=unknown,
            available=sorted(SUPPORTED_FIELDS),
        )

    missing = data.get("missingData") or []
    missing_fields = [item["field"] for item in missing]
    fields = requested_fields or missing_fields
    if not fields:
        return {
            "ok": True,
            "tool": "acquire_data",
            "data": {
                "company": {"label": (data.get("company") or {}).get("label"), "code": _code_of(data)},
                "message": "当前没有缺失的可获取短线字段。",
                "acquired": {},
                "remainingMissing": [],
            },
            "citations": [],
        }

    as_of = arguments.get("asOf")
    if as_of is not None:
        as_of = str(as_of).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
            return _error("acquire_data", "invalid_as_of", "asOf 必须是 YYYY-MM-DD。")
        try:
            date.fromisoformat(as_of)
        except ValueError:
            return _error("acquire_data", "invalid_as_of", "asOf 不是有效日期。")

    context = _context_for_company(data)
    if as_of:
        context["base_date"] = as_of
    service = _acquisition_service(store)
    if service is None:
        return _error(
            "acquire_data",
            "acquisition_disabled",
            "服务端已关闭 Agent 自驱数据获取。",
        )
    datasets: list[Any] = []
    errors: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    custom = arguments.get("source")

    if custom is not None:
        if not isinstance(custom, dict):
            return _error("acquire_data", "invalid_source", "source 必须是声明式数据源对象。")
        try:
            dataset = service.fetch_custom(custom, context)
        except AcquisitionError as exc:
            return _error(
                "acquire_data",
                exc.code,
                exc.message,
                sources=service.list_sources(),
                missing=missing,
            )
        values.update(dataset.values)
        datasets.append(dataset)
        try:
            service.register_source(custom)
        except AcquisitionError as exc:
            errors.append({"sourceId": str(custom.get("id") or "custom"), "code": exc.code, "message": exc.message})
    else:
        source_ids = arguments.get("sources")
        if source_ids is not None and not isinstance(source_ids, list):
            return _error("acquire_data", "invalid_sources", "sources 必须是数据源 id 数组。")
        selected: list[str] = [str(item) for item in source_ids] if source_ids else []
        if not selected:
            for field in fields:
                for source_id in _SOURCE_PLANS.get(field, []):
                    if source_id not in selected:
                        selected.append(source_id)
        if not selected:
            return _error(
                "acquire_data",
                "no_builtin_source",
                "这些字段没有内置数据源；请用 source 传入声明式数据源（url + fields 映射）自行接入。",
                missing=missing,
                builtin=service.list_sources(),
            )
        for source_id in selected:
            try:
                dataset = service.fetch(source_id, context)
            except AcquisitionError as exc:
                errors.append({"sourceId": source_id, "code": exc.code, "message": exc.message})
                continue
            values.update(dataset.values)
            datasets.append(dataset)

    seats = values.pop("seats", None)
    if isinstance(seats, list):
        classified = _classify_seats(seats)
        if classified:
            values["seats"] = classified

    merge_values = {
        key: value
        for key, value in values.items()
        if value is not None and (key in SUPPORTED_MERGE_FIELDS or key == "seats")
    }
    if not merge_values:
        message = "没有获取到可写入本体的数据。"
        if errors:
            message += " " + "；".join(item["message"] for item in errors)
        return _error(
            "acquire_data",
            "no_data",
            message,
            errors=errors,
            sources=[dataset.as_dict() for dataset in datasets],
            missing=missing,
        )

    label = "、".join(dict.fromkeys(dataset.label for dataset in datasets)) or "公开数据源"
    source_url = datasets[0].url if datasets else ""
    as_of_value = max((dataset.as_of for dataset in datasets), default="") or (as_of or "")
    attribution = "；".join(sorted({dataset.attribution for dataset in datasets if dataset.attribution}))
    as_of_by_field = {
        key: dataset.as_of
        for dataset in datasets
        for key in dataset.values
        if dataset.as_of
    }
    try:
        store.merge_short_term(
            _code_of(data),
            merge_values,
            source_label=label,
            source_url=source_url,
            as_of=as_of_value,
            as_of_by_field=as_of_by_field,
            attribution=attribution,
        )
    except ValueError as exc:
        return _error("acquire_data", "merge_failed", str(exc))

    after = _company_analysis(store, _code_of(data))
    after_data = after.get("data") or {}
    changes = _rule_changes(data.get("signals") or [], after_data.get("signals") or [])
    relevant_rules = {
        rule_id
        for field in fields
        for rule_id in SUPPORTED_FIELDS[field]["rules"]
    }
    relevant_rules.update(item["ruleId"] for item in changes)
    signals = [
        signal
        for signal in after_data.get("signals") or []
        if signal.get("ruleId") in relevant_rules
    ]
    acquired = {key: value for key, value in merge_values.items() if key != "seats"}
    if "seats" in merge_values:
        acquired["hotMoneySeatCount"] = sum(
            1 for seat in merge_values["seats"] if seat.get("type") == "hot-money"
        )
        acquired["seats"] = [
            {"name": seat["name"], "type": seat.get("type")}
            for seat in merge_values["seats"]
        ]
    remaining = [
        item
        for item in (after_data.get("missingData") or [])
        if item["field"] in fields
    ]
    return {
        "ok": True,
        "tool": "acquire_data",
        "data": {
            "company": {
                "label": (after_data.get("company") or {}).get("label"),
                "code": _code_of(after_data),
            },
            "dataMode": "real",
            "acquired": acquired,
            "sources": [dataset.as_dict() for dataset in datasets],
            "errors": errors,
            "asOf": as_of_value,
            "ruleChanges": changes,
            "ruleSummary": after_data.get("ruleSummary"),
            "signals": signals,
            "shortTerm": after_data.get("shortTerm"),
            "dataNote": after_data.get("dataNote"),
            "remainingMissing": remaining,
        },
        "summary": after.get("summary"),
        "citations": after.get("citations") or [],
    }


def _code_of(data: dict[str, Any]) -> str:
    security = data.get("security") or {}
    company = data.get("company") or {}
    return str(security.get("code") or company.get("companyCode") or "")


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
    text = str(rule_id or "")
    prefixed = re.search(r"(OP|VP|AUC|MKT|EVT|POS|RSK|EVA)\s*-?\s*(\d{1,3})", text, re.IGNORECASE)
    if prefixed:
        normalized = f"{prefixed.group(1).upper()}-{int(prefixed.group(2)):03d}"
    else:
        match = re.search(r"R?\s*(\d{1,2})", text, re.IGNORECASE)
        if not match:
            return _error("get_rule", "invalid_rule", "请提供规则编号，例如 R01 或 OP-001。")
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


def _describe(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        data = describe_ontology(
            store,
            focus=arguments.get("focus", ""),
            kind=arguments.get("kind", "all"),
            limit=arguments.get("limit") or 30,
        )
    except SparqlError as exc:
        return _error("describe_ontology", exc.code, exc.message, **exc.extra)
    return {
        "ok": True,
        "tool": "describe_ontology",
        "data": data,
        "queryPath": data.get("queryPath", []),
    }


def _sparql(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        data = run_sparql(
            store,
            arguments.get("query", ""),
            limit=arguments.get("limit") or 25,
        )
    except SparqlError as exc:
        return _error("sparql_query", exc.code, exc.message, **exc.extra)
    return {
        "ok": True,
        "tool": "sparql_query",
        "data": data,
        "citations": data.get("citations", []),
        "queryPath": data.get("queryPath", []),
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


def _trade(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    company = str(arguments.get("company")) if arguments.get("company") else None
    side = str(arguments.get("side") or "both")
    try:
        data = evaluate_trade(store, company=company, side=side)
    except DecisionError as exc:
        return _error("evaluate_trade", exc.code, exc.message, **exc.extra)
    return {
        "ok": True,
        "tool": "evaluate_trade",
        "data": data,
        "citations": data.get("citations", []),
        "queryPath": data.get("queryPath", []),
    }


def _cognition(store: OntologyStore, arguments: dict[str, Any]) -> dict[str, Any]:
    company = str(arguments.get("company")) if arguments.get("company") else None
    scenario = str(arguments.get("scenario") or "auto")
    try:
        data = assess_cognition(store, company=company, scenario=scenario)
    except CognitionError as exc:
        return _error("evaluate_cognition", exc.code, exc.message, **exc.extra)
    return {
        "ok": True,
        "tool": "evaluate_cognition",
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
        if name == "acquire_data":
            return _acquire(store, arguments)
        if name == "get_portfolio_analysis":
            return _portfolio(store)
        if name == "get_rule":
            return _get_rule(store, str(arguments.get("rule_id", "")))
        if name == "get_policies":
            return _policies(store)
        if name == "search_ontology":
            return _search(store, str(arguments.get("query", "")))
        if name == "load_company_data":
            return _load_company_data(store, str(arguments.get("company", "")))
        if name == "describe_ontology":
            return _describe(store, arguments)
        if name == "sparql_query":
            return _sparql(store, arguments)
        if name == "query_ontology":
            return _query(store, arguments)
        if name == "trace_evidence":
            return _trace(store, arguments)
        if name == "check_constraints":
            return _constraints(store, arguments)
        if name == "evaluate_trade":
            return _trade(store, arguments)
        if name == "evaluate_cognition":
            return _cognition(store, arguments)
        if name == "simulate_scenario":
            return _scenario(store, arguments)
    except Exception as exc:  # noqa: BLE001 - tool boundary must not crash the agent
        return _error(name, "tool_failed", f"工具执行失败：{type(exc).__name__}")
    return _error(name, "unknown_tool", "未知工具。", available=list(TOOL_LABELS))


# The LLM works directly against the ontology: schema discovery, a data-loading
# primitive for external facts, agent-driven acquisition of missing public data,
# and arbitrary read-only SPARQL.  The curated analysis tools remain available to
# the deterministic rules-mode fallback, but are deliberately hidden from the LLM
# so ontology usage is agent-generated.
LLM_TOOL_NAMES: tuple[str, ...] = (
    "load_company_data",
    "acquire_data",
    "describe_ontology",
    "sparql_query",
)
LLM_TOOLS: list[dict[str, Any]] = [
    next(tool for tool in TOOLS if tool["function"]["name"] == name)
    for name in LLM_TOOL_NAMES
]


__all__ = [
    "LLM_TOOL_NAMES",
    "LLM_TOOLS",
    "TOOLS",
    "TOOL_LABELS",
    "call_tool",
]
