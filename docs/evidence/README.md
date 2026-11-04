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
| `expansion-after.png` | 1.8 branch | 1440 × 1000 | Expanded page: 294 classes / 40,574 triples / 3,404 entities / 151 rules / 5 policies. |
| `expansion-explorer.png` | 1.1 branch | 1440 × 1000 | `Fund` search in the 564-entity Explorer with class detail. |
| `expansion-graph.png` | 1.7 branch | 1440 × 1000 | Core overview: 51 classes / 82 relations. |
| `expansion-graph-all.png` | 1.7 branch | 1440 × 1000 | All-class overview: 294 classes / 434 relations. |
| `short-before.png` | Merged `main` at `852e52c` (1.1) | 1440 × 1000 | Baseline before the short-term module: no 短线 nav item, fallback hero stats 136 classes / 6,253 triples. |
| `rules-before.png` | 1.6 branch | 1440 × 1000 | Rule section before the 1.7 expansion: 26 rules. |
| `rules-after.png` | 1.7 branch | 1440 × 1000 | Rule section at 76 rules. |
| `rules-after-1.8.png` | 1.8 branch | 1440 × 1000 | Rule section at 151 rules. |
| `youzi-before.png` | Merged `main` at `115eb98` (1.2) | 1440 × 1000 | Same 短线 section before 1.3: four-step playbook and R16–R21 only; no methodology cards or emotion cycle. |
| `short-term.png` | 1.8 branch | 1440 × 1000 | Short-term panel with methodology cards, emotion cycle, four trader-voice excerpts, R16–R26 and a short-term decision; source line indexes 50 skills/821 sections/1,327 statements. |
| `agent-before.png` | Live GitHub Pages at `main` `7bc4064` (PR #2 merged, before this Agent PR) | 1440 × 1000 | Baseline: graph UI is present, but there is no Agent nav entry, no “问 Agent” action and no Agent section. |
| `agent-after.png` | This Agent branch after merging `main`; served by `uvicorn` on `127.0.0.1:8010` | 1440 × 1000 | Same hero and graph-era header, plus the new Agent nav entry and “问 Agent” action. |
| `agent-section.png` | Same merged branch head; rules mode, no server key | 1240 × 941 | New Agent section: status, starter questions, key-safety note, empty conversation. |
| `agent-answer.png` | Same merged branch head; question “分析华辰智造” | 1240 × 1061 | Summary card, ontology-grounded answer, R01/R06/R08 signals, decision chain and citations. |
| `agent-summary.png` | Same state | 808 × 76 | Close-up of the structured conclusion card. |
| `agent-mobile.png` | Same merged branch head; 390 px viewport | 390 × 1289 | Responsive Agent layout with no horizontal overflow. |
| `real-data-before.png` | Merged `main` at `07ad134`, before this ticket; served by `uvicorn`, rules mode | 1440 × 1000 | Baseline: asking “分析贵州茅台” returns “没有找到对应公司”, and the footnote says the Agent only covers 4 synthetic companies. |
| `real-data-after.png` | This ticket branch; same rules-mode server and scenario | 1440 × 1000 | The same question returns a real-data answer: source and dates, 2025 annual metrics, PE/PB, real-data summary card and evidence chips. |
| `short-term-before.png` | Merged `main` at `115eb98`, before PR #14; live LLM (`deepseek-flash`) | 1440 × 1000 | 云南白药 answer with only R01–R11 long-term signals; no short/medium-term rules or MA/limit-up facts are evaluated. |
| `short-term-after.png` | PR #14 head; same server, question, viewport and model | 1440 × 1000 | The same question now includes MA5/MA20/MA60, limit-up/broken-board facts and R16–R21 statuses (R18/R19/R20 evaluated; R16/R17/R21 cannot be assessed from available fields). |
| `compare-after.png` | PR #14 head; multi-stock comparison, live LLM | 1440 × 1000 | New `compare_companies` result for 茅台/平安/泸州老窖: common ontology fields, R01–R21 statuses, and the RDF property paths used for the comparison. No prior comparison view existed. |
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
| `open-query-before.png` | Merged `main` at `9530cab`, before this ticket; live LLM (`deepseek-flash`), question “哪些投资决策缺少风险评估？” | 1240 × 2068 | Baseline: no graph-query tool. The agent can only call fixed tools, here six `trace_evidence` walks, and has to assemble the negative-condition answer from those results. |
| `open-query-after.png` | Ticket branch head; same server settings, question, model and viewport | 1240 × 2689 | `describe_ontology` plus multiple generated `sparql_query` calls: the query path shows the actual `SELECT` statements, including a `FILTER NOT EXISTS` check for missing risk assessments and a `GROUP BY` aggregation. |
| `decision-layer-before-page.png` | `main` at `0474f89` (1.8), before the 1.9 decision-layer branch; rules-mode server on `127.0.0.1:8013` | 1440 × 1000 | Baseline hero: 294 classes, 40,574 triples, 151 rules, 147 concepts; version v1.8.0. |
| `decision-layer-after-page.png` | 1.9 ticket branch, same server settings on `127.0.0.1:8012` | 1440 × 1000 | Hero after the expansion: 337 classes, 44,372 triples, 161 rules, 173 concepts; version v1.9.0. |
| `decision-layer-before-graph.png` | Same baseline, “决策链” graph mode | 1440 × 1000 | Baseline decision chain: 19 curated classes. |
| `decision-layer-after-graph.png` | 1.9 branch, same graph mode, viewport and mouse position | 1440 × 1000 | Expanded decision chain: account, position state, risk budget, trade plan, sizing, order intent, execution quality, outcome, review and rule revision nodes around the same decision core. |
| `decision-layer-before-agent.png` | Same baseline, rules mode, question “华辰智造的买点、卖点和仓位限制是什么？” | 1240 × 1062 | Baseline: the question is treated as ordinary company analysis; R06 is reported but there is no account, risk-budget, sizing or buy/sell limit answer. |
| `decision-layer-after-agent.png` | 1.9 branch, same rules-mode server, question, viewport and scroll position | 1240 × 1062 | `evaluate_trade` reads the account, position, 77.5% risk-budget utilization, 10% single-name cap and blocked entry plan; shows the buy/sell limits and approval gate. |
| `decision-layer-after-review.png` | Same 1.9 answer, scrolled to the bottom | 1240 × 1062 | Closed loop: 12 bps slippage, 15.8% realized return, PROCESS_IMPROVE review, recurring finding and rule revision RR-2026-001; query path shows R152–R161. |
| `cognition-before.png` | `main` at `2472cbb` (1.9), before the 1.10 cognition branch; static page on `127.0.0.1:8013` | 1440 × 1000 | Baseline hero: 337 classes, 44,372 triples, 161 rules, 173 concepts; version v1.9.0; 6 ODRL policies. |
| `cognition-after.png` | 1.10 ticket branch, same page, viewport and theme on `127.0.0.1:8014` | 1440 × 1000 | Hero after the expansion: 363 classes, 47,958 triples, 169 rules, 225 concepts; version v1.10.0; 7 ODRL policies. |
| `cognition-explorer-after.png` | 1.10 ticket branch, Explorer opened at `#entity=class:MarketCognition`, same viewport | 1440 × 1000 | The new `市场认知 Market Cognition` class detail: definition, superclass, OWL restrictions (data date, summary, regime) and the 4,058-entity browser. |

The `agent-before.png` baseline is a real capture of the deployed site before this ticket's UI change,
not a mockup. Most after captures use the actual FastAPI backend and the real `index.html`; no LLM
provider key was configured for those, so they show the deterministic **rules mode**. LLM mode and
the tool loop are covered by `tests/test_llm.py` with a local OpenAI-compatible stub.

The `open-query-*` pair is a live LLM comparison: the baseline worktree is `main` at `9530cab`
served on `127.0.0.1:8023`, and the after capture is this ticket branch served on
`127.0.0.1:8022`. Both used the same git-ignored provider config (`deepseek-flash`), question,
1240 × 1000 viewport and `AGENT_MAX_STEPS=6`; `.agent-log` was expanded and the sticky header hidden
on both sides. The baseline has no graph-query tool, so it can only chain fixed tools
(`trace_evidence` per company); the after agent calls `describe_ontology` and then generates
`sparql_query` statements that appear in the query-path panel. The provider key is not committed and
does not appear in the captures.

The `decision-layer-*` pair uses the same rules-mode server settings (`MARKET_DATA_ENABLED=false`,
no LLM key): the baseline is a detached worktree at `0474f89` served on `127.0.0.1:8013`, and the
after captures are the ticket branch on `127.0.0.1:8012`. The page and graph shots use the same
1440 × 1000 viewport and mouse position; the Agent shots use the same 1240 × 1062 section capture and
question, with the log scrolled to the top on both sides. The `decision-layer-after-review.png`
additionally shows the review/rule-revision tail of the same answer.

The `query-*`, `evidence-*`, `constraints-*` and `scenario-*` pairs use the same rules-mode server
settings (`MARKET_DATA_ENABLED=false`, no LLM key): the baseline worktree is `main` at `1a25a68`
before this ticket, and the after captures are from the ticket branch served on
`127.0.0.1:8020`. To show the complete conversation, the `.agent-log` was expanded to full height and
the sticky header was hidden for these screenshots; both sides of each pair use the same viewport,
question and treatment. The baseline is a real capture of the previous implementation, not a mockup.

The page was served by `uvicorn server.main:app`; screenshots were taken with Playwright/Chromium (the cognition pair uses the bundled Firefox headless CLI).
All example content is synthetic; the `real-data-*` pair additionally shows a live public-data query
against Eastmoney's anonymous JSON endpoints. The `trace-*` pair uses the same rules-mode scenario
(before/after the change) and the same 1440 × 1000 viewport; `trace-after-detail.png` is a close-up
of the changed panel. LLM-mode trace rendering was checked in Chromium against a stubbed
`/api/agent/analyze` response for the rules-mode pairs; the `open-query-*` pair was captured against
the live provider. See the repository README for the disclaimer.

The `cognition-*` pair uses the same static page and 1440 × 1000 viewport: the baseline is the `main` worktree at `2472cbb` before this ticket, and the after capture is the ticket branch. Both were served by `python3 -m http.server` and rendered with the bundled Firefox headless CLI; the intended difference is the regenerated `assets/js/data.js` snapshot and the version badge; `cognition-explorer-after.png` additionally opens the new `MarketCognition` class in the Explorer.
