# Four-agent orchestration

`inventorypulse.agentic.build_workflow` creates four Microsoft Agent Framework `Agent` instances in typed `Executor` nodes connected by `WorkflowBuilder`: retrieval → SKU matching → E&O calculation → recommendation.

Each agent invokes only its bounded deterministic stage tool. Retrieval returns three scalar fields (disposition, reason_code, rationale); its receipt and sources are attached by code. Subsequent agents return a validated Assessment acknowledging their exact receipt and source citations. A skipped tool, changed receipt, bad citation, timeout or invalid response stops execution. SKU suggestions and review requests stop downstream stages; suggestions never mutate the accepted crosswalk. Complete runs await the existing human approval API/CLI; agents have no approval or ERP execution tool.

`inventorypulse.engine.Analysis` exposes separate stage methods, reused by the offline `run_pack` baseline. It does not execute the whole pipeline behind each agent. Agents never receive offline expected-match labels. Each workflow invocation uses a distinct ID; tool retries within that invocation are idempotent. Do not reuse a Runtime across concurrent sessions.

Fabric integration is a published Data Agent MCP retrieval tool with Entra credentials, running from `fabric/agentic.ipynb`. Azure OpenAI clients can use separately configured managed identities; actual Entra Agent ID/permission bindings and Agent 365 traces must be verified in the tenant. Logical `maf:*` IDs and mocked model tests do not establish governed cloud identities.

Supplier extraction (`extract-suppliers`) uses a structured-output agent over the 50 Markdown documents. It frames each product section, asks the model for nine scalar fields, and attaches verbatim evidence, unit counts and hashes in code, then `agentic-run --supplier-extraction ... --supplier-documents ...` can enrich missing product identity by supplier name and SKU. Changed sources, duplicate vendor keys or conflicting identities block ingestion. Catalogue prices and availability never become our inventory quantities or costs. Plant records must already use a consistent currency and base unit.
