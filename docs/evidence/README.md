# Visual evidence

These captures document the browser work for the A-share ontology tickets.

| File | Revision / state | Viewport | What it shows |
| --- | --- | --- | --- |
| `before.png` | Initial branch `92d2b75` (repository had only `README.md`) | 1440 × 1000 | The root route served a directory listing; no ontology viewer existed. |
| `after.png` | Head of `agent/a-share-ontology-a9c9d9ebdae6` | 1440 × 1000 | The ontology browser: hero, decision object, seven-layer navigation, scale metrics. |
| `after-explorer.png` | Same branch | 1440 × 1000 | Search for `InvestmentDecision`, filtered result, and the entity inspector with OWL restrictions. |
| `agent-before.png` | Live GitHub Pages at `83f4493` (before the Agent UI) | 1440 × 1000 | Baseline: nav has no Agent entry and the hero has no “问 Agent” action. |
| `agent-after.png` | Agent branch head, served by `uvicorn` on `127.0.0.1:8010` | 1440 × 1000 | Same hero with the new Agent nav entry and “问 Agent” action. |
| `agent-section.png` | Same agent branch head; rules mode, no server key | 1240 × 941 | New Agent section: status, starter questions, key-safety note, empty conversation. |
| `agent-answer.png` | Same agent branch head; question “分析华辰智造” | 1240 × 1061 | Summary card, ontology-grounded answer, R01/R06/R08 signals, decision chain and citations. |
| `agent-summary.png` | Same state | 808 × 76 | Close-up of the structured conclusion card. |
| `agent-mobile.png` | Same agent branch head; 390 px viewport | 390 × 1289 | Responsive Agent layout with no horizontal overflow. |

The `agent-before.png` baseline is a real capture of the deployed site before this ticket's UI change,
not a mockup. The after captures use the actual FastAPI backend and the real `index.html`; no LLM
provider key was configured, so the screenshots show the deterministic **rules mode**. LLM mode and
the tool loop are covered by `tests/test_llm.py` with a local OpenAI-compatible stub.

The page was served by `uvicorn server.main:app`; screenshots were taken with Puppeteer/Chromium.
All example content is synthetic; see the repository README for the disclaimer.
