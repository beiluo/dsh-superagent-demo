"""Deterministic SWRL-signal evaluation used by the ontology agent.

The thresholds below mirror the example constants in
``ontology/swrl/rules.ttl``.  ``tests/test_rules.py`` asserts that every
configured value appears in the corresponding SWRL rule, so the server cannot
silently drift from the canonical ontology.
"""

from __future__ import annotations

from typing import Any

# R01 value screen, R02 financial risk, R05 stop-loss, R06 concentration,
# R09 illiquidity, R10 growth screen, R11 high-risk buy review.
# R16-R21 are the 1.2 short-term/medium-term rules (hot money, limit-up streak,
# overheat, board-break, medium-term trend and theme catalyst).
RULE_THRESHOLDS: dict[str, dict[str, float]] = {
    "R01": {"roe_min": 15.0, "pe_max": 20.0, "net_profit_min": 0.0},
    "R02": {"debt_ratio_min": 70.0, "interest_coverage_max": 2.0},
    "R05": {"stop_loss_ratio": 0.8},
    "R06": {"max_weight": 0.10},
    "R09": {"turnover_max": 0.5, "market_cap_max": 5_000_000_000.0},
    "R10": {"revenue_growth_min": 25.0, "profit_growth_min": 20.0, "pe_min": 40.0},
    "R11": {"risk_score_min": 60.0},
    "R16": {"dragon_tiger_net_buy_min": 50_000_000.0},
    "R17": {
        "limit_up_days_min": 3,
        "broken_board_count_max": 1,
        "seal_amount_min": 50_000_000.0,
    },
    "R18": {"turnover_rate_min": 15.0, "limit_up_days_min": 3},
    "R19": {"broken_board_count_min": 2},
    "R20": {"revenue_growth_min": 20.0},
    "R21": {"theme_heat_min": 80.0},
}

SIGNAL_STATUS_LABELS = {
    "triggered": "触发",
    "clear": "未触发",
    "unknown": "无法评估",
}


def _signal(rule_id: str, status: str, detail: str) -> dict[str, str]:
    return {"ruleId": rule_id, "status": status, "detail": detail}


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_num(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}"
    return f"{number:,.1f}"


def fmt_pct(value: Any, digits: int = 1) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return f"{number:.{digits}f}%"


def fmt_weight(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return f"{number * 100:.1f}%"


def fmt_money(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.1f} 亿元"
    if abs(number) >= 10_000:
        return f"{number / 10_000:.1f} 万元"
    return fmt_num(number)


def fmt_price(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return f"¥{number:,.2f}"


def fmt_ratio(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return f"{number:.1f}×"


def _conditions(passed: list[tuple[str, bool, str]]) -> tuple[bool, str]:
    """Render a rule condition list.

    Each item is ``(current value, condition passed, requirement text)``.
    """

    ok = all(item[1] for item in passed)
    if ok:
        return True, "条件全部满足：" + "；".join(f"{item[0]}（要求 {item[2]}）" for item in passed)
    failed = [f"{item[0]}（要求 {item[2]}）" for item in passed if not item[1]]
    satisfied = any(item[1] for item in passed)
    suffix = "；其余条件满足" if satisfied else ""
    return False, "规则未触发：" + "；".join(failed) + suffix


def _has(value: Any) -> bool:
    return value not in (None, "", [], {})


def evaluate_company(knowledge: dict[str, Any]) -> list[dict[str, str]]:
    """Evaluate company/decision/position rules for one company fact sheet."""

    company = knowledge.get("company") or {}
    security = knowledge.get("security") or {}
    report = knowledge.get("financials") or {}
    quote = knowledge.get("quote") or {}
    valuation = knowledge.get("valuation") or {}
    risk = knowledge.get("risk") or {}
    decision = knowledge.get("decision") or {}
    position = knowledge.get("position") or {}

    is_st = bool(company.get("isST"))
    delisting = bool(company.get("delistingRisk"))
    signals: list[dict[str, str]] = []

    roe = _num(report.get("roe"))
    pe = _num(valuation.get("peTtm"))
    net_profit = _num(report.get("netProfit"))
    if roe is None or pe is None or net_profit is None:
        signals.append(_signal("R01", "unknown", "缺少年报 ROE、净利润或 PE(TTM) 快照，无法执行价值筛选。"))
    else:
        ok, detail = _conditions(
            [
                (f"ROE {fmt_pct(roe)}", roe >= RULE_THRESHOLDS["R01"]["roe_min"], f"≥ {fmt_pct(RULE_THRESHOLDS['R01']['roe_min'])}"),
                (f"PE(TTM) {fmt_num(pe)}", pe <= RULE_THRESHOLDS["R01"]["pe_max"], f"≤ {fmt_num(RULE_THRESHOLDS['R01']['pe_max'])}"),
                (f"净利润 {fmt_money(net_profit)}", net_profit > RULE_THRESHOLDS["R01"]["net_profit_min"], "> 0"),
                ("非 ST", not is_st, "isST = false"),
            ]
        )
        signals.append(_signal("R01", "triggered" if ok else "clear", detail))

    debt_ratio = _num(report.get("debtRatio"))
    interest = _num(report.get("interestCoverage"))
    if debt_ratio is None or interest is None:
        signals.append(_signal("R02", "unknown", "缺少资产负债率或利息保障倍数，无法执行财务风险识别。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"资产负债率 {fmt_pct(debt_ratio)}",
                    debt_ratio >= RULE_THRESHOLDS["R02"]["debt_ratio_min"],
                    f"≥ {fmt_pct(RULE_THRESHOLDS['R02']['debt_ratio_min'])}",
                ),
                (
                    f"利息保障倍数 {fmt_ratio(interest)}",
                    interest < RULE_THRESHOLDS["R02"]["interest_coverage_max"],
                    f"< {fmt_num(RULE_THRESHOLDS['R02']['interest_coverage_max'])}",
                ),
            ]
        )
        signals.append(_signal("R02", "triggered" if ok else "clear", detail))

    signals.append(
        _signal(
            "R03",
            "triggered" if is_st else "clear",
            f"isST = {'true' if is_st else 'false'}（{company.get('label', '该公司')}）。",
        )
    )
    signals.append(
        _signal(
            "R04",
            "triggered" if delisting else "clear",
            f"delistingRisk = {'true' if delisting else 'false'}（{company.get('label', '该公司')}）。",
        )
    )

    avg_cost = _num(position.get("avgCost"))
    last_price = _num(quote.get("lastPrice"))
    if avg_cost is None or last_price is None:
        signals.append(_signal("R05", "unknown", "没有持仓成本或行情快照，止损规则不适用。"))
    else:
        threshold = avg_cost * RULE_THRESHOLDS["R05"]["stop_loss_ratio"]
        ok = last_price <= threshold
        detail = (
            f"最新价 {fmt_price(last_price)} ≤ 成本 × 0.8 = {fmt_price(threshold)}"
            if ok
            else f"最新价 {fmt_price(last_price)} > 成本 × 0.8 = {fmt_price(threshold)}"
        )
        signals.append(_signal("R05", "triggered" if ok else "clear", detail))

    weight = _num(position.get("weight"))
    if weight is None:
        signals.append(_signal("R06", "unknown", "没有组合持仓权重，集中度规则不适用。"))
    else:
        ok = weight > RULE_THRESHOLDS["R06"]["max_weight"]
        detail = (
            f"组合权重 {fmt_weight(weight)} > 上限 {fmt_weight(RULE_THRESHOLDS['R06']['max_weight'])}"
            if ok
            else f"组合权重 {fmt_weight(weight)} ≤ 上限 {fmt_weight(RULE_THRESHOLDS['R06']['max_weight'])}"
        )
        signals.append(_signal("R06", "triggered" if ok else "clear", detail))

    if not decision:
        signals.append(_signal("R07", "unknown", "该公司在本体中没有示例决策，限制名单规则不适用。"))
    else:
        restricted = bool(security.get("isRestricted"))
        signals.append(
            _signal(
                "R07",
                "triggered" if restricted else "clear",
                f"证券 isRestricted = {'true' if restricted else 'false'}。",
            )
        )

    if not decision:
        signals.append(_signal("R08", "unknown", "没有示例决策，无法检查可审计性。"))
    else:
        has_risk = _has(decision.get("risk"))
        has_rationale = _has((decision.get("rationale") or {}).get("text"))
        evidence_count = len(decision.get("evidence") or [])
        policy_count = len(decision.get("policies") or [])
        parts = [
            (f"风险评估{'有' if has_risk else '缺失'}", has_risk),
            (f"决策理由{'有' if has_rationale else '缺失'}", has_rationale),
            (f"证据 {evidence_count} 条", evidence_count > 0),
            (f"政策 {policy_count} 项", policy_count > 0),
        ]
        ok = all(item[1] for item in parts)
        signals.append(_signal("R08", "triggered" if ok else "clear", "；".join(item[0] for item in parts) + "。"))

    turnover = _num(quote.get("turnoverRate"))
    market_cap = _num(quote.get("marketCap"))
    if turnover is None or market_cap is None:
        signals.append(_signal("R09", "unknown", "缺少换手率或总市值，无法执行低流动性识别。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"换手率 {fmt_pct(turnover)}",
                    turnover < RULE_THRESHOLDS["R09"]["turnover_max"],
                    f"< {fmt_pct(RULE_THRESHOLDS['R09']['turnover_max'])}",
                ),
                (
                    f"总市值 {fmt_money(market_cap)}",
                    market_cap < RULE_THRESHOLDS["R09"]["market_cap_max"],
                    f"< {fmt_money(RULE_THRESHOLDS['R09']['market_cap_max'])}",
                ),
            ]
        )
        signals.append(_signal("R09", "triggered" if ok else "clear", detail))

    revenue_growth = _num(report.get("revenueGrowth"))
    profit_growth = _num(report.get("profitGrowth"))
    if revenue_growth is None or profit_growth is None or pe is None:
        signals.append(_signal("R10", "unknown", "缺少营收增速、净利润增速或 PE(TTM)，无法执行成长筛选。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"营收增速 {fmt_pct(revenue_growth)}",
                    revenue_growth >= RULE_THRESHOLDS["R10"]["revenue_growth_min"],
                    f"≥ {fmt_pct(RULE_THRESHOLDS['R10']['revenue_growth_min'])}",
                ),
                (
                    f"净利润增速 {fmt_pct(profit_growth)}",
                    profit_growth >= RULE_THRESHOLDS["R10"]["profit_growth_min"],
                    f"≥ {fmt_pct(RULE_THRESHOLDS['R10']['profit_growth_min'])}",
                ),
                (
                    f"PE(TTM) {fmt_num(pe)}",
                    pe > RULE_THRESHOLDS["R10"]["pe_min"],
                    f"> {fmt_num(RULE_THRESHOLDS['R10']['pe_min'])}",
                ),
            ]
        )
        signals.append(_signal("R10", "triggered" if ok else "clear", detail))

    if not decision or not risk:
        signals.append(_signal("R11", "unknown", "没有决策或风险评估，二次复核规则不适用。"))
    else:
        action = str((decision.get("recommendation") or {}).get("actionCode") or "")
        score = _num(risk.get("score"))
        if score is None:
            signals.append(_signal("R11", "unknown", "风险评估缺少 riskScore，无法执行二次复核判断。"))
        else:
            ok = action.upper() == "BUY" and score >= RULE_THRESHOLDS["R11"]["risk_score_min"]
            detail = (
                f"建议 {action or '—'}，风险分数 {fmt_num(score)} ≥ {fmt_num(RULE_THRESHOLDS['R11']['risk_score_min'])}"
                if ok
                else f"建议 {action or '—'}，风险分数 {fmt_num(score)}；未同时满足 BUY 与 ≥ {fmt_num(RULE_THRESHOLDS['R11']['risk_score_min'])}"
            )
            signals.append(_signal("R11", "triggered" if ok else "clear", detail))

    signals.extend(_evaluate_short_term(knowledge, quote, report))
    return signals


def _evaluate_short_term(
    knowledge: dict[str, Any],
    quote: dict[str, Any],
    report: dict[str, Any],
) -> list[dict[str, str]]:
    """Evaluate the 1.2 short-term / medium-term rules (R16-R21).

    These rules only emit signals when the fact sheet actually contains
    short-term facts, so companies without hot-money, limit-up, MA or theme
    snapshots keep the previous long-term-only output.
    """

    short = knowledge.get("shortTerm") or {}
    tracked = (
        "ma5",
        "ma20",
        "ma60",
        "limitUpDays",
        "brokenBoardCount",
        "sealAmount",
        "dragonTigerNetBuy",
    )
    if not any(short.get(key) is not None for key in tracked):
        return []

    signals: list[dict[str, str]] = []
    revenue_growth = _num(report.get("revenueGrowth"))
    turnover = _num(quote.get("turnoverRate"))

    net_buy = _num(short.get("dragonTigerNetBuy"))
    hot_seats = _num(short.get("hotMoneySeatCount"))
    if net_buy is None or hot_seats is None:
        signals.append(_signal("R16", "unknown", "缺少龙虎榜净买入或游资席位数据，无法判断游资流入。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"龙虎榜净买入 {fmt_money(net_buy)}",
                    net_buy > RULE_THRESHOLDS["R16"]["dragon_tiger_net_buy_min"],
                    f"> {fmt_money(RULE_THRESHOLDS['R16']['dragon_tiger_net_buy_min'])}",
                ),
                (
                    f"游资席位 {int(hot_seats)} 个",
                    hot_seats > 0,
                    "> 0",
                ),
            ]
        )
        signals.append(_signal("R16", "triggered" if ok else "clear", detail))

    limit_up_days = _num(short.get("limitUpDays"))
    broken_boards = _num(short.get("brokenBoardCount"))
    seal_amount = _num(short.get("sealAmount"))
    if limit_up_days is None or broken_boards is None or seal_amount is None:
        signals.append(_signal("R17", "unknown", "缺少连板天数、炸板次数或封单金额，无法判断连板动量。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"连板 {int(limit_up_days)} 天",
                    limit_up_days >= RULE_THRESHOLDS["R17"]["limit_up_days_min"],
                    f"≥ {int(RULE_THRESHOLDS['R17']['limit_up_days_min'])}",
                ),
                (
                    f"炸板 {int(broken_boards)} 次",
                    broken_boards <= RULE_THRESHOLDS["R17"]["broken_board_count_max"],
                    f"≤ {int(RULE_THRESHOLDS['R17']['broken_board_count_max'])}",
                ),
                (
                    f"封单 {fmt_money(seal_amount)}",
                    seal_amount > RULE_THRESHOLDS["R17"]["seal_amount_min"],
                    f"> {fmt_money(RULE_THRESHOLDS['R17']['seal_amount_min'])}",
                ),
            ]
        )
        signals.append(_signal("R17", "triggered" if ok else "clear", detail))

    if turnover is None or limit_up_days is None:
        signals.append(_signal("R18", "unknown", "缺少换手率或连板天数，无法判断短线过热。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"换手率 {fmt_pct(turnover)}",
                    turnover > RULE_THRESHOLDS["R18"]["turnover_rate_min"],
                    f"> {fmt_pct(RULE_THRESHOLDS['R18']['turnover_rate_min'])}",
                ),
                (
                    f"连板 {int(limit_up_days)} 天",
                    limit_up_days >= RULE_THRESHOLDS["R18"]["limit_up_days_min"],
                    f"≥ {int(RULE_THRESHOLDS['R18']['limit_up_days_min'])}",
                ),
            ]
        )
        signals.append(_signal("R18", "triggered" if ok else "clear", detail))

    if broken_boards is None:
        signals.append(_signal("R19", "unknown", "缺少炸板次数，无法判断炸板风险。"))
    else:
        ok = broken_boards >= RULE_THRESHOLDS["R19"]["broken_board_count_min"]
        detail = (
            f"炸板 {int(broken_boards)} 次 ≥ {int(RULE_THRESHOLDS['R19']['broken_board_count_min'])}"
            if ok
            else f"炸板 {int(broken_boards)} 次 < {int(RULE_THRESHOLDS['R19']['broken_board_count_min'])}"
        )
        signals.append(_signal("R19", "triggered" if ok else "clear", detail))

    ma20 = _num(short.get("ma20"))
    ma60 = _num(short.get("ma60"))
    if ma20 is None or ma60 is None or revenue_growth is None:
        signals.append(_signal("R20", "unknown", "缺少 MA20、MA60 或营收增速，无法判断中期趋势。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"MA20 {fmt_num(ma20)} > MA60 {fmt_num(ma60)}",
                    ma20 > ma60,
                    "MA20 > MA60",
                ),
                (
                    f"营收增速 {fmt_pct(revenue_growth)}",
                    revenue_growth >= RULE_THRESHOLDS["R20"]["revenue_growth_min"],
                    f"≥ {fmt_pct(RULE_THRESHOLDS['R20']['revenue_growth_min'])}",
                ),
            ]
        )
        signals.append(_signal("R20", "triggered" if ok else "clear", detail))

    theme_heat = _num(short.get("themeHeatScore"))
    news = short.get("hasNewsCatalyst")
    if theme_heat is None or news is None:
        signals.append(_signal("R21", "unknown", "缺少主题热度或新闻催化数据，无法判断事件驱动。"))
    else:
        ok, detail = _conditions(
            [
                (
                    f"主题热度 {fmt_num(theme_heat)}",
                    theme_heat > RULE_THRESHOLDS["R21"]["theme_heat_min"],
                    f"> {fmt_num(RULE_THRESHOLDS['R21']['theme_heat_min'])}",
                ),
                ("新闻催化", bool(news), "存在新闻催化"),
            ]
        )
        signals.append(_signal("R21", "triggered" if ok else "clear", detail))

    return signals


def evaluate_portfolio(portfolio: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Evaluate portfolio-level R05/R06 signals."""

    positions = portfolio.get("positions") or []
    breaches = [
        item
        for item in positions
        if (item.get("signals", {}).get("R06") or {}).get("status") == "triggered"
    ]
    stop_losses = [
        item
        for item in positions
        if (item.get("signals", {}).get("R05") or {}).get("status") == "triggered"
    ]

    if not positions:
        r05 = _signal("R05", "unknown", "组合没有建模持仓。")
        r06 = _signal("R06", "unknown", "组合没有建模持仓。")
    else:
        if stop_losses:
            detail = "；".join(
                f"{item.get('company', {}).get('label', item.get('label', '持仓'))} 触发止损"
                for item in stop_losses
            )
        else:
            detail = "所有持仓的最新价均高于成本 × 0.8。"
        r05 = _signal("R05", "triggered" if stop_losses else "clear", detail)

        if breaches:
            detail = "；".join(
                f"{item.get('company', {}).get('label', item.get('label', '持仓'))} "
                f"{fmt_weight(item.get('weight'))} > {fmt_weight(RULE_THRESHOLDS['R06']['max_weight'])}"
                for item in breaches
            )
        else:
            detail = f"没有持仓权重超过 {fmt_weight(RULE_THRESHOLDS['R06']['max_weight'])}。"
        r06 = _signal("R06", "triggered" if breaches else "clear", detail)

    return {"R05": r05, "R06": r06}
