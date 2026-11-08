"""Offline preparation checks only; never a timed reviewer observation or validation claim."""

import csv
import hashlib
import json
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inventorypulse.engine import run_pack
from inventorypulse.models import Policy

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/review-packet"


def read(path):
    return json.loads(path.read_text())


def cents(value):
    return value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def verify():
    manifest = read(PACKET / "evidence-manifest.json")
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((PACKET / name).read_bytes()).hexdigest() == expected, name
    compact = read(ROOT / "docs/experiments/connected-demo-results.json")
    assert manifest["source_run"] == compact["completed"]["run_id"]
    for name in ("extraction.json", "before-approval.json"):
        assert hashlib.sha256((PACKET / "assisted" / name).read_bytes()).hexdigest() == compact[
            "fingerprints"
        ][name]
    raw = ROOT / manifest["raw_artifacts"]
    if raw.exists():
        frozen = read(raw / "frozen-manifest.json")
        for name, digest in frozen["files"].items():
            assert hashlib.sha256((raw / name).read_bytes()).hexdigest() == digest, name
        for path in (PACKET / "manual-inputs").rglob("*"):
            if path.is_file():
                assert path.read_bytes() == (raw / "inputs" / path.relative_to(
                    PACKET / "manual-inputs"
                )).read_bytes()
    # Verify templates have no observation values. Only task/phase/SKU/criterion scaffolding allowed.
    for path in (PACKET / "forms").glob("*.csv"):
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            assert None not in row, path.name
            for field, value in row.items():
                assert value == "" or field in {
                    "case", "canonical_sku", "phase", "criterion_id", "expected_points"
                }, (path.name, field)
    policy = read(PACKET / "manual-inputs/policy.json")
    folder = PACKET / "manual-inputs/accepted_scope"
    masters = read(folder / "sku_master.json")
    oracle = read(PACKET / "key/extraction-oracle.json")
    extraction = read(PACKET / "assisted/extraction.json")
    catalogue = {}
    for gold, extracted in zip(oracle, extraction, strict=True):
        assert gold["document_id"] == extracted["document_id"]
        assert gold["supplier_name"] == extracted["supplier_name"]
        text = (PACKET / "manual-inputs/documents" / gold["document_id"]).read_text()
        assert hashlib.sha256(text.encode()).hexdigest() == extracted["source_sha256"]
        for offer, actual in zip(gold["offers"], extracted["offers"], strict=True):
            assert actual["source_quote"] in text
            for field, expected in offer.items():
                assert actual[field] == expected, (gold["document_id"], field)
            catalogue[(gold["supplier_name"], offer["source_sku"])] = offer
    with (folder / "holdings.csv").open(newline="") as stream:
        holdings = list(csv.DictReader(stream))
    cutoff = date(2026, 10, 31)
    accepted = [h for h in holdings if 0 <= (cutoff - date.fromisoformat(
        h["snapshot_date"])).days <= policy["max_feed_age_days"]]
    assert len(accepted) == 4 and len(holdings) == 5
    assert len({h["physical_holding_id"] for h in accepted}) == 4
    expected_positions = {}
    expected_options = {}
    for master in masters:
        rows = [h for h in accepted if catalogue[(h["supplier_name"], h["source_sku"])][
            "manufacturer_part_number"] == master["manufacturer_part_number"]]
        assert len({(h["unit_cost"], h["monthly_demand"], h["safety_stock"]) for h in rows}) == 1
        qty = sum(Decimal(h["quantity"]) for h in rows)
        first = rows[0]
        target = Decimal(first["monthly_demand"]) * Decimal(policy["horizon_months"]) + Decimal(
            first["safety_stock"])
        obsolete = sum((Decimal(h["quantity"]) for h in rows if master["lifecycle"] == "obsolete"
                        or ((cutoff - date.fromisoformat(h["last_movement"])).days >= policy[
                            "obsolete_after_days"] and Decimal(h["monthly_demand"]) == 0)), Decimal(0))
        excess = max(Decimal(0), qty - obsolete - target)
        eo = cents((obsolete + excess) * Decimal(first["unit_cost"]))
        sku = master["canonical_sku"]
        expected_positions[sku] = dict(quantity=qty, target_stock=target, obsolete_quantity=obsolete,
                                       excess_quantity=excess, eo_value=eo,
                                       inventory_value=cents(qty * Decimal(first["unit_cost"])),
                                       open_po_quantity=sum(Decimal(h["open_po_quantity"]) for h in rows))
        options = {"scrap": "scrap_rate"}
        if master["returnable"]:
            options["supplier_return"] = "return_rate"
        if master["lifecycle"] != "obsolete":
            options["discount"] = "discount_rate"
            if master["transferable"]:
                options["transfer"] = "transfer_rate"
        expected_options[sku] = {option: cents(max(Decimal(0), eo * Decimal(policy[rate]) - (
            obsolete + excess) * Decimal(policy["handling_cost_per_unit"])))
            for option, rate in options.items()}
    assisted = read(PACKET / "assisted/before-approval.json")
    assert assisted["run_id"] == manifest["source_run"]
    assert sum(v["eo_value"] for v in expected_positions.values()) == Decimal("3160")
    assert sum(v["inventory_value"] for v in expected_positions.values()) == Decimal("4400")
    assert sum(max(v.values()) for v in expected_options.values()) == Decimal("2516")
    assert sum(v["open_po_quantity"] for v in expected_positions.values()) == 5
    # Current deterministic implementation receives source-grounded identity, never model inference.
    with TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in ("sku_master.json", "labels.json", "legacy_baseline.json", "SYNTHETIC_DATA.md"):
            (tmp / name).write_bytes((folder / name).read_bytes())
        enriched = []
        for holding in holdings:
            offer = catalogue[(holding["supplier_name"], holding["source_sku"])]
            enriched.append({**holding, "manufacturer": offer["manufacturer"],
                             "manufacturer_part_number": offer["manufacturer_part_number"]})
        with (tmp / "holdings.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=enriched[0])
            writer.writeheader()
            writer.writerows(enriched)
        current = run_pack(tmp, cutoff, Policy.model_validate(policy))
    for result in (assisted, current):
        assert len(result["exceptions"]) == 1
        assert result["exceptions"][0]["reason"] == "stale_or_future_snapshot"
        for position in result["positions"]:
            for field, expected in expected_positions[position["canonical_sku"]].items():
                assert Decimal(str(position[field])) == expected, field
        actual_options = {(rec["canonical_sku"], rec["option"]): Decimal(rec["estimated_release"])
                          for rec in result["recommendations"]}
        assert actual_options == {(sku, option): net for sku, options in expected_options.items()
                                  for option, net in options.items()}
        assert Decimal(result["summary"]["eo_value"]) == Decimal("3160")
        assert Decimal(result["summary"]["estimated_release"]) == Decimal("2516")
        assert all(rec["approval_state"] == "pending" for rec in result["recommendations"])
        assert Decimal(str(result["summary"]["realized_cash"])) == 0
        assert Decimal(str(result["summary"]["approved_release"])) == 0
        assert Decimal(result["reconciliation"]["absolute_item_variance"]) == 0
    baseline = read(folder / "legacy_baseline.json")
    assert baseline["as_of_date"] == str(cutoff)
    assert {p["canonical_sku"]: Decimal(p["eo_value"]) for p in baseline["positions"]} == {
        sku: p["eo_value"] for sku, p in expected_positions.items()}
    with (PACKET / "manual-inputs/stop_for_review/holdings.csv").open(newline="") as stream:
        assert all((cutoff - date.fromisoformat(h["snapshot_date"])).days > policy[
            "max_feed_age_days"] for h in csv.DictReader(stream))
    print("Preparation dry run passed: fingerprints, blank forms, six offers, four holdings, "
          "EUR 3160 exposure / 2516 conditional recovery, current implementation agreement. "
          "No reviewer observations or customer validation.")


if __name__ == "__main__":
    verify()
