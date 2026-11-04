"""Decision-lifecycle context and trade checks.

The deterministic agent uses this module to answer the questions that the
1.3 ontology expansion makes representable: what the account and position
state is, how much portfolio risk budget remains, whether a buy or sell plan
is executable, what limits apply, and how execution feeds back into review
and rule revision.

Everything is read-only. Missing facts are reported as ``unknown`` instead of
being guessed, and no order is ever sent.
"""

from __future__ import annotations

from typing import Any, Iterable

from rdflib import RDF, URIRef

from .namespaces import ASH
from .ontology import OntologyStore, local_name
from .rules import RULE_THRESHOLDS, fmt_money, fmt_num, fmt_pct, fmt_price, fmt_weight

BUY_ACTIONS = {"buy", "increase", "加仓", "买入", "增持", "建仓"}


class DecisionError(Exception):
    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def _dedupe_citations(items: Iterable[dict[str, Any] | None], limit: int = 24) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
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


def _ref(store: OntologyStore, subject: Any) -> dict[str, Any] | None:
    if not isinstance(subject, URIRef):
        return None
    return store._ref(subject)


def _latest(store: OntologyStore, parent: Any, predicate: Any) -> Any:
    values = [value for value in store._all(parent, predicate) if isinstance(value, URIRef)]
    if not values:
        return None
    return max(values, key=lambda item: str(store._literal(item, ASH.dataAsOf) or ""))


def _price_level(store: OntologyStore, plan: Any, predicate: Any) -> dict[str, Any] | None:
    node = store._first(plan, predicate)
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "value": store._num(node, ASH.priceLevelValue),
        "basis": store._text(node, ASH.priceLevelBasis) or "",
    }


def _trigger(store: OntologyStore, plan: Any, predicate: Any) -> dict[str, Any] | None:
    node = store._first(plan, predicate)
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "type": store._text(node, ASH.triggerType) or "",
        "condition": store._text(node, ASH.triggerCondition) or "",
    }


def _sizing(store: OntologyStore, plan: Any) -> dict[str, Any] | None:
    node = store._first(plan, ASH.hasTradeSizing)
    if not isinstance(node, URIRef):
        return None
    method = store._first(node, ASH.usesSizingMethod)
    return {
        **(store._ref(node) or {}),
        "method": store._ref(method),
        "quantity": store._num(node, ASH.sizingQuantity),
        "weight": store._num(node, ASH.sizingWeight),
        "projectedWeight": store._num(node, ASH.projectedWeight),
        "riskAmount": store._num(node, ASH.riskAmount),
        "sizingRiskAmount": store._num(node, ASH.sizingRiskAmount),
        "asOf": store._date(node, ASH.sizingAsOf),
    }


def _order_intent(store: OntologyStore, plan: Any) -> dict[str, Any] | None:
    node = store._first(plan, ASH.hasOrderIntent)
    if not isinstance(node, URIRef):
        return None
    realised = store._first(node, ASH.intentRealizedBy)
    return {
        **(store._ref(node) or {}),
        "id": store._text(node, ASH.orderIntentId) or local_name(node),
        "side": store._text(node, ASH.orderIntentSide) or "",
        "quantity": store._num(node, ASH.orderIntentQuantity),
        "price": store._num(node, ASH.orderIntentPrice),
        "status": store._text(node, ASH.orderIntentStatus) or "",
        "order": store._ref(realised),
    }


def _plan(store: OntologyStore, plan: Any) -> dict[str, Any]:
    return {
        **(store._ref(plan) or {}),
        "planId": store._text(plan, ASH.planId) or local_name(plan),
        "side": store._text(plan, ASH.planSide) or "",
        "status": store._text(plan, ASH.planStatus) or "",
        "asOf": store._date(plan, ASH.planAsOf),
        "validUntil": store._date(plan, ASH.planValidUntil),
        "quantity": store._num(plan, ASH.plannedQuantity),
        "notional": store._num(plan, ASH.plannedNotional),
        "weight": store._num(plan, ASH.plannedWeight),
        "rewardRiskRatio": store._num(plan, ASH.rewardRiskRatio),
        "entryPrice": _price_level(store, plan, ASH.hasEntryPrice),
        "stopPrice": _price_level(store, plan, ASH.hasStopPrice),
        "targetPrice": _price_level(store, plan, ASH.hasTargetPrice),
        "entryTrigger": _trigger(store, plan, ASH.hasEntryTrigger),
        "exitTrigger": _trigger(store, plan, ASH.hasExitTrigger),
        "sizing": _sizing(store, plan),
        "orderIntent": _order_intent(store, plan),
        "exitForPosition": store._ref(store._first(plan, ASH.exitPlanForPosition)),
        "kind": "EntryPlan" if (plan, RDF.type, ASH.EntryPlan) in store.graph else (
            "ExitPlan" if (plan, RDF.type, ASH.ExitPlan) in store.graph else "TradePlan"
        ),
    }


def _account(store: OntologyStore, portfolio: Any) -> dict[str, Any] | None:
    account = next(
        (item for item in store.graph.subjects(ASH.holdsPortfolio, portfolio) if isinstance(item, URIRef)),
        None,
    )
    if not isinstance(account, URIRef):
        accounts = [item for item in store.graph.subjects(RDF.type, ASH.Account) if isinstance(item, URIRef)]
        account = sorted(accounts, key=str)[0] if accounts else None
    if not isinstance(account, URIRef):
        return None
    state = _latest(store, account, ASH.hasAccountState)
    state_dict = None
    if isinstance(state, URIRef):
        state_dict = {
            **(store._ref(state) or {}),
            "cashBalance": store._num(state, ASH.cashBalance),
            "availableCash": store._num(state, ASH.availableCash),
            "frozenCash": store._num(state, ASH.frozenCash),
            "buyingPower": store._num(state, ASH.buyingPower),
            "totalEquity": store._num(state, ASH.totalEquity),
            "asOf": store._date(state, ASH.dataAsOf),
        }
    movements = []
    for item in store._all(account, ASH.hasCashMovement):
        if not isinstance(item, URIRef):
            continue
        movements.append(
            {
                **(store._ref(item) or {}),
                "type": store._text(item, ASH.cashMovementType) or "",
                "amount": store._num(item, ASH.cashMovementAmount),
                "date": store._date(item, ASH.cashMovementDate),
            }
        )
    return {
        **(store._ref(account) or {}),
        "code": store._text(account, ASH.accountCode) or "",
        "status": store._text(account, ASH.accountStatus) or "",
        "currency": store._text(account, ASH.baseCurrency) or "",
        "state": state_dict,
        "cashMovements": movements,
    }


def _position_state(store: OntologyStore, position: Any) -> dict[str, Any] | None:
    state = _latest(store, position, ASH.hasPositionState)
    if not isinstance(state, URIRef):
        return None
    return {
        **(store._ref(state) or {}),
        "status": store._text(state, ASH.positionStatus) or "",
        "availableQuantity": store._num(state, ASH.availableQuantity),
        "frozenQuantity": store._num(state, ASH.frozenQuantity),
        "marketValue": store._num(state, ASH.marketValue),
        "lastPrice": store._num(state, ASH.stateLastPrice),
        "unrealizedPnl": store._num(state, ASH.unrealizedPnl),
        "unrealizedPnlPct": store._num(state, ASH.unrealizedPnlPct),
        "realizedPnl": store._num(state, ASH.realizedPnl),
        "holdingDays": store._num(state, ASH.holdingDays),
        "asOf": store._date(state, ASH.dataAsOf),
    }


def _limits(store: OntologyStore, budget: Any) -> list[dict[str, Any]]:
    limits = []
    for item in store._all(budget, ASH.hasRiskLimit):
        if not isinstance(item, URIRef):
            continue
        limits.append(
            {
                **(store._ref(item) or {}),
                "type": store._text(item, ASH.riskLimitType) or "",
                "threshold": store._num(item, ASH.riskLimitThreshold),
                "hard": store._bool(item, ASH.riskLimitHard),
                "appliesTo": store._ref(store._first(item, ASH.riskLimitAppliesTo)),
            }
        )
    return sorted(limits, key=lambda item: item["type"])


def _utilizations(store: OntologyStore, budget: Any) -> list[dict[str, Any]]:
    rows = []
    for item in store._all(budget, ASH.hasRiskUtilization):
        if not isinstance(item, URIRef):
            continue
        limit = store._first(item, ASH.utilizationOfLimit)
        rows.append(
            {
                **(store._ref(item) or {}),
                "pct": store._num(item, ASH.riskUtilizationPct),
                "status": store._text(item, ASH.riskUtilizationStatus) or "",
                "limit": store._ref(limit),
                "limitType": store._text(limit, ASH.riskLimitType) if isinstance(limit, URIRef) else "",
                "hard": store._bool(limit, ASH.riskLimitHard) if isinstance(limit, URIRef) else None,
                "asOf": store._date(item, ASH.dataAsOf),
            }
        )
    return rows


def _risk_budget(store: OntologyStore, portfolio: Any) -> dict[str, Any] | None:
    budget = store._first(portfolio, ASH.hasRiskBudget)
    if not isinstance(budget, URIRef):
        return None
    allocations = []
    for item in store._all(budget, ASH.hasRiskAllocation):
        if not isinstance(item, URIRef):
            continue
        allocations.append(
            {
                **(store._ref(item) or {}),
                "security": store._ref(store._first(item, ASH.allocationToSecurity)),
                "amount": store._num(item, ASH.budgetAmount),
                "used": store._num(item, ASH.budgetUsed),
                "utilization": store._num(item, ASH.budgetUtilization),
            }
        )
    snapshot = store._first(portfolio, ASH.hasPortfolioRiskSnapshot)
    snapshot_dict = None
    if isinstance(snapshot, URIRef):
        contributions = []
        for item in store._all(snapshot, ASH.hasRiskContribution):
            if not isinstance(item, URIRef):
                continue
            contributions.append(
                {
                    **(store._ref(item) or {}),
                    "pct": store._num(item, ASH.riskContributionPct),
                    "marginal": store._num(item, ASH.marginalRiskContribution),
                }
            )
        snapshot_dict = {
            **(store._ref(snapshot) or {}),
            "volatility": store._num(snapshot, ASH.portfolioVolatility),
            "var95": store._num(snapshot, ASH.portfolioVar95),
            "expectedShortfall": store._num(snapshot, ASH.expectedShortfall),
            "beta": store._num(snapshot, ASH.portfolioBeta),
            "trackingError": store._num(snapshot, ASH.portfolioTrackingError),
            "hhi": store._num(snapshot, ASH.concentrationHhi),
            "maxDrawdown": store._num(snapshot, ASH.portfolioMaxDrawdown),
            "asOf": store._date(snapshot, ASH.dataAsOf),
            "contributions": contributions,
        }
    return {
        **(store._ref(budget) or {}),
        "total": store._num(budget, ASH.riskBudgetTotal),
        "used": store._num(budget, ASH.riskBudgetUsed),
        "remaining": store._num(budget, ASH.riskBudgetRemaining),
        "utilization": store._num(budget, ASH.riskBudgetUtilization),
        "riskPerTrade": store._num(budget, ASH.riskPerTradeLimit),
        "maxPortfolioLoss": store._num(budget, ASH.maxPortfolioLoss),
        "maxGrossExposure": store._num(budget, ASH.maxGrossExposure),
        "maxSingleNameWeight": store._num(budget, ASH.maxSingleNameWeight),
        "maxSectorWeight": store._num(budget, ASH.maxSectorWeight),
        "maxDrawdownLimit": store._num(budget, ASH.portfolioMaxDrawdownLimit),
        "varLimit": store._num(budget, ASH.varLimit),
        "asOf": store._date(budget, ASH.riskBudgetAsOf),
        "allocations": allocations,
        "limits": _limits(store, budget),
        "utilizations": _utilizations(store, budget),
        "riskSnapshot": snapshot_dict,
    }


def _execution(store: OntologyStore, trade: Any) -> dict[str, Any] | None:
    if not isinstance(trade, URIRef):
        return None
    quality = store._first(trade, ASH.hasExecutionQuality)
    quality_dict = None
    if isinstance(quality, URIRef):
        quality_dict = {
            **(store._ref(quality) or {}),
            "slippageBps": store._num(quality, ASH.slippageBps),
            "fillRate": store._num(quality, ASH.fillRate),
            "latencyMs": store._num(quality, ASH.executionLatencyMs),
            "marketImpactBps": store._num(quality, ASH.marketImpactBps),
            "asOf": store._date(quality, ASH.dataAsOf),
        }
    order = store._first(trade, ASH.generatedFromOrder)
    return {
        **(store._ref(trade) or {}),
        "price": store._num(trade, ASH.executionPrice),
        "quantity": store._num(trade, ASH.executionQuantity),
        "date": store._date(trade, ASH.tradeDate),
        "order": store._ref(order),
        "quality": quality_dict,
    }


def _outcome(store: OntologyStore, decision: Any) -> dict[str, Any] | None:
    outcome = store._first(decision, ASH.hasOutcome)
    if not isinstance(outcome, URIRef):
        return None
    trade = store._first(outcome, ASH.outcomeFromTrade)
    return {
        **(store._ref(outcome) or {}),
        "realizedReturn": store._num(outcome, ASH.realizedReturn),
        "realizedPnl": store._num(outcome, ASH.realizedPnlAmount),
        "holdingDays": store._num(outcome, ASH.holdingPeriodDays),
        "maxAdverseExcursion": store._num(outcome, ASH.maxAdverseExcursion),
        "maxFavorableExcursion": store._num(outcome, ASH.maxFavorableExcursion),
        "status": store._text(outcome, ASH.outcomeStatus) or "",
        "asOf": store._date(outcome, ASH.dataAsOf),
        "trade": store._ref(trade),
    }


def _review(store: OntologyStore, decision: Any) -> dict[str, Any] | None:
    review = store._first(decision, ASH.hasPostTradeReview)
    if not isinstance(review, URIRef):
        return None
    findings, lessons, attributions, revisions = [], [], [], []
    for item in store._all(review, ASH.hasReviewFinding):
        if isinstance(item, URIRef):
            findings.append(
                {
                    **(store._ref(item) or {}),
                    "type": store._text(item, ASH.findingType) or "",
                    "severity": store._text(item, ASH.findingSeverity) or "",
                    "recommendation": store._text(item, ASH.findingRecommendation) or "",
                    "occurrenceCount": store._num(item, ASH.findingOccurrenceCount),
                }
            )
    for item in store._all(review, ASH.hasLesson):
        if isinstance(item, URIRef):
            lessons.append(
                {
                    **(store._ref(item) or {}),
                    "text": store._text(item, ASH.lessonText) or "",
                    "action": store._text(item, ASH.lessonAction) or "",
                    "status": store._text(item, ASH.lessonStatus) or "",
                }
            )
    for item in store._all(review, ASH.hasAttribution):
        if isinstance(item, URIRef):
            attributions.append(
                {
                    **(store._ref(item) or {}),
                    "effect": store._text(item, ASH.attributionEffect) or "",
                    "pct": store._num(item, ASH.attributionPct),
                }
            )
    for item in store._all(review, ASH.resultsInRevision):
        if isinstance(item, URIRef):
            revisions.append(
                {
                    **(store._ref(item) or {}),
                    "id": store._text(item, ASH.revisionId) or local_name(item),
                    "rule": store._ref(store._first(item, ASH.revisionOfRule)),
                    "rationale": store._text(item, ASH.revisionRationale) or "",
                    "status": store._text(item, ASH.revisionStatus) or "",
                    "effectiveFrom": store._date(item, ASH.revisionEffectiveFrom),
                }
            )
    trade = store._first(review, ASH.reviewsTrade)
    return {
        **(store._ref(review) or {}),
        "verdict": store._text(review, ASH.reviewVerdict) or "",
        "score": store._num(review, ASH.reviewScore),
        "processScore": store._num(review, ASH.processScore),
        "outcomeScore": store._num(review, ASH.outcomeScore),
        "completedDate": store._date(review, ASH.reviewCompletedDate),
        "dueDate": store._date(review, ASH.reviewDueDate),
        "overdueDays": store._num(review, ASH.reviewOverdueDays),
        "findings": findings,
        "lessons": lessons,
        "attributions": attributions,
        "revisions": revisions,
        "trade": store._ref(trade),
    }


def _cycle(store: OntologyStore, decision: Any, portfolio: Any) -> dict[str, Any] | None:
    cycle = store._first(decision, ASH.decisionCycleOf)
    if not isinstance(cycle, URIRef):
        cycle = store._first(portfolio, ASH.hasDecisionCycle)
    if not isinstance(cycle, URIRef):
        return None
    stage = store._first(cycle, ASH.hasLifecycleStage)
    return {
        **(store._ref(cycle) or {}),
        "id": store._text(cycle, ASH.cycleId) or local_name(cycle),
        "number": store._num(cycle, ASH.cycleNumber),
        "status": store._text(cycle, ASH.cycleStatus) or "",
        "stage": store._ref(stage),
        "security": store._ref(store._first(cycle, ASH.cycleForSecurity)),
        "executions": [
            store._ref(item)
            for item in store._all(cycle, ASH.hasCycleExecution)
            if isinstance(item, URIRef)
        ],
    }


def _context(store: OntologyStore, decision: Any) -> dict[str, Any] | None:
    node = store._first(decision, ASH.hasDecisionContext)
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.contextAsOf),
        "marketRegime": store._text(node, ASH.marketRegime) or "",
        "accountState": store._ref(store._first(node, ASH.contextAccountState)),
        "riskBudget": store._ref(store._first(node, ASH.contextRiskBudget)),
        "riskSnapshot": store._ref(store._first(node, ASH.contextRiskSnapshot)),
    }


def build_trade_context(store: OntologyStore, company: str | None = None) -> dict[str, Any]:
    """Read the 1.3 decision-lifecycle facts for one company."""

    subject: URIRef | None
    if company:
        subject = store.find_company(company)
        if subject is None:
            raise DecisionError("company_not_found", f"没有找到公司“{company}”。")
    else:
        candidates = []
        for item in store.graph.subjects(ASH.hasTradePlan):
            for security in store.graph.objects(item, ASH.aboutSecurity):
                if not isinstance(security, URIRef):
                    continue
                company_subject = store._first(security, ASH.issuedBy)
                if isinstance(company_subject, URIRef):
                    candidates.append(company_subject)
        subject = sorted(set(candidates), key=str)[0] if candidates else (
            sorted(store._company_subjects, key=str)[0] if store._company_subjects else None
        )
    if not isinstance(subject, URIRef):
        raise DecisionError("no_company", "本体中没有可用的公司实例。")

    knowledge = store.company_knowledge(subject)
    data = knowledge.to_dict()
    security = data.get("security") or {}
    security_iri = URIRef(security["iri"]) if security.get("iri") else None
    decisions = store._all_decisions(subject)
    decision_iri = URIRef(data["decision"]["iri"]) if (data.get("decision") or {}).get("iri") else (
        decisions[0] if decisions else None
    )

    positions = []
    portfolio_iri = None
    if security_iri is not None:
        for position in store.graph.subjects(ASH.positionIn, security_iri):
            if not isinstance(position, URIRef):
                continue
            portfolio = store._first(position, ASH.positionOf)
            if not isinstance(portfolio, URIRef):
                continue
            portfolio_iri = portfolio_iri or portfolio
            positions.append(
                {
                    **(store._ref(position) or {}),
                    "weight": store._num(position, ASH.positionWeight),
                    "avgCost": store._num(position, ASH.avgCost),
                    "quantity": store._num(position, ASH.quantity),
                    "state": _position_state(store, position),
                    "lots": [
                        {
                            **(store._ref(lot) or {}),
                            "quantity": store._num(lot, ASH.lotQuantity),
                            "cost": store._num(lot, ASH.lotCost),
                            "openDate": store._date(lot, ASH.lotOpenDate),
                        }
                        for lot in store._all(position, ASH.hasPositionLot)
                        if isinstance(lot, URIRef)
                    ],
                }
            )
    if portfolio_iri is None:
        portfolios = [item for item in store.graph.subjects(RDF.type, ASH.Portfolio) if isinstance(item, URIRef)]
        portfolio_iri = sorted(portfolios, key=str)[0] if portfolios else None

    data_mode = data.get("dataMode") or "example"
    account = _account(store, portfolio_iri) if data_mode == "example" else None
    budget = _risk_budget(store, portfolio_iri) if (portfolio_iri is not None and data_mode == "example") else None

    plans: list[dict[str, Any]] = []
    if decision_iri is not None:
        for plan in store._all(decision_iri, ASH.hasTradePlan):
            if isinstance(plan, URIRef):
                plans.append(_plan(store, plan))

    outcome = _outcome(store, decision_iri) if decision_iri is not None else None
    review = _review(store, decision_iri) if decision_iri is not None else None
    execution = _execution(store, URIRef(outcome["trade"]["iri"])) if (outcome or {}).get("trade", {}).get("iri") else None
    decision_ref = store._ref(decision_iri) if decision_iri is not None else None
    decision_dict = data.get("decision") or {}
    position = next(
        (item for item in positions if item.get("state")),
        positions[0] if positions else None,
    )

    citations: list[dict[str, Any] | None] = [store._cite(subject)]
    for item in (security_iri, decision_iri, portfolio_iri):
        if isinstance(item, URIRef):
            citations.append(store._cite(item))
    if account:
        citations.append(store._cite(URIRef(account["iri"])))
    if budget:
        citations.append(store._cite(URIRef(budget["iri"])))
    for plan in plans:
        citations.append(store._cite(URIRef(plan["iri"])))
    if outcome:
        citations.append(store._cite(URIRef(outcome["iri"])))
    if review:
        citations.append(store._cite(URIRef(review["iri"])))

    return {
        "company": data.get("company"),
        "requestedCompany": bool(company),
        "portfolio": store._ref(portfolio_iri),
        "security": security,
        "risk": data.get("risk"),
        "decision": {
            **(decision_ref or {}),
            "decisionId": decision_dict.get("decisionId") or "",
            "recommendation": (decision_dict.get("recommendation") or {}).get("label"),
            "actionCode": (decision_dict.get("recommendation") or {}).get("actionCode"),
            "decisionDate": decision_dict.get("decisionDate"),
            "targetPrice": decision_dict.get("targetPrice"),
            "stopLoss": decision_dict.get("stopLoss"),
        },
        "position": position,
        "positions": positions,
        "account": account,
        "riskBudget": budget,
        "plans": plans,
        "context": _context(store, decision_iri) if decision_iri is not None else None,
        "cycle": _cycle(store, decision_iri, portfolio_iri) if decision_iri is not None else None,
        "outcome": outcome,
        "execution": execution,
        "review": review,
        "citations": _dedupe_citations(citations, 24),
    }


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(ok: bool | None) -> str:
    if ok is None:
        return "unknown"
    return "pass" if ok else "fail"


def _check(
    check_id: str,
    label: str,
    ok: bool | None,
    detail: str,
    *,
    blocking: bool = True,
    side: str = "both",
    rule_id: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": _status(ok),
        "detail": detail,
        "blocking": blocking and ok is not True,
        "side": side,
        "ruleId": rule_id,
    }


def evaluate_trade(store: OntologyStore, company: str | None = None, side: str | None = None) -> dict[str, Any]:
    """Check whether a buy or sell plan is executable under the 1.3 model."""

    context = build_trade_context(store, company)
    account = context.get("account") or {}
    account_state = account.get("state") or {}
    budget = context.get("riskBudget") or {}
    position = context.get("position") or {}
    position_state = position.get("state") or {}
    plans = context.get("plans") or []
    entry_plans = [item for item in plans if item.get("kind") == "EntryPlan"]
    exit_plans = [item for item in plans if item.get("kind") == "ExitPlan"]
    entry = next((item for item in entry_plans if item.get("status") != "FILLED"), entry_plans[0] if entry_plans else None)
    reduce_plan = next((item for item in exit_plans if (item.get("exitTrigger") or {}).get("type") == "REBALANCE"), None)
    bracket = next((item for item in exit_plans if item.get("stopPrice")), None)

    current_weight = _num(position.get("weight"))
    max_weight = _num(budget.get("maxSingleNameWeight")) or float(RULE_THRESHOLDS["R06"]["max_weight"])
    per_trade = _num(budget.get("riskPerTrade"))
    buying_power = _num(account_state.get("buyingPower"))
    available_quantity = _num(position_state.get("availableQuantity"))
    last_price = _num(position_state.get("lastPrice"))
    stop_price = _num((bracket or {}).get("stopPrice", {}).get("value")) if bracket else None
    target_price = _num((bracket or {}).get("targetPrice", {}).get("value")) if bracket else None
    entry_sizing = (entry or {}).get("sizing") or {}
    projected_weight = _num(entry_sizing.get("projectedWeight"))
    risk_amount = _num(entry_sizing.get("riskAmount")) or _num(entry_sizing.get("sizingRiskAmount"))
    planned_notional = _num((entry or {}).get("notional"))
    planned_quantity = _num((entry or {}).get("quantity"))
    reduce_quantity = _num((reduce_plan or {}).get("quantity")) or planned_quantity

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "R06",
            "当前单票集中度",
            None if current_weight is None else current_weight <= max_weight,
            (
                f"当前权重 {fmt_weight(current_weight)} {'≤' if current_weight is not None and current_weight <= max_weight else '>'} "
                f"上限 {fmt_weight(max_weight)}；买入不得继续增加超限暴露"
                if current_weight is not None
                else "没有当前持仓权重，无法检查 R06。"
            ),
            blocking=True,
            side="buy",
            rule_id="R06",
        )
    )
    checks.append(
        _check(
            "R154",
            "预计权重",
            None if projected_weight is None else projected_weight <= max_weight,
            (
                f"计划执行后预计权重 {fmt_weight(projected_weight)} {'≤' if projected_weight is not None and projected_weight <= max_weight else '>'} "
                f"单票上限 {fmt_weight(max_weight)}"
                if projected_weight is not None
                else "没有买入计划的预计权重，无法检查 R154。"
            ),
            blocking=True,
            side="buy",
            rule_id="R154",
        )
    )
    checks.append(
        _check(
            "R153",
            "单笔风险",
            None if risk_amount is None or per_trade is None else risk_amount <= per_trade,
            (
                f"计划风险 {fmt_money(risk_amount)} {'≤' if risk_amount is not None and per_trade is not None and risk_amount <= per_trade else '>'} "
                f"单笔预算 {fmt_money(per_trade)}"
                if risk_amount is not None and per_trade is not None
                else "没有计划风险金额或单笔预算，无法检查 R153。"
            ),
            blocking=True,
            side="buy",
            rule_id="R153",
        )
    )
    checks.append(
        _check(
            "R155",
            "购买力",
            None if planned_notional is None or buying_power is None else planned_notional <= buying_power,
            (
                f"计划金额 {fmt_money(planned_notional)} {'≤' if planned_notional is not None and buying_power is not None and planned_notional <= buying_power else '>'} "
                f"购买力 {fmt_money(buying_power)}"
                if planned_notional is not None and buying_power is not None
                else "没有计划金额或购买力，无法检查 R155。"
            ),
            blocking=True,
            side="buy",
            rule_id="R155",
        )
    )
    utilization = _num(budget.get("utilization"))
    checks.append(
        _check(
            "R152",
            "组合风险预算",
            None if utilization is None else utilization < 100,
            (
                f"风险预算使用率 {fmt_pct(utilization)} {'<' if utilization is not None and utilization < 100 else '≥'} 100%"
                if utilization is not None
                else "没有风险预算使用率，无法检查 R152。"
            ),
            blocking=True,
            side="buy",
            rule_id="R152",
        )
    )
    hard_breaches = [
        item for item in budget.get("utilizations") or []
        if item.get("hard") and (_num(item.get("pct")) or 0) >= 100
    ]
    checks.append(
        _check(
            "R161",
            "硬性限额",
            not hard_breaches if budget.get("utilizations") else None,
            (
                "；".join(
                    f"{item.get('limitType') or item.get('label')} 使用率 {fmt_pct(item.get('pct'))}"
                    for item in hard_breaches
                )
                if hard_breaches
                else "没有硬性限额被突破。"
            )
            if budget.get("utilizations")
            else "没有风险限额使用率，无法检查 R161。",
            blocking=True,
            side="buy",
            rule_id="R161",
        )
    )
    checks.append(
        _check(
            "R156",
            "止损价",
            None if last_price is None or stop_price is None else last_price > stop_price,
            (
                f"最新价 {fmt_price(last_price)} {'>' if last_price is not None and stop_price is not None and last_price > stop_price else '≤'} "
                f"止损价 {fmt_price(stop_price)}"
                if last_price is not None and stop_price is not None
                else "没有最新价或止损价，无法检查 R156。"
            ),
            blocking=False,
            rule_id="R156",
        )
    )
    checks.append(
        _check(
            "R157",
            "目标价",
            None if last_price is None or target_price is None else last_price < target_price,
            (
                f"最新价 {fmt_price(last_price)} {'<' if last_price is not None and target_price is not None and last_price < target_price else '≥'} "
                f"目标价 {fmt_price(target_price)}"
                if last_price is not None and target_price is not None
                else "没有最新价或目标价，无法检查 R157。"
            ),
            blocking=False,
            rule_id="R157",
        )
    )
    checks.append(
        _check(
            "T1_AVAILABLE",
            "可卖数量",
            None if reduce_quantity is None or available_quantity is None else reduce_quantity <= available_quantity,
            (
                f"减仓数量 {fmt_num(reduce_quantity)} {'≤' if reduce_quantity is not None and available_quantity is not None and reduce_quantity <= available_quantity else '>'} "
                f"可卖数量 {fmt_num(available_quantity)}（T+1 与冻结已扣除）"
                if reduce_quantity is not None and available_quantity is not None
                else "没有减仓数量或可卖数量，无法检查 T+1。"
            ),
            blocking=True,
            side="sell",
        )
    )
    restricted = bool((context.get("security") or {}).get("restricted"))
    checks.append(
        _check(
            "R07",
            "限制名单",
            not restricted,
            f"证券 isRestricted = {'true' if restricted else 'false'}。",
            blocking=True,
            rule_id="R07",
        )
    )
    risk_data = context.get("risk") or {}
    risk_score = _num(risk_data.get("score"))
    if risk_score is None:
        company_label = str((context.get("company") or {}).get("label") or "")
        company_subject = store.find_company(company_label) if company_label else None
        if company_subject is not None:
            risk_score = _num((store.company_knowledge(company_subject).to_dict().get("risk") or {}).get("score"))
    needs_review = risk_score is not None and risk_score >= float(RULE_THRESHOLDS["R11"]["risk_score_min"])
    checks.append(
        _check(
            "R11",
            "高风险买入复核",
            None if risk_score is None else not needs_review,
            (
                f"风险分数 {fmt_num(risk_score)} {'≥' if needs_review else '<'} "
                f"{fmt_num(RULE_THRESHOLDS['R11']['risk_score_min'])}，"
                f"{'需要' if needs_review else '不需要'}二次复核"
                if risk_score is not None
                else "缺少风险评估分数，无法检查 R11。"
            ),
            blocking=True,
            side="buy",
            rule_id="R11",
        )
    )
    review = context.get("review") or {}
    overdue = _num(review.get("overdueDays"))
    checks.append(
        _check(
            "R159",
            "复盘时限",
            None if overdue is None else overdue < 5,
            (
                f"复盘逾期 {int(overdue)} 天 {'<' if overdue is not None and overdue < 5 else '≥'} 5 天"
                if overdue is not None
                else "没有复盘记录，无法检查 R159。"
            ),
            blocking=False,
            rule_id="R159",
        )
    )
    recurring = [
        item for item in review.get("findings") or []
        if (item.get("severity") == "high") and (_num(item.get("occurrenceCount")) or 0) >= 2
    ]
    checks.append(
        _check(
            "R160",
            "重复高严重度发现",
            not recurring if review.get("findings") else None,
            (
                "；".join(item.get("recommendation") or item.get("label") or "" for item in recurring)
                if recurring
                else "没有重复高严重度发现。"
            )
            if review.get("findings")
            else "没有复盘发现，无法检查 R160。",
            blocking=False,
            rule_id="R160",
        )
    )
    quality = (context.get("execution") or {}).get("quality")
    slippage = _num((quality or {}).get("slippageBps"))
    checks.append(
        _check(
            "R158",
            "执行滑点",
            None if slippage is None else slippage <= 50,
            (
                f"上次成交滑点 {fmt_num(slippage)} bps {'≤' if slippage is not None and slippage <= 50 else '>'} 50 bps"
                if slippage is not None
                else "没有成交执行质量记录，无法检查 R158。"
            ),
            blocking=False,
            rule_id="R158",
        )
    )
    decision_iri = URIRef((context.get("decision") or {}).get("iri")) if (context.get("decision") or {}).get("iri") else None
    approval = store._first(decision_iri, ASH.hasApproval) if decision_iri is not None else None
    if not isinstance(approval, URIRef):
        approval = next(
            (
                item for item in store.graph.subjects(RDF.type, ASH.Approval)
                if store._first(item, ASH.approves) is not None
            ),
            None,
        )
    approval_status = store._text(approval, ASH.approvalStatus) if isinstance(approval, URIRef) else None
    checks.append(
        _check(
            "APPROVAL",
            "人工审批",
            None if not approval_status else approval_status.upper() == "APPROVED",
            (
                f"审批状态 {approval_status}；执行前必须由人工确认"
                if approval_status
                else "没有审批记录；执行前必须由人工确认"
            ),
            blocking=True,
            side="both",
        )
    )

    def _blockers(check_side: str) -> list[dict[str, Any]]:
        return [
            item for item in checks
            if item["blocking"] and item["status"] != "pass" and item["side"] in {"both", check_side}
        ]

    buy_blockers = _blockers("buy")
    sell_blockers = _blockers("sell")
    warnings = [
        item for item in checks
        if (not item["blocking"]) and item["status"] == "fail"
    ]

    def _verdict(blockers: list[dict[str, Any]], action: str) -> dict[str, Any]:
        return {
            "action": action,
            "allowed": not blockers,
            "summary": "可执行" if not blockers else "受阻",
            "reasons": [item["detail"] for item in blockers],
        }

    buy = _verdict(buy_blockers, "buy")
    sell = _verdict(sell_blockers, "sell")
    if side and str(side).lower() not in {"both", ""}:
        selected = buy if str(side).lower() in BUY_ACTIONS else sell
        summary = selected["summary"]
    else:
        summary = f"买入{buy['summary']}；卖出（减仓）{sell['summary']}"

    buy_limits = [
        f"单票上限 {fmt_weight(max_weight)}，当前 {fmt_weight(current_weight)}，加仓后预计 {fmt_weight(projected_weight)}",
        f"单笔风险预算 {fmt_money(per_trade)}，本计划 {fmt_money(risk_amount)}",
        f"购买力 {fmt_money(buying_power)}，本计划金额 {fmt_money(planned_notional)}",
        f"组合风险预算使用率 {fmt_pct(utilization)}，剩余 {fmt_money(budget.get('remaining'))}",
        "硬性限额突破时暂停新增风险敞口；高风险证券买入需二次复核",
        "订单意图必须经过人工批准与合规检查，本体不直接下单",
    ]
    sell_limits = [
        f"可卖数量 {fmt_num(available_quantity)}（T+1 与冻结已扣除），本次减仓 {fmt_num(reduce_quantity)}",
        f"止损价 {fmt_price(stop_price)}，目标价 {fmt_price(target_price)}，最新价 {fmt_price(last_price)}",
        "减仓用于修复集中度或降低风险时，不受单票上限阻断；但受可卖数量、限制名单与人工审批约束",
        "触发止损或目标价只进入卖出评估，不自动成交",
    ]

    citations = list(context.get("citations") or [])
    for rule_id in ("R06", "R152", "R153", "R154", "R155", "R156", "R157", "R159", "R160"):
        rule = store.rule(rule_id)
        if rule:
            citations.append(store._cite(URIRef(rule["iri"])))

    return {
        "company": context.get("company"),
        "scope": "company" if context.get("requestedCompany") else "portfolio",
        "portfolio": context.get("portfolio"),
        "security": context.get("security"),
        "decision": context.get("decision"),
        "account": account,
        "position": position,
        "riskBudget": budget,
        "plans": {
            "entry": entry,
            "reduce": reduce_plan,
            "bracket": bracket,
            "all": plans,
        },
        "context": context.get("context"),
        "cycle": context.get("cycle"),
        "outcome": context.get("outcome"),
        "execution": context.get("execution"),
        "review": context.get("review"),
        "checks": checks,
        "buy": buy,
        "sell": sell,
        "summary": summary,
        "limits": {"buy": buy_limits, "sell": sell_limits},
        "warnings": warnings,
        "dataNote": (
            "账户、持仓、风险预算、计划、成交与复盘均为本体中的合成示例；"
            "检查只读取 RDF 事实与 SWRL 规则阈值，不连接真实账户或交易通道。"
        ),
        "queryPath": [
            {"kind": "select", "label": "定位账户、组合与持仓状态", "detail": (context.get("company") or {}).get("label") or "—"},
            {"kind": "traverse", "label": "读取风险预算、限额与使用率", "detail": f"{len(budget.get('limits') or [])} 项限额"},
            {"kind": "traverse", "label": "读取买卖点、仓位测算与订单意图", "detail": f"{len(plans)} 个计划"},
            {"kind": "verify", "label": "执行 R152–R161 交易生命周期检查", "detail": f"{len(checks)} 项"},
            {"kind": "review", "label": "读取执行质量、结果与复盘闭环", "detail": (review.get("verdict") or "无复盘")},
        ],
        "citations": _dedupe_citations(citations, 24),
    }


__all__ = ["DecisionError", "build_trade_context", "evaluate_trade"]
