"""Real Microsoft Agent Framework graph and tool loop; only the model transport is simulated."""

import asyncio
import json
from datetime import date

import pytest
from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message

from inventorypulse.agentic import Runtime, build_workflow, digest, run_workflow
from inventorypulse.sample import generate


class SimulatedModel(FunctionInvocationLayer, BaseChatClient):
    def __init__(self, role, *, review=False, fabricate=False, skip_tool=False, suggest=False):
        super().__init__()
        self.role, self.review, self.fabricate = role, review, fabricate
        self.skip_tool, self.suggest = skip_tool, suggest
        self.calls = 0

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.calls += 1
        results = [c for m in messages for c in m.contents if c.type == "function_result"]
        if not results and not self.skip_tool:
            return ChatResponse(
                messages=Message(
                    "assistant",
                    [
                        Content(
                            "function_call",
                            call_id=f"call-{self.role}",
                            name=f"run_{self.role.replace('-', '_')}",
                            arguments="{}",
                        )
                    ],
                )
            )
        if results:
            receipt = results[-1].result
            if isinstance(receipt, list):
                receipt = "".join(c.text for c in receipt if c.type == "text")
            if isinstance(receipt, str):
                receipt = json.loads(receipt)
            # SDK function results wrap strings as Content text on some transport versions.
            if isinstance(receipt, dict) and "receipt" not in receipt and "text" in receipt:
                receipt = json.loads(receipt["text"])
        else:
            receipt = {"receipt": "0" * 64, "handoff": {"source_references": ["invented"]}}
        if self.skip_tool:
            assessment = {"reason_code": "ready", "rationale": "Skipped tool"}
        else:
            if self.role == "retrieval":
                code = (
                    "no_usable_data"
                    if receipt["accepted_records"] == 0
                    else "partial_scope"
                    if receipt["quarantined_records"]
                    else "ready"
                )
            elif self.role == "sku-matching":
                code = (
                    "unresolved_identity"
                    if receipt["unresolved_records"]
                    else "no_matched_data"
                    if not receipt["matched_records"]
                    else "ready"
                )
            elif self.role == "eo-calculation":
                code = (
                    "no_positions"
                    if not receipt["positions_count"]
                    else "baseline_not_comparable"
                    if not receipt["baseline_comparable"]
                    else "reconciliation_difference"
                    if receipt["absolute_variance"] not in ("0", "0.00")
                    else "ready"
                )
            else:
                code = (
                    "approval_boundary_violation"
                    if receipt["nonpending_proposals"] or receipt["realized_before_execution"]
                    else "ready_for_approval"
                    if receipt["proposal_count"]
                    else "no_action_required"
                )
            assessment = dict(reason_code=code, rationale="Simulated stage decision; not live model evidence")
        if self.fabricate:
            assessment["receipt"] = "0" * 64
        if self.suggest:
            assessment["match_suggestions"] = [{"canonical_sku": "INVENTED"}]
        return ChatResponse(messages=Message("assistant", [json.dumps(assessment)]))


@pytest.fixture
def runtime(tmp_path):
    pack = tmp_path / "pack"
    generate(pack, include_exceptions=False)
    return Runtime(data=pack, cutoff=date(2026, 10, 31), provider="simulated_model")


def test_real_maf_graph_four_tool_calling_agents(runtime):
    clients = {}

    def factory(role):
        clients[role] = SimulatedModel(role)
        return clients[role]

    outcome = asyncio.run(run_workflow(runtime, factory))
    assert outcome.status == "awaiting_human_approval"
    assert list(runtime.receipts) == ["retrieval", "sku-matching", "eo-calculation", "recommendation"]
    assert all(c.calls == 2 for c in clients.values())
    run = runtime.final_run()
    assert outcome.run_id == run["run_id"]
    assert len(run["agent_framework"]["agent_assessments"]) == 4
    assert all(h["run_id"] == run["run_id"] for h in run["handoffs"])
    assert all(r["approval_state"] == "pending" for r in run["recommendations"])
    assert run["summary"]["realized_cash"] == 0
    for receipt in runtime.receipts.values():
        assert receipt["receipt"] == digest(receipt["handoff"])
    assert "examples" not in runtime.receipts["sku-matching"]["handoff"]["payload"]["scorecard"]


def test_review_request_stops_downstream_tools(runtime):
    generate(runtime.data, include_exceptions=True)
    outcome = asyncio.run(
        run_workflow(runtime, lambda role: SimulatedModel(role, review=role == "sku-matching"))
    )
    assert outcome.status == "review_required"
    assert list(runtime.receipts) == ["retrieval", "sku-matching"]
    assert runtime.analysis.phase == 2
    with pytest.raises(ValueError, match="not complete"):
        runtime.final_run()


def test_agent_cannot_skip_tools_or_fabricate_receipts(runtime):
    for mode in ("skip_tool", "fabricate"):
        with pytest.raises(Exception):
            asyncio.run(run_workflow(runtime, lambda role: SimulatedModel(role, **{mode: True})))
        assert len(runtime.trace) == 0


def test_model_cannot_generate_match_suggestions_outside_its_flat_contract(runtime):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        asyncio.run(run_workflow(runtime, lambda role: SimulatedModel(role, suggest=role == "sku-matching")))
    assert runtime.analysis.phase == 2
    assert len(runtime.trace) == 1


def test_stage_tool_retries_are_idempotent_and_out_of_order_calls_fail(runtime):
    async def scenario():
        with pytest.raises(ValueError, match="order"):
            await runtime.execute("recommendation")
        first = await runtime.execute("retrieval")
        assert first == await runtime.execute("retrieval")
        assert runtime.analysis.phase == 1
        assert len(runtime.analysis.handoffs) == 1

    asyncio.run(scenario())


def test_supplier_document_read_scope_and_graph_build(runtime, tmp_path):
    docs = tmp_path / "suppliers"
    docs.mkdir()
    (docs / "allowed.md").write_text("# Synthetic offer")
    runtime.supplier_documents = docs
    assert list(runtime.documents()) == ["allowed.md"]
    build_workflow(runtime, lambda role: SimulatedModel(role))
    (docs / "escape.md").symlink_to(tmp_path / "outside.md")
    with pytest.raises(ValueError, match="escapes"):
        runtime.documents()


def test_fabric_failure_never_uses_local_sample_fallback(runtime, monkeypatch):
    import inventorypulse.fabric_mcp

    async def failing(*args, **kwargs):
        raise RuntimeError("Fabric MCP unavailable")

    monkeypatch.setattr(inventorypulse.fabric_mcp, "fetch_pack", failing)
    runtime.fabric_workspace = runtime.fabric_data_agent = "11111111-1111-1111-1111-111111111111"
    runtime.fabric_destination = runtime.data.parent / "remote"
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(runtime.execute("retrieval"))
    assert runtime.analysis is None and not runtime.receipts
