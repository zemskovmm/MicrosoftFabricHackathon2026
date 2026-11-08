# Connected local supplier-to-approval demonstration

On 2026-11-08, one fresh live run passed with installed `gpt-oss:latest` through loopback Ollama 0.40.15 and the real Microsoft Agent Framework graph. No agents were replaced. The selected model digest is `f38aa0c53da5f8c49d08c43a99df24ff53167fe68e24664a7777288e7656fdfe`. [Compact results and fingerprints](experiments/connected-demo-results.json) identify the original raw artifacts under `output/connected-demo/20261108T102736Z-7dbd9c11/` (ignored local evidence, retained on this machine).

This is a bounded representative demonstration of known fixtures, **not an independent holdout** or business-owner validation. The historical experiments and their failures remain unchanged. Cloud governance, tenant identities, Fabric MCP, Agent 365, Power BI and delivery channels were not exercised or verified.

## Observed evidence

| Operation | Actual model calls | Result |
| --- | ---: | --- |
| Extract table, product cards and numbered offers | 6 | All six offers passed exact supplier/SKU/manufacturer/MPN/unit/price/currency oracle checks; pack counts and source quotations attached by code |
| Retrieval → SKU Matching → E&O Calculation → Recommendation | 8 | Four ordered tool calls and four model assessments; `awaiting_human_approval` |
| Separate all-stale input through the same full graph | 2 | `review_required` at Retrieval; no later stage receipts, recommendations or saved completed run |

Before inference, the runner freezes original supplier documents, separate synthetic inventory, master, labels, baseline, policy, application sources, runner and prompt text. SHA-256 manifests link these inputs to final artifacts. `calls.json` contains actual requests, final replies, tool calls/results, timestamps and elapsed times; hidden reasoning is removed. `operations.json` and runtime snapshots preserve progress, including failures. There are no automatic retries or fallback models. A new invocation creates a unique directory; a failed inference returns failure and retains its original diagnosis. If an operator chooses another run after a failure, preserve the failed directory and document the reason and original path; do not overwrite it or describe the second run as the original attempt.

The accepted-scope graph uses exact supplier/source-SKU references to enrich four distinct physical holdings: two bearing holdings (120 + 80 each), one belt holding and one obsolete CPU holding. A fifth, stale 999-unit holding is quarantined. Retrieval explicitly returns `partial_scope`; its rationale limits continuation to accepted rows. All position source references connect inventory rows to original supplier sections. Catalogue prices and availability never supply inventory costs or stock quantities.

The invented EUR economics are deliberately simple: bearings have 200 units, target 70 and excess 130 × €12 = €1,560; belts have 50 units, target 20 and excess 30 × €20 = €600; the obsolete CPU has 10 × €100 = €1,000. Total E&O is €3,160. The same-cutoff invented baseline agrees exactly. Recommendations offer mutually exclusive alternatives, with €2,516 estimated recovery counted from the highest-ranked option per SKU. These are illustrative assumptions, not savings or a customer opportunity claim.

`before-approval.json` preserves pending proposals. The existing `Store.decide` human-decision interface then records one **SIMULATED-DEMO-REVIEWER** decision for the bearing supplier-return proposal (€1,196). This is a labelled simulated reviewer, not a model approval, customer approval or impersonation of the user. Reopening SQLite verifies the decision persists, alternative options become not selected, and duplicate and alternative final decisions are rejected without changing state or totals. Realized cash stays €0; no ERP action occurs.

`audit-before-approval.json` and `audit-after-simulated-approval.json` preserve the audit export before/after that decision. The store records four ordered handoffs, then four ordered model assessments when saving the completed run, then the simulated reviewer event. This is the store's persistence order, not a claim that model assessments happened after all stages in wall-clock execution. The runner verifies nine sequential SHA-256-linked events, assessment role order and reviewer identity. Runtime receipts and HTTP evidence retain the actual graph execution order.

## Reproduce locally

With dependencies already installed and an installed model served by Ollama at `http://127.0.0.1:11434`:

```sh
.venv/bin/python scripts/connected_demo_experiment.py --model gpt-oss:latest
.venv/bin/pytest -q tests/test_connected_demo.py
```

The runner creates `output/connected-demo/<UTC timestamp>-<unique suffix>/`, prints the result and exits nonzero on material failure. `--output-parent` chooses another parent; `--model llama3.1:8b` explicitly selects the other installed model but is not claimed as live-verified by this experiment. No model download, tenant call or external action is performed.

The four focused tests use an explicitly labelled simulated HTTP transport with the real extraction/parser/framework/store interfaces. They check connected persistence and stop behavior, hidden-reasoning exclusion, audit/input tamper detection, immutable output directories, retained transport failure with no retry, and contradictory readiness rejection without later stages or saved output. These tests are separate from the 16 live inference calls above. All 36 repository tests and lint passed after this change.
