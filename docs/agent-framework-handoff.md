# InventoryPulse: Microsoft Agent Framework hand-off

## Implementation

- `inventorypulse/agentic.py`: four `Agent` instances in a typed `WorkflowBuilder` graph: retrieval → SKU matching → deterministic E&O → recommendations.
- `inventorypulse/engine.py`: independent stage tools; decimal arithmetic, quarantine, same-cutoff reconciliation and pending proposals.
- `inventorypulse/supplier_ingestion.py`: structured extraction of the 50 Markdown supplier documents; verbatim quotes, SKU/identity validation and source hashes. Supplier data is not plant inventory.
- `inventorypulse/fabric_mcp.py`: published Fabric Data Agent MCP handshake and Entra-authenticated retrieval; remote failure stops execution.
- `fabric/agentic.ipynb`: Fabric Spark notebook entry point; writes workflow evidence to OneLake and Delta tables.
- Existing approval API/CLI persists human decisions; no agent can approve or execute an ERP action.

## Run

```sh
python -m pip install -e '.[agentic,test]'
# Configure AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_CHAT_DEPLOYMENT_NAME and Entra credentials.
inventorypulse extract-suppliers --documents data/vendor-documents --destination output/supplier-offers.json
inventorypulse agentic-run --data data/sample --as-of 2026-10-31
# Fabric retrieval replaces --data; destination must not exist:
inventorypulse agentic-run --workspace WORKSPACE_UUID --data-agent DATA_AGENT_UUID \
  --destination output/fabric-pack --as-of 2026-10-31
```

Use `--supplier-extraction output/supplier-offers.json --supplier-documents data/vendor-documents` to enrich a corresponding plant pack. Plant `supplier_name` + `source_sku` must match extraction keys. Generic `data/sample` is an independent arithmetic fixture, not corresponding plant inventory for the 50 vendor files. Separate plant stock, demand, unit costs, open POs and legacy baseline are required for real E&O. Supplier prices are not copied into inventory costs; a 5 kg can is not five units.

Configure optional per-role managed identity client IDs and actual Entra Agent IDs using `.env.example`. The CLI reads the process environment; it does not load `.env` automatically. Logical role IDs are used otherwise. Identity configuration is not proof of tenant permission enforcement.

Outcomes: `review_required` stops the graph; `awaiting_human_approval` saves the completed analysis in `output/<run_id>/`. Inspect `agent-outcome.json`, `run.json` and per-tool receipts. Sources, policy, execution ID and provider are bound to run identity. Receipts validate the authoritative stage payload; model prose never overwrites financial results.

## Verification / remaining deployment

Local tests use the actual Microsoft Agent Framework graph and function-calling loop with a simulated model transport. No live Azure model, Fabric MCP, governed Entra identity, Agent 365, Power BI, Activator or Teams deployment has been verified. Supply licensed tenant resources and capture live evidence separately. Dependencies pinned: `agent-framework-core==1.24.0`, `agent-framework-openai==1.18.0`.

## Primary references

- [Microsoft Agent Framework: agents in workflows](https://github.com/microsoft/agent-framework/blob/main/python/samples/03-workflows/agents/custom_agent_executors.py)
- [Structured agent outputs](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs)
- [Published Fabric Data Agent MCP](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-mcp-server)
