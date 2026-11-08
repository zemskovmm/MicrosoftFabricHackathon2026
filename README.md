# InventoryPulse AI

A runnable inventory excess and obsolescence (E&O) demonstrator for **ZX Spectrum / EPAM Fabric Frontier Hackathon**. It implements the proposed workflow with reproducible synthetic data, deterministic financial calculations, a browser dashboard, an exception queue, and durable human decisions.

**Status:** local prototype implemented. Microsoft Fabric, Azure/Foundry model deployment, Entra Agent ID, Agent 365, Power BI, Activator and Teams have **not** been deployed or validated in a tenant. Deployment assets and a live Data Agent MCP client are included. Do not present local roles or exported reports as cloud integration evidence.

## Try it

Requires Python 3.11 or later (3.12 recommended).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,fabric,agentic]'
.venv/bin/inventorypulse run
.venv/bin/inventorypulse serve
```

Open **http://127.0.0.1:8000**. The terminal prints a temporary local approval key. Use it with your reviewer name and rationale to approve or reject a proposal. The server listens only on your computer. The key is not persisted. This is a local demonstration, not production authentication.

The committed sample pack uses **October 31, 2026** as a fixed, reproducible cutoff. It is deliberately not today's stock. To create another synthetic cutoff:

```sh
.venv/bin/inventorypulse sample --folder data/another-sample --as-of 2026-11-07
.venv/bin/inventorypulse run --data data/another-sample --as-of 2026-11-07
```

Run exports go to `output/<run_id>/`; local runs, decisions and hash-linked audit events persist in `output/inventorypulse.db` (excluded from Git). The dashboard reads live decision state. CLI `decide` refreshes exported files; browser decisions update the database, so use `/api/run` to retrieve the latest state rather than stale initial CSVs.

## What is built

- Four bounded local agents: validated retrieval, SKU reconciliation, daily E&O calculation, ranked recommendations.
- Source hashes, reproducible run IDs, versioned policy and schema-validated hand-offs.
- Normalized exact-ID and numeric-aware description matching, explicit abstention, crosswalk and labelled precision/recall.
- Decimal arithmetic, lifecycle/aging rules, deduplication, input quarantine, same-cutoff monthly reconciliation.
- Mutually exclusive disposition options; one final human decision per SKU per run; approved opportunity is separate from realized cash.
- Dashboard with positions, recommendations/approvals, scorecard, variance, exceptions, weekly role reports and audit evidence.
- CSV/JSON outputs, breach events and a Teams Adaptive Card sender (opt-in; no messages sent automatically).
- Entra-authenticated streamable HTTP client for a published Fabric Data Agent, importable Fabric notebook, Power BI measures and cloud deployment instructions.

`run` is the deterministic offline baseline. `agentic-run` executes four real Microsoft Agent Framework tool-calling agents with Azure OpenAI models; its transport is simulated only in tests. No live Microsoft tenant has been configured or validated here. Description matching is conservative and numeric/MPN-aware; model suggestions require human review. See [the concise agent hand-off](docs/agent-framework-handoff.md). See [deployment instructions](fabric/README.md) and [challenge evidence matrix](docs/acceptance.md).

## Run with local Ollama

The same four-agent graph supports a running local Ollama server; it does not download models or call Azure in local mode.

```sh
.venv/bin/python -m pip install -e '.[ollama,test]'
.venv/bin/inventorypulse sample --clean --folder output/ollama-clean
.venv/bin/inventorypulse --db output/ollama.db agentic-run --provider ollama --model llama3.1:8b --data output/ollama-clean
.venv/bin/inventorypulse --db output/ollama.db serve
```

Open http://127.0.0.1:8000. The model must already appear in Ollama's installed-model list. `--model` and `--ollama-url` override `OLLAMA_MODEL` / `OLLAMA_BASE_URL`; the defaults are `llama3.1:8b` and `http://127.0.0.1:11434`. Only loopback URLs are permitted. The native Ollama adapter separates model tool selection from schema-constrained final assessments. Receipts and citations are constrained to actual tool evidence, then validated by the unchanged workflow gate.

The clean sample is generated explicitly for the complete workflow demonstration. The default sample retains intentional bad records and may correctly stop for review. If any agent requests review, later stages are not executed and no completed run is saved. The 50 supplier files remain a separate extraction demo; this command exercises the 24-SKU arithmetic fixture.

The first-agent prompt and flat output contracts were tested against a real local `gpt-oss:latest` server. See [experiment results](docs/retrieval-gptoss-experiment.md). Stage decisions now have two scalar fields (reason_code and rationale); supplier offers have nine. Application-generated source evidence and collections are kept outside the required LLM response. [Isolated generalization tests](docs/agent-generalization-experiment.md) passed 15/15 stage holdout cases; supplier extraction passed 2/3 heldout documents, with one supplier qualifier omission left open rather than tuned on the holdout.

## Sample data and policy

`data/sample/` contains **24 canonical SKUs**, **48 separate warehouse holdings**, **five intentionally invalid/uncertain records**, and **50 labelled examples**. All records and economics are invented. Repeated global demand and safety stock values are checked for consistency rather than summed across warehouses. Holdings must represent distinct physical inventory, not mirrored ERP/WMS copies. One currency (illustrative USD) is assumed; mixed-currency data requires conversion before ingestion.

The default illustrative policy is a three-month demand horizon plus safety stock. Obsolete lifecycle stock is fully at risk; stock with no demand and no movement for 365 days is obsolete. Excess on remaining stock is `max(0, on_hand - obsolete - target)`. The policy does not cancel open purchase orders. Return, transfer, discount and scrap recovery rates and per-unit handling costs are assumptions, not achieved savings. Transfer value represents avoided/internal utilization cost, not cash proceeds. `realized_cash` remains zero.

Load an explicit policy with `run --policy policy.json`. Its full schema is in `contracts/Policy.json`.

## Fabric MCP retrieval

Install the `fabric` extra, authenticate through an approved Entra credential supported by `DefaultAzureCredential`, and publish a Data Agent scoped to approved tables. No tokens are saved by this application.

```sh
.venv/bin/inventorypulse fabric-fetch \
  --workspace WORKSPACE_UUID --data-agent DATA_AGENT_UUID \
  --as-of 2026-10-31 --destination output/fabric-pack
.venv/bin/inventorypulse run --data output/fabric-pack --as-of 2026-10-31
```

The client performs initialization, discovers the published tool and validates the returned JSON. It fails on authentication errors, invalid schemas, empty datasets or mismatched cutoffs. A language-model answer can still omit or misstate data: independently reconcile row counts/totals to source SQL before relying on it. Use deterministic Lakehouse ingestion for large production datasets.

## Verification

Future planning: [SKU detection improvements](docs/architecture.md#future-improvements-sku-detection-and-reconciliation) covers evaluating regular expressions and conditional random fields (CRF), with held-out validation before adoption. This is future work and is not implemented in the MVP.

```sh
.venv/bin/ruff check inventorypulse tests
.venv/bin/pytest -q
.venv/bin/inventorypulse run
```

GitHub Actions repeats these checks on Python 3.12. Tests cover the full synthetic scenario, invalid data, duplicate and conflicting holdings, ambiguous matching, reconciliation boundaries, financial aggregation, approval durability, concurrent decisions, audit hashes and API access. Cloud verification is separate and remains pending.

## Repository map

- `inventorypulse/`: analysis agents, API, dashboard, CLI, MCP client, delivery adapter and local audit store.
- `contracts/`: generated JSON schemas for public inputs, hand-offs and decisions.
- `data/sample/`: reproducible synthetic inventory pack.
- `fabric/`: notebook, Power BI measures and tenant setup instructions.
- `agents/`: bounded roles and orchestration contracts.
- `.idd/intent/`: durable observable requirements derived from the proposed blueprint.
- `docs/`: architecture, acceptance evidence and demo guide.

The local approval key and self-declared reviewer names are for demonstration only. Real service deployment requires Entra authentication, durable managed storage, authenticated approval owners, isolated roles, managed secrets, cloud audit and verified retention/access policy. The local SQLite chain detects casual event changes but is not tamper-proof against an administrator rewriting the database.
