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
| `trace-before.png` | Merged `main` at `852e52c`, before the execution-trace change; rules mode, question “分析华辰智造” | 1440 × 1000 | Baseline: the answer ends with tool chips and ontology citations; there is no execution trace. |
| `trace-after.png` | This ticket branch, same rules-mode server, question and scroll position | 1440 × 1000 | The same answer now ends with the expanded “执行详情” panel: USER message, TOOL call with arguments, collapsed raw tool data and raw JSON. |
| `trace-after-detail.png` | Same state as `trace-after.png` | 808 × 299 | Close-up of the new execution-trace panel. |
| `query-idle-before.png` | Merged `main` at `1a25a68`, before the ontology-query change; rules mode, no market data | 1240 × 942 | Baseline Agent section: fixed starter questions and the old “先检索企业、规则、决策与政策” welcome copy. |
| `query-idle-after.png` | Ticket branch head, same server settings | 1240 × 942 | New starter questions for filters, evidence, constraints and what-if, plus welcome copy explaining that the question chooses the query path. |
| `query-before.png` | Merged `main` at `1a25a68`; question “PE 低于 20 且 ROE 高于 15 的公司” | 1240 × 1153 | Baseline: the rules agent cannot turn the filter into a query and returns “没有找到对应公司” plus the company list. |
| `query-after.png` | Ticket branch head; same question, viewport and rules mode | 1240 × 1282 | The same question now runs `query_ontology`: ROE/PE filters, the RDF property paths used, R01/R06/R08 signals, and the new “本体查询路径” panel. |
| `evidence-before.png` | Merged `main` at `1a25a68`; question “华辰智造的决策证据链” | 1240 × 1333 | Baseline: the question is treated as an ordinary company-analysis request; no evidence-chain traversal is shown. |
| `evidence-after.png` | Ticket branch head; same question | 1240 × 1681 | `trace_evidence` walks the decision graph: company → decision → evidence → source, with data dates and policy links, plus the query-path panel. |
| `constraints-before.png` | Merged `main` at `1a25a68`; question “如果加仓华辰智造到 15%，组合约束允许吗？” | 1240 × 1333 | Baseline: the position question falls back to company analysis; R06 is reported, but there is no proposed-weight or ODRL gate check. |
| `constraints-after.png` | Ticket branch head; same question | 1240 × 1368 | `check_constraints` evaluates the proposed 15% weight, R07/R11 and the ODRL trade-guard human-approval/compliance gates. |
| `scenario-before.png` | Merged `main` at `1a25a68`; question “如果华辰智造 ROE 下降 5 个百分点会怎样？” | 1240 × 1333 | Baseline: the what-if question is treated as a request to analyse the company; the hypothetical change is ignored. |
| `scenario-after.png` | Ticket branch head; same question | 1240 × 1132 | `simulate_scenario` changes ROE in an in-memory copy and shows R01 moving from triggered to clear, without writing back to the ontology. |

The `agent-before.png` baseline is a real capture of the deployed site before this ticket's UI change,
not a mockup. The after captures use the actual FastAPI backend and the real `index.html`; no LLM
provider key was configured, so the screenshots show the deterministic **rules mode**. LLM mode and
the tool loop are covered by `tests/test_llm.py` with a local OpenAI-compatible stub.

The `query-*`, `evidence-*`, `constraints-*` and `scenario-*` pairs use the same rules-mode server
settings (`MARKET_DATA_ENABLED=false`, no LLM key): the baseline worktree is `main` at `1a25a68`
before this ticket, and the after captures are from the ticket branch served on
`127.0.0.1:8020`. To show the complete conversation, the `.agent-log` was expanded to full height and
the sticky header was hidden for these screenshots; both sides of each pair use the same viewport,
question and treatment. The baseline is a real capture of the previous implementation, not a mockup.

The page was served by `uvicorn server.main:app`; screenshots were taken with Playwright/Chromium.
All example content is synthetic; the `real-data-*` pair additionally shows a live public-data query
against Eastmoney's anonymous JSON endpoints. The `trace-*` pair uses the same rules-mode scenario
(before/after the change) and the same 1440 × 1000 viewport; `trace-after-detail.png` is a close-up
of the changed panel. LLM-mode trace rendering was checked in Chromium against a stubbed
`/api/agent/analyze` response, because no provider key is configured here. See the repository README
for the disclaimer.
