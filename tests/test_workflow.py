import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from inventorypulse.api import create_app
from inventorypulse.engine import reconcile, run_pack
from inventorypulse.matching import match, scorecard
from inventorypulse.models import Decision, Holding, Master, Policy
from inventorypulse.sample import generate
from inventorypulse.store import Store

CUTOFF = date(2026, 10, 31)


@pytest.fixture
def pack(tmp_path):
    folder = tmp_path / "pack"
    generate(folder)
    return folder


def mutate(folder, change):
    path = folder / "holdings.csv"
    rows = list(csv.DictReader(path.open()))
    change(rows)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_full_synthetic_workflow_reproducible_and_reconciled(pack):
    first = run_pack(pack, CUTOFF)
    assert first == run_pack(pack, CUTOFF)
    assert len(first["handoffs"]) == 4
    assert len(first["positions"]) == 24
    assert first["summary"]["exceptions"] == 5
    assert first["scorecard"]["precision"] == 1
    assert first["scorecard"]["recall"] == 1
    assert first["reconciliation"]["absolute_item_variance"] == "0.00"
    assert first["alerts"]
    # Independently known sample: PART-001 has 230 on hand, target 70, price 15.
    p = first["positions"][0]
    assert p["quantity"] == "230"
    assert p["eo_value"] == "2400.00"
    assert all(Decimal(p["eo_quantity"]) <= Decimal(p["quantity"]) for p in first["positions"])
    # Every sixth SKU is obsolete; quantity is not counted again as excess.
    obsolete = next(p for p in first["positions"] if p["canonical_sku"] == "PART-006")
    assert obsolete["excess_quantity"] == "0"
    assert obsolete["obsolete_quantity"] == obsolete["quantity"]
    assert Decimal(first["summary"]["estimated_release"]) == sum(
        Decimal(r["estimated_release"]) for r in first["recommendations"] if r["rank"] == 1
    )
    assert first["summary"]["realized_cash"] == 0
    mutate(pack, lambda rows: rows[0].update(quantity="231"))
    assert run_pack(pack, CUTOFF)["run_id"] != first["run_id"]


def test_duplicate_holdings_are_all_quarantined(pack):
    mutate(pack, lambda rows: rows.append(dict(rows[0])))
    result = run_pack(pack, CUTOFF)
    assert sum(e["reason"] == "duplicate_holding" for e in result["exceptions"]) == 2
    position = next(p for p in result["positions"] if p["canonical_sku"] == "PART-001")
    assert position["quantity"] == "115"


def test_inconsistent_shared_cost_or_demand_quarantines_entire_sku(pack):
    mutate(pack, lambda rows: rows[1].update(unit_cost="99"))
    result = run_pack(pack, CUTOFF)
    assert not any(p["canonical_sku"] == "PART-001" for p in result["positions"])
    assert any(e["reason"] == "conflicting_cost_or_demand" for e in result["exceptions"])
    assert any(r["exception"] == "missing_daily" for r in result["reconciliation"]["rows"])


def test_matching_abstains_on_ambiguity_and_different_numeric_specs():
    masters = [
        Master(canonical_sku="A", description="steel bolt 10 mm"),
        Master(canonical_sku="B", description="steel bolt 10 mm"),
    ]
    assert match("X", "steel bolt 10 mm", masters, Policy())["canonical_sku"] is None
    assert match("X", "steel bolt 11 mm", masters, Policy())["canonical_sku"] is None
    labels = [dict(source_sku="A", description="any", canonical_sku="B")]
    result = scorecard(labels, masters, Policy())
    assert result["false_positive"] == 1 and result["false_negative"] == 1


def test_no_future_stale_negative_or_nonfinite_data_is_accepted(pack):
    rows = list(csv.DictReader((pack / "holdings.csv").open()))
    for change in (dict(quantity="NaN"), dict(unit_cost="Infinity"), dict(quantity="-1")):
        with pytest.raises(ValidationError):
            Holding.model_validate({**rows[0], **change})
    result = run_pack(pack, CUTOFF)
    assert sum(e["reason"] == "stale_or_future_snapshot" for e in result["exceptions"]) == 2
    with pytest.raises(ValidationError):
        Policy(alert_value="NaN")


def test_reconciliation_requires_same_cutoff_and_reports_zero_baseline():
    with pytest.raises(ValueError, match="same cutoff"):
        reconcile([], dict(as_of_date="2026-09-30", positions=[]), CUTOFF)
    result = reconcile(
        [dict(canonical_sku="NEW", eo_value=Decimal("20"))],
        dict(as_of_date=str(CUTOFF), positions=[dict(canonical_sku="OLD", eo_value="10")]),
        CUTOFF,
    )
    assert result["absolute_item_variance"] == Decimal("30.00")
    assert result["rows"][0]["variance_pct"] is None
    assert {r["exception"] for r in result["rows"]} == {"missing_daily", "missing_baseline"}


def test_misaligned_baseline_is_marked_not_comparable(pack):
    payload = json.loads((pack / "legacy_baseline.json").read_text())
    payload["as_of_date"] = "2026-09-30"
    (pack / "legacy_baseline.json").write_text(json.dumps(payload))
    result = run_pack(pack, CUTOFF)
    assert result["reconciliation"]["status"] == "not_comparable"


def test_approval_persistence_mutual_exclusion_and_hash_chain(pack, tmp_path):
    store = Store(tmp_path / "audit.db")
    run = run_pack(pack, CUTOFF)
    store.save(run)
    store.save(run)  # Idempotent retries cannot duplicate audit events.
    chosen = run["recommendations"][0]
    decision = Decision(
        recommendation_id=chosen["recommendation_id"],
        decision="approved",
        reviewer="Local tester",
        reason="Validate sample proposal",
    )
    result = store.decide(run["run_id"], decision)
    assert Decimal(result["summary"]["approved_release"]) == Decimal(chosen["estimated_release"])
    assert result["summary"]["realized_cash"] == 0
    assert Store(tmp_path / "audit.db").get()["decisions"] == result["decisions"]
    with pytest.raises(ValueError, match="already"):
        store.decide(run["run_id"], decision)
    siblings = [r for r in result["recommendations"] if r["canonical_sku"] == chosen["canonical_sku"]]
    assert sum(r["approval_state"] == "approved" for r in siblings) == 1
    assert all(r["approval_state"] in ("approved", "not_selected") for r in siblings)
    previous = "0" * 64
    audit = store.audit()
    assert len(audit) == 5
    for event in audit:
        assert event["previous_hash"] == previous
        assert (
            event["hash"]
            == hashlib.sha256((previous + json.dumps(event["event"], sort_keys=True)).encode()).hexdigest()
        )
        previous = event["hash"]


def test_concurrent_approval_only_one_wins(pack, tmp_path):
    store = Store(tmp_path / "concurrent.db")
    run = run_pack(pack, CUTOFF)
    store.save(run)
    options = [r for r in run["recommendations"] if r["canonical_sku"] == "PART-002"]

    def decide(rec):
        try:
            store.decide(
                run["run_id"],
                Decision(
                    recommendation_id=rec["recommendation_id"],
                    decision="approved",
                    reviewer="Tester",
                    reason="Concurrent test",
                ),
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(decide, options[:2])) == 1


def test_api_requires_key_and_protects_decision_contract(pack, tmp_path):
    store = Store(tmp_path / "api.db")
    run = run_pack(pack, CUTOFF)
    store.save(run)
    client = TestClient(create_app(store, "test-approval-key"))
    assert client.get("/").status_code == 200
    assert client.get("/api/run").json()["run_id"] == run["run_id"]
    payload = dict(
        recommendation_id=run["recommendations"][0]["recommendation_id"],
        decision="approved",
        reviewer="Test reviewer",
        reason="Sample test",
    )
    url = f"/api/runs/{run['run_id']}/decisions"
    assert client.post(url, json=payload).status_code == 403
    headers = {"X-Approval-Key": "test-approval-key"}
    assert client.post(url, json={**payload, "decision": "executed"}, headers=headers).status_code == 422
    assert client.post(url, json=payload, headers=headers).status_code == 200
    assert client.post(url, json=payload, headers=headers).status_code == 409
    assert client.post("/api/runs/nonexistent/decisions", json=payload, headers=headers).status_code == 404
    assert client.get("/api/run", headers={"Host": "evil.example"}).status_code == 400
