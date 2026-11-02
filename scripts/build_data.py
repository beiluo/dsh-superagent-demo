#!/usr/bin/env python3
"""Build the static browser data for the A-share ontology site.

The ontology stays canonical in Turtle under ``ontology/``. This script reads
those modules with rdflib and emits a deterministic JSON snapshot used by the
browser. Run it from the repository root:

    python3 scripts/build_data.py
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef
from rdflib.namespace import DCTERMS, SKOS, XSD

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
EXPR = Namespace("http://www.daml.org/services/owl-s/1.2/generic/Expression.owl#")

MODULES = [
    {
        "key": "rdf",
        "index": "01",
        "name": "RDF",
        "zh": "资源描述框架",
        "spec": "RDF 1.1 / Turtle 1.1",
        "specUrl": "https://www.w3.org/TR/rdf11-concepts/",
        "file": "ontology/rdf/instances.ttl",
        "desc": "用三元组描述公司、证券、行情、财报、风险与决策实例；所有示例均可与词表层自由合并。",
        "color": "#b52a22",
    },
    {
        "key": "rdfs",
        "index": "02",
        "name": "RDFS",
        "zh": "RDF 词汇描述",
        "spec": "RDF Schema 1.1",
        "specUrl": "https://www.w3.org/TR/rdf-schema/",
        "file": "ontology/rdfs/schema.ttl",
        "desc": "定义类层次、属性定义域与值域、标签和自然语言释义，构成可读的领域词汇表。",
        "color": "#b8862f",
    },
    {
        "key": "owl",
        "index": "03",
        "name": "OWL 2",
        "zh": "本体公理",
        "spec": "OWL 2 DL / Structural Specification",
        "specUrl": "https://www.w3.org/TR/owl2-overview/",
        "file": "ontology/owl/ontology.ttl",
        "desc": "用限制、基数、属性特征、键与不相交公理表达决策对象的结构约束和身份规则。",
        "color": "#7b4d9e",
    },
    {
        "key": "skos",
        "index": "04",
        "name": "SKOS",
        "zh": "知识组织",
        "spec": "SKOS Reference",
        "specUrl": "https://www.w3.org/TR/skos-reference/",
        "file": "ontology/skos/taxonomy.ttl",
        "desc": "以概念方案组织行业、主题和投资风格；支持多语言标签、层级、关联与映射。",
        "color": "#0f766e",
    },
    {
        "key": "swrl",
        "index": "05",
        "name": "SWRL",
        "zh": "规则推理",
        "spec": "SWRL W3C Member Submission",
        "specUrl": "https://www.w3.org/Submission/SWRL/",
        "file": "ontology/swrl/rules.ttl",
        "desc": "把价值筛选、财务风险、止损、集中度、限制名单和可审计性写成可执行 Horn 规则。",
        "color": "#c2410c",
    },
    {
        "key": "owl-s",
        "index": "06",
        "name": "OWL-S",
        "zh": "语义服务",
        "spec": "OWL-S 1.2 W3C Member Submission",
        "specUrl": "https://www.w3.org/Submission/OWL-S/",
        "file": "ontology/owl-s/service.ttl",
        "desc": "从 Profile、Process Model 与 Grounding 三个视角描述七步决策服务及其调用契约。",
        "color": "#2563a8",
    },
    {
        "key": "odrl",
        "index": "07",
        "name": "ODRL",
        "zh": "政策与治理",
        "spec": "ODRL Information Model 2.2",
        "specUrl": "https://www.w3.org/TR/odrl-model/",
        "file": "ontology/odrl/policies.ttl",
        "desc": "以权限、禁止、义务和约束表达数据使用、决策消费与人工批准交易护栏。",
        "color": "#6d28d9",
    },
]


def local_name(term: Any) -> str:
    if isinstance(term, URIRef):
        text = str(term)
        return re.split(r"[#/]", text.rstrip("/"))[-1]
    return str(term)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def lang_literal(g: Graph, subject: Any, predicates: Iterable[Any], lang: str = "zh") -> str | None:
    for predicate in predicates:
        for value in g.objects(subject, predicate):
            if isinstance(value, Literal) and (value.language or "").startswith(lang):
                return clean(str(value))
    for predicate in predicates:
        for value in g.objects(subject, predicate):
            if isinstance(value, Literal):
                return clean(str(value))
    return None


def label(g: Graph, subject: Any) -> str:
    text = lang_literal(g, subject, (RDFS.label, SKOS.prefLabel, DCTERMS.title), "zh")
    if text:
        return text
    text = lang_literal(g, subject, (RDFS.label, SKOS.prefLabel, DCTERMS.title), "en")
    if text:
        return text
    return local_name(subject).replace("_", " ").replace("-", " ")


def label_en(g: Graph, subject: Any) -> str:
    text = lang_literal(g, subject, (RDFS.label, SKOS.prefLabel, DCTERMS.title), "en")
    if text:
        return text
    return label(g, subject)


def comment(g: Graph, subject: Any) -> str:
    return (
        lang_literal(g, subject, (RDFS.comment, SKOS.definition, DCTERMS.description, SKOS.scopeNote), "zh")
        or ""
    )


def ref(g: Graph, term: Any) -> dict[str, Any]:
    if isinstance(term, URIRef):
        return {"id": local_name(term), "iri": str(term), "label": label(g, term)}
    if isinstance(term, Literal):
        return {"id": f"literal-{local_name(term)}", "label": str(term), "literal": True}
    return {"id": f"anonymous-{str(term)[:8]}", "label": "匿名类", "anonymous": True}


def refs(g: Graph, values: Iterable[Any]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for value in values:
        item = ref(g, value)
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    return out


def rdf_list(g: Graph, head: Any) -> list[Any]:
    if head is None:
        return []
    try:
        return list(g.items(head))
    except Exception:
        return []


def literal_value(value: Literal) -> str:
    if value.datatype == XSD.boolean:
        return "true" if bool(value) else "false"
    text = str(value)
    if value.datatype in (XSD.date, XSD.dateTime, XSD.gYear, XSD.gYearMonth):
        return text
    return text


def source_of(subject: Any, type_sources: dict[Any, str], fallback: str) -> str:
    return type_sources.get(subject, fallback)


def parse_modules() -> tuple[Graph, dict[str, Graph], dict[Any, str]]:
    combined = Graph()
    module_graphs: dict[str, Graph] = {}
    type_sources: dict[Any, str] = {}

    # Bind prefixes for readable serialisation / debugging.
    for prefix, ns in {
        "ash": ASH,
        "ashd": ASHD,
        "ashs": ASHS,
        "owl": OWL,
        "rdf": RDF,
        "rdfs": RDFS,
        "skos": SKOS,
        "dcterms": DCTERMS,
        "swrl": SWRL,
        "swrlb": SWRLB,
        "odrl": ODRL,
        "service": SERVICE,
        "profile": PROFILE,
        "process": PROCESS,
        "grounding": GROUNDING,
        "expr": EXPR,
    }.items():
        combined.bind(prefix, ns)

    for module in MODULES:
        graph = Graph()
        graph.parse(ROOT / module["file"], format="turtle")
        module_graphs[module["key"]] = graph
        for triple in graph:
            combined.add(triple)
        for subject, predicate, obj in graph:
            if predicate == RDF.type and isinstance(subject, URIRef) and isinstance(obj, URIRef):
                if str(subject).startswith(str(ASH)) or str(subject).startswith(str(ASHD)) or str(subject).startswith(str(ASHS)):
                    type_sources.setdefault(subject, module["key"])
    return combined, module_graphs, type_sources


def kind_of(g: Graph, subject: Any) -> str | None:
    types = set(g.objects(subject, RDF.type))
    if OWL.Class in types:
        return "class"
    if OWL.ObjectProperty in types:
        return "objectProperty"
    if OWL.DatatypeProperty in types:
        return "dataProperty"
    if SWRL.Imp in types:
        return "rule"
    if SKOS.Concept in types:
        return "concept"
    if types & {ODRL.Policy, ODRL.Set, ODRL.Offer, ODRL.Agreement, ASH.DecisionPolicy}:
        return "policy"
    if SERVICE.Service in types or ASH.DecisionService in types:
        return "service"
    if OWL.NamedIndividual in types or any(
        str(t).startswith(str(ASH)) for t in types if isinstance(t, URIRef)
    ):
        return "individual"
    return None


def parse_restrictions(g: Graph, cls: Any) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for restriction in g.objects(cls, RDFS.subClassOf):
        if not isinstance(restriction, BNode) and not (
            isinstance(restriction, URIRef) and (restriction, RDF.type, OWL.Restriction) in g
        ):
            continue
        if (restriction, RDF.type, OWL.Restriction) not in g:
            continue
        prop = g.value(restriction, OWL.onProperty)
        if prop is None:
            continue
        item: dict[str, Any] = {
            "property": ref(g, prop),
            "onClass": None,
            "kind": "",
            "cardinality": None,
            "value": None,
            "summary": "",
        }
        on_class = g.value(restriction, OWL.onClass)
        if on_class is not None:
            item["onClass"] = ref(g, on_class)
        for predicate, kind in [
            (OWL.someValuesFrom, "some"),
            (OWL.allValuesFrom, "all"),
            (OWL.hasValue, "value"),
            (OWL.qualifiedCardinality, "qualifiedExactly"),
            (OWL.minQualifiedCardinality, "qualifiedMin"),
            (OWL.maxQualifiedCardinality, "qualifiedMax"),
            (OWL.cardinality, "exactly"),
            (OWL.minCardinality, "min"),
            (OWL.maxCardinality, "max"),
        ]:
            value = g.value(restriction, predicate)
            if value is None:
                continue
            item["kind"] = kind
            if kind in {"some", "all", "value"}:
                item["value"] = ref(g, value)
            else:
                item["cardinality"] = str(value)
            break
        prop_label = item["property"]["label"]
        on_label = item["onClass"]["label"] if item["onClass"] else ""
        kind = item["kind"]
        card = item["cardinality"]
        if kind == "some":
            item["summary"] = f"{prop_label} 至少有一个 {item['value']['label']}"
        elif kind == "all":
            item["summary"] = f"{prop_label} 的取值只能是 {item['value']['label']}"
        elif kind == "value":
            item["summary"] = f"{prop_label} 必须取值为 {item['value']['label']}"
        elif kind == "qualifiedExactly":
            item["summary"] = f"{prop_label} 恰好 {card} 个 {on_label}"
        elif kind == "qualifiedMin":
            item["summary"] = f"{prop_label} 至少 {card} 个 {on_label}"
        elif kind == "qualifiedMax":
            item["summary"] = f"{prop_label} 至多 {card} 个 {on_label}"
        elif kind == "exactly":
            item["summary"] = f"{prop_label} 恰好 {card} 个值"
        elif kind == "min":
            item["summary"] = f"{prop_label} 至少 {card} 个值"
        elif kind == "max":
            item["summary"] = f"{prop_label} 至多 {card} 个值"
        else:
            item["summary"] = f"{prop_label} 的结构约束"
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def class_property_refs(g: Graph, cls: Any) -> list[dict[str, Any]]:
    out = []
    for prop in g.subjects(RDFS.domain, cls):
        if (prop, RDF.type, OWL.ObjectProperty) in g or (prop, RDF.type, OWL.DatatypeProperty) in g:
            out.append(ref(g, prop))
    return sorted(out, key=lambda item: item["label"])


def parse_classes(g: Graph, type_sources: dict[Any, str], disjoint_groups: dict[Any, list[Any]]) -> list[dict[str, Any]]:
    classes = []
    for cls in g.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef) or not str(cls).startswith(str(ASH)):
            continue
        super_classes = []
        for parent in g.objects(cls, RDFS.subClassOf):
            if isinstance(parent, URIRef):
                super_classes.append(parent)
        sub_classes = [child for child in g.subjects(RDFS.subClassOf, cls) if isinstance(child, URIRef)]
        disjoint = [item for item in disjoint_groups.get(cls, []) if item != cls]
        keys = []
        for key_list in g.objects(cls, OWL.hasKey):
            keys.append(refs(g, rdf_list(g, key_list)))
        classes.append(
            {
                "id": local_name(cls),
                "iri": str(cls),
                "kind": "class",
                "label": {"zh": label(g, cls), "en": label_en(g, cls)},
                "comment": comment(g, cls),
                "example": lang_literal(g, cls, (ASH.example,), "zh") or "",
                "source": source_of(cls, type_sources, "rdfs"),
                "layer": "rdfs",
                "superClasses": refs(g, super_classes),
                "subClasses": refs(g, sub_classes),
                "disjointWith": refs(g, disjoint),
                "keys": [item for item in keys if item],
                "restrictions": parse_restrictions(g, cls),
                "properties": class_property_refs(g, cls),
                "deprecated": bool(g.value(cls, OWL.deprecated)),
            }
        )
    return sorted(classes, key=lambda item: item["label"]["zh"])


def parse_properties(g: Graph, type_sources: dict[Any, str]) -> list[dict[str, Any]]:
    out = []
    for prop_type, kind in [(OWL.ObjectProperty, "objectProperty"), (OWL.DatatypeProperty, "dataProperty")]:
        for prop in g.subjects(RDF.type, prop_type):
            if not isinstance(prop, URIRef) or not str(prop).startswith(str(ASH)):
                continue
            domains = [item for item in g.objects(prop, RDFS.domain) if isinstance(item, URIRef)]
            ranges = [item for item in g.objects(prop, RDFS.range) if isinstance(item, URIRef)]
            characteristics = []
            for characteristic, name in [
                (OWL.FunctionalProperty, "函数式"),
                (OWL.InverseFunctionalProperty, "反函数式"),
                (OWL.TransitiveProperty, "传递"),
                (OWL.SymmetricProperty, "对称"),
                (OWL.AsymmetricProperty, "非对称"),
                (OWL.ReflexiveProperty, "自反"),
                (OWL.IrreflexiveProperty, "反自反"),
            ]:
                if (prop, RDF.type, characteristic) in g:
                    characteristics.append(name)
            inverse = [item for item in g.objects(prop, OWL.inverseOf) if isinstance(item, URIRef)]
            parents = [item for item in g.objects(prop, RDFS.subPropertyOf) if isinstance(item, URIRef)]
            out.append(
                {
                    "id": local_name(prop),
                    "iri": str(prop),
                    "kind": kind,
                    "label": {"zh": label(g, prop), "en": label_en(g, prop)},
                    "comment": comment(g, prop),
                    "source": source_of(prop, type_sources, "rdfs"),
                    "layer": "rdfs",
                    "domain": refs(g, domains),
                    "range": refs(g, ranges),
                    "inverseOf": refs(g, inverse),
                    "subPropertyOf": refs(g, parents),
                    "characteristics": characteristics,
                }
            )
    return sorted(out, key=lambda item: (item["kind"], item["label"]["zh"]))


def object_facts(g: Graph, subject: Any, exclude: set[Any]) -> list[dict[str, Any]]:
    out = []
    for predicate, obj in g.predicate_objects(subject):
        if predicate in exclude:
            continue
        if not isinstance(predicate, URIRef):
            continue
        if (predicate, RDF.type, OWL.ObjectProperty) in g:
            out.append({"property": ref(g, predicate), "value": ref(g, obj)})
        elif (predicate, RDF.type, OWL.DatatypeProperty) in g and isinstance(obj, Literal):
            out.append({"property": ref(g, predicate), "value": {"literal": literal_value(obj), "datatype": local_name(obj.datatype) if obj.datatype else ""}})
    return out


def parse_individuals(g: Graph, type_sources: dict[Any, str]) -> list[dict[str, Any]]:
    exclude = {RDF.type, RDFS.label, RDFS.comment, ASH.isExample, ASH.exampleNote}
    out = []
    for subject in set(g.subjects(RDF.type, OWL.NamedIndividual)):
        if not isinstance(subject, URIRef) or not str(subject).startswith(str(ASHD)):
            continue
        kind = kind_of(g, subject)
        if kind != "individual":
            continue
        if g.value(subject, ASH.isExample) not in (None, Literal(True)):
            continue
        types = [item for item in g.objects(subject, RDF.type) if isinstance(item, URIRef)]
        out.append(
            {
                "id": local_name(subject),
                "iri": str(subject),
                "kind": "individual",
                "label": {"zh": label(g, subject), "en": label_en(g, subject)},
                "comment": comment(g, subject),
                "source": source_of(subject, type_sources, "rdf"),
                "layer": "rdf",
                "types": refs(g, types),
                "facts": object_facts(g, subject, exclude),
                "exampleNote": lang_literal(g, subject, (ASH.exampleNote,), "zh") or "",
            }
        )
    return sorted(out, key=lambda item: item["label"]["zh"])


def parse_schemes_and_concepts(g: Graph, type_sources: dict[Any, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    schemes = []
    for scheme in g.subjects(RDF.type, SKOS.ConceptScheme):
        if not str(scheme).startswith(str(ASHS)):
            continue
        top = [item for item in g.objects(scheme, SKOS.hasTopConcept) if isinstance(item, URIRef)]
        schemes.append(
            {
                "id": local_name(scheme),
                "iri": str(scheme),
                "label": {"zh": label(g, scheme), "en": label_en(g, scheme)},
                "definition": comment(g, scheme),
                "topConcepts": refs(g, top),
                "source": source_of(scheme, type_sources, "skos"),
            }
        )
    concepts = []
    for concept in g.subjects(RDF.type, SKOS.Concept):
        if not str(concept).startswith(str(ASHS)):
            continue
        scheme = g.value(concept, SKOS.inScheme)
        alt_labels = [str(item) for item in g.objects(concept, SKOS.altLabel) if isinstance(item, Literal)]
        concepts.append(
            {
                "id": local_name(concept),
                "iri": str(concept),
                "kind": "concept",
                "label": {"zh": label(g, concept), "en": label_en(g, concept)},
                "definition": comment(g, concept),
                "scopeNote": lang_literal(g, concept, (SKOS.scopeNote,), "zh") or "",
                "notation": str(g.value(concept, SKOS.notation) or ""),
                "scheme": ref(g, scheme) if scheme is not None else None,
                "altLabels": alt_labels,
                "broader": refs(g, [item for item in g.objects(concept, SKOS.broader) if isinstance(item, URIRef)]),
                "narrower": refs(g, [item for item in g.objects(concept, SKOS.narrower) if isinstance(item, URIRef)]),
                "related": refs(g, [item for item in g.objects(concept, SKOS.related) if isinstance(item, URIRef)]),
                "topConcept": any(True for _ in g.objects(concept, SKOS.topConceptOf)),
                "source": source_of(concept, type_sources, "skos"),
                "layer": "skos",
            }
        )
    scheme_order = {"scheme-industry": 0, "scheme-theme": 1, "scheme-style": 2}
    schemes.sort(key=lambda item: (scheme_order.get(item["id"], 99), item["label"]["zh"]))
    return schemes, sorted(concepts, key=lambda item: item["label"]["zh"])


def variable_label(g: Graph, term: Any) -> str:
    if isinstance(term, URIRef):
        value = g.value(term, RDFS.label)
        if value:
            return str(value)
    if isinstance(term, Literal):
        if term.datatype == XSD.boolean:
            return "true" if bool(term) else "false"
        return str(term)
    return local_name(term)


def atom_text(g: Graph, atom: Any) -> str:
    atom_type = g.value(atom, RDF.type)
    if atom_type == SWRL.ClassAtom:
        predicate = g.value(atom, SWRL.classPredicate)
        argument = g.value(atom, SWRL.argument1)
        return f"{variable_label(g, argument)} a {label(g, predicate) if predicate else '?'}"
    if atom_type in (SWRL.IndividualPropertyAtom, SWRL.DatavaluedPropertyAtom):
        predicate = g.value(atom, SWRL.propertyPredicate)
        argument1 = g.value(atom, SWRL.argument1)
        argument2 = g.value(atom, SWRL.argument2)
        return f"{variable_label(g, argument1)} {local_name(predicate) if predicate else '?'} {variable_label(g, argument2)}"
    if atom_type == SWRL.BuiltinAtom:
        builtin = g.value(atom, SWRL.builtin)
        args = [variable_label(g, item) for item in rdf_list(g, g.value(atom, SWRL.arguments))]
        return f"{local_name(builtin) if builtin else 'builtin'}({', '.join(args)})"
    return "原子"


def parse_rules(g: Graph, type_sources: dict[Any, str]) -> list[dict[str, Any]]:
    out = []
    for rule in g.subjects(RDF.type, SWRL.Imp):
        if not isinstance(rule, URIRef) or not str(rule).startswith(str(ASHD)):
            continue
        body = rdf_list(g, g.value(rule, SWRL.body))
        head = rdf_list(g, g.value(rule, SWRL.head))
        out.append(
            {
                "id": local_name(rule),
                "iri": str(rule),
                "kind": "rule",
                "label": {"zh": label(g, rule), "en": label_en(g, rule)},
                "comment": comment(g, rule),
                "source": source_of(rule, type_sources, "swrl"),
                "layer": "swrl",
                "ruleId": str(g.value(rule, ASH.ruleId) or ""),
                "ruleIf": str(g.value(rule, ASH.ruleIf) or ""),
                "ruleThen": str(g.value(rule, ASH.ruleThen) or ""),
                "severity": str(g.value(rule, ASH.severity) or ""),
                "priority": str(g.value(rule, ASH.rulePriority) or ""),
                "status": str(g.value(rule, ASH.ruleStatus) or ""),
                "version": str(g.value(rule, ASH.ruleVersion) or ""),
                "owner": str(g.value(rule, ASH.ruleOwner) or ""),
                "effectiveFrom": str(g.value(rule, ASH.ruleEffectiveFrom) or ""),
                "appliesTo": refs(g, [item for item in g.objects(rule, ASH.appliesTo) if isinstance(item, URIRef)]),
                "uses": refs(g, [item for item in g.objects(rule, ASH.ruleUses) if isinstance(item, URIRef)]),
                "bodyAtoms": [{"text": atom_text(g, atom)} for atom in body],
                "headAtoms": [{"text": atom_text(g, atom)} for atom in head],
            }
        )
    return sorted(out, key=lambda item: item["ruleId"])


def parse_parameter(g: Graph, node: Any) -> dict[str, Any]:
    param_type = g.value(node, PROCESS.parameterType)
    return {
        "id": local_name(node),
        "label": label(g, node),
        "comment": comment(g, node),
        "parameterType": str(param_type) if param_type else "",
    }


def parse_service(g: Graph, service: Any, type_sources: dict[Any, str]) -> dict[str, Any]:
    profile = g.value(service, SERVICE.presents)
    process = g.value(service, SERVICE.describedBy)
    grounding = g.value(service, SERVICE.supports)

    profile_data: dict[str, Any] = {}
    if profile is not None:
        category = g.value(profile, PROFILE.serviceCategory)
        profile_data = {
            "id": local_name(profile),
            "label": label(g, profile),
            "comment": comment(g, profile),
            "serviceName": str(g.value(profile, PROFILE.serviceName) or ""),
            "description": str(g.value(profile, PROFILE.textDescription) or ""),
            "category": label(g, category) if category is not None else "",
            "categoryCode": str(g.value(category, PROFILE.code) or "") if category is not None else "",
            "inputs": [parse_parameter(g, item) for item in g.objects(profile, PROFILE.hasInput)],
            "outputs": [parse_parameter(g, item) for item in g.objects(profile, PROFILE.hasOutput)],
            "preconditions": [
                {
                    "id": local_name(item),
                    "label": label(g, item),
                    "body": str(g.value(item, EXPR.expressionBody) or ""),
                }
                for item in g.objects(profile, PROFILE.hasPrecondition)
            ],
        }

    process_data: dict[str, Any] = {}
    if process is not None:
        steps = []
        sequence = g.value(process, PROCESS.composedOf)
        if sequence is not None:
            for perform in rdf_list(g, g.value(sequence, PROCESS.components)):
                atomic = g.value(perform, PROCESS.process)
                if atomic is None:
                    continue
                steps.append(
                    {
                        "id": local_name(atomic),
                        "label": label(g, atomic),
                        "comment": comment(g, atomic),
                        "inputs": [parse_parameter(g, item) for item in g.objects(atomic, PROCESS.hasInput)],
                        "outputs": [parse_parameter(g, item) for item in g.objects(atomic, PROCESS.hasOutput)],
                    }
                )
        process_data = {
            "id": local_name(process),
            "label": label(g, process),
            "comment": comment(g, process),
            "inputs": [parse_parameter(g, item) for item in g.objects(process, PROCESS.hasInput)],
            "outputs": [parse_parameter(g, item) for item in g.objects(process, PROCESS.hasOutput)],
            "preconditions": [
                {
                    "id": local_name(item),
                    "label": label(g, item),
                    "body": str(g.value(item, EXPR.expressionBody) or ""),
                }
                for item in g.objects(process, PROCESS.hasPrecondition)
            ],
            "steps": steps,
        }

    grounding_data: dict[str, Any] = {}
    if grounding is not None:
        groundings = []
        for node in g.objects(grounding, GROUNDING.hasAtomicProcessGrounding):
            op = g.value(node, GROUNDING.wsdlOperation)
            groundings.append(
                {
                    "id": local_name(node),
                    "process": label(g, g.value(node, GROUNDING.owlsProcess)) if g.value(node, GROUNDING.owlsProcess) else "",
                    "document": str(g.value(node, GROUNDING.wsdlDocument) or ""),
                    "service": str(g.value(node, GROUNDING.wsdlService) or ""),
                    "port": str(g.value(node, GROUNDING.wsdlPort) or ""),
                    "operation": str(g.value(op, GROUNDING.operation) or "") if op is not None else "",
                }
            )
        grounding_data = {
            "id": local_name(grounding),
            "label": label(g, grounding),
            "comment": comment(g, grounding),
            "groundings": groundings,
        }

    return {
        "id": local_name(service),
        "iri": str(service),
        "kind": "service",
        "label": {"zh": label(g, service), "en": label_en(g, service)},
        "comment": comment(g, service),
        "source": source_of(service, type_sources, "owl-s"),
        "layer": "owl-s",
        "version": str(g.value(service, ASH.serviceVersion) or ""),
        "endpointStatus": str(g.value(service, ASH.endpointStatus) or ""),
        "humanApprovalRequired": bool(g.value(service, ASH.humanApprovalRequired)) if g.value(service, ASH.humanApprovalRequired) is not None else None,
        "profile": profile_data,
        "process": process_data,
        "grounding": grounding_data,
    }


def rule_actions(g: Graph, rule: Any) -> list[dict[str, str]]:
    action_labels = {
        "read": "读取", "derive": "派生", "aggregate": "聚合", "distribute": "分发",
        "commercialize": "商业化", "execute": "执行", "use": "使用", "reproduce": "复制",
        "attribute": "标注来源", "delete": "删除", "inform": "告知", "obtainConsent": "获取同意",
        "reviewPolicy": "复核政策",
    }
    out = []
    for action in g.objects(rule, ODRL.action):
        local = local_name(action)
        out.append({"id": local, "label": action_labels.get(local, local)})
    return out


def constraint_text(g: Graph, constraint: Any) -> str:
    operand_labels = {
        "purpose": "目的", "spatial": "地域", "dateTime": "时间", "count": "次数",
        "recipient": "接收方", "humanApproval": "人工批准", "compliancePassed": "合规检查通过",
        "event": "事件", "elapsedTime": "经过时间", "industry": "行业",
    }
    operator_labels = {
        "eq": "=", "lt": "<", "lteq": "≤", "gt": ">", "gteq": "≥", "neq": "≠",
        "isA": "属于", "isNoneOf": "不属于", "isAnyOf": "属于任一", "isAllOf": "包含全部",
    }
    left = g.value(constraint, ODRL.leftOperand)
    op = g.value(constraint, ODRL.operator)
    right = g.value(constraint, ODRL.rightOperand)
    left_local = local_name(left) if left else "?"
    left_label = operand_labels.get(left_local, label(g, left) if left else left_local)
    op_label = operator_labels.get(local_name(op), local_name(op)) if op else "?"
    if isinstance(right, Literal):
        right_label = literal_value(right)
    elif isinstance(right, URIRef):
        right_label = label(g, right)
    elif isinstance(right, BNode):
        values = rdf_list(g, right)
        right_label = "、".join(label(g, item) for item in values) if values else "列表"
    else:
        right_label = "?"
    return f"{left_label} {op_label} {right_label}"


def parse_rule_node(g: Graph, node: Any) -> dict[str, Any]:
    return {
        "actions": rule_actions(g, node),
        "targets": refs(g, [item for item in g.objects(node, ODRL.target) if isinstance(item, URIRef)]),
        "assigner": refs(g, [item for item in g.objects(node, ODRL.assigner) if isinstance(item, URIRef)]),
        "assignee": refs(g, [item for item in g.objects(node, ODRL.assignee) if isinstance(item, URIRef)]),
        "constraints": [constraint_text(g, item) for item in g.objects(node, ODRL.constraint) if isinstance(item, BNode)],
        "duties": [parse_rule_node(g, item) for item in g.objects(node, ODRL.duty) if isinstance(item, BNode)],
        "remedy": [parse_rule_node(g, item) for item in g.objects(node, ODRL.remedy) if isinstance(item, BNode)],
        "consequence": [parse_rule_node(g, item) for item in g.objects(node, ODRL.consequence) if isinstance(item, BNode)],
    }


def parse_policies(g: Graph, type_sources: dict[Any, str]) -> list[dict[str, Any]]:
    out = []
    for policy in g.subjects(RDF.type, ASH.DecisionPolicy):
        if not isinstance(policy, URIRef):
            continue
        out.append(
            {
                "id": local_name(policy),
                "iri": str(policy),
                "kind": "policy",
                "label": {"zh": label(g, policy), "en": label_en(g, policy)},
                "comment": comment(g, policy),
                "source": source_of(policy, type_sources, "odrl"),
                "layer": "odrl",
                "title": lang_literal(g, policy, (DCTERMS.title,), "zh") or label(g, policy),
                "description": lang_literal(g, policy, (DCTERMS.description,), "zh") or comment(g, policy),
                "uid": str(g.value(policy, ODRL.uid) or ""),
                "profile": ref(g, g.value(policy, ODRL.profile)).get("label", "") if g.value(policy, ODRL.profile) else "",
                "conflict": local_name(g.value(policy, ODRL.conflict)) if g.value(policy, ODRL.conflict) else "",
                "version": str(g.value(policy, ASH.policyVersion) or ""),
                "status": str(g.value(policy, ASH.policyStatus) or ""),
                "reviewDate": str(g.value(policy, ASH.reviewDate) or ""),
                "permissions": [parse_rule_node(g, item) for item in g.objects(policy, ODRL.permission)],
                "prohibitions": [parse_rule_node(g, item) for item in g.objects(policy, ODRL.prohibition)],
                "obligations": [parse_rule_node(g, item) for item in g.objects(policy, ODRL.obligation)],
            }
        )
    return sorted(out, key=lambda item: item["label"]["zh"])


def build() -> dict[str, Any]:
    g, module_graphs, type_sources = parse_modules()

    disjoint_groups: dict[Any, list[Any]] = {}
    disjoint_group_count = 0
    for group in g.subjects(RDF.type, OWL.AllDisjointClasses):
        members = rdf_list(g, g.value(group, OWL.members))
        if not members:
            continue
        disjoint_group_count += 1
        for member in members:
            disjoint_groups[member] = members

    classes = parse_classes(g, type_sources, disjoint_groups)
    properties = parse_properties(g, type_sources)
    object_properties = [item for item in properties if item["kind"] == "objectProperty"]
    data_properties = [item for item in properties if item["kind"] == "dataProperty"]
    individuals = parse_individuals(g, type_sources)
    schemes, concepts = parse_schemes_and_concepts(g, type_sources)
    rules = parse_rules(g, type_sources)
    services = [parse_service(g, item, type_sources) for item in g.subjects(RDF.type, SERVICE.Service)]
    policies = parse_policies(g, type_sources)

    # Attach rule usage to properties after rules are parsed.
    rule_usage: dict[str, list[dict[str, str]]] = {}
    for rule in rules:
        for used in rule["uses"]:
            rule_usage.setdefault(used["id"], []).append({"id": rule["ruleId"], "label": rule["label"]["zh"]})
    for prop in properties:
        prop["usedByRules"] = sorted(rule_usage.get(prop["id"], []), key=lambda item: item["id"])

    competency_questions = []
    for cq in sorted(g.subjects(RDF.type, ASH.CompetencyQuestion), key=lambda item: str(item)):
        competency_questions.append(
            {
                "id": local_name(cq),
                "label": label(g, cq),
                "question": str(g.value(cq, ASH.competencyQuestion) or label(g, cq)),
            }
        )

    restrictions = sum(len(item["restrictions"]) for item in classes)
    characteristics = sum(len(item["characteristics"]) for item in properties)
    keys = sum(len(item["keys"]) for item in classes)

    layers = []
    for module in MODULES:
        key = module["key"]
        graph = module_graphs[key]
        if key == "rdf":
            count = len(graph)
            unit = "实例三元组"
        elif key == "rdfs":
            count = len(classes) + len(properties)
            unit = "类 / 属性"
        elif key == "owl":
            count = restrictions + disjoint_group_count + keys + characteristics
            unit = "结构公理"
        elif key == "skos":
            count = len(concepts)
            unit = "概念"
        elif key == "swrl":
            count = len(rules)
            unit = "条规则"
        elif key == "owl-s":
            count = len(services)
            unit = "项服务"
        elif key == "odrl":
            count = len(policies)
            unit = "项政策"
        else:
            count = 0
            unit = ""
        layers.append({**module, "count": count, "unit": unit, "triples": len(graph)})

    stats = {
        "totalTriples": len(g),
        "classes": len(classes),
        "objectProperties": len(object_properties),
        "dataProperties": len(data_properties),
        "properties": len(properties),
        "individuals": len(individuals),
        "concepts": len(concepts),
        "schemes": len(schemes),
        "rules": len(rules),
        "services": len(services),
        "policies": len(policies),
        "restrictions": restrictions,
        "disjointGroups": disjoint_group_count,
        "keys": keys,
        "competencyQuestions": len(competency_questions),
    }

    return {
        "meta": {
            "title": "A 股投资决策本体",
            "titleEn": "A-Share Investment Decision Ontology",
            "version": "1.0.0",
            "date": "2026-11",
            "namespace": str(ASH),
            "repo": "https://github.com/beiluo/dsh-superagent-demo",
            "site": "https://beiluo.github.io/dsh-superagent-demo/",
            "description": "覆盖 RDF、RDFS、OWL 2、SKOS、SWRL、OWL-S 与 ODRL 的可审计 A 股投资决策语义模型。",
            "disclaimer": "本体、规则、政策与页面中的全部数据均为设计示例，不构成投资建议，也不连接真实交易系统。",
        },
        "stats": stats,
        "layers": layers,
        "classes": classes,
        "properties": properties,
        "objectProperties": object_properties,
        "dataProperties": data_properties,
        "individuals": individuals,
        "schemes": schemes,
        "concepts": concepts,
        "rules": rules,
        "services": services,
        "policies": policies,
        "competencyQuestions": competency_questions,
    }


def main() -> None:
    data = build()
    encoded = json.dumps(data, ensure_ascii=False, indent=2)
    (ROOT / "assets/js/data.js").write_text(
        "/* Generated by scripts/build_data.py from ontology/*.ttl. Do not edit by hand. */\n"
        "window.ASH_DATA = "
        + encoded
        + ";\n",
        encoding="utf-8",
    )
    (ROOT / "assets/data/ontology.json").write_text(encoded + "\n", encoding="utf-8")
    print(
        "Built assets/js/data.js and assets/data/ontology.json: "
        f"{data['stats']['totalTriples']} triples, "
        f"{data['stats']['classes']} classes, "
        f"{data['stats']['properties']} properties, "
        f"{data['stats']['concepts']} concepts, "
        f"{data['stats']['rules']} rules, "
        f"{data['stats']['policies']} policies."
    )


if __name__ == "__main__":
    main()
