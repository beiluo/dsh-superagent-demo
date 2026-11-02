"""Read-only ontology access layer for the stock-analysis agent."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rdflib import Graph, Literal, RDF, RDFS, SKOS, URIRef
from rdflib.namespace import DCTERMS, OWL

from .namespaces import ASH, ASHD, ASHS, ODRL, ONTOLOGY_MODULES
from .rules import RULE_THRESHOLDS, evaluate_company, evaluate_portfolio, fmt_money, fmt_pct, fmt_weight


def local_name(term: Any) -> str:
    if isinstance(term, URIRef):
        return re.split(r"[#/]", str(term).rstrip("/"))[-1]
    return str(term)


def normalize_text(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"\s+", "", value)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


@dataclass
class CompanyKnowledge:
    company: dict[str, Any]
    security: dict[str, Any] | None
    financials: dict[str, Any] | None
    quote: dict[str, Any] | None
    valuation: dict[str, Any] | None
    risk: dict[str, Any] | None
    decision: dict[str, Any] | None
    position: dict[str, Any] | None
    portfolio: dict[str, Any] | None
    macro: list[dict[str, Any]]
    citations: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "security": self.security,
            "financials": self.financials,
            "quote": self.quote,
            "valuation": self.valuation,
            "risk": self.risk,
            "decision": self.decision,
            "position": self.position,
            "portfolio": self.portfolio,
            "macro": self.macro,
            "dataNote": "所有公司、财务、行情、决策、规则与政策均为本体中的合成示例，不构成投资建议。",
        }


class OntologyStore:
    """Loads the canonical Turtle modules and exposes compact fact sheets."""

    def __init__(self, root: Path):
        self.root = root
        self.graph = Graph()
        for module in ONTOLOGY_MODULES:
            path = root / "ontology" / module
            self.graph.parse(path, format="turtle")

        self._company_subjects = self._find_company_subjects()
        self._aliases = self._build_aliases()
        self._knowledge_cache: dict[URIRef, CompanyKnowledge] = {}
        self._rule_cache: dict[str, dict[str, Any]] | None = None
        self._policy_cache: list[dict[str, Any]] | None = None
        self._search_index: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # RDF helpers
    # ------------------------------------------------------------------

    def _first(self, subject: Any, predicate: Any) -> Any:
        return next(self.graph.objects(subject, predicate), None)

    def _all(self, subject: Any, predicate: Any) -> list[Any]:
        return list(self.graph.objects(subject, predicate))

    def _literal(self, subject: Any, predicate: Any) -> Any:
        value = self._first(subject, predicate)
        if isinstance(value, Literal):
            converter = getattr(value, "to_python", None) or getattr(value, "toPython", None)
            try:
                return converter() if converter else str(value)
            except Exception:
                return str(value)
        if isinstance(value, URIRef):
            return str(value)
        return value

    def _text(self, subject: Any, predicate: Any) -> str | None:
        value = self._first(subject, predicate)
        return _clean(value) if isinstance(value, Literal) else None

    def _label(self, subject: Any) -> str:
        if isinstance(subject, Literal):
            return _clean(subject)
        for predicate in (RDFS.label, SKOS.prefLabel, DCTERMS.title):
            for lang in ("zh", "en"):
                for value in self.graph.objects(subject, predicate):
                    if isinstance(value, Literal) and (value.language or "").startswith(lang):
                        return _clean(value)
        for predicate in (RDFS.label, SKOS.prefLabel, DCTERMS.title):
            value = self._first(subject, predicate)
            if isinstance(value, Literal):
                return _clean(value)
        name = local_name(subject)
        return name.replace("_", " ").replace("-", " ")

    def _comment(self, subject: Any) -> str:
        for predicate in (RDFS.comment, SKOS.definition, DCTERMS.description, SKOS.scopeNote):
            value = self._text(subject, predicate)
            if value:
                return value
        return ""

    def _num(self, subject: Any, predicate: Any) -> float | int | None:
        value = self._literal(subject, predicate)
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value) if float(value).is_integer() else float(value)
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return None
        return int(parsed) if parsed.is_integer() else parsed

    def _bool(self, subject: Any, predicate: Any) -> bool:
        value = self._literal(subject, predicate)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes"}

    def _date(self, subject: Any, predicate: Any) -> str | None:
        value = self._literal(subject, predicate)
        return str(value) if value is not None else None

    def _ref(self, subject: Any) -> dict[str, str] | None:
        if not isinstance(subject, URIRef):
            return None
        return {
            "id": local_name(subject),
            "iri": str(subject),
            "label": self._label(subject),
            "kind": self._kind(subject),
        }

    def _refs(self, subject: Any, predicate: Any) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in self.graph.objects(subject, predicate):
            ref = self._ref(value)
            if ref and ref["iri"] not in seen:
                seen.add(ref["iri"])
                refs.append(ref)
        return refs

    def _kind(self, subject: Any) -> str:
        if (subject, RDF.type, ASH.RuleArtifact) in self.graph:
            return "rule"
        if any(self.graph.objects(subject, ODRL.uid)):
            return "policy"
        if (subject, RDF.type, ASH.DecisionService) in self.graph:
            return "service"
        if (subject, RDF.type, OWL.Class) in self.graph:
            return "class"
        if (subject, RDF.type, OWL.ObjectProperty) in self.graph:
            return "objectProperty"
        if (subject, RDF.type, OWL.DatatypeProperty) in self.graph:
            return "dataProperty"
        if (subject, RDF.type, SKOS.Concept) in self.graph:
            return "concept"
        return "individual"

    def _cite(self, subject: Any) -> dict[str, str] | None:
        ref = self._ref(subject)
        if not ref:
            return None
        return {
            "id": ref["id"],
            "iri": ref["iri"],
            "label": ref["label"],
            "kind": ref["kind"],
        }

    def _dedupe_citations(
        self, groups: Iterable[Iterable[dict[str, str] | None]], limit: int = 18
    ) -> list[dict[str, str]]:
        citations: list[dict[str, str]] = []
        seen: set[str] = set()
        for group in groups:
            for item in group:
                if not item or item["iri"] in seen:
                    continue
                seen.add(item["iri"])
                citations.append(item)
                if len(citations) >= limit:
                    return citations
        return citations

    # ------------------------------------------------------------------
    # Company aliases and fact sheets
    # ------------------------------------------------------------------

    def _find_company_subjects(self) -> list[URIRef]:
        subjects = [s for s in self.graph.subjects(RDF.type, ASH.ListedCompany) if isinstance(s, URIRef)]
        return sorted(set(subjects), key=lambda item: self._label(item))

    def _build_aliases(self) -> dict[str, URIRef]:
        raw: dict[str, set[URIRef]] = {}

        def add(alias: Any, subject: URIRef) -> None:
            normalized = normalize_text(alias)
            if not normalized or len(normalized) < 2:
                return
            if normalized in {"示例", "公司", "股票", "标的"}:
                return
            raw.setdefault(normalized, set()).add(subject)

        for subject in self._company_subjects:
            label = self._label(subject)
            company_name = self._text(subject, ASH.companyName) or ""
            company_code = self._text(subject, ASH.companyCode) or ""
            for alias in (label, company_name, company_code, local_name(subject)):
                add(alias, subject)
            if company_name.endswith("股份有限公司"):
                add(company_name[: -len("股份有限公司")], subject)
            if len(label) >= 4 and not re.search(r"[A-Za-z0-9]", label) and not label.startswith("示例"):
                add(label[:2], subject)
            security = self._first(subject, ASH.hasSecurity)
            if isinstance(security, URIRef):
                for alias in (
                    self._text(security, ASH.securityName),
                    self._text(security, ASH.securityCode),
                    self._label(security),
                ):
                    add(alias, subject)
                code = self._text(security, ASH.securityCode)
                if code:
                    add(f"{code}.SH", subject)
                    add(f"{code}.SZ", subject)
        return {alias: next(iter(subjects)) for alias, subjects in raw.items() if len(subjects) == 1}

    def find_companies(self, text: str) -> list[URIRef]:
        normalized = normalize_text(text)
        matches: list[URIRef] = []
        for alias, subject in sorted(self._aliases.items(), key=lambda item: len(item[0]), reverse=True):
            if alias in normalized and subject not in matches:
                matches.append(subject)
        return matches

    def find_company(self, text: str) -> URIRef | None:
        matches = self.find_companies(text)
        return matches[0] if matches else None

    def company_names(self) -> list[dict[str, str]]:
        names = []
        for subject in self._company_subjects:
            security = self._first(subject, ASH.hasSecurity)
            security = security if isinstance(security, URIRef) else None
            names.append(
                {
                    "id": local_name(subject),
                    "iri": str(subject),
                    "label": self._label(subject),
                    "code": (self._text(security, ASH.securityCode) if security else "") or "",
                }
            )
        return names

    def company_knowledge(self, subject: URIRef) -> CompanyKnowledge:
        cached = self._knowledge_cache.get(subject)
        if cached:
            return cached

        security = self._first(subject, ASH.hasSecurity)
        security = security if isinstance(security, URIRef) else None
        report = self._latest(subject, ASH.hasFinancialReport, ASH.dataAsOf)
        quote = self._first(security, ASH.hasMarketQuote) if security else None
        valuation = self._first(security, ASH.hasValuation) if security else None
        decisions = self._all_decisions(subject)
        decision = decisions[0] if decisions else None
        risk = None
        if isinstance(decision, URIRef):
            risk = self._first(decision, ASH.hasRiskAssessment)
        if not isinstance(risk, URIRef) and security:
            assessments = sorted(
                (s for s in self.graph.subjects(ASH.assessesSecurity, security) if isinstance(s, URIRef)),
                key=str,
            )
            risk = assessments[0] if assessments else None
        rationale = self._first(decision, ASH.hasRationale) if isinstance(decision, URIRef) else None
        compliance = self._first(decision, ASH.hasComplianceCheck) if isinstance(decision, URIRef) else None
        positions = self._all_positions(security)
        position = positions[0] if positions else None
        portfolio = self._first(position, ASH.positionOf) if isinstance(position, URIRef) else None

        company_ref = self._ref(subject) or {}
        company = {
            **company_ref,
            "labelEn": self._label_en(subject),
            "comment": self._comment(subject),
            "companyName": self._text(subject, ASH.companyName) or "",
            "companyCode": self._text(subject, ASH.companyCode) or "",
            "isST": self._bool(subject, ASH.isST),
            "delistingRisk": self._bool(subject, ASH.delistingRisk),
            "industry": self._ref(self._first(subject, ASH.primaryIndustry)),
            "themes": self._refs(subject, ASH.hasThemeExposure),
        }

        security_dict = None
        if security:
            security_dict = {
                **(self._ref(security) or {}),
                "name": self._text(security, ASH.securityName) or "",
                "code": self._text(security, ASH.securityCode) or "",
                "isin": self._text(security, ASH.isin) or "",
                "exchange": self._ref(self._first(security, ASH.listedOn)),
                "segment": self._ref(self._first(security, ASH.tradesOn)),
                "restricted": self._bool(security, ASH.isRestricted),
                "suspended": self._bool(security, ASH.isSuspended),
                "listingDate": self._date(security, ASH.listingDate),
            }

        financials = None
        if isinstance(report, URIRef):
            financials = {
                **(self._ref(report) or {}),
                "period": str(self._literal(report, ASH.reportPeriod) or ""),
                "revenue": self._num(report, ASH.revenue),
                "netProfit": self._num(report, ASH.netProfit),
                "roe": self._num(report, ASH.roe),
                "roa": self._num(report, ASH.roa),
                "debtRatio": self._num(report, ASH.debtRatio),
                "interestCoverage": self._num(report, ASH.interestCoverage),
                "operatingCashFlow": self._num(report, ASH.operatingCashFlow),
                "revenueGrowth": self._num(report, ASH.revenueGrowth),
                "profitGrowth": self._num(report, ASH.profitGrowth),
                "eps": self._num(report, ASH.eps),
                "asOf": self._date(report, ASH.dataAsOf),
                "source": self._text(report, ASH.dataSource) or "",
                "quality": self._text(report, ASH.dataQualityFlag) or "",
            }

        quote_dict = None
        if isinstance(quote, URIRef):
            quote_dict = {
                **(self._ref(quote) or {}),
                "lastPrice": self._num(quote, ASH.lastPrice),
                "changePct": self._num(quote, ASH.changePct),
                "volume": self._num(quote, ASH.volume),
                "turnoverRate": self._num(quote, ASH.turnoverRate),
                "marketCap": self._num(quote, ASH.marketCap),
                "asOf": self._date(quote, ASH.dataAsOf),
                "source": self._text(quote, ASH.dataSource) or "",
            }

        valuation_dict = None
        if isinstance(valuation, URIRef):
            valuation_dict = {
                **(self._ref(valuation) or {}),
                "peTtm": self._num(valuation, ASH.peTtm),
                "pb": self._num(valuation, ASH.pb),
                "psTtm": self._num(valuation, ASH.psTtm),
                "dividendYield": self._num(valuation, ASH.dividendYield),
                "asOf": self._date(valuation, ASH.dataAsOf),
                "source": self._text(valuation, ASH.dataSource) or "",
            }

        risk_dict = self._risk_dict(risk)
        decision_dict = self._decision_dict(decision, risk_dict, rationale, compliance)
        position_dict = self._position_dict(position, portfolio)
        portfolio_dict = self._portfolio_dict(portfolio)
        macro = self._refs(decision, ASH.hasMacroContext) if isinstance(decision, URIRef) else []

        citations = self._dedupe_citations(
            [
                [self._cite(subject)],
                [self._cite(security)] if security else [],
                [self._cite(report)] if isinstance(report, URIRef) else [],
                [self._cite(quote)] if isinstance(quote, URIRef) else [],
                [self._cite(valuation)] if isinstance(valuation, URIRef) else [],
                [self._cite(risk)] if isinstance(risk, URIRef) else [],
                [self._cite(decision)] if isinstance(decision, URIRef) else [],
                [self._cite(rationale)] if isinstance(rationale, URIRef) else [],
                [self._cite(compliance)] if isinstance(compliance, URIRef) else [],
                [self._cite(position)] if isinstance(position, URIRef) else [],
                [self._cite(portfolio)] if isinstance(portfolio, URIRef) else [],
                [self._cite(item) for item in self._all(decision, ASH.basedOn)] if isinstance(decision, URIRef) else [],
                [self._cite(item) for item in self._all(decision, ASH.governedBy)] if isinstance(decision, URIRef) else [],
                [self._cite(item) for item in self._all(decision, ASH.hasMacroContext)] if isinstance(decision, URIRef) else [],
                [self._cite(self._first(subject, ASH.primaryIndustry))],
            ]
        )

        knowledge = CompanyKnowledge(
            company=company,
            security=security_dict,
            financials=financials,
            quote=quote_dict,
            valuation=valuation_dict,
            risk=risk_dict,
            decision=decision_dict,
            position=position_dict,
            portfolio=portfolio_dict,
            macro=macro,
            citations=citations,
        )
        self._knowledge_cache[subject] = knowledge
        return knowledge

    def _label_en(self, subject: Any) -> str:
        for predicate in (RDFS.label, SKOS.prefLabel, DCTERMS.title):
            for value in self.graph.objects(subject, predicate):
                if isinstance(value, Literal) and (value.language or "").startswith("en"):
                    return _clean(value)
        return self._label(subject)

    def _latest(self, subject: Any, predicate: Any, date_predicate: Any) -> URIRef | None:
        candidates = [value for value in self.graph.objects(subject, predicate) if isinstance(value, URIRef)]
        if not candidates:
            return None
        return max(candidates, key=lambda item: str(self._literal(item, date_predicate) or ""))

    def _all_decisions(self, company: URIRef) -> list[URIRef]:
        decisions = [
            item for item in self.graph.subjects(ASH.aboutCompany, company) if isinstance(item, URIRef)
        ]
        if not decisions:
            security = self._first(company, ASH.hasSecurity)
            if isinstance(security, URIRef):
                decisions = [
                    item for item in self.graph.subjects(ASH.aboutSecurity, security) if isinstance(item, URIRef)
                ]
        return sorted(
            decisions,
            key=lambda item: str(self._literal(item, ASH.decisionDate) or ""),
            reverse=True,
        )

    def _all_positions(self, security: Any) -> list[URIRef]:
        if not isinstance(security, URIRef):
            return []
        return sorted(
            (item for item in self.graph.subjects(ASH.positionIn, security) if isinstance(item, URIRef)),
            key=str,
        )

    def _risk_dict(self, risk: Any) -> dict[str, Any] | None:
        if not isinstance(risk, URIRef):
            return None
        level = self._first(risk, ASH.hasRiskLevel)
        factors = []
        for factor in self._all(risk, ASH.hasRiskFactor):
            ref = self._ref(factor)
            if ref:
                factors.append({**ref, "comment": self._comment(factor)})
        return {
            **(self._ref(risk) or {}),
            "score": self._num(risk, ASH.riskScore),
            "level": self._ref(level),
            "factors": factors,
            "comment": self._comment(risk),
            "asOf": self._date(risk, ASH.dataAsOf),
        }

    def _decision_dict(
        self,
        decision: Any,
        risk: dict[str, Any] | None,
        rationale: Any,
        compliance: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(decision, URIRef):
            return None
        recommendation = self._first(decision, ASH.hasRecommendation)
        rec_ref = self._ref(recommendation) if recommendation else None
        if rec_ref:
            rec_ref["actionCode"] = self._text(recommendation, ASH.actionCode) or ""
        rationale_dict = None
        if isinstance(rationale, URIRef):
            rationale_dict = {
                "id": local_name(rationale),
                "iri": str(rationale),
                "label": self._label(rationale),
                "text": self._text(rationale, ASH.rationaleText) or "",
                "assumption": self._text(rationale, ASH.assumption) or "",
                "counterArgument": self._text(rationale, ASH.counterArgument) or "",
            }
        compliance_dict = None
        if isinstance(compliance, URIRef):
            compliance_dict = {
                "id": local_name(compliance),
                "iri": str(compliance),
                "label": self._label(compliance),
                "passed": self._bool(compliance, ASH.passed),
                "note": self._text(compliance, ASH.checkNote) or "",
            }
        evidence = []
        for item in self._all(decision, ASH.basedOn):
            ref = self._ref(item)
            if ref:
                evidence.append(
                    {
                        **ref,
                        "comment": self._comment(item),
                        "asOf": self._date(item, ASH.dataAsOf),
                        "source": self._text(item, ASH.dataSource) or "",
                    }
                )
        policies = []
        for item in self._all(decision, ASH.governedBy):
            ref = self._ref(item)
            if ref:
                policies.append(
                    {
                        **ref,
                        "comment": self._comment(item),
                        "version": self._text(item, ASH.policyVersion) or "",
                        "status": self._text(item, ASH.policyStatus) or "",
                    }
                )
        return {
            **(self._ref(decision) or {}),
            "decisionId": self._text(decision, ASH.decisionId) or "",
            "recommendation": rec_ref,
            "confidence": self._num(decision, ASH.confidence),
            "targetPrice": self._num(decision, ASH.targetPrice),
            "stopLoss": self._num(decision, ASH.stopLoss),
            "horizon": self._ref(self._first(decision, ASH.hasHorizon)),
            "decisionDate": self._date(decision, ASH.decisionDate),
            "validUntil": self._date(decision, ASH.validUntil),
            "rationale": rationale_dict,
            "risk": risk,
            "evidence": evidence,
            "policies": policies,
            "compliance": compliance_dict,
            "service": self._ref(self._first(decision, ASH.generatedBy)),
            "comment": self._comment(decision),
        }

    def _position_dict(self, position: Any, portfolio: Any) -> dict[str, Any] | None:
        if not isinstance(position, URIRef):
            return None
        return {
            **(self._ref(position) or {}),
            "weight": self._num(position, ASH.positionWeight),
            "avgCost": self._num(position, ASH.avgCost),
            "quantity": self._num(position, ASH.quantity),
            "portfolio": self._ref(portfolio),
        }

    def _portfolio_dict(self, portfolio: Any) -> dict[str, Any] | None:
        if not isinstance(portfolio, URIRef):
            return None
        return {
            **(self._ref(portfolio) or {}),
            "comment": self._comment(portfolio),
            "strategy": self._ref(self._first(portfolio, ASH.followsStrategy)),
            "benchmark": self._ref(self._first(portfolio, ASH.hasBenchmark)),
        }

    # ------------------------------------------------------------------
    # Rule metadata and policy summaries
    # ------------------------------------------------------------------

    def rules(self) -> list[dict[str, Any]]:
        if self._rule_cache is not None:
            return self._rule_cache
        rules: list[dict[str, Any]] = []
        for subject in self.graph.subjects(RDF.type, ASH.RuleArtifact):
            if not isinstance(subject, URIRef):
                continue
            rule_id = self._text(subject, ASH.ruleId) or local_name(subject)
            rules.append(
                {
                    "id": local_name(subject),
                    "iri": str(subject),
                    "ruleId": rule_id,
                    "label": self._label(subject),
                    "comment": self._comment(subject),
                    "ruleIf": self._text(subject, ASH.ruleIf) or "",
                    "ruleThen": self._text(subject, ASH.ruleThen) or "",
                    "severity": self._text(subject, ASH.severity) or "",
                    "priority": self._num(subject, ASH.rulePriority),
                    "status": self._text(subject, ASH.ruleStatus) or "",
                    "version": self._text(subject, ASH.ruleVersion) or "",
                    "owner": self._text(subject, ASH.ruleOwner) or "",
                    "effectiveFrom": self._date(subject, ASH.ruleEffectiveFrom),
                    "appliesTo": self._refs(subject, ASH.appliesTo),
                    "uses": self._refs(subject, ASH.ruleUses),
                    "thresholds": RULE_THRESHOLDS.get(rule_id, {}),
                }
            )
        rules.sort(key=lambda item: _rule_sort_key(item["ruleId"]))
        self._rule_cache = rules
        return rules

    def rule(self, rule_id: str) -> dict[str, Any] | None:
        normalized = rule_id.strip().upper()
        for item in self.rules():
            if item["ruleId"].upper() == normalized or item["id"].upper() == normalized:
                return item
        return None

    def policies(self) -> list[dict[str, Any]]:
        if self._policy_cache is not None:
            return self._policy_cache
        policies: list[dict[str, Any]] = []
        for subject in self.graph.subjects(ODRL.uid, None):
            if not isinstance(subject, URIRef):
                continue
            policies.append(self._policy_summary(subject))
        policies.sort(key=lambda item: item["label"])
        self._policy_cache = policies
        return policies

    def _policy_summary(self, subject: URIRef) -> dict[str, Any]:
        permissions = [self._policy_rule(item) for item in self._all(subject, ODRL.permission)]
        prohibitions = [self._policy_rule(item) for item in self._all(subject, ODRL.prohibition)]
        obligations = [self._policy_rule(item) for item in self._all(subject, ODRL.obligation)]
        for permission in self._all(subject, ODRL.permission):
            obligations.extend(self._policy_rule(item) for item in self._all(permission, ODRL.duty))
        return {
            **(self._ref(subject) or {}),
            "label": self._label(subject),
            "description": self._comment(subject) or (self._text(subject, DCTERMS.description) or ""),
            "uid": local_name(self._first(subject, ODRL.uid) or subject),
            "version": self._text(subject, ASH.policyVersion) or "",
            "status": self._text(subject, ASH.policyStatus) or "",
            "conflict": self._label(self._first(subject, ODRL.conflict)),
            "reviewDate": self._date(subject, ASH.reviewDate),
            "permissions": permissions,
            "prohibitions": prohibitions,
            "obligations": obligations,
        }

    def _policy_rule(self, rule: Any) -> dict[str, Any]:
        constraints = []
        for constraint in self._all(rule, ODRL.constraint):
            constraints.append(self._constraint_text(constraint))
        duties = []
        for duty in self._all(rule, ODRL.duty):
            duties.append(
                {
                    "action": self._label(self._first(duty, ODRL.action)),
                    "target": self._label(self._first(duty, ODRL.target)),
                }
            )
        return {
            "actions": [self._label(item) for item in self._all(rule, ODRL.action)],
            "targets": [self._label(item) for item in self._all(rule, ODRL.target)],
            "assignees": [self._label(item) for item in self._all(rule, ODRL.assignee)],
            "constraints": constraints,
            "duties": duties,
        }

    def _constraint_text(self, constraint: Any) -> str:
        left = self._label(self._first(constraint, ODRL.leftOperand))
        operator = self._label(self._first(constraint, ODRL.operator))
        right = self._first(constraint, ODRL.rightOperand)
        if isinstance(right, Literal):
            right_text = _clean(right)
        elif isinstance(right, URIRef):
            right_text = self._label(right)
        elif right is None:
            right_text = ""
        else:
            right_text = "复合值"
        return f"{left} {operator} {right_text}".strip()

    # ------------------------------------------------------------------
    # Search, screening, portfolio, and tool-friendly result builders
    # ------------------------------------------------------------------

    def _build_search_index(self) -> list[dict[str, Any]]:
        if self._search_index is not None:
            return self._search_index
        kinds: dict[URIRef, str] = {}
        for predicate, kind in (
            (OWL.Class, "class"),
            (OWL.ObjectProperty, "objectProperty"),
            (OWL.DatatypeProperty, "dataProperty"),
            (OWL.NamedIndividual, "individual"),
            (SKOS.Concept, "concept"),
        ):
            for subject in self.graph.subjects(RDF.type, predicate):
                if isinstance(subject, URIRef) and subject not in kinds:
                    kinds[subject] = kind
        for subject in self.graph.subjects(RDF.type, ASH.RuleArtifact):
            if isinstance(subject, URIRef):
                kinds[subject] = "rule"
        for subject in self.graph.subjects(ODRL.uid, None):
            if isinstance(subject, URIRef):
                kinds[subject] = "policy"
        for subject in self.graph.subjects(RDF.type, ASH.DecisionService):
            if isinstance(subject, URIRef):
                kinds[subject] = "service"

        index = []
        for subject, kind in kinds.items():
            label = self._label(subject)
            comment = self._comment(subject)
            extra = ""
            if kind == "rule":
                extra = self._text(subject, ASH.ruleId) or ""
            elif kind == "policy":
                extra = self._text(subject, ASH.policyStatus) or ""
            elif kind == "concept":
                scheme = self._first(subject, SKOS.inScheme)
                extra = self._label(scheme) if scheme else ""
            index.append(
                {
                    "id": local_name(subject),
                    "iri": str(subject),
                    "kind": kind,
                    "label": label,
                    "comment": comment,
                    "extra": extra,
                    "haystack": normalize_text(
                        " ".join(
                            [
                                label,
                                self._label_en(subject),
                                local_name(subject),
                                str(subject),
                                comment,
                                extra,
                            ]
                        )
                    ),
                }
            )
        self._search_index = index
        return index

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        normalized = normalize_text(query)
        if not normalized:
            return []
        scored = []
        for item in self._build_search_index():
            haystack = item["haystack"]
            label = normalize_text(item["label"])
            identifier = normalize_text(item["id"])
            score = 0
            if normalized == label or normalized == identifier:
                score = 100
            elif label.startswith(normalized) or identifier.startswith(normalized):
                score = 80
            elif normalized in label or normalized in identifier:
                score = 65
            elif normalized in haystack:
                score = 35
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["kind"], pair[1]["label"]))
        return [item for _, item in scored[:limit]]

    def screen(self, rule_id: str | None = None) -> dict[str, Any]:
        rule_filter = rule_id.strip().upper() if rule_id else None
        if rule_filter:
            known = {item["ruleId"].upper() for item in self.rules()}
            if rule_filter not in known:
                raise ValueError(f"未知规则：{rule_filter}")
            if rule_filter in {"R05", "R06"}:
                raise ValueError("R05/R06 是组合级规则，请使用 get_portfolio_analysis。")

        companies = []
        citations: list[dict[str, str] | None] = []
        for subject in self._company_subjects:
            knowledge = self.company_knowledge(subject)
            data = knowledge.to_dict()
            signals = [self._enrich_signal(item) for item in evaluate_company(data)]
            if rule_filter:
                signals = [item for item in signals if item["ruleId"].upper() == rule_filter]
            triggered = [item["ruleId"] for item in signals if item["status"] == "triggered"]
            metrics = {
                "roe": (data.get("financials") or {}).get("roe"),
                "peTtm": (data.get("valuation") or {}).get("peTtm"),
                "debtRatio": (data.get("financials") or {}).get("debtRatio"),
                "revenueGrowth": (data.get("financials") or {}).get("revenueGrowth"),
                "riskScore": (data.get("risk") or {}).get("score"),
                "positionWeight": (data.get("position") or {}).get("weight"),
            }
            companies.append(
                {
                    "id": knowledge.company.get("id"),
                    "iri": knowledge.company.get("iri"),
                    "label": knowledge.company.get("label"),
                    "labelEn": knowledge.company.get("labelEn"),
                    "code": (knowledge.security or {}).get("code", ""),
                    "industry": (knowledge.company.get("industry") or {}).get("label", ""),
                    "isST": knowledge.company.get("isST"),
                    "delistingRisk": knowledge.company.get("delistingRisk"),
                    "recommendation": (knowledge.decision or {}).get("recommendation"),
                    "confidence": (knowledge.decision or {}).get("confidence"),
                    "riskLevel": (knowledge.risk or {}).get("level"),
                    "metrics": metrics,
                    "signals": signals,
                    "triggered": triggered,
                }
            )
            citations.extend([knowledge.citations, [self._cite(subject)]])
            for signal in signals:
                if signal["status"] == "triggered":
                    rule = self.rule(signal["ruleId"])
                    if rule:
                        citations.append([self._cite(URIRef(rule["iri"]))])

        return {
            "ruleFilter": rule_filter,
            "companies": companies,
            "ruleCatalog": [
                {
                    "ruleId": item["ruleId"],
                    "label": item["label"],
                    "severity": item["severity"],
                    "iri": item["iri"],
                }
                for item in self.rules()
            ],
            "dataNote": "筛选只针对本体中的合成示例公司，阈值来自示例 SWRL 规则。",
            "citations": self._dedupe_citations(citations),
        }

    def portfolio(self) -> dict[str, Any]:
        portfolios = [
            subject
            for subject in self.graph.subjects(RDF.type, ASH.Portfolio)
            if isinstance(subject, URIRef)
        ]
        if not portfolios:
            return {
                "portfolio": None,
                "positions": [],
                "signals": {},
                "citations": [],
                "dataNote": "本体中没有组合实例。",
            }
        portfolio = sorted(portfolios, key=str)[0]
        positions = []
        citations: list[list[dict[str, str] | None]] = [[self._cite(portfolio)]]
        for position_subject in self._all(portfolio, ASH.holdsPosition):
            if not isinstance(position_subject, URIRef):
                continue
            security = self._first(position_subject, ASH.positionIn)
            company = self._first(security, ASH.issuedBy) if isinstance(security, URIRef) else None
            if not isinstance(company, URIRef):
                continue
            knowledge = self.company_knowledge(company)
            data = knowledge.to_dict()
            data["position"] = {
                "id": local_name(position_subject),
                "iri": str(position_subject),
                "label": self._label(position_subject),
                "weight": self._num(position_subject, ASH.positionWeight),
                "avgCost": self._num(position_subject, ASH.avgCost),
                "quantity": self._num(position_subject, ASH.quantity),
                "portfolio": self._ref(portfolio),
            }
            signals = [self._enrich_signal(item) for item in evaluate_company(data)]
            selected = {item["ruleId"]: item for item in signals if item["ruleId"] in {"R05", "R06"}}
            quote = data.get("quote") or {}
            last_price = quote.get("lastPrice")
            quantity = data["position"].get("quantity")
            position_value = (
                float(last_price) * float(quantity)
                if isinstance(last_price, (int, float)) and isinstance(quantity, (int, float))
                else None
            )
            positions.append(
                {
                    "id": data["position"]["id"],
                    "iri": data["position"]["iri"],
                    "label": data["position"]["label"],
                    "company": {
                        "id": knowledge.company.get("id"),
                        "iri": knowledge.company.get("iri"),
                        "label": knowledge.company.get("label"),
                    },
                    "security": {
                        "id": (knowledge.security or {}).get("id"),
                        "iri": (knowledge.security or {}).get("iri"),
                        "label": (knowledge.security or {}).get("label"),
                        "code": (knowledge.security or {}).get("code"),
                    },
                    "weight": data["position"].get("weight"),
                    "avgCost": data["position"].get("avgCost"),
                    "quantity": quantity,
                    "lastPrice": last_price,
                    "positionValue": position_value,
                    "signals": selected,
                }
            )
            citations.extend([knowledge.citations, [self._cite(position_subject), self._cite(security)]])
            for signal in selected.values():
                if signal["status"] == "triggered":
                    rule = self.rule(signal["ruleId"])
                    if rule:
                        citations.append([self._cite(URIRef(rule["iri"]))])

        signals = evaluate_portfolio({"positions": positions})
        enriched = {rule_id: self._enrich_signal(signal) for rule_id, signal in signals.items()}
        for rule_id in ("R05", "R06"):
            rule = self.rule(rule_id)
            if rule:
                citations.append([self._cite(URIRef(rule["iri"]))])
        total_weight = sum(
            float(item["weight"]) for item in positions if isinstance(item.get("weight"), (int, float))
        )
        return {
            "portfolio": {
                **(self._ref(portfolio) or {}),
                "comment": self._comment(portfolio),
                "strategy": self._ref(self._first(portfolio, ASH.followsStrategy)),
                "benchmark": self._ref(self._first(portfolio, ASH.hasBenchmark)),
            },
            "positions": positions,
            "totalWeight": total_weight,
            "signals": enriched,
            "maxSingleWeight": RULE_THRESHOLDS["R06"]["max_weight"],
            "dataNote": "组合、持仓、价格与权重均为合成示例；权重合计只覆盖本体中建模的持仓。",
            "citations": self._dedupe_citations(citations),
        }

    def _enrich_signal(self, signal: dict[str, str]) -> dict[str, Any]:
        rule = self.rule(signal["ruleId"]) or {}
        return {
            **signal,
            "label": rule.get("label", signal["ruleId"]),
            "severity": rule.get("severity", ""),
            "ruleIri": rule.get("iri", ""),
        }

    def rule_effects(self, rule_id: str) -> dict[str, Any]:
        rule = self.rule(rule_id)
        if not rule:
            raise ValueError(f"未知规则：{rule_id}")
        normalized = rule["ruleId"].upper()
        affected = []
        citations: list[dict[str, str] | None] = [[self._cite(URIRef(rule["iri"]))]]
        if normalized in {"R05", "R06"}:
            portfolio = self.portfolio()
            for item in portfolio["positions"]:
                signal = item["signals"].get(normalized)
                if not signal:
                    continue
                affected.append(
                    {
                        "kind": "position",
                        "subjectId": item["id"],
                        "subjectIri": item["iri"],
                        "subjectLabel": item["label"],
                        "companyLabel": item["company"].get("label"),
                        "status": signal["status"],
                        "detail": signal["detail"],
                    }
                )
                citations.append([self._cite(URIRef(item["iri"]))])
            citations.append(list(portfolio.get("citations") or []))
        else:
            for subject in self._company_subjects:
                knowledge = self.company_knowledge(subject)
                signals = [self._enrich_signal(item) for item in evaluate_company(knowledge.to_dict())]
                signal = next((item for item in signals if item["ruleId"].upper() == normalized), None)
                if not signal:
                    continue
                affected.append(
                    {
                        "kind": "company",
                        "subjectId": knowledge.company.get("id"),
                        "subjectIri": knowledge.company.get("iri"),
                        "subjectLabel": knowledge.company.get("label"),
                        "status": signal["status"],
                        "detail": signal["detail"],
                    }
                )
                citations.extend([knowledge.citations, [self._cite(subject)]])
        triggered = [item for item in affected if item["status"] == "triggered"]
        return {
            "rule": rule,
            "affected": affected,
            "triggeredCount": len(triggered),
            "dataNote": "规则结论仅基于本体中的合成示例数据。",
            "citations": self._dedupe_citations(citations),
        }


def _rule_sort_key(rule_id: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", rule_id)
    return (int(match.group(1)) if match else 999, rule_id)


__all__ = [
    "ASH",
    "ASHD",
    "ASHS",
    "CompanyKnowledge",
    "OntologyStore",
    "fmt_money",
    "fmt_pct",
    "fmt_weight",
    "local_name",
    "normalize_text",
]
