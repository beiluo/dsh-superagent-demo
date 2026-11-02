# Visual evidence

These captures document the browser work for the A-share ontology ticket.

| File | Revision / state | Viewport | What it shows |
| --- | --- | --- | --- |
| `before.png` | Initial branch `92d2b75` (repository had only `README.md`) | 1440 × 1000 | The root route served a directory listing; no ontology viewer existed. |
| `after.png` | Head of `agent/a-share-ontology-a9c9d9ebdae6` | 1440 × 1000 | The new browser: hero, decision object, seven-layer navigation, scale metrics. |
| `after-explorer.png` | Same branch | 1440 × 1000 | Search for `InvestmentDecision`, filtered result, and the entity inspector with OWL restrictions. |
| `after-graph.png` | Same branch | 1440 × 1000 | Domain overview graph: 72 class nodes, 96 hierarchy/property edges, cluster legend and scale assessment. |
| `after-graph-decision.png` | Same branch | 1440 × 1000 | Decision-chain graph: 19 nodes, 15 labelled object-property edges. |

The baseline is a real capture of the repository before the page existed, not a mockup. The page was
served with `python3 -m http.server 8000`; screenshots were taken with Playwright/Firefox. All example
content is synthetic; see the repository README for the disclaimer.
