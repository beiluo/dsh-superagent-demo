#!/usr/bin/env python3
"""Structural validation for the A-share ontology.

This is not a full OWL 2 DL consistency proof. It checks:
  * every Turtle module parses and the aggregate imports all layers;
  * RDFS labels and property definitions are present;
  * OWL restrictions, keys and disjointness point at defined terms;
  * SKOS schemes, top concepts and broader/narrower reciprocity;
  * SWRL rule structure, variable safety and supported built-ins;
  * OWL-S profile/process/grounding wiring;
  * ODRL policy and rule structure;
  * example decision completeness;
  * OWL RL closure runs without error;
  * SPARQL competency questions parse.

Run:
    python3 scripts/validate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rdflib import Graph, BNode, Literal, Namespace, RDF, RDFS, OWL, URIRef
from rdflib.namespace import DCTERMS, SKOS, XSD
from rdflib.plugins.sparql import prepareQuery
from owlrl import DeductiveClosure, OWLRL_Semantics

ROOT = Path(__file__).resolve().parents[1]
ASH = Namespace("https://beiluo.github.io/dsh-superagent-demo/ontology/a-share#")
ASHD = Namespace("https://beiluo.github.io/dsh-superagent-demo/ontology/a-share/data#")
ASHS = Namespace("https://beiluo.github.io/dsh-superagent-demo/ontology/a-share/skos#")
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
SWRLB = Namespace("http://www.w3.org/2003/11/swrlb#")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
SERVICE = Namespace("http://www.daml.org/services/owl-s/1.2/Service.owl#")
PROFILE = Namespace("http://www.daml.org/services/owl-s/1.2/Profile.owl#")
PROCESS = Namespace("http://www.daml.org/services/owl-s/1.2/Process.owl#")
GROUNDING = Namespace("http://www.daml.org/services/owl-s/1.2/Grounding.owl#")

KNOWLEDGE_FILE = "knowledge/youzi.ttl"

MODULE_FILES = [
    "ontology/rdfs/schema.ttl",
    "ontology/owl/ontology.ttl",
    "ontology/skos/taxonomy.ttl",
    "ontology/rdf/instances.ttl",
    "ontology/swrl/rules.ttl",
    "ontology/owl-s/service.ttl",
    "ontology/odrl/policies.ttl",
]

errors: list[str] = []
warnings: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def warn(condition: bool, message: str) -> None:
    if not condition:
        warnings.append(message)


def rdf_list(graph: Graph, head) -> list:
    if head is None:
        return []
    try:
        return list(graph.items(head))
    except Exception:
        return []


def local(term) -> str:
    return str(term).rstrip("/").split("#")[-1].split("/")[-1]


def load_graph() -> tuple[Graph, dict[str, Graph]]:
    combined = Graph()
    modules = {}
    for filename in MODULE_FILES:
        graph = Graph()
        try:
            graph.parse(ROOT / filename, format="turtle")
        except Exception as exc:  # pragma: no cover - exact exception is surfaced
            errors.append(f"Turtle parse failed: {filename}: {exc}")
            continue
        modules[filename] = graph
        for triple in graph:
            combined.add(triple)
    return combined, modules


def validate_rdfs(g: Graph, classes: set, object_properties: set, data_properties: set) -> None:
    for cls in classes:
        check(any(isinstance(v, Literal) and (v.language or "").startswith("zh") for v in g.objects(cls, RDFS.label)),
              f"Class has no Chinese rdfs:label: {local(cls)}")
        warn(any(isinstance(v, Literal) for v in g.objects(cls, RDFS.comment)),
             f"Class has no rdfs:comment: {local(cls)}")
    for prop in object_properties | data_properties:
        check(any(isinstance(v, Literal) and (v.language or "").startswith("zh") for v in g.objects(prop, RDFS.label)),
              f"Property has no Chinese rdfs:label: {local(prop)}")
        check(any(True for _ in g.objects(prop, RDFS.domain)),
              f"Property has no rdfs:domain: {local(prop)}")
        check(any(True for _ in g.objects(prop, RDFS.range)),
              f"Property has no rdfs:range: {local(prop)}")
    for prop in object_properties:
        for domain in g.objects(prop, RDFS.domain):
            if isinstance(domain, URIRef) and str(domain).startswith(str(ASH)):
                check(domain in classes or any(True for _ in g.objects(domain, RDF.type)),
                      f"Object property domain is not a declared class: {local(prop)} -> {local(domain)}")


def validate_owl(g: Graph, classes: set, object_properties: set, data_properties: set) -> None:
    properties = object_properties | data_properties
    for restriction in g.subjects(RDF.type, OWL.Restriction):
        prop = g.value(restriction, OWL.onProperty)
        check(prop in properties, f"Restriction uses an undefined property: {local(restriction)} -> {local(prop) if prop else 'None'}")
        for predicate in (OWL.someValuesFrom, OWL.allValuesFrom):
            value = g.value(restriction, predicate)
            if isinstance(value, URIRef) and str(value).startswith(str(ASH)):
                check(value in classes, f"Restriction uses an undefined class: {local(value)}")
        on_class = g.value(restriction, OWL.onClass)
        if isinstance(on_class, URIRef) and str(on_class).startswith(str(ASH)):
            check(on_class in classes, f"Restriction uses an undefined onClass: {local(on_class)}")
    for cls in classes:
        for key_list in g.objects(cls, OWL.hasKey):
            for prop in rdf_list(g, key_list):
                check(prop in properties, f"Key uses an undefined property: {local(cls)} -> {local(prop)}")
    for group in g.subjects(RDF.type, OWL.AllDisjointClasses):
        members = rdf_list(g, g.value(group, OWL.members))
        check(len(members) >= 2, "AllDisjointClasses needs at least two members")
        for member in members:
            check(member in classes, f"AllDisjointClasses member is not a class: {local(member)}")
    for prop in properties:
        if (prop, RDF.type, OWL.FunctionalProperty) in g:
            check(prop in data_properties or prop in object_properties, "FunctionalProperty must be a declared property")


def validate_skos(g: Graph, concepts: set) -> None:
    schemes = set(g.subjects(RDF.type, SKOS.ConceptScheme))
    check(len(schemes) >= 5, f"Expected at least 5 SKOS concept schemes, found {len(schemes)}")
    for scheme in schemes:
        tops = [item for item in g.objects(scheme, SKOS.hasTopConcept)]
        check(len(tops) > 0, f"Concept scheme has no top concepts: {local(scheme)}")
    for concept in concepts:
        check(any(isinstance(v, Literal) and (v.language or "").startswith("zh") for v in g.objects(concept, SKOS.prefLabel)),
              f"Concept has no Chinese prefLabel: {local(concept)}")
        check(any(isinstance(v, Literal) and (v.language or "").startswith("en") for v in g.objects(concept, SKOS.prefLabel)),
              f"Concept has no English prefLabel: {local(concept)}")
        check(any(True for _ in g.objects(concept, SKOS.inScheme)), f"Concept has no skos:inScheme: {local(concept)}")
        for parent in g.objects(concept, SKOS.broader):
            check(parent in concepts, f"Concept has undefined broader: {local(concept)} -> {local(parent)}")
            check(concept in set(g.objects(parent, SKOS.narrower)),
                  f"broader/narrower not reciprocal: {local(parent)} -> {local(concept)}")
        for child in g.objects(concept, SKOS.narrower):
            check(child in concepts, f"Concept has undefined narrower: {local(concept)} -> {local(child)}")
            check(concept in set(g.objects(child, SKOS.broader)),
                  f"narrower/broader not reciprocal: {local(concept)} -> {local(child)}")


def atom_terms(g: Graph, atom) -> set:
    terms = set()
    for predicate in (SWRL.argument1, SWRL.argument2):
        value = g.value(atom, predicate)
        if isinstance(value, URIRef):
            terms.add(value)
    for value in rdf_list(g, g.value(atom, SWRL.arguments)):
        if isinstance(value, URIRef):
            terms.add(value)
    return terms


def validate_swrl(g: Graph, classes: set, properties: set) -> None:
    supported_builtins = {
        SWRLB.greaterThan, SWRLB.greaterThanOrEqual, SWRLB.lessThan, SWRLB.lessThanOrEqual,
        SWRLB.equal, SWRLB.notEqual, SWRLB.multiply, SWRLB.add, SWRLB.subtract,
        SWRLB.divide, SWRLB.mod, SWRLB.abs, SWRLB.ceiling, SWRLB.floor,
    }
    rules = list(g.subjects(RDF.type, SWRL.Imp))
    check(len(rules) >= 10, f"Expected at least 10 SWRL rules, found {len(rules)}")
    for rule in rules:
        body = rdf_list(g, g.value(rule, SWRL.body))
        head = rdf_list(g, g.value(rule, SWRL.head))
        check(bool(body), f"SWRL rule has empty body: {local(rule)}")
        check(bool(head), f"SWRL rule has empty head: {local(rule)}")
        body_vars: set = set()
        for atom in body:
            atom_type = g.value(atom, RDF.type)
            check(atom_type in {SWRL.ClassAtom, SWRL.IndividualPropertyAtom, SWRL.DatavaluedPropertyAtom, SWRL.BuiltinAtom},
                  f"Unsupported SWRL atom type in {local(rule)}: {atom_type}")
            body_vars |= atom_terms(g, atom)
            if atom_type == SWRL.ClassAtom:
                predicate = g.value(atom, SWRL.classPredicate)
                check(predicate in classes, f"SWRL class atom uses undefined class: {local(predicate)}")
            elif atom_type in {SWRL.IndividualPropertyAtom, SWRL.DatavaluedPropertyAtom}:
                predicate = g.value(atom, SWRL.propertyPredicate)
                check(predicate in properties, f"SWRL property atom uses undefined property: {local(predicate)}")
            elif atom_type == SWRL.BuiltinAtom:
                builtin = g.value(atom, SWRL.builtin)
                check(builtin in supported_builtins, f"Unsupported SWRL built-in: {local(builtin)}")
        head_vars: set = set()
        for atom in head:
            atom_type = g.value(atom, RDF.type)
            head_vars |= atom_terms(g, atom)
            if atom_type == SWRL.ClassAtom:
                predicate = g.value(atom, SWRL.classPredicate)
                check(predicate in classes, f"SWRL head uses undefined class: {local(predicate)}")
        check(head_vars <= body_vars, f"SWRL rule head has unbound variables: {local(rule)} -> {sorted(local(v) for v in head_vars - body_vars)}")


def validate_rule_library(g: Graph) -> None:
    """Validate the declarative V2.0 rule library and its shared machinery."""
    rules = [item for item in g.subjects(RDF.type, ASH.DecisionRule) if isinstance(item, URIRef)]
    check(len(rules) == 60, f"Expected 60 V2.0 decision rules, found {len(rules)}")
    ids: set[str] = set()
    for rule in rules:
        rule_id = g.value(rule, ASH.ruleId)
        check(rule_id is not None, f"Decision rule has no ruleId: {local(rule)}")
        if rule_id is not None:
            check(str(rule_id) not in ids, f"Duplicate decision rule id: {rule_id}")
            ids.add(str(rule_id))
        check((rule, RDF.type, SWRL.Imp) not in g, f"V2.0 rule must not masquerade as SWRL: {local(rule)}")
        for predicate, name in [
            (ASH.ruleDefinition, "ruleDefinition"),
            (ASH.ruleScope, "ruleScope"),
            (ASH.rulePreconditions, "rulePreconditions"),
            (ASH.ruleInputData, "ruleInputData"),
            (ASH.ruleObservations, "ruleObservations"),
            (ASH.ruleTrigger, "ruleTrigger"),
            (ASH.ruleContraryEvidence, "ruleContraryEvidence"),
            (ASH.ruleVeto, "ruleVeto"),
            (ASH.ruleStateMachine, "ruleStateMachine"),
            (ASH.ruleNextActions, "ruleNextActions"),
            (ASH.ruleInvalidation, "ruleInvalidation"),
            (ASH.ruleParameters, "ruleParameters"),
            (ASH.ruleTypicalScenario, "ruleTypicalScenario"),
            (ASH.ruleCounterExample, "ruleCounterExample"),
            (ASH.ruleVerification, "ruleVerification"),
            (ASH.ruleConfidenceBasis, "ruleConfidenceBasis"),
            (ASH.ruleVersion, "ruleVersion"),
            (ASH.ruleStatus, "ruleStatus"),
            (ASH.ruleOwner, "ruleOwner"),
        ]:
            check(g.value(rule, predicate) is not None, f"Decision rule {local(rule)} lacks {name}")
        check(g.value(rule, ASH.belongsToRuleCategory) is not None,
              f"Decision rule {local(rule)} lacks a rule category")
        check(g.value(rule, ASH.usesRuleStateMachine) is not None,
              f"Decision rule {local(rule)} lacks a state machine")
        check(g.value(rule, ASH.hasRuleParameter) is not None,
              f"Decision rule {local(rule)} lacks a parameter placeholder")
        for label in g.objects(rule, RDFS.label):
            if isinstance(label, Literal) and (label.language or "").startswith("zh"):
                break
        else:
            check(False, f"Decision rule has no Chinese label: {local(rule)}")
    categories = [item for item in g.subjects(RDF.type, ASH.RuleCategory) if isinstance(item, URIRef)]
    check(len(categories) == 8, f"Expected 8 rule categories, found {len(categories)}")
    for category in categories:
        for predicate, name in [
            (ASH.categoryCode, "categoryCode"),
            (ASH.categoryResponsibility, "categoryResponsibility"),
            (ASH.categoryBoundary, "categoryBoundary"),
        ]:
            check(g.value(category, predicate) is not None, f"Rule category {local(category)} lacks {name}")
        check(any(True for _ in g.objects(category, ASH.categoryHasRule)),
              f"Rule category {local(category)} has no rules")
    states = [item for item in g.subjects(RDF.type, ASH.RuleState) if isinstance(item, URIRef)]
    check(len(states) == 9, f"Expected 9 rule states, found {len(states)}")
    machine = g.value(next(iter(rules)), ASH.usesRuleStateMachine) if rules else None
    check(machine is not None, "Rule library has no unified state machine")
    if machine is not None:
        check(len(list(g.objects(machine, ASH.hasRuleState))) == 9,
              "Unified state machine does not expose all 9 states")
    transitions = [item for item in g.subjects(RDF.type, ASH.RuleStateTransition) if isinstance(item, URIRef)]
    check(len(transitions) >= 20, f"Expected at least 20 state transitions, found {len(transitions)}")
    conventions = [item for item in g.subjects(RDF.type, ASH.DataQualityConvention) if isinstance(item, URIRef)]
    check(len(conventions) == 7, f"Expected 7 data-quality conventions, found {len(conventions)}")
    runs = [item for item in g.subjects(RDF.type, ASH.RuleRun) if isinstance(item, URIRef)]
    check(len(runs) >= 2, f"Expected at least 2 example rule runs, found {len(runs)}")
    for run in runs:
        for predicate, name in [
            (ASH.runOfRule, "runOfRule"),
            (ASH.runState, "runState"),
            (ASH.runAsOf, "runAsOf"),
            (ASH.runConfidenceBasis, "runConfidenceBasis"),
        ]:
            check(g.value(run, predicate) is not None, f"Rule run {local(run)} lacks {name}")


def validate_owl_s(g: Graph) -> None:
    services = list(g.subjects(RDF.type, SERVICE.Service))
    check(len(services) >= 1, "No OWL-S service found")
    for service in services:
        profile = g.value(service, SERVICE.presents)
        process = g.value(service, SERVICE.describedBy)
        grounding = g.value(service, SERVICE.supports)
        check(profile is not None, f"Service has no profile: {local(service)}")
        check(process is not None, f"Service has no process model: {local(service)}")
        check(grounding is not None, f"Service has no grounding: {local(service)}")
        if profile is not None:
            check(g.value(profile, PROFILE.has_process) == process, "Profile has_process does not match describedBy process")
            check(len(list(g.objects(profile, PROFILE.hasInput))) >= 1, "Profile has no inputs")
            check(len(list(g.objects(profile, PROFILE.hasOutput))) >= 1, "Profile has no outputs")
            check(len(list(g.objects(profile, PROFILE.hasPrecondition))) >= 1, "Profile has no preconditions")
        if process is not None:
            check((process, RDF.type, PROCESS.CompositeProcess) in g, "Service process is not a CompositeProcess")
            sequence = g.value(process, PROCESS.composedOf)
            check(sequence is not None, "CompositeProcess has no composedOf sequence")
            if sequence is not None:
                performs = rdf_list(g, g.value(sequence, PROCESS.components))
                check(len(performs) >= 5, "CompositeProcess has fewer than 5 steps")
                for perform in performs:
                    atomic = g.value(perform, PROCESS.process)
                    check(atomic is not None and (atomic, RDF.type, PROCESS.AtomicProcess) in g,
                          "Perform does not reference an AtomicProcess")
        if grounding is not None:
            groundings = list(g.objects(grounding, GROUNDING.hasAtomicProcessGrounding))
            check(len(groundings) >= 5, "Grounding has fewer than 5 atomic process groundings")
            for node in groundings:
                check(g.value(node, GROUNDING.owlsProcess) is not None, "Atomic grounding has no owlsProcess")
                check(g.value(node, GROUNDING.wsdlDocument) is not None, "Atomic grounding has no wsdlDocument")
                op = g.value(node, GROUNDING.wsdlOperation)
                check(op is not None and g.value(op, GROUNDING.operation) is not None,
                      "Atomic grounding has no WSDL operation")


def validate_odrl(g: Graph) -> None:
    policies = list(g.subjects(RDF.type, ASH.DecisionPolicy))
    check(len(policies) >= 3, f"Expected at least 3 ODRL policies, found {len(policies)}")
    for policy in policies:
        check(g.value(policy, ODRL.uid) is not None, f"Policy has no odrl:uid: {local(policy)}")
        check(g.value(policy, ODRL.profile) is not None, f"Policy has no odrl:profile: {local(policy)}")
        rules = list(g.objects(policy, ODRL.permission)) + list(g.objects(policy, ODRL.prohibition))
        check(len(rules) >= 1, f"Policy has no permission/prohibition rules: {local(policy)}")
        for rule in rules:
            check(len(list(g.objects(rule, ODRL.action))) >= 1, f"ODRL rule has no action: {local(policy)}")
            check(len(list(g.objects(rule, ODRL.target))) >= 1, f"ODRL rule has no target: {local(policy)}")
            for constraint in g.objects(rule, ODRL.constraint):
                check(g.value(constraint, ODRL.leftOperand) is not None, "Constraint has no leftOperand")
                check(g.value(constraint, ODRL.operator) is not None, "Constraint has no operator")
                check(g.value(constraint, ODRL.rightOperand) is not None, "Constraint has no rightOperand")


def validate_examples(g: Graph) -> None:
    decisions = list(g.subjects(RDF.type, ASH.InvestmentDecision))
    check(len(decisions) >= 3, f"Expected at least 3 example decisions, found {len(decisions)}")
    for decision in decisions:
        for predicate, name in [
            (ASH.aboutSecurity, "aboutSecurity"),
            (ASH.hasRecommendation, "hasRecommendation"),
            (ASH.hasRiskAssessment, "hasRiskAssessment"),
            (ASH.hasRationale, "hasRationale"),
            (ASH.basedOn, "basedOn"),
            (ASH.governedBy, "governedBy"),
            (ASH.hasComplianceCheck, "hasComplianceCheck"),
            (ASH.decidedFor, "decidedFor"),
            (ASH.hasHorizon, "hasHorizon"),
        ]:
            check(g.value(decision, predicate) is not None, f"Decision {local(decision)} lacks {name}")
        check(g.value(decision, ASH.decisionId) is not None, f"Decision {local(decision)} lacks decisionId")
        check(g.value(decision, ASH.decisionDate) is not None, f"Decision {local(decision)} lacks decisionDate")
    companies = list(g.subjects(RDF.type, ASH.ListedCompany))
    check(len(companies) >= 3, "Expected at least 3 example companies")
    for company in companies:
        check(g.value(company, ASH.primaryIndustry) is not None, f"Company {local(company)} lacks primaryIndustry")
        check(g.value(company, ASH.hasSecurity) is not None, f"Company {local(company)} lacks hasSecurity")
        check(g.value(company, ASH.hasFinancialReport) is not None, f"Company {local(company)} lacks hasFinancialReport")


def validate_page_snapshot(g: Graph, classes: set, object_properties: set, data_properties: set, concepts: set, expected_total: int) -> None:
    data_file = ROOT / "assets/js/data.js"
    page_file = ROOT / "index.html"
    check(page_file.exists(), "index.html is missing")
    check(data_file.exists(), "assets/js/data.js is missing; run scripts/build_data.py")
    if not data_file.exists():
        return
    text = data_file.read_text(encoding="utf-8")
    marker = "window.ASH_DATA = "
    check(marker in text, "assets/js/data.js does not contain window.ASH_DATA")
    if marker not in text:
        return
    try:
        payload = json.loads(text.split(marker, 1)[1].rsplit(";", 1)[0])
    except Exception as exc:
        errors.append(f"assets/js/data.js is not valid JSON payload: {exc}")
        return
    check(payload.get("stats", {}).get("totalTriples") == expected_total,
          "Page snapshot is stale: totalTriples differs from the current ontology + knowledge catalog")
    check(payload.get("stats", {}).get("classes") == len(classes),
          "Page snapshot is stale: class count differs from the current ontology")
    check(payload.get("stats", {}).get("objectProperties") == len(object_properties),
          "Page snapshot is stale: object property count differs")
    check(payload.get("stats", {}).get("dataProperties") == len(data_properties),
          "Page snapshot is stale: data property count differs")
    check(payload.get("stats", {}).get("concepts") == len(concepts),
          "Page snapshot is stale: concept count differs")
    check(len(payload.get("competencyQuestions", [])) == len(list(g.subjects(RDF.type, ASH.CompetencyQuestion))),
          "Page snapshot is stale: competency question count differs")


def validate_sparql(g: Graph) -> None:
    query_file = ROOT / "docs/competency-questions.rq"
    if not query_file.exists():
        warnings.append("docs/competency-questions.rq is missing; SPARQL parse check skipped")
        return
    text = query_file.read_text(encoding="utf-8")
    # Split on a marker so each query can be parsed independently.
    blocks = [block.strip() for block in text.split("# --- CQ ---") if block.strip()]
    parsed = 0
    for index, block in enumerate(blocks, start=1):
        query = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
        if not query.strip():
            continue
        try:
            prepareQuery(query)
            parsed += 1
        except Exception as exc:
            errors.append(f"SPARQL query {index} does not parse: {exc}")
    check(parsed >= 6, f"Expected at least 6 parseable competency questions, found {parsed}")


def main() -> int:
    g, modules = load_graph()
    classes = {item for item in g.subjects(RDF.type, OWL.Class) if isinstance(item, URIRef) and str(item).startswith(str(ASH))}
    object_properties = {item for item in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(item, URIRef) and str(item).startswith(str(ASH))}
    data_properties = {item for item in g.subjects(RDF.type, OWL.DatatypeProperty) if isinstance(item, URIRef) and str(item).startswith(str(ASH))}
    concepts = {item for item in g.subjects(RDF.type, SKOS.Concept) if isinstance(item, URIRef) and str(item).startswith(str(ASHS))}
    properties = object_properties | data_properties

    check(len(modules) == len(MODULE_FILES), "Not all ontology modules parsed")
    check(len(g) > 3000, f"Unexpectedly small combined graph: {len(g)} triples")
    check(len(classes) >= 60, f"Too few classes: {len(classes)}")
    check(len(object_properties) >= 40, f"Too few object properties: {len(object_properties)}")
    check(len(data_properties) >= 60, f"Too few data properties: {len(data_properties)}")
    check(len(concepts) >= 45, f"Too few SKOS concepts: {len(concepts)}")
    competency_questions = list(g.subjects(RDF.type, ASH.CompetencyQuestion))
    check(len(competency_questions) >= 10, f"Expected at least 10 competency questions, found {len(competency_questions)}")

    aggregate = Graph()
    aggregate.parse(ROOT / "ontology/a-share.ttl", format="turtle")
    ontology = next(aggregate.subjects(RDF.type, OWL.Ontology), None)
    check(ontology is not None, "Aggregate ontology declaration missing")
    imports = set(aggregate.objects(ontology, OWL.imports)) if ontology else set()
    check(len(imports) >= 7, f"Aggregate ontology imports {len(imports)} modules; expected 7")
    for spec in (
        "https://www.w3.org/TR/rdf11-concepts/",
        "https://www.w3.org/TR/rdf-schema/",
        "https://www.w3.org/TR/owl2-overview/",
        "https://www.w3.org/TR/skos-reference/",
        "https://www.w3.org/Submission/SWRL/",
        "https://www.w3.org/Submission/OWL-S/",
        "https://www.w3.org/TR/odrl-model/",
    ):
        check((ontology, DCTERMS.conformsTo, URIRef(spec)) in aggregate,
              f"Aggregate ontology does not declare conformance to {spec}")

    validate_rdfs(g, classes, object_properties, data_properties)
    validate_owl(g, classes, object_properties, data_properties)
    validate_skos(g, concepts)
    validate_swrl(g, classes, properties)
    validate_rule_library(g)
    validate_owl_s(g)
    validate_odrl(g)
    validate_examples(g)
    knowledge_graph = Graph()
    try:
        knowledge_graph.parse(ROOT / KNOWLEDGE_FILE, format="turtle")
    except Exception as exc:
        errors.append(f"Turtle parse failed: {KNOWLEDGE_FILE}: {exc}")
    check(len(knowledge_graph) > 0, "Knowledge catalog is empty or missing")
    validate_page_snapshot(g, classes, object_properties, data_properties, concepts, len(g + knowledge_graph))
    validate_sparql(g)

    closure_graph = Graph()
    for filename in ["ontology/rdfs/schema.ttl", "ontology/owl/ontology.ttl", "ontology/skos/taxonomy.ttl", "ontology/rdf/instances.ttl"]:
        closure_graph.parse(ROOT / filename, format="turtle")
    before = len(closure_graph)
    try:
        DeductiveClosure(OWLRL_Semantics).expand(closure_graph)
    except Exception as exc:
        errors.append(f"OWL RL closure failed: {exc}")
    inferred = len(closure_graph) - before

    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"  - {item}")
    if errors:
        print("\nErrors:")
        for item in errors:
            print(f"  - {item}")
        print(f"\nFAILED: {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1

    print("A-share ontology validation passed.")
    print(f"  modules: {len(modules)}")
    print(f"  triples: {len(g)}")
    print(f"  classes: {len(classes)}")
    print(f"  object properties: {len(object_properties)}")
    print(f"  data properties: {len(data_properties)}")
    print(f"  SKOS concepts: {len(concepts)}")
    print(f"  SWRL rules: {len(list(g.subjects(RDF.type, SWRL.Imp)))}")
    print(f"  decision rules (V2.0): {len(list(g.subjects(RDF.type, ASH.DecisionRule)))}")
    print(f"  OWL-S services: {len(list(g.subjects(RDF.type, SERVICE.Service)))}")
    print(f"  ODRL policies: {len(list(g.subjects(RDF.type, ASH.DecisionPolicy)))}")
    print(f"  OWL RL closure: {before} -> {len(closure_graph)} triples ({inferred} inferred)")
    print(f"  warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
