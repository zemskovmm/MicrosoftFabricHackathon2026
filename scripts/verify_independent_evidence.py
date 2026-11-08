"""Read-only evidence integrity verification. Does not invoke inference or production tools."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    manifest = json.loads((root / 'artifact-manifest.json').read_text())
    assert all(digest(root / name) == value for name, value in manifest.items()), 'Evidence changed'
    frozen = json.loads((root / 'frozen-manifest.json').read_text())
    assert all(digest(root / name) == value for name, value in frozen['files'].items()), 'Frozen data changed'
    result = json.loads((root / 'result.json').read_text())
    calls = json.loads((root / 'calls.json').read_text())
    assert all('thinking' not in c.get('response', {}).get('message', {}) for c in calls)
    assert all(c['request']['model'] == result['model'] for c in calls)
    # Actual model inputs must never include the gold collection or labelled example payloads.
    for call in calls:
        text = json.dumps(call['request'])
        assert 'gold/oracle.json' not in text and '"canonical_sku"' not in text and 'true_positive' not in text
    receipts = 0
    for scenario, row in result['scenarios'].items():
        runtime = json.loads((root / f'{scenario}-runtime.json').read_text())
        for receipt in runtime['receipts'].values():
            expected = hashlib.sha256(json.dumps(receipt['handoff'], sort_keys=True).encode()).hexdigest()
            assert receipt['receipt'] == expected
            receipts += 1
        if row.get('actual', {}).get('status') == 'review_required':
            assert row['stages_executed'][-1] == row['actual']['stage']
            assert not (root / f'{scenario}-run.json').exists()
    return dict(files=len(manifest), calls=len(calls), receipts=receipts,
                frozen_files=len(frozen['files']), gold_excluded_from_requests=True,
                hidden_reasoning_excluded=True, all_stops_have_no_completed_run=True)


if __name__ == '__main__':
    import sys
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
