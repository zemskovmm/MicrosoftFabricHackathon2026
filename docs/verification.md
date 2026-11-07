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
