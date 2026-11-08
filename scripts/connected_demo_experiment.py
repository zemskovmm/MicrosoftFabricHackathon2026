"""Frozen connected demonstration; live loopback inference, never a holdout or customer approval."""

import argparse
import asyncio
import csv
import hashlib
import json
import shutil
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inventorypulse.agentic import Runtime, role_instructions, run_workflow
from inventorypulse.engine import AGENTS
from inventorypulse.models import Decision, Policy
from inventorypulse.ollama_clients import OllamaChatClient
from inventorypulse.store import Store
from inventorypulse.supplier_ingestion import EXTRACTION_INSTRUCTIONS, extract_documents
from scripts.retrieval_experiment import document_gold

REPO = Path(__file__).resolve().parents[1]
CUTOFF = date(2026, 10, 31)
DOCUMENTS = ('001-table-01.md', '002-card-01.md', '003-quote-01.md')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(root):
    """Freeze all demonstration inputs and evaluation oracle before any model request."""
    documents = root / 'inputs/documents'
    documents.mkdir(parents=True)
    oracle, masters = [], []
    identities = [
        ('BEARING', 'SKF', '6205-2RSH', 'active'),
        ('BELT', 'Gates', '500-5M-15', 'active'),
        ('CPU', 'Siemens', '6ES7214-1AG40-0XB0', 'obsolete'),
    ]
    for name, (sku, maker, mpn, lifecycle) in zip(DOCUMENTS, identities):
        shutil.copy2(REPO / 'data/vendor-documents' / name, documents / name)
        supplier, offers = document_gold((documents / name).read_text())
        oracle.append(dict(document_id=name, supplier_name=supplier, offers=offers))
        masters.append(dict(canonical_sku=sku, description=f'{maker} {mpn}', manufacturer=maker,
                            manufacturer_part_number=mpn, lifecycle=lifecycle,
                            returnable=True, transferable=True))
    rows = []
    for i, (doc, qty, cost, demand, safety, movement) in enumerate([
        (0, 120, 12, 20, 10, '2026-09-01'), (0, 80, 12, 20, 10, '2026-09-01'),
        (1, 50, 20, 5, 5, '2026-09-01'), (2, 10, 100, 0, 0, '2024-01-01'),
        (0, 999, 12, 20, 10, '2026-09-01'),
    ]):
        rows.append(dict(source_system='ERP-SYNTHETIC', supplier_name=oracle[doc]['supplier_name'],
                         source_sku=oracle[doc]['offers'][0]['source_sku'],
                         physical_holding_id=f'PHYSICAL-{i+1}', warehouse=f'Depot-{i+1}',
                         description='Unresolved supplier item', snapshot_date='2026-10-31' if i < 4 else
                         '2026-10-01', quantity=qty, unit_cost=cost, monthly_demand=demand,
                         safety_stock=safety, last_movement=movement, open_po_quantity=5 if i == 0 else 0))
    for scenario in ('accepted_scope', 'stop_for_review'):
        folder = root / 'inputs' / scenario
        folder.mkdir()
        write(folder / 'sku_master.json', masters)
        labels = [dict(source_sku=m['canonical_sku'], description=m['description'],
                       manufacturer=m['manufacturer'], manufacturer_part_number=m['manufacturer_part_number'],
                       canonical_sku=m['canonical_sku']) for m in masters]
        labels.append(dict(source_sku='UNKNOWN', description='Uncatalogued', canonical_sku=None))
        write(folder / 'labels.json', labels)
        write(folder / 'legacy_baseline.json', dict(as_of_date=str(CUTOFF), positions=[
            dict(canonical_sku=s, eo_value=v) for s, v in [('BEARING', '1560.00'),
                                                        ('BELT', '600.00'), ('CPU', '1000.00')]]))
        with (folder / 'holdings.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
            writer.writeheader()
            writer.writerows([{**r, 'snapshot_date': '2026-10-01'} if scenario == 'stop_for_review' else r
                              for r in rows])
        (folder / 'SYNTHETIC_DATA.md').write_text(
            'Invented EUR inventory economics; each is the base unit. Physical holdings are distinct.\n'
            'Catalogue prices/availability are not inventory costs/stock. This is demonstration data, not holdout.\n')
    write(root / 'inputs/oracle.json', oracle)
    write(root / 'inputs/policy.json', Policy().model_dump(mode='json'))
    write(root / 'prompts.json', dict(extraction=EXTRACTION_INSTRUCTIONS,
                                    stages={role: role_instructions(role) for role in AGENTS}))
    for source in [*sorted((REPO / 'inventorypulse').glob('*.py')), Path(__file__),
                   REPO / 'scripts/retrieval_experiment.py']:
        target = root / 'frozen-code' / source.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    frozen = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    write(root / 'frozen-manifest.json', dict(frozen_at=stamp(), files=frozen))
    return frozen


def verify_frozen(root, frozen):
    require(all((root / name).is_file() and sha(root / name) == digest for name, digest in frozen.items()),
            'Frozen inputs/code/prompts changed')


def validate_audit(events):
    previous = '0' * 64
    for index, row in enumerate(events, 1):
        require(row['sequence'] == index and row['previous_hash'] == previous, 'Broken audit order/link')
        digest = hashlib.sha256((previous + json.dumps(row['event'], sort_keys=True)).encode()).hexdigest()
        require(row['hash'] == digest, 'Broken audit hash')
        previous = digest
    require([r['event']['kind'] for r in events] == ['agent_handoff'] * 4 + ['agent_assessment'] * 4
            + ['human_decision'], 'Unexpected audit event order')
    require([r['event']['agent'] for r in events[4:8]] == list(AGENTS), 'Assessment order incorrect')
    require(events[-1]['event']['reviewer'] == 'SIMULATED-DEMO-REVIEWER', 'Reviewer not labelled')
    return previous


def persist_and_check(root, runtime):
    run = runtime.final_run()
    require(list(runtime.receipts) == list(AGENTS), 'Four ordered tool stages required')
    require(runtime.trace[0]['reason_code'] == 'partial_scope', 'Quarantine scope not accepted explicitly')
    require(runtime.receipts['retrieval']['handoff']['payload'] == dict(accepted=4, quarantined=1),
            'Unexpected accepted/quarantined scope')
    require(len(run['positions']) == 3 and run['summary']['eo_value'] == '3160.00', 'Invented E&O oracle failed')
    bearing = next(p for p in run['positions'] if p['canonical_sku'] == 'BEARING')
    require(bearing['quantity'] == '200' and bearing['unit_cost'] == '12', 'Holdings/cost separation failed')
    require(all('supplier_documents/' in ref for p in run['positions'] for ref in p['source_references']),
            'Position disconnected from supplier evidence')
    require(all(r['approval_state'] == 'pending' for r in run['recommendations']), 'Proposal not pending')
    store = Store(root / 'store.sqlite3')
    store.save(run)
    before = store.get(run['run_id'])
    write(root / 'before-approval.json', before)
    write(root / 'audit-before-approval.json', store.audit())
    chosen = next(r for r in before['recommendations'] if r['canonical_sku'] == 'BEARING' and r['rank'] == 1)
    decision = Decision(recommendation_id=chosen['recommendation_id'], decision='approved',
                        reviewer='SIMULATED-DEMO-REVIEWER',
                        reason='Simulated demonstration decision only; no customer approval or execution')
    store.decide(run['run_id'], decision)
    reopened = Store(root / 'store.sqlite3')
    after = reopened.get(run['run_id'])
    write(root / 'after-simulated-approval.json', after)
    rejected = []
    alternative = next(r for r in before['recommendations'] if r['canonical_sku'] == 'BEARING'
                       and r['recommendation_id'] != chosen['recommendation_id'])
    for label, rec in [('duplicate', chosen), ('alternative', alternative)]:
        try:
            reopened.decide(run['run_id'], decision.model_copy(update={
                'recommendation_id': rec['recommendation_id'], 'decision': 'rejected'}))
        except ValueError as exc:
            rejected.append(dict(attempt=label, error=str(exc)))
        else:
            raise ValueError('Duplicate/alternative decision unexpectedly accepted')
    require(reopened.get(run['run_id']) == after, 'Rejected decisions changed totals/state')
    require(len(after['decisions']) == 1 and Decimal(after['summary']['approved_release']) ==
            Decimal(chosen['estimated_release']), 'Approval did not persist exactly once')
    require(Decimal(str(after['summary']['realized_cash'])) == 0 and
            all(Decimal(r['realized_cash']) == 0 for r in after['recommendations']), 'Realized cash changed')
    audit = reopened.audit()
    head = validate_audit(audit)
    write(root / 'audit-after-simulated-approval.json', audit)
    write(root / 'rejected-decisions.json', rejected)
    return dict(run_id=run['run_id'], eo_value=run['summary']['eo_value'],
                estimated_release=run['summary']['estimated_release'],
                simulated_approved_release=after['summary']['approved_release'], realized_cash=0,
                audit_events=len(audit), audit_head=head, duplicate_decisions_rejected=len(rejected))


async def execute(root, model='gpt-oss:latest', *, transport=None):
    root.mkdir(parents=True, exist_ok=False)
    frozen = prepare(root)
    evidence_kind = 'simulated HTTP transport test' if transport is not None else 'live loopback Ollama'
    result = dict(passed=False, evidence_kind=evidence_kind, started_at=stamp(), model=model,
                  provider='ollama', endpoint='http://127.0.0.1:11434', retry_of=None,
                  simulated_reviewer=True, independent_holdout=False, cloud_verified=False)
    calls, operations = [], []
    client = OllamaChatClient(model, transport=transport)
    active = {'operation': 'metadata'}

    async def before(request):
        if request.url.path == '/api/chat':
            calls.append(dict(operation=active['operation'], started_at=stamp(),
                              monotonic_start=time.monotonic(), request=json.loads(request.content)))
            write(root / 'calls.json', calls)

    async def after(response):
        if response.request.url.path == '/api/chat':
            await response.aread()
            row = calls[-1]
            row['seconds'] = round(time.monotonic() - row.pop('monotonic_start'), 4)
            row['finished_at'] = stamp()
            row['status_code'] = response.status_code
            try:
                body = response.json()
                if isinstance(body.get('message'), dict):
                    body['message'].pop('thinking', None)
                row['response'] = body
            except ValueError:
                row['response_text'] = response.text
            write(root / 'calls.json', calls)

    client.http.event_hooks = {'request': [before], 'response': [after]}

    async def operation(name, action, runtime=None):
        active['operation'] = name
        row = dict(operation=name, started_at=stamp(), first_call=len(calls))
        operations.append(row)
        start = time.monotonic()
        try:
            value = await action()
            row['passed'] = True
            return value
        except Exception as exc:
            row.update(passed=False, error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            row.update(finished_at=stamp(), seconds=round(time.monotonic()-start, 4),
                       call_count=len(calls)-row['first_call'])
            if runtime is not None:
                write(root / f'{name}-runtime.json', dict(receipts=runtime.receipts, assessments=runtime.trace,
                      phase=runtime.analysis.phase if runtime.analysis else None))
            write(root / 'operations.json', operations)

    try:
        tags = await client.http.get('/api/tags')
        tags.raise_for_status()
        selected = next(m for m in tags.json()['models'] if m['name'] == model)
        version = await client.http.get('/api/version')
        version.raise_for_status()
        write(root / 'model-server.json', dict(selected=selected, server=version.json(),
                                              provider='ollama', endpoint=str(client.http.base_url)))
        result['model_digest'] = selected['digest']
        verify_frozen(root, frozen)
        extraction = await operation('extraction', lambda: extract_documents(
            root / 'inputs/documents', client, root / 'extraction.json'))
        oracle = json.loads((root / 'inputs/oracle.json').read_text())
        for actual, expected in zip(extraction, oracle, strict=True):
            require(actual['supplier_name'] == expected['supplier_name'], 'Supplier extraction oracle failed')
            require(len(actual['offers']) == len(expected['offers']), 'Offer count oracle failed')
            for got, wanted in zip(actual['offers'], expected['offers'], strict=True):
                require(all(got[key] == value for key, value in wanted.items()), 'Offer extraction oracle failed')
        for scenario in ('accepted_scope', 'stop_for_review'):
            runtime = Runtime(data=root / 'inputs' / scenario, cutoff=CUTOFF,
                              policy=Policy.model_validate_json((root / 'inputs/policy.json').read_text()),
                              supplier_documents=root / 'inputs/documents',
                              supplier_extraction=root / 'extraction.json', provider=f'ollama:{model}',
                              timeout_seconds=300)
            outcome = await operation(scenario, lambda: run_workflow(runtime, lambda role: client), runtime)
            write(root / f'{scenario}-outcome.json', outcome.model_dump(mode='json'))
            if scenario == 'accepted_scope':
                require(outcome.status == 'awaiting_human_approval', 'Connected graph did not reach approval')
                result['completed'] = persist_and_check(root, runtime)
            else:
                require(outcome.status == 'review_required' and outcome.stage == 'retrieval',
                        'No-data scenario did not stop at Retrieval')
                require(list(runtime.receipts) == ['retrieval'] and len(runtime.trace) == 1 and
                        runtime.analysis.phase == 1, 'Later stages executed after stop')
                require(not hasattr(runtime.analysis, 'recommendations'), 'Stopped scenario generated recommendations')
                with Store(root / 'store.sqlite3').connect() as db:
                    require(db.execute('SELECT count(*) FROM runs').fetchone()[0] == 1 and
                            db.execute('SELECT count(*) FROM runs WHERE id=?', (outcome.run_id,)).fetchone()[0]
                            == 0, 'Stopped scenario saved as completed run')
                result['stopped'] = dict(status=outcome.status, stages_executed=['retrieval'],
                                         recommendations=0, saved_completed_run=False)
        verify_frozen(root, frozen)
        result['passed'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        result['finished_at'] = stamp()
        result['calls'] = len(calls)
        result['operations'] = operations
        for row in calls:
            if 'monotonic_start' in row:
                row['seconds_until_failure'] = round(time.monotonic()-row.pop('monotonic_start'), 4)
        write(root / 'calls.json', calls)
        await client.close()
        write(root / 'result.json', result)
        write(root / 'artifact-manifest.json', {str(p.relative_to(root)): sha(p)
              for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'artifact-manifest.json'})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='gpt-oss:latest')
    parser.add_argument('--output-parent', type=Path, default=Path('output/connected-demo'))
    args = parser.parse_args()
    destination = args.output_parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    outcome = asyncio.run(execute(destination, args.model))
    print(json.dumps(dict(output=str(destination), **outcome), indent=2))
    sys.exit(0 if outcome['passed'] else 1)
