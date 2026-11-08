"""First-attempt independent local experiment; no cloud, downloads, tuning or silent retries."""
import argparse
import asyncio
import csv
import importlib.metadata
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inventorypulse.agentic import Runtime, role_instructions, run_workflow
from inventorypulse.engine import AGENTS
from inventorypulse.models import Policy
from inventorypulse.ollama_clients import OllamaChatClient
from inventorypulse.supplier_ingestion import EXTRACTION_INSTRUCTIONS, extract_one_document
from scripts.connected_demo_experiment import CUTOFF, REPO, sha, stamp, verify_frozen, write
from scripts.independent_validation_data import build, financial_oracle


def serial(value):
    return json.loads(json.dumps(value, default=str))


def prepare(root):
    docs, expected, masters, scenarios, outcomes = build()
    for name, text in docs.items():
        target = root / 'inputs/documents' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    lifecycles = {m['canonical_sku']: m['lifecycle'] for m in masters}
    financial = {}
    for scenario, rows in scenarios.items():
        folder = root / 'inputs' / scenario
        folder.mkdir(parents=True)
        write(folder / 'sku_master.json', masters)
        # Labels are intentionally empty: experiment gold stays outside all model inputs.
        write(folder / 'labels.json', [])
        with (folder / 'holdings.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)
        (folder / 'SYNTHETIC_DATA.md').write_text('New invented validation data. EUR/base units. No customer records.\n')
        if scenario in ('clean', 'connected_clean', 'cutoff', 'variance'):
            financial[scenario] = financial_oracle(scenarios['clean'], lifecycles)
        elif scenario in ('injection', 'variant'):
            canonical = 'VALVE-Q' if scenario == 'injection' else 'HOLD-B'
            financial[scenario] = financial_oracle([{**r, 'source_sku': canonical} for r in rows], lifecycles)
        baseline = [dict(canonical_sku=sku, eo_value=str(p['eo_value']))
                    for sku, p in financial.get(scenario, {}).get('positions', {}).items()]
        if scenario == 'variance':
            baseline[0]['eo_value'] = str(Decimal(baseline[0]['eo_value']) + Decimal('.01'))
        write(folder / 'legacy_baseline.json', dict(as_of_date='2026-09-30' if scenario == 'cutoff'
                                                   else str(CUTOFF), positions=baseline))
    identities = dict(clean=['HOLD-A', 'HOLD-A', 'HOLD-R'], connected_clean=['HOLD-A', 'HOLD-A', 'HOLD-R'],
                      ambiguous=[None], injection=['VALVE-Q'], variant=['HOLD-B'],
                      conflict=['HOLD-A', 'HOLD-A'], cutoff=['HOLD-A', 'HOLD-A', 'HOLD-R'],
                      variance=['HOLD-A', 'HOLD-A', 'HOLD-R'])
    oracle = serial(dict(extraction=expected, outcomes=outcomes, financial=financial, identities=identities))
    write(root / 'gold/oracle.json', oracle)
    write(root / 'inputs/policy.json', Policy().model_dump(mode='json'))
    write(root / 'prompts.json', dict(extraction=EXTRACTION_INSTRUCTIONS,
                                    stages={r: role_instructions(r) for r in AGENTS}))
    sources = [*sorted((REPO / 'inventorypulse').glob('*.py')), Path(__file__),
               REPO / 'scripts/independent_validation_data.py', REPO / 'scripts/connected_demo_experiment.py',
               REPO / 'scripts/retrieval_experiment.py', REPO / 'pyproject.toml']
    for source in sources:
        target = root / 'frozen-code' / source.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    frozen = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    write(root / 'frozen-manifest.json', dict(frozen_at=stamp(), files=frozen))
    return frozen, oracle


def score_extraction(actual, expected):
    fields = {field: dict(correct=0, total=len(expected)) for field in next(iter(expected.values()))}
    exact = 0
    for name, gold in expected.items():
        row = actual.get(name)
        got = {**row['offers'][0], 'supplier_name': row['supplier_name']} if row else {}
        for field, value in gold.items():
            fields[field]['correct'] += int(field in got and got[field] == value)
        exact += int(all(field in got and got[field] == value for field, value in gold.items()))
    return dict(fields=fields, exact_records=exact, total_records=len(expected),
                supplier_exact=fields['supplier_name'],
                limitation='Fresh synthetic cases, small denominator; failures count as incorrect, not abstentions.')


def compare_financial(run, expected):
    checks = []
    def check(path, actual, wanted):
        checks.append(dict(path=path, actual=str(actual), expected=str(wanted),
                           passed=Decimal(str(actual)) == Decimal(str(wanted))))
    positions = {p['canonical_sku']: p for p in run['positions']}
    if set(positions) != set(expected['positions']):
        return dict(passed=False, error='Position identity set differs', checks=[])
    for sku, gold in expected['positions'].items():
        for field, value in gold.items():
            check(f'positions/{sku}/{field}', positions[sku][field], value)
    actual_options = {(r['canonical_sku'], r['option']): r for r in run['recommendations']}
    option_keys = {(sku, option) for sku, options in expected['proposals'].items() for option in options}
    if set(actual_options) != option_keys:
        return dict(passed=False, error='Proposal option set differs', checks=checks)
    for sku, options in expected['proposals'].items():
        for option, value in options.items():
            row = actual_options[sku, option]
            check(f'proposals/{sku}/{option}', row['estimated_release'], value)
            check(f'cash/{sku}/{option}', row['realized_cash'], 0)
            checks.append(dict(path=f'pending/{sku}/{option}', passed=row['approval_state'] == 'pending'))
    for field, value in expected['summary'].items():
        check(f'summary/{field}', run['summary'][field], value)
    return dict(passed=all(r['passed'] for r in checks), checks=checks)


async def execute(root, model='gpt-oss:latest'):
    root.mkdir(parents=True, exist_ok=False)
    frozen, oracle = prepare(root)
    calls, extracted, scenarios = [], {}, {}
    active = {'operation': 'metadata'}
    result = dict(evidence_kind='live loopback Ollama', independent_synthetic=True, retry_of=None,
                  started_at=stamp(), provider='ollama', model=model, cloud_verified=False)
    client = OllamaChatClient(model)
    async def before(request):
        if request.url.path == '/api/chat':
            calls.append(dict(operation=active['operation'], started_at=stamp(),
                              clock=time.monotonic(), request=json.loads(request.content)))
            write(root / 'calls.json', calls)
    async def after(response):
        if response.request.url.path == '/api/chat':
            await response.aread()
            row = calls[-1]
            row.update(seconds=round(time.monotonic()-row.pop('clock'), 4), status_code=response.status_code,
                       finished_at=stamp())
            body = response.json()
            if isinstance(body.get('message'), dict):
                body['message'].pop('thinking', None)
            row['response'] = body
            write(root / 'calls.json', calls)
    client.http.event_hooks = dict(request=[before], response=[after])
    try:
        tags = await client.http.get('/api/tags')
        tags.raise_for_status()
        selected = next(m for m in tags.json()['models'] if m['name'] == model)
        version = await client.http.get('/api/version')
        version.raise_for_status()
        write(root / 'model-server.json', dict(selected=selected, server=version.json(),
             packages={p: importlib.metadata.version(p) for p in ('agent-framework-core', 'httpx', 'pydantic')}))
        result['model_digest'] = selected['digest']
        verify_frozen(root, frozen)
        extraction_attempts = {}
        for path in sorted((root / 'inputs/documents').glob('*.md')):
            active['operation'] = f'extraction/{path.name}'
            start = time.monotonic()
            try:
                parsed = await extract_one_document(path.read_text(), client)
                extracted[path.name] = dict(document_id=path.name, source_sha256=sha(path),
                                           **parsed.model_dump(mode='json'))
                extraction_attempts[path.name] = dict(validated=True)
            except Exception as exc:
                extraction_attempts[path.name] = dict(validated=False, error=f'{type(exc).__name__}: {exc}')
            extraction_attempts[path.name]['seconds'] = round(time.monotonic()-start, 4)
            write(root / 'extraction-attempts.json', extraction_attempts)
            write(root / 'extraction.json', list(extracted.values()))
            print(active['operation'], extraction_attempts[path.name], flush=True)
        result['extraction'] = score_extraction(extracted, oracle['extraction'])
        result['extraction_attempts'] = extraction_attempts
        for scenario, expected in oracle['outcomes'].items():
            active['operation'] = scenario
            connected = scenario in ('connected_clean', 'ambiguous', 'injection', 'variant')
            needed = {'connected_clean': ['01-actuator.md', '02-relay.md'], 'ambiguous': ['03-ambiguous.md'],
                      'injection': ['04-injection.md'], 'variant': ['05-variant.md']}.get(scenario, [])
            row = dict(expected=expected, first_call=len(calls), started_at=stamp())
            scenarios[scenario] = row
            if any(name not in extracted for name in needed):
                row.update(passed=False, blocked_by='extraction failure; no gold substitution or retry')
                continue
            extraction_path = root / f'{scenario}-extraction.json'
            if connected:
                write(extraction_path, [extracted[name] for name in needed])
            runtime = Runtime(data=root / 'inputs' / scenario, cutoff=CUTOFF, policy=Policy(),
                              supplier_documents=root / 'inputs/documents' if connected else None,
                              supplier_extraction=extraction_path if connected else None,
                              provider=f'ollama:{model}', timeout_seconds=300)
            start = time.monotonic()
            try:
                outcome = await run_workflow(runtime, lambda role: client)
                write(root / f'{scenario}-outcome.json', outcome.model_dump(mode='json'))
                row.update(actual=dict(status=outcome.status, stage=outcome.stage),
                           workflow_correct=outcome.status == expected['status'] and outcome.stage == expected['stage'])
                row['passed'] = row['workflow_correct']
                if scenario in oracle['identities'] and hasattr(runtime.analysis, 'crosswalk'):
                    got = [r['canonical_sku'] for r in runtime.analysis.crosswalk]
                    row['identity'] = dict(actual=got, expected=oracle['identities'][scenario],
                                           passed=got == oracle['identities'][scenario])
                    row['passed'] &= row['identity']['passed']
                if outcome.status == 'awaiting_human_approval':
                    run = runtime.final_run()
                    write(root / f'{scenario}-run.json', run)
                    comparison = compare_financial(run, oracle['financial'][scenario])
                    write(root / f'{scenario}-financial-comparison.json', comparison)
                    row['financial_passed'] = comparison['passed']
                    row['passed'] &= comparison['passed']
            except Exception as exc:
                row.update(passed=False, error=f'{type(exc).__name__}: {exc}')
            finally:
                write(root / f'{scenario}-runtime.json', serial(dict(receipts=runtime.receipts,
                      assessments=runtime.trace, phase=runtime.analysis.phase if runtime.analysis else None,
                      exceptions=runtime.analysis.exceptions if runtime.analysis else [],
                      crosswalk=runtime.analysis.crosswalk if runtime.analysis else [])))
                row.update(seconds=round(time.monotonic()-start, 4), calls=len(calls)-row['first_call'],
                           stages_executed=list(runtime.receipts), assessments=len(runtime.trace))
                write(root / 'scenario-results.json', scenarios)
                print(scenario, row, flush=True)
        verify_frozen(root, frozen)
        result['frozen_integrity'] = True
        result['all_scenarios_correct'] = all(r['passed'] for r in scenarios.values())
    except Exception as exc:
        result['fatal_error'] = f'{type(exc).__name__}: {exc}'
    finally:
        result.update(finished_at=stamp(), calls=len(calls), scenarios=scenarios)
        for call in calls:
            if 'clock' in call:
                call['seconds_until_failure'] = round(time.monotonic()-call.pop('clock'), 4)
        write(root / 'calls.json', calls)
        await client.close()
        write(root / 'result.json', result)
        write(root / 'artifact-manifest.json', {str(p.relative_to(root)): sha(p)
              for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'artifact-manifest.json'})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='gpt-oss:latest')
    parser.add_argument('--output-parent', type=Path, default=Path('output/independent-validation'))
    args = parser.parse_args()
    destination = args.output_parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    result = asyncio.run(execute(destination, args.model))
    print(json.dumps(dict(output=str(destination), **result), indent=2))
    sys.exit(1 if 'fatal_error' in result or not result.get('all_scenarios_correct') else 0)
