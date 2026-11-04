"""Trading-cognition pipeline.

The five engines in the 1.10 ontology are not five independent agents. They are
the stages of one decision process:

    market cognition -> opportunity identification -> trading judgment
    -> behavior management -> outcome verification

This module reads the structured ``AnalysisCase`` facts from the RDF graph and
turns them into a deterministic, evidence-first judgment. It deliberately does
not use a weighted score: hard market/evidence/risk-reward gates can veto an
opportunity, and the buy-side and holding-side flows are evaluated with
different rules.

Everything is read-only. Missing facts are reported as ``unknown`` rather than
being guessed, and no order is ever sent.
"""

from __future__ import annotations

from typing import Any, Iterable

from rdflib import RDF, URIRef
from rdflib.namespace import SKOS

from .decision import DecisionError, build_trade_context
from .marketdata import SOURCE_LABEL, MarketDataError
from .namespaces import ASH
from .ontology import OntologyStore, local_name
from .rules import evaluate_company


SCENARIOS = {"non_position", "held"}
ACTION_LABELS = {
    "buy": "买入",
    "hold": "持有",
    "add": "加仓",
    "reduce": "减仓",
    "sell": "卖出",
    "watch": "观望",
}
STAGE_LABELS = {
    "launch": "启动",
    "confirm": "确认",
    "extend": "延续",
    "decline": "衰退",
}
ENGINE_LABELS = {
    "market": "市场认知引擎",
    "stock": "个股认知引擎",
    "event": "事件认知引擎",
    "opportunity": "交易机会引擎",
    "decision": "交易决策引擎",
}
PRIMARY_RULE = {
    "buy": "enter",
    "hold": "hold",
    "add": "add",
    "reduce": "reduce",
    "sell": "stop",
    "watch": "watch",
}


class CognitionError(Exception):
    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


# ---------------------------------------------------------------------------
# Small RDF readers
# ---------------------------------------------------------------------------


def _ref(store: OntologyStore, subject: Any) -> dict[str, Any] | None:
    if not isinstance(subject, URIRef):
        return None
    return store._ref(subject)


def _refs(store: OntologyStore, subject: Any, predicate: Any) -> list[dict[str, Any]]:
    return [item for item in store._refs(subject, predicate) if item]


def _concept(store: OntologyStore, subject: Any) -> dict[str, Any] | None:
    if not isinstance(subject, URIRef):
        return None
    ref = store._ref(subject)
    if not ref:
        return None
    code = store._text(subject, SKOS.notation)
    return {**ref, "code": code or local_name(subject)}


def _latest(store: OntologyStore, parent: Any, predicate: Any) -> Any:
    values = [value for value in store._all(parent, predicate) if isinstance(value, URIRef)]
    if not values:
        return None
    return max(values, key=lambda item: str(store._date(item, ASH.dataAsOf) or store._date(item, ASH.caseAsOf) or ""))


def _dedupe_citations(items: Iterable[dict[str, Any] | None], limit: int = 28) -> list[dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------


def _market(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "regimeCode": store._text(node, ASH.marketRegimeCode) or "",
        "trend": store._text(node, ASH.marketTrendState) or "",
        "breadth": store._text(node, ASH.marketBreadthState) or "",
        "sentiment": store._text(node, ASH.marketSentimentState) or "",
        "liquidity": store._text(node, ASH.marketLiquidityState) or "",
        "riskAppetiteScore": store._num(node, ASH.marketRiskAppetiteScore),
        "shortTermEcology": store._text(node, ASH.marketShortTermEcology) or "",
        "summary": store._text(node, ASH.marketCognitionSummary) or "",
        "regime": _ref(store, store._first(node, ASH.cognitionOfRegime)),
        "sentimentCycle": _ref(store, store._first(node, ASH.cognitionOfSentiment)),
    }


def _sector(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "sector": _concept(store, store._first(node, ASH.cognitionOfSector)),
        "themeHeat": _ref(store, store._first(node, ASH.cognitionOfThemeHeat)),
        "trend": store._text(node, ASH.sectorTrendState) or "",
        "capital": store._text(node, ASH.sectorCapitalState) or "",
        "diffusion": store._text(node, ASH.sectorDiffusionState) or "",
        "leader": store._text(node, ASH.sectorLeaderState) or "",
        "position": store._text(node, ASH.stockSectorPosition) or "",
        "persistence": store._text(node, ASH.themePersistenceState) or "",
        "summary": store._text(node, ASH.sectorCognitionSummary) or "",
    }


def _volume_price(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "type": store._text(node, ASH.volumePriceType) or "",
        "code": store._text(node, ASH.volumePriceTypeCode) or "",
        "priceChangePct": store._num(node, ASH.priceChangePct),
        "volumeChangePct": store._num(node, ASH.volumeChangePct),
        "sequence": store._text(node, ASH.volumePriceSequence) or "",
        "meaning": store._text(node, ASH.volumePriceMeaning) or "",
    }


def _auction(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "type": store._text(node, ASH.auctionBehaviorType) or "",
        "code": store._text(node, ASH.auctionBehaviorCode) or "",
        "note": store._text(node, ASH.auctionBehaviorNote) or "",
        "snapshot": _ref(store, store._first(node, ASH.behaviorFromAuction)),
    }


def _intraday(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "type": store._text(node, ASH.intradayBehaviorType) or "",
        "code": store._text(node, ASH.intradayBehaviorCode) or "",
        "note": store._text(node, ASH.intradayBehaviorNote) or "",
    }


def _stock(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "security": _ref(store, store._first(node, ASH.stockCognitionOfSecurity)),
        "trendState": _ref(store, store._first(node, ASH.cognitionTrendState)),
        "pricePattern": _ref(store, store._first(node, ASH.cognitionPricePattern)),
        "trendDirection": store._text(node, ASH.stockTrendDirection) or "",
        "trendStage": store._text(node, ASH.stockTrendStage) or "",
        "pricePosition": store._text(node, ASH.stockPricePosition) or "",
        "keyLevel": store._text(node, ASH.stockKeyLevel) or "",
        "structure": store._text(node, ASH.stockPriceStructure) or "",
        "volatility": store._text(node, ASH.stockVolatilityState) or "",
        "quality": store._text(node, ASH.stockTrendQuality) or "",
        "summary": store._text(node, ASH.stockCognitionSummary) or "",
        "volumePrice": [
            item
            for item in (_volume_price(store, value) for value in store._all(node, ASH.hasVolumePriceBehavior))
            if item
        ],
        "auction": [
            item
            for item in (_auction(store, value) for value in store._all(node, ASH.hasAuctionBehavior))
            if item
        ],
        "intraday": [
            item
            for item in (_intraday(store, value) for value in store._all(node, ASH.hasIntradayBehavior))
            if item
        ],
    }


def _event(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "event": _ref(store, store._first(node, ASH.eventCognitionOfEvent)),
        "type": store._text(node, ASH.eventType) or "",
        "verified": store._bool(node, ASH.eventVerified),
        "businessRelevant": store._bool(node, ASH.eventBusinessRelevant),
        "alreadyPriced": store._bool(node, ASH.eventAlreadyPriced),
        "sectorResonance": store._bool(node, ASH.eventSectorResonance),
        "priceConfirmation": store._bool(node, ASH.eventPriceConfirmation),
        "counterEvidence": store._text(node, ASH.eventCounterEvidence) or "",
        "summary": store._text(node, ASH.eventCognitionSummary) or "",
    }


def _risk_reward(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "winRateBasis": store._text(node, ASH.winRateBasis) or "",
        "winRateSampleSize": store._num(node, ASH.winRateSampleSize),
        "winRateSource": store._text(node, ASH.winRateSource) or "",
        "potentialGainPct": store._num(node, ASH.potentialGainPct),
        "potentialLossPct": store._num(node, ASH.potentialLossPct),
        "expectedRewardRiskRatio": store._num(node, ASH.expectedRewardRiskRatio),
        "plannedPositionWeight": store._num(node, ASH.plannedPositionWeight),
        "invalidation": store._text(node, ASH.riskRewardInvalidation) or "",
        "tradingCostNote": store._text(node, ASH.tradingCostNote) or "",
        "verdict": store._text(node, ASH.riskRewardVerdict) or "",
    }


def _evidence(store: OntologyStore, node: Any) -> dict[str, Any]:
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "source": store._text(node, ASH.dataSource) or "",
    }


def _opportunity(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    stage = _concept(store, store._first(node, ASH.hasOpportunityStage))
    supporting = [_evidence(store, item) for item in store._all(node, ASH.opportunitySupportingEvidence)]
    counter = [_evidence(store, item) for item in store._all(node, ASH.opportunityCounterEvidence)]
    return {
        **(store._ref(node) or {}),
        "asOf": store._date(node, ASH.dataAsOf),
        "security": _ref(store, store._first(node, ASH.opportunityForSecurity)),
        "structure": store._text(node, ASH.opportunityStructure) or "",
        "stage": stage,
        "stageCode": store._text(node, ASH.opportunityStageCode) or (stage or {}).get("code", ""),
        "confirmation": store._text(node, ASH.opportunityConfirmation) or "",
        "supportingSummary": store._text(node, ASH.supportingEvidenceSummary) or "",
        "counterSummary": store._text(node, ASH.counterEvidenceSummary) or "",
        "counterEvidenceCount": store._num(node, ASH.counterEvidenceCount),
        "counterEvidenceReviewed": store._bool(node, ASH.counterEvidenceReviewed),
        "verdict": store._text(node, ASH.opportunityVerdict) or "",
        "supportingEvidence": supporting,
        "counterEvidence": counter,
        "riskReward": _risk_reward(store, store._first(node, ASH.hasRiskReward)),
        "fromMarket": _ref(store, store._first(node, ASH.fromMarketCognition)),
        "fromSector": _ref(store, store._first(node, ASH.fromSectorCognition)),
        "fromStock": _ref(store, store._first(node, ASH.fromStockCognition)),
        "fromEvent": _ref(store, store._first(node, ASH.fromEventCognition)),
    }


def _behavior_rule(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    action = _concept(store, store._first(node, ASH.hasBehaviorAction))
    return {
        **(store._ref(node) or {}),
        "ruleId": store._text(node, ASH.behaviorRuleId) or local_name(node),
        "action": action,
        "actionCode": store._text(node, ASH.behaviorActionCode) or (action or {}).get("code", ""),
        "condition": store._text(node, ASH.behaviorCondition) or "",
        "priority": store._num(node, ASH.behaviorPriority),
        "asOf": store._date(node, ASH.behaviorAsOf),
    }


def _revision(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    return {
        **(store._ref(node) or {}),
        "revisionId": store._text(node, ASH.judgmentRevisionId) or local_name(node),
        "fromVersion": store._num(node, ASH.revisionFromVersion),
        "toVersion": store._num(node, ASH.revisionToVersion),
        "reason": store._text(node, ASH.revisionReason) or "",
        "changedField": store._text(node, ASH.revisionChangedField) or "",
        "summary": store._text(node, ASH.revisionSummary) or "",
        "asOf": store._date(node, ASH.revisionAsOf),
        "triggerEvidence": [
            _evidence(store, item) for item in store._all(node, ASH.revisionTriggerEvidence)
        ],
    }


def _verification(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    result = _concept(store, store._first(node, ASH.hasVerificationResult))
    return {
        **(store._ref(node) or {}),
        "verificationId": store._text(node, ASH.verificationId) or local_name(node),
        "result": result,
        "resultCode": store._text(node, ASH.verificationResultCode) or (result or {}).get("code", ""),
        "returnPct": store._num(node, ASH.verificationReturnPct),
        "maxAdverseExcursion": store._num(node, ASH.verificationMaxAdverseExcursion),
        "maxFavorableExcursion": store._num(node, ASH.verificationMaxFavorableExcursion),
        "logicStillValid": store._bool(node, ASH.verificationLogicStillValid),
        "lesson": store._text(node, ASH.verificationLesson) or "",
        "asOf": store._date(node, ASH.verificationAsOf),
        "evidence": [_evidence(store, item) for item in store._all(node, ASH.verificationEvidence)],
    }


def _judgment(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    scenario = _concept(store, store._first(node, ASH.hasJudgmentScenario))
    decision = _concept(store, store._first(node, ASH.hasJudgmentDecision))
    rules = [
        item
        for item in (_behavior_rule(store, value) for value in store._all(node, ASH.hasBehaviorRule))
        if item
    ]
    rules.sort(key=lambda item: (item.get("priority") is None, item.get("priority") or 0))
    revisions = [
        item
        for item in (_revision(store, value) for value in store._all(node, ASH.hasJudgmentRevision))
        if item
    ]
    revisions.sort(key=lambda item: item.get("toVersion") or 0)
    return {
        **(store._ref(node) or {}),
        "security": _ref(store, store._first(node, ASH.judgmentOfSecurity)),
        "case": _ref(store, store._first(node, ASH.judgmentForCase)),
        "assessment": _ref(store, store._first(node, ASH.judgmentFromAssessment)),
        "scenario": scenario,
        "scenarioCode": store._text(node, ASH.judgmentScenarioCode) or (scenario or {}).get("code", ""),
        "decision": decision,
        "decisionCode": store._text(node, ASH.judgmentDecisionCode) or (decision or {}).get("code", ""),
        "coreOpportunity": store._text(node, ASH.judgmentCoreOpportunity) or "",
        "marketState": store._text(node, ASH.judgmentMarketState) or "",
        "stockState": store._text(node, ASH.judgmentStockState) or "",
        "supportingSummary": store._text(node, ASH.judgmentSupportingSummary) or "",
        "counterSummary": store._text(node, ASH.judgmentCounterSummary) or "",
        "invalidation": store._text(node, ASH.judgmentInvalidation) or "",
        "version": store._num(node, ASH.judgmentVersion),
        "originalLogic": store._text(node, ASH.judgmentOriginalLogic) or "",
        "logicStillValid": store._bool(node, ASH.judgmentLogicStillValid),
        "confidenceBasis": store._text(node, ASH.judgmentConfidenceBasis) or "",
        "asOf": store._date(node, ASH.judgmentAsOf),
        "plan": _ref(store, store._first(node, ASH.judgmentHasPlan)),
        "linkedDecision": _ref(store, store._first(node, ASH.judgmentLinkedDecision)),
        "basedOn": [_evidence(store, item) for item in store._all(node, ASH.judgmentBasedOn)],
        "counterEvidence": [
            _evidence(store, item) for item in store._all(node, ASH.judgmentCounterEvidence)
        ],
        "behaviorRules": rules,
        "revisions": revisions,
    }


def _case(store: OntologyStore, node: Any) -> dict[str, Any] | None:
    if not isinstance(node, URIRef):
        return None
    scenario = _concept(store, store._first(node, ASH.caseScenario))
    return {
        **(store._ref(node) or {}),
        "caseId": store._text(node, ASH.caseId) or local_name(node),
        "security": _ref(store, store._first(node, ASH.caseOfSecurity)),
        "company": _ref(store, store._first(node, ASH.caseOfCompany)),
        "scenario": scenario,
        "scenarioCode": store._text(node, ASH.caseScenarioCode) or (scenario or {}).get("code", ""),
        "asOf": store._date(node, ASH.caseAsOf),
        "summary": store._text(node, ASH.caseSummary) or "",
        "version": store._num(node, ASH.caseVersion),
        "engines": _refs(store, node, ASH.caseUsesEngine),
    }


# ---------------------------------------------------------------------------
# Case discovery
# ---------------------------------------------------------------------------


def _case_subjects(store: OntologyStore) -> list[URIRef]:
    return sorted(
        (item for item in store.graph.subjects(RDF.type, ASH.AnalysisCase) if isinstance(item, URIRef)),
        key=str,
    )


def _find_case(
    store: OntologyStore,
    company: URIRef | None,
    security: URIRef | None,
    scenario: str | None,
) -> URIRef | None:
    candidates = []
    for case in _case_subjects(store):
        if company is not None and store._first(case, ASH.caseOfCompany) != company:
            continue
        if security is not None and store._first(case, ASH.caseOfSecurity) != security:
            continue
        if scenario in SCENARIOS:
            case_scenario = store._text(case, ASH.caseScenarioCode)
            if case_scenario != scenario:
                continue
        candidates.append(case)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            str(store._date(item, ASH.caseAsOf) or ""),
            store._num(item, ASH.caseVersion) or 0,
        ),
        reverse=True,
    )
    return candidates[0]


def _position_for(store: OntologyStore, security: URIRef | None) -> dict[str, Any] | None:
    if security is None:
        return None
    for position in store.graph.subjects(ASH.positionIn, security):
        if not isinstance(position, URIRef):
            continue
        state = _latest(store, position, ASH.hasPositionState)
        state_dict = None
        if isinstance(state, URIRef):
            state_dict = {
                **(store._ref(state) or {}),
                "status": store._text(state, ASH.positionStatus) or "",
                "availableQuantity": store._num(state, ASH.availableQuantity),
                "lastPrice": store._num(state, ASH.stateLastPrice),
                "unrealizedPnlPct": store._num(state, ASH.unrealizedPnlPct),
                "asOf": store._date(state, ASH.dataAsOf),
            }
        return {
            **(store._ref(position) or {}),
            "weight": store._num(position, ASH.positionWeight),
            "avgCost": store._num(position, ASH.avgCost),
            "quantity": store._num(position, ASH.quantity),
            "state": state_dict,
        }
    return None


def _resolve_company(store: OntologyStore, company: str | None) -> tuple[URIRef | None, URIRef | None]:
    if company:
        subject = store.find_company(company)
        if subject is None and store.market_data is not None:
            try:
                subject = store.real_company(company)
            except MarketDataError as exc:
                raise CognitionError(
                    "real_data_unavailable",
                    f"真实行情获取失败：{exc.message}",
                    available=[store._label(item) for item in store._company_subjects],
                ) from exc
        if subject is None:
            raise CognitionError(
                "company_not_found",
                f"没有找到公司“{company}”。请使用本体示例公司，或提供 6 位 A 股代码/证券简称。",
                available=[store._label(item) for item in store._company_subjects],
            )
        security = store._first(subject, ASH.hasSecurity)
        return subject, security if isinstance(security, URIRef) else None
    for case in _case_subjects(store):
        case_company = store._first(case, ASH.caseOfCompany)
        case_security = store._first(case, ASH.caseOfSecurity)
        if isinstance(case_company, URIRef):
            return case_company, case_security if isinstance(case_security, URIRef) else None
    return None, None


# ---------------------------------------------------------------------------
# Public context builder
# ---------------------------------------------------------------------------


def _real_evidence(item: dict[str, Any], label: str, *, fallback_id: str = "") -> dict[str, Any]:
    return {
        "id": item.get("id") or fallback_id,
        "iri": item.get("iri") or "",
        "label": label,
        "kind": "real",
        "asOf": item.get("asOf"),
        "source": item.get("source") or "",
    }


def _real_behavior_rule(
    rule_id: str,
    action_code: str,
    action_label: str,
    condition: str,
    priority: int,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "iri": "",
        "label": action_label,
        "kind": "real",
        "ruleId": rule_id,
        "action": {"id": action_code, "label": action_label, "code": action_code},
        "actionCode": action_code,
        "condition": condition,
        "priority": priority,
        "asOf": None,
    }


def _build_real_context(
    store: OntologyStore,
    subject: URIRef,
    scenario: str | None,
) -> dict[str, Any]:
    """Build a provisional five-stage view from public real-company facts.

    Real A-shares do not have historical ``AnalysisCase`` individuals. This
    fallback only uses the facts the public adapter actually returned and marks
    every missing dimension explicitly. It must not invent auction, sector
    performance, event or historical win-rate evidence.
    """

    knowledge = store.company_knowledge(subject)
    data = knowledge.to_dict()
    company = data.get("company") or {}
    security = data.get("security") or {}
    quote = data.get("quote") or {}
    valuation = data.get("valuation") or {}
    financials = data.get("financials") or {}
    short = data.get("shortTerm") or {}
    industry = company.get("industry") or {}
    signals = evaluate_company(data)

    last = _num(quote.get("lastPrice"))
    change = _num(quote.get("changePct"))
    turnover = _num(quote.get("turnoverRate"))
    pe = _num(valuation.get("peTtm"))
    roe = _num(financials.get("roe"))
    interest = _num(financials.get("interestCoverage"))
    profit_growth = _num(financials.get("profitGrowth"))
    revenue_growth = _num(financials.get("revenueGrowth"))
    ma5 = _num(short.get("ma5"))
    ma20 = _num(short.get("ma20"))
    ma60 = _num(short.get("ma60"))
    limit_up_days = _num(short.get("limitUpDays"))

    direction = "未知"
    if last is not None and ma20 is not None and ma60 is not None:
        if last >= ma20 >= ma60:
            direction = "上升"
        elif last <= ma20 <= ma60:
            direction = "下降"
        else:
            direction = "横盘"

    stage = "未知"
    if change is not None and change >= 9.5 and (limit_up_days or 0) <= 1:
        stage = "启动"
    elif direction == "上升":
        stage = "延续"
    elif direction == "下降":
        stage = "衰竭"
    elif direction == "横盘":
        stage = "整理"

    position_label = "未知"
    if last is not None and ma20 is not None and ma60 is not None:
        if last <= ma20 and last <= ma60:
            position_label = "低位"
        elif last >= ma20 and last >= ma60:
            position_label = "高位"
        else:
            position_label = "中位"

    structure = "未知"
    if last is not None and ma20 is not None:
        if last >= ma20:
            structure = "站上 MA20"
        elif change is not None and change >= 5:
            structure = "跌破 MA20 后单日反弹"
        else:
            structure = "跌破 MA20"

    key_level_bits = []
    if ma5 is not None:
        key_level_bits.append(f"MA5 {ma5:.2f}")
    if ma20 is not None:
        key_level_bits.append(f"MA20 {ma20:.2f}")
    if ma60 is not None:
        key_level_bits.append(f"MA60 {ma60:.2f}")
    if last is not None:
        key_level_bits.append(f"现价 {last:.2f}")

    stock = {
        "id": f"real-stock-{security.get('code') or ''}",
        "iri": security.get("iri") or "",
        "label": f"{company.get('label') or '真实证券'} 真实数据个股状态",
        "kind": "real",
        "asOf": quote.get("asOf"),
        "security": security,
        "trendState": None,
        "pricePattern": None,
        "trendDirection": direction,
        "trendStage": stage,
        "pricePosition": position_label,
        "keyLevel": "；".join(key_level_bits) or "缺少均线数据",
        "structure": structure,
        "volatility": "未知",
        "quality": "待确认" if direction != "下降" else "偏弱",
        "summary": (
            f"价格 {last:.2f}" if last is not None else "价格未知"
        )
        + (f"、当日 {change:+.2f}%" if change is not None else "")
        + (f"，低于 MA20 {ma20:.2f} 与 MA60 {ma60:.2f}" if ma20 is not None and ma60 is not None and last is not None and last < ma20 and last < ma60 else "")
        + "；真实数据未覆盖成交量变化、竞价与分时，量价与盘中行为无法确认。",
        "volumePrice": [
            {
                "id": f"real-vp-{security.get('code') or ''}",
                "iri": "",
                "label": "量价待确认",
                "kind": "real",
                "asOf": quote.get("asOf"),
                "type": "量价待确认",
                "code": "unknown",
                "priceChangePct": change,
                "volumeChangePct": None,
                "sequence": "",
                "meaning": "真实数据只有当日涨跌幅、换手率与成交量总量，缺少成交量变化与分时，不能确认放量或缩量。",
            }
        ],
        "auction": [],
        "intraday": [],
    }

    sector = {
        "id": f"real-sector-{industry.get('id') or 'unknown'}",
        "iri": industry.get("iri") or "",
        "label": f"{industry.get('label') or '未知行业'} 板块认知（真实数据）",
        "kind": "real",
        "asOf": quote.get("asOf"),
        "sector": industry or None,
        "themeHeat": None,
        "trend": "未知",
        "capital": "未知",
        "diffusion": "未知",
        "leader": "未知",
        "position": "未知",
        "persistence": "未知",
        "summary": (
            f"行业为{industry.get('label')}" if industry.get("label") else "行业未知"
        )
        + "；真实数据未覆盖板块资金、扩散、龙头与题材持续性，无法确认板块共振。",
    }

    support = [
        _real_evidence(quote, f"{company.get('label') or '证券'} {quote.get('asOf') or ''} 行情（{change:+.2f}%）" if change is not None else f"{company.get('label') or '证券'} 行情"),
    ]
    if financials:
        support.append(_real_evidence(financials, f"{financials.get('period') or ''} 年报：净利润增长 {profit_growth:+.2f}%" if profit_growth is not None else "年报"))
    if industry.get("label"):
        support.append({"id": industry.get("id"), "iri": industry.get("iri"), "label": f"所属行业：{industry.get('label')}", "kind": "concept", "asOf": None, "source": ""})

    counter = []
    if last is not None and ma20 is not None and ma60 is not None and last < ma20 and last < ma60:
        counter.append(
            {
                "id": f"real-counter-ma-{security.get('code') or ''}",
                "iri": "",
                "label": f"价格 {last:.2f} 低于 MA20 {ma20:.2f} 与 MA60 {ma60:.2f}",
                "kind": "real",
                "asOf": quote.get("asOf"),
                "source": quote.get("source") or "",
            }
        )
    if pe is not None and pe >= 60:
        counter.append(
            {
                "id": f"real-counter-pe-{security.get('code') or ''}",
                "iri": "",
                "label": f"PE(TTM) {pe:.1f} 偏高，缺少盈利增速匹配",
                "kind": "real",
                "asOf": valuation.get("asOf"),
                "source": valuation.get("source") or "",
            }
        )
    if interest is not None and interest < 2:
        counter.append(
            {
                "id": f"real-counter-interest-{security.get('code') or ''}",
                "iri": "",
                "label": f"利息保障倍数 {interest:.2f} 偏低",
                "kind": "real",
                "asOf": financials.get("asOf"),
                "source": financials.get("source") or "",
            }
        )
    if roe is not None and roe < 10:
        counter.append(
            {
                "id": f"real-counter-roe-{security.get('code') or ''}",
                "iri": "",
                "label": f"ROE {roe:.2f}% 低于价值筛选门槛",
                "kind": "real",
                "asOf": financials.get("asOf"),
                "source": financials.get("source") or "",
            }
        )

    stage_code = "launch" if stage == "启动" else ("confirm" if stage == "延续" else "decline" if stage == "衰竭" else "launch")
    invalidation = "跌破本次涨停打开后的低点、重新跌破 MA20，或 2025 年报逻辑被证伪。"
    risk_reward = {
        "id": f"real-rr-{security.get('code') or ''}",
        "iri": "",
        "label": "真实数据风险收益评估",
        "kind": "real",
        "asOf": quote.get("asOf"),
        "winRateBasis": "真实数据没有同场景历史样本，不能给出胜率；需要先建立可复现的样本库。",
        "winRateSampleSize": None,
        "winRateSource": "",
        "potentialGainPct": None,
        "potentialLossPct": None,
        "expectedRewardRiskRatio": None,
        "plannedPositionWeight": None,
        "invalidation": invalidation,
        "tradingCostNote": "缺少具体入场、止损与目标，无法计算交易成本对盈亏比的影响。",
        "verdict": "风险收益无法评估；单日涨停不足以确定入场、止损与目标。",
    }

    opportunity = {
        "id": f"real-opportunity-{security.get('code') or ''}",
        "iri": "",
        "label": "真实数据机会评估",
        "kind": "real",
        "asOf": quote.get("asOf"),
        "security": security,
        "structure": (
            f"单日 {change:+.2f}% 涨停反弹，但价格仍在 MA20/MA60 下方；" if change is not None else "单日价格异动；"
        )
        + "缺少板块资金、事件、竞价与量能变化证据。",
        "stage": {"id": stage_code, "label": STAGE_LABELS.get(stage_code, stage_code), "code": stage_code},
        "stageCode": stage_code,
        "confirmation": f"站上 MA20 {ma20:.2f} 并放量、板块同步走强，或出现可验证的事件催化。" if ma20 is not None else "站上中期均线并放量、板块同步走强，或出现可验证的事件催化。",
        "supportingSummary": "；".join(item["label"] for item in support) or "缺少支持证据。",
        "counterSummary": "；".join(item["label"] for item in counter) or "没有识别到反向证据。",
        "counterEvidenceCount": len(counter),
        "counterEvidenceReviewed": True,
        "verdict": "仅单日反弹，机会未确认；缺少板块/事件/竞价/量能证据，不能给出买入结论。",
        "supportingEvidence": support,
        "counterEvidence": counter,
        "riskReward": risk_reward,
        "fromMarket": None,
        "fromSector": {"id": sector["id"], "label": sector["label"]},
        "fromStock": {"id": stock["id"], "label": stock["label"]},
        "fromEvent": None,
    }

    behavior_rules = [
        _real_behavior_rule(
            "REAL-WATCH",
            "watch",
            "观望",
            "等待站上 MA20 且成交量/板块确认，否则不参与。",
            10,
        ),
        _real_behavior_rule(
            "REAL-ENTER",
            "enter",
            "建仓",
            "站上 MA20 并放量、板块同步走强后，才评估小仓位试错。",
            20,
        ),
        _real_behavior_rule(
            "REAL-STOP",
            "stop",
            "止损",
            "跌破本次涨停打开后的低点，或重新跌破 MA20。",
            1,
        ),
        _real_behavior_rule(
            "REAL-TAKE-PROFIT",
            "take_profit",
            "止盈",
            "接近 MA60 且量价背离时评估止盈。",
            15,
        ),
    ]

    triggered = [item for item in signals if item.get("status") == "triggered"]
    unknown = [item for item in signals if item.get("status") == "unknown"]
    citations: list[dict[str, Any] | None] = list(knowledge.citations)
    for ref in (subject, store._first(subject, ASH.hasSecurity), store._first(subject, ASH.hasMarketQuote), store._first(subject, ASH.hasValuation), store._first(subject, ASH.hasFinancialReport)):
        if isinstance(ref, URIRef):
            citations.append(store._cite(ref))
    for signal in triggered:
        rule = store.rule(signal["ruleId"])
        if rule:
            citations.append(store._cite(URIRef(rule["iri"])))

    wanted = "held" if (scenario or "").strip().lower() == "held" else "non_position"
    position = _position_for(store, store._first(subject, ASH.hasSecurity))
    if wanted == "held" and position is None:
        raise CognitionError(
            "no_position",
            f"{company.get('label') or '该证券'} 当前没有持仓，不能使用已持仓流程。",
        )

    return {
        "company": store._ref(subject),
        "security": security or None,
        "scenario": wanted,
        "scenarioLabel": "已持仓" if wanted == "held" else "非持仓",
        "detectedScenario": "held" if position else "non_position",
        "scenarioMatchesRecord": False,
        "case": None,
        "market": None,
        "sector": sector,
        "stock": stock,
        "event": None,
        "opportunity": opportunity,
        "riskReward": risk_reward,
        "judgment": None,
        "behaviorRules": behavior_rules,
        "verification": None,
        "revisions": [],
        "position": position,
        "tradeContext": None,
        "engines": [
            {"id": "market", "label": ENGINE_LABELS["market"], "status": "missing", "detail": "真实数据缺少指数、广度、情绪、流动性与风险偏好，无法确认市场是否允许交易。"},
            {"id": "stock", "label": ENGINE_LABELS["stock"], "status": "partial", "detail": "已有价格、均线、换手与财务；缺少成交量变化、竞价与分时。"},
            {"id": "event", "label": ENGINE_LABELS["event"], "status": "missing", "detail": "真实数据缺少事件/公告，无法判断事件真实性与持续性。"},
            {"id": "opportunity", "label": ENGINE_LABELS["opportunity"], "status": "partial", "detail": "已有价格结构与反向证据；缺少板块、事件、量能与历史样本。"},
            {"id": "decision", "label": ENGINE_LABELS["decision"], "status": "missing", "detail": "真实证券没有历史判断记录；本次只生成临时判断，不写回本体。"},
        ],
        "riskSignals": signals,
        "missingDimensions": [
            "市场认知（指数、广度、情绪、流动性、风险偏好）",
            "板块资金/扩散/龙头/题材持续性",
            "事件与公告",
            "集合竞价与盘中分时",
            "成交量变化（放量/缩量）",
            "同场景历史胜率样本",
            "历史判断记录与结果验证",
        ],
        "dataMode": "real",
        "dataSource": quote.get("source") or SOURCE_LABEL,
        "marketDataAsOf": quote.get("asOf"),
        "citations": _dedupe_citations(citations, 28),
        "dataNote": (
            "真实数据模式：只使用公开行情、估值、年报与短线快照，缺失的市场、板块、事件、竞价、分时、"
            "历史样本与判断记录明确标为未知；不猜测缺失维度，不连接真实账户或交易通道，不构成投资建议。"
        ),
    }


def build_cognition_context(
    store: OntologyStore,
    company: str | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Read one AnalysisCase and return all five engine outputs."""

    requested_scenario = (scenario or "auto").strip().lower()
    if requested_scenario in {"", "auto"}:
        requested_scenario = None
    if requested_scenario is not None and requested_scenario not in SCENARIOS:
        raise CognitionError(
            "invalid_scenario",
            "scenario 只能是 auto、non_position 或 held。",
            available=sorted(SCENARIOS),
        )

    company_subject, security = _resolve_company(store, company)
    if company_subject is not None and store.is_real_company(company_subject):
        return _build_real_context(store, company_subject, requested_scenario)
    case_subject = _find_case(store, company_subject, security, requested_scenario)
    if case_subject is not None:
        case_data = _case(store, case_subject)
        if case_data and case_data.get("security"):
            security = URIRef(case_data["security"]["iri"])
    else:
        case_data = None

    position = _position_for(store, security)
    detected_scenario = "held" if position else "non_position"
    active_scenario = requested_scenario or (case_data or {}).get("scenarioCode") or detected_scenario

    market = sector = stock = event = opportunity = judgment = verification = None
    revisions: list[dict[str, Any]] = []
    behavior_rules: list[dict[str, Any]] = []

    if case_subject is not None:
        market = _market(store, store._first(case_subject, ASH.hasMarketCognition))
        sector = _sector(store, store._first(case_subject, ASH.hasSectorCognition))
        stock = _stock(store, store._first(case_subject, ASH.hasStockCognition))
        event = _event(store, store._first(case_subject, ASH.hasEventCognition))
        opportunity = _opportunity(store, store._first(case_subject, ASH.hasOpportunityAssessment))
        judgment = _judgment(store, store._first(case_subject, ASH.hasTradingJudgment))
        verification = _verification(store, _latest(store, case_subject, ASH.hasOutcomeVerification))
    if judgment is None and security is not None:
        judgments = [
            item for item in store.graph.subjects(ASH.judgmentOfSecurity, security) if isinstance(item, URIRef)
        ]
        if judgments:
            judgments.sort(key=lambda item: store._num(item, ASH.judgmentVersion) or 0, reverse=True)
            judgment = _judgment(store, judgments[0])
            if opportunity is None and judgment.get("assessment"):
                opportunity = _opportunity(store, URIRef(judgment["assessment"]["iri"]))
    if judgment:
        revisions = judgment.get("revisions") or []
        behavior_rules = judgment.get("behaviorRules") or []

    trade_context: dict[str, Any] | None = None
    try:
        if company_subject is not None:
            trade_context = build_trade_context(store, store._label(company_subject))
    except DecisionError:
        trade_context = None

    wanted = "held" if active_scenario == "held" else "non_position"
    scenario_match = bool(judgment) and judgment.get("scenarioCode") == wanted

    engines = [
        {
            "id": "market",
            "label": ENGINE_LABELS["market"],
            "status": "ok" if market and sector else ("partial" if market or sector else "missing"),
            "detail": (market or {}).get("summary") or (sector or {}).get("summary") or "缺少市场或板块认知。",
        },
        {
            "id": "stock",
            "label": ENGINE_LABELS["stock"],
            "status": "ok" if stock and (stock.get("volumePrice") or stock.get("auction")) else ("partial" if stock else "missing"),
            "detail": (stock or {}).get("summary") or "缺少个股认知。",
        },
        {
            "id": "event",
            "label": ENGINE_LABELS["event"],
            "status": "ok" if event else "missing",
            "detail": (event or {}).get("summary") or "缺少事件认知。",
        },
        {
            "id": "opportunity",
            "label": ENGINE_LABELS["opportunity"],
            "status": "ok" if opportunity and opportunity.get("riskReward") else ("partial" if opportunity else "missing"),
            "detail": (opportunity or {}).get("verdict") or "缺少机会评估。",
        },
        {
            "id": "decision",
            "label": ENGINE_LABELS["decision"],
            "status": "ok" if judgment and behavior_rules else ("partial" if judgment else "missing"),
            "detail": (judgment or {}).get("coreOpportunity") or "缺少交易判断。",
        },
    ]

    citations: list[dict[str, Any] | None] = []
    for node in (case_subject,):
        if isinstance(node, URIRef):
            citations.append(store._cite(node))
    for record in (market, sector, stock, event, opportunity, judgment, verification):
        if record and record.get("iri"):
            citations.append(store._cite(URIRef(record["iri"])))
    if opportunity:
        risk_reward = opportunity.get("riskReward") or {}
        if risk_reward.get("iri"):
            citations.append(store._cite(URIRef(risk_reward["iri"])))
        for item in (opportunity.get("supportingEvidence") or []) + (opportunity.get("counterEvidence") or []):
            if item.get("iri"):
                citations.append(store._cite(URIRef(item["iri"])))
    for rule in behavior_rules:
        if rule.get("iri"):
            citations.append(store._cite(URIRef(rule["iri"])))
    for revision in revisions:
        if revision.get("iri"):
            citations.append(store._cite(URIRef(revision["iri"])))
    if trade_context:
        citations.extend(trade_context.get("citations") or [])

    return {
        "company": store._ref(company_subject),
        "security": store._ref(security),
        "scenario": wanted,
        "scenarioLabel": "已持仓" if wanted == "held" else "非持仓",
        "detectedScenario": detected_scenario,
        "scenarioMatchesRecord": scenario_match,
        "case": case_data,
        "market": market,
        "sector": sector,
        "stock": stock,
        "event": event,
        "opportunity": opportunity,
        "riskReward": (opportunity or {}).get("riskReward"),
        "judgment": judgment,
        "behaviorRules": behavior_rules,
        "verification": verification,
        "revisions": revisions,
        "position": position,
        "tradeContext": trade_context,
        "engines": engines,
        "citations": _dedupe_citations(citations, 28),
        "dataNote": (
            "市场、板块、个股、量价、竞价、事件、机会、判断、行为规则与结果验证均为本体中的合成示例；"
            "判断只读取 RDF 事实与示例阈值，不连接真实行情、账户或交易通道。"
        ),
    }


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def _status(ok: bool | None) -> str:
    if ok is None:
        return "unknown"
    return "pass" if ok else "fail"


def _check(
    check_id: str,
    stage: str,
    label: str,
    ok: bool | None,
    detail: str,
    *,
    blocking: bool = True,
    rule_id: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "stage": stage,
        "label": label,
        "status": _status(ok),
        "detail": detail,
        "blocking": blocking and ok is not True,
        "ruleId": rule_id,
    }


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    market = context.get("market") or {}
    score = _num(market.get("riskAppetiteScore"))
    regime = market.get("regimeCode") or ""
    return [
        _check(
            "C-MKT-01",
            "market",
            "市场风险偏好",
            None if score is None else score >= 30,
            (
                f"风险偏好分数 {score:.0f}，门槛 30；低于门槛时暂停新增风险敞口。"
                if score is not None
                else "缺少市场风险偏好分数，无法判断市场是否允许交易。"
            ),
            rule_id="R162",
        ),
        _check(
            "C-MKT-02",
            "market",
            "市场状态否决",
            None if not regime else regime not in {"ebb", "defense"},
            (
                f"市场状态代码 {regime}；退潮或防守状态不新增风险。"
                if regime
                else "缺少市场状态代码，无法判断是否退潮。"
            ),
        ),
        _check(
            "C-MKT-03",
            "market",
            "市场广度与情绪",
            None
            if not (market.get("breadth") or market.get("sentiment"))
            else (market.get("breadth") != "普跌" and market.get("sentiment") != "退潮"),
            f"广度 {market.get('breadth') or '—'}，情绪 {market.get('sentiment') or '—'}；极端普跌或退潮时降低仓位。",
            blocking=False,
        ),
    ]


def _opportunity_checks(context: dict[str, Any], scenario: str) -> list[dict[str, Any]]:
    opportunity = context.get("opportunity") or {}
    stock = context.get("stock") or {}
    stage = opportunity.get("stageCode") or ""
    reviewed = opportunity.get("counterEvidenceReviewed")
    count = _num(opportunity.get("counterEvidenceCount"))
    vp_codes = {item.get("code") for item in (stock.get("volumePrice") or []) if item.get("code")}
    auction_codes = {item.get("code") for item in (stock.get("auction") or []) if item.get("code")}
    intraday_codes = {item.get("code") for item in (stock.get("intraday") or []) if item.get("code")}
    structure_ok = stock.get("structure") not in {"破位", "跌破"}
    vp_ok = not (vp_codes & {"volume_decline", "seq_high_breakdown", "divergence"})
    behavior_ok = not (auction_codes & {"strong_to_weak", "seal_decay"}) and not (
        intraday_codes & {"breakdown"}
    )
    return [
        _check(
            "C-OPP-01",
            "opportunity",
            "机会阶段",
            None if not stage else (stage in {"confirm", "extend"} if scenario == "non_position" else stage != "decline"),
            (
                f"机会阶段 {STAGE_LABELS.get(stage, stage)}；买入场景要求确认或延续，持仓场景下衰退会触发减仓评估。"
                if stage
                else "缺少机会阶段，无法判断机会是否成立。"
            ),
            blocking=scenario == "non_position",
            rule_id="R169",
        ),
        _check(
            "C-OPP-02",
            "opportunity",
            "反向证据审查",
            None if count is None and reviewed is None else (count in (None, 0) or reviewed is True),
            (
                f"识别反向证据 {int(count or 0)} 条，已审查={reviewed}；存在反向证据但未审查时判断不完整。"
                if count is not None or reviewed is not None
                else "缺少反向证据审查记录，无法判断证据是否完整。"
            ),
            rule_id="R164",
        ),
        _check(
            "C-OPP-03",
            "opportunity",
            "失效条件",
            bool(opportunity.get("riskReward", {}).get("invalidation") or (context.get("judgment") or {}).get("invalidation")),
            "判断必须写明什么新证据会推翻当前结论；没有失效条件就不能完成判断。",
        ),
        _check(
            "C-OPP-04",
            "opportunity",
            "价格结构与量价确认",
            structure_ok and vp_ok,
            (
                f"价格结构 {stock.get('structure') or '—'}；量价 {', '.join(sorted(vp_codes)) or '—'}。"
                "破位或放量下跌会削弱机会。"
            ),
            blocking=scenario == "non_position",
        ),
        _check(
            "C-OPP-05",
            "opportunity",
            "竞价与盘中确认",
            behavior_ok,
            (
                f"竞价 {', '.join(sorted(auction_codes)) or '—'}；盘中 {', '.join(sorted(intraday_codes)) or '—'}。"
                "强转弱或跌破失守不支持新增仓位。"
            ),
            blocking=scenario == "non_position",
        ),
    ]


def _event_checks(context: dict[str, Any], scenario: str) -> list[dict[str, Any]]:
    event = context.get("event") or {}
    return [
        _check(
            "C-EVT-01",
            "event",
            "事件真实性与相关性",
            None
            if not event
            else bool(event.get("verified")) and bool(event.get("businessRelevant")),
            (
                f"事件 {event.get('type') or '—'}：真实={event.get('verified')}，业务相关={event.get('businessRelevant')}。"
                if event
                else "缺少事件认知，无法判断事件是否支撑交易。"
            ),
            blocking=False,
        ),
        _check(
            "C-EVT-02",
            "event",
            "事件是否已被价格确认",
            None
            if not event
            else bool(event.get("priceConfirmation")) and not bool(event.get("alreadyPriced")),
            (
                f"已反映={event.get('alreadyPriced')}，价格确认={event.get('priceConfirmation')}；"
                "利好已兑现且价格不确认时不支持加仓。"
                if event
                else "缺少事件认知，无法判断价格确认。"
            ),
            blocking=scenario == "non_position",
        ),
    ]


def _risk_reward_checks(context: dict[str, Any], scenario: str) -> list[dict[str, Any]]:
    rr = context.get("riskReward") or {}
    ratio = _num(rr.get("expectedRewardRiskRatio"))
    threshold = 2.0 if scenario == "non_position" else 1.5
    return [
        _check(
            "C-RR-01",
            "judgment",
            "风险收益门槛",
            None if ratio is None else ratio >= threshold,
            (
                f"预期盈亏比 {ratio:.2f}，{scenario} 场景门槛 {threshold:.1f}；"
                "不足门槛时只能观望或降低暴露。"
                if ratio is not None
                else "缺少预期盈亏比，无法判断交易是否划算。"
            ),
            blocking=scenario == "non_position",
            rule_id="R163",
        ),
        _check(
            "C-RR-02",
            "judgment",
            "胜率依据",
            bool(rr.get("winRateBasis")),
            (
                f"胜率依据：{rr.get('winRateBasis')}"
                if rr.get("winRateBasis")
                else "缺少胜率依据；不能由 LLM 凭感觉生成概率。"
            ),
            blocking=False,
        ),
        _check(
            "C-RR-03",
            "judgment",
            "风险收益失效条件",
            bool(rr.get("invalidation")),
            rr.get("invalidation") or "缺少风险收益失效条件。",
        ),
    ]


def _judgment_checks(context: dict[str, Any], scenario: str) -> list[dict[str, Any]]:
    judgment = context.get("judgment") or {}
    scenario_match = context.get("scenarioMatchesRecord")
    return [
        _check(
            "C-JUD-01",
            "judgment",
            "场景一致性",
            scenario_match,
            (
                f"本体判断场景 {judgment.get('scenarioCode') or '—'}，当前评估场景 {scenario}；"
                "买入与持仓不能共用一套规则。"
            ),
            blocking=False,
        ),
        _check(
            "C-JUD-02",
            "judgment",
            "判断版本",
            None if judgment.get("version") is None else judgment.get("version") >= 1,
            (
                f"判断版本 v{judgment.get('version')}，修订 {len(context.get('revisions') or [])} 次。"
                if judgment.get("version") is not None
                else "缺少判断版本。"
            ),
            blocking=False,
        ),
        _check(
            "C-JUD-03",
            "judgment",
            "原始持仓逻辑",
            (
                True
                if scenario != "held"
                else (None if judgment.get("logicStillValid") is None else bool(judgment.get("logicStillValid")))
            ),
            (
                f"原始买入逻辑仍成立={judgment.get('logicStillValid')}；失效时进入减仓或退出评估。"
                if scenario == "held"
                else "非持仓场景不适用原始持仓逻辑，按机会与风险收益判断。"
            ),
            blocking=scenario == "held",
            rule_id="R168",
        ),
        _check(
            "C-JUD-04",
            "judgment",
            "行为管理规则",
            None if not context.get("behaviorRules") else len(context["behaviorRules"]) >= 1,
            f"行为规则 {len(context.get('behaviorRules') or [])} 条；判断必须落到可执行的条件。",
            blocking=False,
        ),
    ]


def _verification_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    verification = context.get("verification") or {}
    return [
        _check(
            "C-VER-01",
            "verification",
            "结果验证",
            None if not verification else bool(verification.get("resultCode")),
            (
                f"验证结论 {verification.get('resultCode') or '—'}；收益 {verification.get('returnPct')}%，"
                f"逻辑仍成立={verification.get('logicStillValid')}。"
                if verification
                else "尚未形成结果验证；新判断应标记待验证。"
            ),
            blocking=False,
            rule_id="R167",
        ),
    ]


def _blockers(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in checks if item["blocking"] and item["status"] != "pass"]


def _computed_decision(
    context: dict[str, Any],
    scenario: str,
    blockers: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    judgment = context.get("judgment") or {}
    opportunity = context.get("opportunity") or {}
    rr = context.get("riskReward") or {}
    stage = opportunity.get("stageCode") or ""
    ratio = _num(rr.get("expectedRewardRiskRatio"))
    reasons: list[str] = []

    if scenario == "non_position":
        if blockers:
            reasons = [item["detail"] for item in blockers]
            return "watch", reasons
        if stage not in {"confirm", "extend"}:
            reasons.append(f"机会阶段为 {STAGE_LABELS.get(stage, stage or '未知')}，尚未确认。")
            return "watch", reasons
        if ratio is None or ratio < 2.0:
            reasons.append("预期盈亏比未达到 2.0 门槛。")
            return "watch", reasons
        reasons.append("市场、机会、反向证据与风险收益均通过；按计划小仓位买入。")
        return "buy", reasons

    position = context.get("position") or {}
    budget = (context.get("tradeContext") or {}).get("riskBudget") or {}
    plans = (context.get("tradeContext") or {}).get("plans") or []
    exit_plans = [item for item in plans if isinstance(item, dict) and item.get("kind") == "ExitPlan"]
    bracket = next((item for item in exit_plans if item.get("stopPrice")), None) or {}
    stop = _num((bracket.get("stopPrice") or {}).get("value"))
    last_price = _num((position.get("state") or {}).get("lastPrice"))
    weight = _num(position.get("weight"))
    max_weight = _num(budget.get("maxSingleNameWeight")) or 0.10
    logic_ok = judgment.get("logicStillValid")

    if logic_ok is False or (stop is not None and last_price is not None and last_price <= stop):
        if stop is not None and last_price is not None and last_price <= stop:
            reasons.append(f"最新价 {last_price:.2f} ≤ 止损价 {stop:.2f}，进入退出评估。")
        else:
            reasons.append("原始买入逻辑已失效，继续持有不再具有正向预期价值。")
        return ("sell" if stop is not None and last_price is not None and last_price <= stop else "reduce"), reasons
    if weight is not None and weight > max_weight:
        reasons.append(
            f"单票权重 {weight:.1%} 超过上限 {max_weight:.1%}，必须减仓修复集中度。"
        )
        return "reduce", reasons
    if stage == "decline":
        reasons.append("机会阶段进入衰退，降低暴露而不是继续持有。")
        return "reduce", reasons
    if ratio is not None and ratio < 1.5:
        reasons.append(f"预期盈亏比 {ratio:.2f} 低于持仓门槛 1.5。")
        return "reduce", reasons
    if judgment.get("decisionCode") == "add" and ratio is not None and ratio >= 2.0:
        reasons.append("原逻辑增强、盈亏比达到门槛，且组合约束允许，进入加仓评估。")
        return "add", reasons
    reasons.append("原始逻辑仍成立，未触发减仓、止损或加仓条件，继续持有。")
    return "hold", reasons


def _behavior_plan(context: dict[str, Any], decision: str) -> dict[str, Any]:
    rules = context.get("behaviorRules") or []
    primary_code = PRIMARY_RULE.get(decision, "")
    groups: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        groups.setdefault(rule.get("actionCode") or "other", []).append(rule)
    return {
        "primaryAction": primary_code,
        "rules": rules,
        "groups": groups,
        "primaryRules": [
            rule for rule in rules if (rule.get("actionCode") or "") == primary_code
        ],
    }


def _pipeline(context: dict[str, Any], checks: list[dict[str, Any]], decision: str) -> list[dict[str, Any]]:
    def stage_checks(stage: str) -> list[dict[str, Any]]:
        return [item for item in checks if item["stage"] == stage]

    def stage_status(stage: str) -> str:
        items = stage_checks(stage)
        if not items:
            return "unknown"
        if any(item["status"] == "fail" and item["blocking"] for item in items):
            return "blocked"
        if any(item["status"] in {"fail", "unknown"} for item in items):
            return "warning"
        return "ok"

    return [
        {
            "stage": "market",
            "label": "市场认知",
            "status": stage_status("market"),
            "detail": (context.get("market") or {}).get("summary") or "缺少市场认知。",
        },
        {
            "stage": "opportunity",
            "label": "机会识别",
            "status": stage_status("opportunity"),
            "detail": (context.get("opportunity") or {}).get("verdict") or "缺少机会评估。",
        },
        {
            "stage": "judgment",
            "label": "交易判断",
            "status": stage_status("judgment"),
            "detail": f"{ACTION_LABELS.get(decision, decision)}；{len(stage_checks('judgment'))} 项检查。",
        },
        {
            "stage": "behavior",
            "label": "行为管理",
            "status": "ok" if context.get("behaviorRules") else "warning",
            "detail": f"{len(context.get('behaviorRules') or [])} 条行为规则。",
        },
        {
            "stage": "verification",
            "label": "结果验证",
            "status": stage_status("verification"),
            "detail": (context.get("verification") or {}).get("lesson") or "尚未形成结果验证。",
        },
    ]


def assess_cognition(
    store: OntologyStore,
    company: str | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Read the case and make the scenario-specific, evidence-first judgment."""

    context = build_cognition_context(store, company, scenario)
    active_scenario = context["scenario"]
    checks = (
        _market_checks(context)
        + _opportunity_checks(context, active_scenario)
        + _event_checks(context, active_scenario)
        + _risk_reward_checks(context, active_scenario)
        + _judgment_checks(context, active_scenario)
        + _verification_checks(context)
    )
    blockers = _blockers(checks)
    computed, reasons = _computed_decision(context, active_scenario, blockers)
    recorded = (context.get("judgment") or {}).get("decisionCode") or ""
    consistent = bool(recorded) and recorded == computed
    summary = (
        f"{'已持仓' if active_scenario == 'held' else '非持仓'}场景："
        f"计算结论为{ACTION_LABELS.get(computed, computed)}"
        + (f"，本体记录为{ACTION_LABELS.get(recorded, recorded)}" if recorded else "，本体暂无判断记录")
        + (f"；{reasons[0]}" if reasons else "")
    )

    return {
        **context,
        "checks": checks,
        "blockers": blockers,
        "decision": {
            "code": computed,
            "label": ACTION_LABELS.get(computed, computed),
            "action": computed,
            "recordedCode": recorded,
            "recordedLabel": ACTION_LABELS.get(recorded, recorded) if recorded else "",
            "consistent": consistent,
            "summary": summary,
            "reasons": reasons,
        },
        "behaviorPlan": _behavior_plan(context, computed),
        "pipeline": _pipeline(context, checks, computed),
        "judgmentModel": "opportunity_structure → evidence_verification → counter_evidence_review → risk_reward_gate",
        "scoring": "no_weighted_sum",
        "summary": summary,
        "queryPath": [
            {
                "kind": "select",
                "label": "定位分析案例与交易场景",
                "detail": (context.get("case") or {}).get("caseId") or "—",
            },
            {
                "kind": "traverse",
                "label": "读取五引擎认知输出",
                "detail": "、".join(item["label"] for item in context.get("engines") or []),
            },
            {
                "kind": "verify",
                "label": "多维证据验证与反向证据审查",
                "detail": f"支持 {len((context.get('opportunity') or {}).get('supportingEvidence') or [])} 条；反向 {len((context.get('opportunity') or {}).get('counterEvidence') or [])} 条",
            },
            {
                "kind": "verify",
                "label": "风险收益与场景规则",
                "detail": f"{len(checks)} 项检查，{len(blockers)} 项阻断",
            },
            {
                "kind": "review",
                "label": "行为规则、判断版本与结果验证",
                "detail": f"{len(context.get('behaviorRules') or [])} 条规则；v{(context.get('judgment') or {}).get('version') or '—'}",
            },
        ],
        "dataNote": (
            context.get("dataNote")
            if context.get("dataMode") == "real"
            else (
                "判断只读取本体中的合成示例事实与示例阈值，采用机会结构 → 证据验证 → 反向证据 → 风险收益的顺序，"
                "不做加权评分；不连接真实行情、账户或交易通道，不构成投资建议。"
            )
        ),
    }


__all__ = ["CognitionError", "assess_cognition", "build_cognition_context"]
