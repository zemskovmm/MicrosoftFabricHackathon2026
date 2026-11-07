# Verification evidence — November 7, 2026

Scope: InventoryPulse four-agent Microsoft Agent Framework graph, supplier document ingestion, deterministic calculations and existing approval boundary (IDD-0001).

- Ruff: passed.
- Pytest: 24 passed. Microsoft Agent Framework graph/Agent/tool loop and Ollama transport checks; automated model transport simulated. A separate live local run completed with llama3.1:8b on November 7, 2026: all four agents, awaiting_human_approval, run c97c9be2440efcfbd189092c.
- Offline end-to-end calculation: passed; 24 analysed SKUs, five quarantined records, same-cutoff synthetic baseline reconciled.
- Dataset: 50 supplier Markdown files across three formats and three product categories.
- Package dependency consistency: passed.
- Live local Ollama: initial invalid-input sample stopped for review; explicitly clean 24-SKU synthetic sample completed all four model agents. No Azure model calls were used.
- Cloud verification: not performed; requires configured Azure OpenAI deployment, published Fabric Data Agent, licensed Fabric environment and authorized Entra credentials.
- Separate Entra identities, Agent 365 audit, Power BI, Activator and Teams delivery: not verified in a tenant.

Focused intent review: the implemented graph enforces stage order, source citations, exact tool receipts and human-only decisions. SKU suggestions stop for human review. Local evidence matches these contracts; live deployment acceptance remains unverified. No `.idd/engineering/` layer is present.

## First-agent GPT-OSS experiment

Real local gpt-oss:latest experiment: six readiness runs passed; all 50 supplier documents (100 offers) processed, four model-field failures corrected and rechecked within seven document rechecks; one injected-instruction document and a two-holding vendor-linked retrieval check passed. See `retrieval-gptoss-experiment.md` and `experiments/retrieval-gptoss-results.json` for exact scope and assembly history. Retrieval LLM output now has three scalar fields; per-offer LLM extraction has nine. Application evidence/collections remain separate. Regression suite: 30 passed.

## Isolated-agent generalization experiment

Each of the four agents was tested separately on local gpt-oss:latest, with deterministic prerequisites and fresh model contexts. After 10/10 development checks, frozen prompts/code passed 15/15 first-pass heldout stage cases. Separate supplier extraction passed 2/3 disjoint heldout documents; a dropped regional qualifier in supplier_name remains open and was not fixed against the revealed holdout. See `agent-generalization-experiment.md`. Current stage LLM responses have two scalar fields; regression suite: 32 passed.
