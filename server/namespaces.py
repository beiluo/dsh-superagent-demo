"""RDF namespaces shared by the ontology agent."""

from __future__ import annotations

from rdflib import Namespace

ASH = Namespace("https://beiluo.github.io/dsh-superagent-demo/ontology/a-share#")
ASHD = Namespace("https://beiluo.github.io/dsh-superagent-demo/ontology/a-share/data#")
ASHS = Namespace("https://beiluo.github.io/dsh-superagent-demo/ontology/a-share/skos#")
# Runtime-only namespace for real A-share snapshots mapped into the ontology.
# Nothing here is written to the Turtle source files.
ASHREAL = Namespace("https://beiluo.github.io/dsh-superagent-demo/ontology/a-share/real#")

DCTERMS = Namespace("http://purl.org/dc/terms/")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
SERVICE = Namespace("http://www.daml.org/services/owl-s/1.2/Service.owl#")
PROFILE = Namespace("http://www.daml.org/services/owl-s/1.2/Profile.owl#")
PROCESS = Namespace("http://www.daml.org/services/owl-s/1.2/Process.owl#")
GROUNDING = Namespace("http://www.daml.org/services/owl-s/1.2/Grounding.owl#")

ONTOLOGY_MODULES = (
    "rdf/instances.ttl",
    "rdfs/schema.ttl",
    "owl/ontology.ttl",
    "skos/taxonomy.ttl",
    "swrl/rules.ttl",
    "owl-s/service.ttl",
    "odrl/policies.ttl",
)
