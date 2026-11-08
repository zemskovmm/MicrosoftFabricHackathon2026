"""Simulated HTTP transport tests only; these are not live inference evidence."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.connected_demo_experiment import (
    DOCUMENTS,
    REPO,
    execute,
    prepare,
    validate_audit,
    verify_frozen,
)
from scripts.retrieval_experiment import document_gold


def simulated_transport(*, fail=False, contradictory=False):
    offers = []
    for name in DOCUMENTS:
        supplier, rows = document_gold((REPO / 'data/vendor-documents' / name).read_text())
        offers.extend((supplier, row) for row in rows)

    def respond(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'test-model', 'digest': 'simulated-digest'}]})
        if request.url.path == '/api/version':
            return httpx.Response(200, json={'version': 'SIMULATED'})
        if fail:
            raise httpx.ReadTimeout('Simulated inference transport failure', request=request)
        payload = json.loads(request.content)
        if 'tools' in payload:
            stage = next(t['function']['name'] for t in payload['tools'] if t['function']['name'].startswith('run_'))
            message = {'content': '', 'tool_calls': [{'function': {'name': stage, 'arguments': {}}}]}
        elif 'supplier_name' in payload['format']['properties']:
            prompt = json.loads(payload['messages'][-1]['content'])
            supplier, row = next((s, r) for s, r in offers if r['source_sku'] in prompt['product_text'])
            extracted = {k: v for k, v in row.items() if k != 'pack_count'}
            message = {'content': json.dumps(dict(supplier_name=supplier, description='Synthetic product',
                                                  warning='', **extracted))}
        else:
            facts = json.loads(next(m['content'] for m in reversed(payload['messages']) if m['role'] == 'tool'))
            if 'accepted_records' in facts:
                reason = 'no_usable_data' if facts['accepted_records'] == 0 else 'partial_scope'
                if contradictory:
                    reason = 'ready'
            elif 'proposal_count' in facts:
                reason = 'ready_for_approval'
            else:
                reason = 'ready'
            message = {'content': json.dumps(dict(reason_code=reason, rationale='Simulated transport assessment'))}
        # Hidden reasoning must never be retained in evidence.
        message['thinking'] = 'SIMULATED-HIDDEN-REASONING-SENTINEL'
        return httpx.Response(200, json={'done': True, 'done_reason': 'stop', 'message': message})

    return httpx.MockTransport(respond)


def test_simulated_connected_evidence_persistence_and_stop(tmp_path):
    root = tmp_path / 'run'
    result = asyncio.run(execute(root, 'test-model', transport=simulated_transport()))
    assert result['passed'], result.get('error')
    assert result['evidence_kind'] == 'simulated HTTP transport test'
    assert result['completed']['audit_events'] == 9
    assert result['completed']['duplicate_decisions_rejected'] == 2
    assert result['stopped']['stages_executed'] == ['retrieval']
    assert 'SIMULATED-HIDDEN-REASONING-SENTINEL' not in (root / 'calls.json').read_text()
    frozen = json.loads((root / 'frozen-manifest.json').read_text())
    calls = json.loads((root / 'calls.json').read_text())
    assert frozen['frozen_at'] < calls[0]['started_at']
    assert all(c['seconds'] >= 0 for c in calls)
    events = json.loads((root / 'audit-after-simulated-approval.json').read_text())
    events[0]['event']['status'] = 'tampered'
    with pytest.raises(ValueError, match='hash'):
        validate_audit(events)
    with pytest.raises(FileExistsError):
        asyncio.run(execute(root, 'test-model', transport=simulated_transport()))


def test_simulated_failure_preserves_original_attempt_and_frozen_inputs(tmp_path):
    root = tmp_path / 'failed'
    result = asyncio.run(execute(root, 'test-model', transport=simulated_transport(fail=True)))
    assert not result['passed'] and 'Simulated inference transport failure' in result['error']
    calls = json.loads((root / 'calls.json').read_text())
    assert len(calls) == 1  # No retry or replacement model.
    assert not (root / 'store.sqlite3').exists()
    assert (root / 'inputs/accepted_scope/legacy_baseline.json').exists()
    assert (root / 'artifact-manifest.json').exists()
    assert result['operations'][0]['passed'] is False


def test_simulated_contradictory_readiness_cannot_save_or_advance(tmp_path):
    root = tmp_path / 'contradiction'
    result = asyncio.run(execute(root, 'test-model', transport=simulated_transport(contradictory=True)))
    assert not result['passed'] and 'contradicts' in result['error']
    runtime = json.loads((root / 'accepted_scope-runtime.json').read_text())
    assert list(runtime['receipts']) == ['retrieval'] and runtime['phase'] == 1
    assert not (root / 'store.sqlite3').exists()
    assert not (root / 'stop_for_review-outcome.json').exists()


def test_frozen_inputs_detect_mutation(tmp_path):
    frozen = prepare(tmp_path)
    (tmp_path / 'inputs/policy.json').write_text('{}')
    with pytest.raises(ValueError, match='Frozen'):
        verify_frozen(tmp_path, frozen)
