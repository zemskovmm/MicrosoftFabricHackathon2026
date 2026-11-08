"""Local deterministic experiment checks; no simulated results are live evidence."""
import ast
import copy
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.connected_demo_experiment import verify_frozen
from scripts.independent_validation_data import build, financial_oracle
from scripts.independent_validation_experiment import compare_financial, prepare, score_extraction


def test_oracle_has_no_application_dependencies():
    source = Path('scripts/independent_validation_data.py').read_text()
    tree = ast.parse(source)
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert imports == ['decimal']
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))


def test_manual_fractional_oracle_and_independent_aggregation():
    _, _, masters, rows, _ = build()
    oracle = financial_oracle(rows['clean'], {m['canonical_sku']: m['lifecycle'] for m in masters})
    assert oracle['positions']['HOLD-A']['quantity'] == Decimal('12.75')
    assert oracle['positions']['HOLD-A']['target_stock'] == Decimal('4.25')
    assert oracle['positions']['HOLD-A']['eo_value'] == Decimal('113.69')
    assert oracle['positions']['HOLD-R']['obsolete_quantity'] == Decimal('3.75')
    assert oracle['positions']['HOLD-R']['excess_quantity'] == 0
    assert oracle['summary']['eo_value'] == Decimal('144.16')
    assert oracle['summary']['inventory_value'] == Decimal('201.00')
    assert oracle['summary']['estimated_release'] == Decimal('110.29')
    assert oracle['summary']['realized_cash'] == 0
    assert oracle['positions']['HOLD-A']['open_po_quantity'] == Decimal('40.75')
    with pytest.raises(ValueError, match='duplicate'):
        financial_oracle(rows['duplicate'], {'HOLD-A': 'active'})
    with pytest.raises(ValueError, match='conflicting'):
        financial_oracle(rows['conflict'], {'HOLD-A': 'active'})


def test_freeze_gold_and_inputs_before_inference_and_detect_mutation(tmp_path):
    frozen, oracle = prepare(tmp_path)
    verify_frozen(tmp_path, frozen)
    assert 'gold/oracle.json' in frozen
    assert 'prompts.json' in frozen
    assert 'frozen-code/inventorypulse/agentic.py' in frozen
    for labels in (tmp_path / 'inputs').glob('*/labels.json'):
        assert json.loads(labels.read_text()) == []
    assert oracle['outcomes']['ambiguous']['stage'] == 'sku-matching'
    target = tmp_path / 'inputs/documents/01-actuator.md'
    target.write_text(target.read_text() + 'mutated')
    with pytest.raises(ValueError, match='Frozen'):
        verify_frozen(tmp_path, frozen)


def test_scoring_does_not_hide_missing_or_partial_supplier_names():
    _, expected, *_ = build()
    actual = {name: dict(supplier_name=row['supplier_name'], offers=[row]) for name, row in expected.items()}
    assert score_extraction(actual, expected)['exact_records'] == 5
    changed = copy.deepcopy(actual)
    changed['01-actuator.md']['supplier_name'] = 'Mistral Components S.L.'
    del changed['02-relay.md']
    score = score_extraction(changed, expected)
    assert score['supplier_exact'] == dict(correct=3, total=5)
    assert score['exact_records'] == 3
    assert score['fields']['source_sku']['correct'] == 4


def test_financial_comparison_detects_double_count_and_cash():
    _, _, masters, rows, _ = build()
    oracle = financial_oracle(rows['clean'], {m['canonical_sku']: m['lifecycle'] for m in masters})
    run = dict(positions=[dict(canonical_sku=sku, **p) for sku, p in oracle['positions'].items()],
               summary=copy.deepcopy(oracle['summary']), recommendations=[
                   dict(canonical_sku=sku, option=opt, estimated_release=value,
                        realized_cash=0, approval_state='pending')
                   for sku, options in oracle['proposals'].items() for opt, value in options.items()])
    assert compare_financial(run, oracle)['passed']
    run['summary']['estimated_release'] = sum(r['estimated_release'] for r in run['recommendations'])
    run['recommendations'][0]['realized_cash'] = 1
    checks = compare_financial(run, oracle)
    assert not checks['passed']
    assert sum(not c['passed'] for c in checks['checks']) == 2
