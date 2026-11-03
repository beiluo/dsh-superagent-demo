"""Markdown answer composers for the deterministic (rules-only) agent mode."""

from __future__ import annotations

from typing import Any

from .rules import fmt_money, fmt_num, fmt_pct, fmt_price, fmt_ratio, fmt_weight

KIND_LABELS = {
    "class": "类",
    "objectProperty": "对象属性",
    "dataProperty": "数据属性",
    "individual": "个体",
    "concept": "概念",
    "rule": "规则",
    "policy": "政策",
    "service": "服务",
    "real": "真实数据",
}

STATUS_LABELS = {"triggered": "触发", "clear": "未触发", "unknown": "未知"}
SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}

BOUNDARY = "**边界**：以上全部为本体中的合成示例数据，不构成投资建议；本体不连接真实行情或交易通道。"


def _pct(value: Any) -> str:
    return f"{value * 100:.0f}%" if isinstance(value, (int, float)) else "—"


def _signal_lines(signals: list[dict[str, Any]], *, show_clear: bool = False) -> list[str]:
    lines = []
    for item in signals:
        if not show_clear and item["status"] != "triggered":
            continue
        status = STATUS_LABELS.get(item["status"], item["status"])
        rule_id = item.get("ruleId", "")
        label = item.get("label") or rule_id
        lines.append(f"- **{status}** `{rule_id}` {label}：{item.get('detail', '')}")
    return lines


def compose_company(data: dict[str, Any]) -> str:
    company = data.get("company") or {}
    security = data.get("security") or {}
    financials = data.get("financials") or {}
    quote = data.get("quote") or {}
    valuation = data.get("valuation") or {}
    risk = data.get("risk") or {}
    decision = data.get("decision") or {}
    position = data.get("position") or {}
    signals = data.get("signals") or []
    data_mode = data.get("dataMode") or "example"
    is_real = data_mode == "real"

    label = company.get("label") or "公司"
    code = security.get("code") or company.get("companyCode") or ""
    industry = (company.get("industry") or {}).get("label")
    title = f"### {label}" + (f"（{code}）" if code else "")
    if is_real:
        title += " · 真实数据"

    lines = [title]
    if industry:
        lines.append(f"**行业**：{industry}；**数据日期**：行情 {quote.get('asOf') or '—'}，估值 {valuation.get('asOf') or '—'}。")
    if is_real:
        lines.append(
            f"**数据来源**：{quote.get('source') or '东方财富公开行情接口'} · "
            f"行情 {quote.get('asOf') or '—'} · 年报 {financials.get('period') or '—'}。"
        )

    recommendation = decision.get("recommendation") or {}
    if is_real:
        lines.append("**说明**：真实数据模式只呈现公开数据与规则信号，不生成目标价、止损价或买卖建议。")
    elif decision:
        lines.append(
            "**本体示例结论**："
            f"{recommendation.get('label') or '—'} · 置信度 {_pct(decision.get('confidence'))} · "
            f"目标价 {fmt_price(decision.get('targetPrice'))} · 止损价 {fmt_price(decision.get('stopLoss'))} · "
            f"风险 {(risk.get('level') or {}).get('label') or '—'}（{fmt_num(risk.get('score'))}/100） · "
            f"期限 {(decision.get('horizon') or {}).get('label') or '—'}。"
        )
    else:
        lines.append("**本体示例结论**：本体中没有为该公司生成示例决策。")

    if financials:
        lines.append(
            "**财务**："
            f"ROE {fmt_pct(financials.get('roe'))} · 资产负债率 {fmt_pct(financials.get('debtRatio'))} · "
            f"利息保障 {fmt_ratio(financials.get('interestCoverage'))} · 营收增速 {fmt_pct(financials.get('revenueGrowth'))} · "
            f"净利润 {fmt_money(financials.get('netProfit'))}（{financials.get('period') or '—'} 年报）。"
        )
    if quote or valuation:
        quote_parts = [
            f"最新价 {fmt_price(quote.get('lastPrice'))}",
            f"换手率 {fmt_pct(quote.get('turnoverRate'))}",
            f"PE(TTM) {fmt_num(valuation.get('peTtm'))}",
            f"PB {fmt_num(valuation.get('pb'))}",
        ]
        if valuation.get("dividendYield") is not None:
            quote_parts.append(f"股息率 {fmt_pct(valuation.get('dividendYield'))}")
        lines.append("**行情与估值**：" + " · ".join(quote_parts) + "。")

    triggered = [item for item in signals if item["status"] == "triggered"]
    lines.append("")
    lines.append("**规则信号**" + ("（阈值仍为演示常量）" if is_real else ""))
    if triggered:
        lines.extend(_signal_lines(triggered))
    else:
        lines.append("- 当前没有 SWRL 规则触发。")
    unknown = [item["ruleId"] for item in signals if item["status"] == "unknown"]
    if unknown:
        if is_real:
            lines.append(
                f"- 另有 {len(unknown)} 条规则不适用或缺少数据：{', '.join(unknown)}"
                "（组合仓位与决策类规则需要持仓或人工决策输入）。"
            )
        else:
            lines.append(f"- 另有 {len(unknown)} 条规则因缺少数据无法评估：{', '.join(unknown)}。")

    if risk and not is_real:
        factors = "、".join(item.get("label", "") for item in risk.get("factors") or [])
        factor_text = f"；风险因子：{factors}" if factors else ""
        lines.append("")
        lines.append(f"**风险**：{(risk.get('level') or {}).get('label') or '—'}（{fmt_num(risk.get('score'))}/100）{factor_text}。")
        if risk.get("comment"):
            lines.append(f"- {risk['comment']}")

    if decision:
        evidence = decision.get("evidence") or []
        policies = decision.get("policies") or []
        compliance = decision.get("compliance") or {}
        passed = "通过" if compliance.get("passed") else "未通过"
        lines.append("")
        lines.append(
            f"**决策链**：{decision.get('decisionId') or '—'} · 证据 {len(evidence)} 条 · "
            f"合规检查{passed} · 政策 {len(policies)} 项。"
        )
        if compliance.get("note"):
            lines.append(f"- 合规备注：{compliance['note']}")
        counter = (decision.get("rationale") or {}).get("counterArgument")
        if counter:
            lines.append(f"- 反方观点：{counter}")
        if position.get("weight") is not None:
            lines.append(f"- 组合权重：{fmt_weight(position.get('weight'))}（成本 {fmt_price(position.get('avgCost'))}）。")

    lines.append("")
    if is_real:
        lines.append(
            f"**边界**：真实行情与年报数据来自{quote.get('source') or '公开数据接口'}，"
            "可能存在延迟或口径差异；规则阈值仍是本体演示常量，不构成投资建议，也不连接交易通道。"
        )
    else:
        lines.append(BOUNDARY)
    return "\n".join(lines)


def compose_screen(data: dict[str, Any]) -> str:
    companies = data.get("companies") or []
    rule_filter = data.get("ruleFilter")
    lines = ["### 本体筛选结果"]
    if rule_filter:
        lines.append(f"只显示规则 `{rule_filter}` 的评估结果。")
    lines.append("")
    for company in companies:
        recommendation = (company.get("recommendation") or {}).get("label") or "无示例决策"
        metrics = company.get("metrics") or {}
        triggered = company.get("triggered") or []
        signal_text = "、".join(triggered) if triggered else "无"
        lines.append(
            f"- **{company.get('label')}（{company.get('code') or '—'}）**：{recommendation}；"
            f"ROE {fmt_pct(metrics.get('roe'))} · PE(TTM) {fmt_num(metrics.get('peTtm'))} · "
            f"负债率 {fmt_pct(metrics.get('debtRatio'))} · 风险 {fmt_num(metrics.get('riskScore'))}；"
            f"触发规则：{signal_text}。"
        )
        if rule_filter:
            for signal in company.get("signals") or []:
                lines.append(f"  - {STATUS_LABELS.get(signal['status'], signal['status'])}：{signal.get('detail', '')}")
    lines.append("")
    lines.append("**阈值来源**：R01（ROE ≥ 15%、PE ≤ 20、净利润 > 0、非 ST）、R02（负债率 ≥ 70%、利息保障 < 2）、R10（营收增速 ≥ 25%、净利增速 ≥ 20%、PE > 40）等，均为示例常量。")
    lines.append(BOUNDARY)
    return "\n".join(lines)


def compose_portfolio(data: dict[str, Any]) -> str:
    portfolio = data.get("portfolio") or {}
    positions = data.get("positions") or []
    signals = data.get("signals") or {}
    lines = [f"### 组合：{portfolio.get('label') or '示例组合'}"]
    if portfolio.get("strategy"):
        lines.append(f"策略：{portfolio['strategy'].get('label')}；基准：{(portfolio.get('benchmark') or {}).get('label') or '—'}。")
    lines.append("")
    for item in positions:
        lines.append(
            f"- **{item.get('label')}**（{item.get('company', {}).get('label')}）：权重 {fmt_weight(item.get('weight'))} · "
            f"成本 {fmt_price(item.get('avgCost'))} · 现价 {fmt_price(item.get('lastPrice'))}。"
        )
        for rule_id in ("R05", "R06"):
            signal = (item.get("signals") or {}).get(rule_id)
            if signal and signal["status"] == "triggered":
                lines.append(f"  - **触发** `{rule_id}`：{signal['detail']}")
    lines.append("")
    r06 = signals.get("R06") or {}
    r05 = signals.get("R05") or {}
    lines.append(f"**集中度 R06**：{STATUS_LABELS.get(r06.get('status'), '—')} — {r06.get('detail', '')}")
    lines.append(f"**止损 R05**：{STATUS_LABELS.get(r05.get('status'), '—')} — {r05.get('detail', '')}")
    lines.append(f"**总权重**：{fmt_weight(data.get('totalWeight'))}（只统计本体中建模的持仓）；单票上限 {fmt_weight(data.get('maxSingleWeight'))}。")
    lines.append("")
    lines.append(BOUNDARY)
    return "\n".join(lines)


def compose_rule(data: dict[str, Any]) -> str:
    rule = data.get("rule") or {}
    affected = data.get("affected") or []
    lines = [f"### {rule.get('ruleId')} · {rule.get('label')}"]
    if rule.get("comment"):
        lines.append(rule["comment"])
    lines.append("")
    if rule.get("ruleIf"):
        lines.append(f"- **IF**：{rule['ruleIf']}")
    if rule.get("ruleThen"):
        lines.append(f"- **THEN**：{rule['ruleThen']}")
    lines.append(
        f"- **严重程度**：{SEVERITY_LABELS.get(rule.get('severity'), rule.get('severity') or '—')}；**责任人**：{rule.get('owner') or '—'}；"
        f"**版本**：{rule.get('version') or '—'}；**状态**：{rule.get('status') or '—'}。"
    )
    if rule.get("uses"):
        lines.append(f"- **读取属性**：{'、'.join(item.get('label', '') for item in rule['uses'])}")
    if rule.get("thresholds"):
        values = "、".join(f"{key}={value}" for key, value in rule["thresholds"].items())
        lines.append(f"- **示例阈值**：{values}")
    lines.append("")
    triggered = [item for item in affected if item["status"] == "triggered"]
    if triggered:
        lines.append("**当前触发**")
        for item in triggered:
            lines.append(f"- {item.get('subjectLabel')}：{item.get('detail')}")
    else:
        lines.append("当前没有对象触发该规则。")
    unknown = [item for item in affected if item["status"] == "unknown"]
    if unknown:
        lines.append(f"另有 {len(unknown)} 个对象因缺少数据无法评估。")
    lines.append("")
    lines.append(BOUNDARY)
    return "\n".join(lines)


def compose_policies(data: dict[str, Any]) -> str:
    policies = data.get("policies") or []
    lines = ["### ODRL 政策"]
    for policy in policies:
        lines.append("")
        lines.append(f"**{policy.get('label')}**（`{policy.get('uid')}`，v{policy.get('version') or '—'}）")
        if policy.get("description"):
            lines.append(policy["description"])
        for key, label in (("permissions", "权限"), ("prohibitions", "禁止"), ("obligations", "义务")):
            rules = policy.get(key) or []
            action_text = "；".join(
                "、".join(item.get("actions") or []) or "—" for item in rules
            )
            lines.append(f"- {label} {len(rules)} 项：{action_text}")
    lines.append("")
    lines.append(BOUNDARY)
    return "\n".join(lines)


def compose_search(data: dict[str, Any]) -> str:
    query = data.get("query") or ""
    matches = data.get("matches") or []
    lines = [f"### 本体检索：{query}"]
    if not matches:
        lines.append("没有找到匹配的本体实体。可以换一个更短的关键词。")
    for item in matches:
        kind = KIND_LABELS.get(item.get("kind"), item.get("kind") or "")
        extra = f"（{item['extra']}）" if item.get("extra") else ""
        lines.append(f"- **{kind} · {item.get('label')}**{extra}：{item.get('comment') or '暂无定义。'}")
    lines.append("")
    lines.append(BOUNDARY)
    return "\n".join(lines)


def compose_list(data: dict[str, Any]) -> str:
    companies = data.get("companies") or []
    lines = ["### 本体中的合成公司"]
    for company in companies:
        rules = "、".join(company.get("triggeredRules") or []) or "无"
        lines.append(
            f"- **{company.get('label')}（{company.get('code') or '—'}）**："
            f"{company.get('recommendation') or '无示例决策'}；风险 {company.get('riskLevel') or '—'}；触发规则：{rules}。"
        )
    lines.append("")
    examples = data.get("exampleQuestions") or []
    if examples:
        lines.append("可以这样问：")
        lines.extend(f"- {item}" for item in examples)
    real_data = data.get("realData") or {}
    if real_data.get("enabled"):
        lines.append(
            f"- 其他真实 A 股：输入 6 位代码或证券简称查询；"
            f"数据源：{real_data.get('provider') or '公开行情接口'}，可能延迟。"
        )
    lines.append("")
    lines.append(BOUNDARY)
    return "\n".join(lines)


def compose_comparison(analyses: list[dict[str, Any]]) -> str:
    lines = ["### 公司对比"]
    for data in analyses:
        company = data.get("company") or {}
        decision = data.get("decision") or {}
        risk = data.get("risk") or {}
        signals = data.get("signals") or []
        recommendation = (decision.get("recommendation") or {}).get("label") or "无示例决策"
        triggered = "、".join(item["ruleId"] for item in signals if item["status"] == "triggered") or "无"
        lines.append(
            f"- **{company.get('label')}**：{recommendation} · 置信度 {_pct(decision.get('confidence'))} · "
            f"风险 {(risk.get('level') or {}).get('label') or '—'}（{fmt_num(risk.get('score'))}/100） · 触发规则：{triggered}。"
        )
    lines.append("")
    lines.append("以上对比只反映本体中的规则信号与示例决策，不构成对真实证券的排序或推荐。")
    lines.append(BOUNDARY)
    return "\n".join(lines)


__all__ = [
    "compose_company",
    "compose_comparison",
    "compose_constraints",
    "compose_evidence",
    "compose_list",
    "compose_policies",
    "compose_portfolio",
    "compose_query",
    "compose_rule",
    "compose_scenario",
    "compose_screen",
    "compose_search",
]


def _fact_path(fact: dict[str, Any]) -> str:
    path = fact.get("path") or []
    if not path:
        return ""
    parts = [path[0]["from"].get("label") or ""]
    for edge in path:
        parts.append(f"—{edge.get('predicateLabel') or edge.get('predicate')}→")
        parts.append(edge["to"].get("label") or "")
    return " ".join(part for part in parts if part)


def compose_query(data: dict[str, Any]) -> str:
    matches = data.get("matches") or []
    criteria = data.get("criteria") or []
    universe = data.get("universe") or "ontology"
    lines = ["### 本体查询 · 跨公司筛选"]
    if universe == "real":
        lines.append("**查询范围**：真实 A 股行情单页样本（非全市场扫描）。")
    else:
        lines.append("**查询范围**：本体中的示例公司与本次运行已加载的真实 A 股。")
    lines.append("")
    lines.append("**查询条件**：" + ("；".join(criteria) if criteria else "无显式条件，列出范围内全部公司"))
    lines.append(
        f"**结果**：{data.get('totalMatches', len(matches))} / {data.get('evaluatedCount', 0)} 家公司命中。"
    )
    if not matches:
        lines.append("")
        lines.append("没有公司满足全部条件。")
        for item in data.get("excluded") or []:
            company = item.get("company") or {}
            reasons = "；".join(item.get("reasons") or [])
            lines.append(f"- {company.get('label') or '—'}：{reasons}")
    for match in matches[:8]:
        company = match.get("company") or {}
        metrics = match.get("metrics") or {}
        code = company.get("code") or "—"
        industry = company.get("industry") or "—"
        lines.append("")
        lines.append(f"- **{company.get('label') or '—'}（{code}，{industry}）**")
        metric_text = " · ".join(
            f"{label} {_metric_text(field, metrics.get(field))}"
            for field, label in (
                ("roe", "ROE"),
                ("peTtm", "PE(TTM)"),
                ("debtRatio", "负债率"),
                ("revenueGrowth", "营收增速"),
                ("riskScore", "风险分"),
                ("marketCap", "总市值"),
                ("positionWeight", "权重"),
            )
            if metrics.get(field) is not None
        )
        if metric_text:
            lines.append(f"  - 指标：{metric_text}")
        if match.get("matchedRules"):
            lines.append(f"  - 触发规则：{'、'.join(match['matchedRules'])}")
        for fact in (match.get("facts") or [])[:4]:
            path = _fact_path(fact)
            suffix = f"；路径：{path}" if path else ""
            date_text = f"；数据日期 {fact['asOf']}" if fact.get("asOf") else ""
            lines.append(f"  - 依据 {fact.get('label')} {fact.get('display')}{date_text}{suffix}")
    lines.append("")
    lines.append(f"**说明**：{data.get('dataNote') or ''}")
    return "\n".join(lines)


def _metric_text(field: str, value: Any) -> str:
    number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if number is None:
        return "—"
    if field == "marketCap":
        return fmt_money(number)
    if field in {"peTtm", "pb"}:
        return fmt_num(number)
    if field == "positionWeight":
        return fmt_weight(number)
    if field == "riskScore":
        return fmt_num(number)
    return fmt_pct(number)


def compose_evidence(data: dict[str, Any]) -> str:
    subject = data.get("subject") or {}
    nodes = data.get("nodes") or []
    chain = data.get("chain") or []
    lines = [f"### 证据链 · {subject.get('label') or '—'}"]
    lines.append("")
    lines.append(f"**起点**：{subject.get('label') or '—'}（{subject.get('kind') or 'entity'}）")
    if data.get("rule"):
        rule = data["rule"]
        lines.append(f"**附加规则**：{rule.get('ruleId')} · {rule.get('label')}")
    lines.append("")
    lines.append("**可读证据链**")
    if chain:
        for item in chain[:12]:
            lines.append(f"- {item}")
        if len(chain) > 12:
            lines.append(f"- 其余 {len(chain) - 12} 条路径见执行详情。")
    else:
        lines.append("- 本体中没有可继续展开的证据关系。")
    provenance = []
    for node in nodes:
        facts = node.get("provenance") or []
        if not facts:
            continue
        text = " · ".join(f"{item['label']} {item['value']}" for item in facts[:3])
        provenance.append(f"- {node.get('label')}：{text}")
    if provenance:
        lines.append("")
        lines.append("**来源与版本**")
        lines.extend(provenance[:8])
    lines.append("")
    lines.append(f"**说明**：{data.get('dataNote') or ''}")
    return "\n".join(lines)


def compose_constraints(data: dict[str, Any]) -> str:
    target = data.get("target") or {}
    checks = data.get("checks") or []
    status_labels = {"pass": "通过", "fail": "未通过", "unknown": "待确认"}
    lines = [f"### 约束检查 · {target.get('label') or '组合'}"]
    lines.append("")
    lines.append(f"**结论**：{data.get('summary') or '—'}")
    if data.get("proposedWeight") is not None:
        lines.append(
            f"**拟议权重**：{fmt_weight(data.get('proposedWeight'))} · **动作**：{data.get('action') or '—'}"
        )
    lines.append("")
    for check in checks:
        status = status_labels.get(check.get("status"), check.get("status") or "—")
        lines.append(f"- **{status}** `{check.get('id')}` {check.get('label')}：{check.get('detail')}")
    blocking = data.get("blocking") or []
    if blocking:
        lines.append("")
        lines.append("**阻断或待补充项**")
        for check in blocking:
            lines.append(f"- {check.get('label')}：{check.get('detail')}")
    lines.append("")
    lines.append(f"**说明**：{data.get('dataNote') or ''}")
    return "\n".join(lines)


def compose_scenario(data: dict[str, Any]) -> str:
    company = data.get("company") or {}
    changed = data.get("changed") or []
    lines = [f"### 情景模拟 · {company.get('label') or '—'}"]
    lines.append("")
    lines.append(f"**假设**：{data.get('scenario') or '—'}")
    lines.append("")
    if changed:
        lines.append("**规则状态变化**")
        for item in changed:
            before = STATUS_LABELS.get(item.get("before"), item.get("before") or "—")
            after = STATUS_LABELS.get(item.get("after"), item.get("after") or "—")
            lines.append(f"- `{item.get('ruleId')}` {item.get('label')}：{before} → {after}")
            detail = item.get("afterDetail")
            if detail:
                lines.append(f"  - 情景后：{detail}")
    else:
        lines.append("上述假设没有改变现有规则状态。")
    lines.append("")
    lines.append(f"**说明**：{data.get('dataNote') or ''}")
    return "\n".join(lines)
