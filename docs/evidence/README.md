# Visual evidence

These captures document the browser work for the A-share ontology tickets.

| File | Revision / state | Viewport | What it shows |
| --- | --- | --- | --- |
| `before.png` | Initial branch `92d2b75` (repository had only `README.md`) | 1440 × 1000 | The root route served a directory listing; no ontology viewer existed. |
| `before-graph.png` | Merged `main` at `83f4493` (PR #1) | 1440 × 1000 | The merged page before the graph follow-up; no "图谱" navigation item. |
| `after.png` | Head of `agent/a-share-ontology-a9c9d9ebdae6` (PR #2) | 1440 × 1000 | The ontology browser: hero, decision object, seven-layer navigation, graph entry and scale metrics. |
| `after-explorer.png` | Same branch | 1440 × 1000 | Search for `InvestmentDecision`, filtered result, and the entity inspector with OWL restrictions. |
| `after-graph.png` | Same branch | 1440 × 1000 | Domain overview graph: 72 class nodes, 96 hierarchy/property edges, cluster legend and scale assessment. |
| `after-graph-decision.png` | Same branch | 1440 × 1000 | Decision-chain graph: 19 nodes, 15 labelled object-property edges. |
| `expansion-before.png` | Merged `main` at `fa2b24f` (1.0) | 1440 × 1000 | Expanded-domain baseline: 72 classes / 4,290 triples. |
| `expansion-after.png` | 1.2 branch | 1440 × 1000 | Expanded page: 194 classes / 8,048 triples / 21 rules / 5 policies. |
| `expansion-explorer.png` | 1.1 branch | 1440 × 1000 | `Fund` search in the 564-entity Explorer with class detail. |
| `expansion-graph.png` | 1.2 branch | 1440 × 1000 | Core overview: 51 classes / 82 relations. |
| `expansion-graph-all.png` | 1.2 branch | 1440 × 1000 | All-class overview: 194 classes / 292 relations. |
| `short-before.png` | Merged `main` at `852e52c` (1.1) | 1440 × 1000 | Baseline before the short-term module: no 短线 nav item, fallback hero stats 136 classes / 6,253 triples. |
| `short-term.png` | 1.2 branch | 1440 × 1000 | Short-term/hot-money panel: 6 KPIs, four-step playbook, R16–R21 signals and a short-term decision. |
| `agent-before.png` | Live GitHub Pages at `main` `7bc4064` (PR #2 merged, before this Agent PR) | 1440 × 1000 | Baseline: graph UI is present, but there is no Agent nav entry, no “问 Agent” action and no Agent section. |
| `agent-after.png` | This Agent branch after merging `main`; served by `uvicorn` on `127.0.0.1:8010` | 1440 × 1000 | Same hero and graph-era header, plus the new Agent nav entry and “问 Agent” action. |
| `agent-section.png` | Same merged branch head; rules mode, no server key | 1240 × 941 | New Agent section: status, starter questions, key-safety note, empty conversation. |
| `agent-answer.png` | Same merged branch head; question “分析华辰智造” | 1240 × 1061 | Summary card, ontology-grounded answer, R01/R06/R08 signals, decision chain and citations. |
| `agent-summary.png` | Same state | 808 × 76 | Close-up of the structured conclusion card. |
| `agent-mobile.png` | Same merged branch head; 390 px viewport | 390 × 1289 | Responsive Agent layout with no horizontal overflow. |
| `real-data-before.png` | Merged `main` at `07ad134`, before this ticket; served by `uvicorn`, rules mode | 1440 × 1000 | Baseline: asking “分析贵州茅台” returns “没有找到对应公司”, and the footnote says the Agent only covers 4 synthetic companies. |
| `real-data-after.png` | This ticket branch; same rules-mode server and scenario | 1440 × 1000 | The same question returns a real-data answer: source and dates, 2025 annual metrics, PE/PB, real-data summary card and evidence chips. |

The `agent-before.png` baseline is a real capture of the deployed site before this ticket's UI change,
not a mockup. The after captures use the actual FastAPI backend and the real `index.html`; no LLM
provider key was configured, so the screenshots show the deterministic **rules mode**. LLM mode and
the tool loop are covered by `tests/test_llm.py` with a local OpenAI-compatible stub.

The page was served by `uvicorn server.main:app`; screenshots were taken with Playwright/Chromium.
All example content is synthetic; the `real-data-*` pair additionally shows a live public-data query
against Eastmoney's anonymous JSON endpoints. See the repository README for the disclaimer.
