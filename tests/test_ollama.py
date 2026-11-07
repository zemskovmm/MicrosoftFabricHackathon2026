import asyncio
import json
from datetime import date

import httpx
import pytest

from inventorypulse.agentic import Runtime, run_workflow
from inventorypulse.engine import AGENTS
from inventorypulse.ollama_clients import OllamaChatClient
from inventorypulse.sample import generate


def test_ollama_transport_runs_real_maf_tool_loop_and_structured_final(tmp_path):
    pack = tmp_path / "clean"
    generate(pack, include_exceptions=False)
    requests = []

    def transport_for(role):
        def respond(request):
            payload = json.loads(request.content)
            requests.append((role, payload))
            if "tools" in payload:
                assert "format" not in payload
                message = {
                    "content": "",
                    "tool_calls": [{"function": {"name": f"run_{role.replace('-', '_')}", "arguments": {}}}],
                }
            else:
                assert payload["format"]["type"] == "object"
                receipt = json.loads(
                    next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool")
                )
                if role == "retrieval":
                    assessment = dict(
                        disposition="proceed", reason_code="ready", rationale="Test transport only"
                    )
                    assert "handoff" not in receipt
                    assert all(not isinstance(v, (list, dict)) for v in receipt.values())
                else:
                    assessment = dict(
                        receipt=receipt["receipt"],
                        disposition="proceed",
                        rationale="Test transport only",
                        citations=receipt["handoff"]["source_references"][:1],
                        match_suggestions=[],
                    )
                message = {"content": json.dumps(assessment)}
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": message})

        return httpx.MockTransport(respond)

    async def scenario():
        clients = {role: OllamaChatClient("test-model", transport=transport_for(role)) for role in AGENTS}
        try:
            runtime = Runtime(data=pack, cutoff=date(2026, 10, 31), provider="ollama:test-model")
            outcome = await run_workflow(runtime, clients.__getitem__)
            assert outcome.status == "awaiting_human_approval"
            assert runtime.final_run()["agent_framework"]["provider"] == "ollama:test-model"
            assert len(runtime.trace) == 4
        finally:
            for client in clients.values():
                await client.close()

    asyncio.run(scenario())
    assert len(requests) == 8
    assert all(p["model"] == "test-model" and p["options"]["num_ctx"] == 16384 for _, p in requests)


def test_ollama_rejects_remote_endpoint():
    with pytest.raises(ValueError, match="loopback"):
        OllamaChatClient("llama3.1:8b", "https://remote.example")


def test_ollama_rejects_truncated_response():
    def truncated(request):
        return httpx.Response(200, json={"done": True, "done_reason": "length", "message": {"content": "{}"}})

    async def scenario():
        client = OllamaChatClient("test-model", transport=httpx.MockTransport(truncated))
        try:
            with pytest.raises(ValueError, match="incomplete"):
                await client._inner_get_response(messages=[], stream=False, options={})
        finally:
            await client.close()

    asyncio.run(scenario())
