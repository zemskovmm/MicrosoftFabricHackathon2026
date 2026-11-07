"""Generate a reproducible, explicitly synthetic pack. No external downloads or customer data."""

import csv
import json
from datetime import date, timedelta
from pathlib import Path


def generate(folder: Path, as_of: date = date(2026, 10, 31), *, include_exceptions: bool = True):
    folder.mkdir(parents=True, exist_ok=True)
    masters, holdings, labels, baseline = [], [], [], []
    for n in range(1, 25):
        sku = f"PART-{n:03}"
        description = f"Industrial assembly {n:03} size {n * 7} millimeter"
        is_obsolete = n % 6 == 0
        masters.append(
            dict(
                canonical_sku=sku,
                description=description,
                lifecycle="obsolete" if is_obsolete else "active",
                returnable=n % 2 == 0,
                transferable=n % 3 == 0,
            )
        )
        # Two distinct physical warehouse holdings, NOT two copies of the same ERP stock.
        for site in ("Madrid", "Berlin"):
            source = sku if site == "Madrid" else f"WMS-{n:03}"
            text = description if site == "Madrid" else description.replace("millimeter", "mm")
            holdings.append(
                dict(
                    source_system="ERP" if site == "Madrid" else "WMS",
                    source_sku=source,
                    warehouse=site,
                    description=text,
                    snapshot_date=str(as_of),
                    quantity=100 + n * 15,
                    unit_cost=10 + n * 5,
                    monthly_demand=20,
                    safety_stock=10,
                    last_movement=str(as_of - timedelta(days=450 if is_obsolete else 30)),
                    open_po_quantity=10 if site == "Madrid" else 0,
                )
            )
            labels.append(dict(source_sku=source, description=text, canonical_sku=sku))
        # Independently stated sample baseline: 70 units target, all stock obsolete for every sixth part.
        total = 2 * (100 + n * 15)
        baseline.append(
            dict(canonical_sku=sku, eo_value=str((total if is_obsolete else total - 70) * (10 + n * 5)))
        )
    if include_exceptions:
        template = dict(holdings[0])
        for code, changes in [
            ("UNKNOWN", dict(description="unidentified mystery component")),
            ("BAD-PRICE", dict(unit_cost=-3)),
            ("STALE", dict(snapshot_date=str(as_of - timedelta(days=9)))),
            ("FUTURE", dict(snapshot_date=str(as_of + timedelta(days=1)))),
            ("BAD-QTY", dict(quantity=-1)),
        ]:
            holdings.append({**template, "source_sku": code, **changes})
    labels.extend(
        [
            dict(source_sku="UNKNOWN", description="unidentified mystery component", canonical_sku=None),
            dict(source_sku="UNMATCHED", description="garden chair furniture", canonical_sku=None),
        ]
    )
    for name, payload in [
        ("sku_master.json", masters),
        ("labels.json", labels),
        (
            "legacy_baseline.json",
            dict(
                as_of_date=str(as_of),
                positions=baseline,
                note="Synthetic legacy-format reference. Not a real historic ERP report.",
            ),
        ),
    ]:
        (folder / name).write_text(json.dumps(payload, indent=2) + "\n")
    with (folder / "holdings.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(holdings[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(holdings)
    (folder / "SYNTHETIC_DATA.md").write_text(
        "# Synthetic inventory pack\n\nEntirely invented, deterministic hackathon data; no real customer records.\n"
        f"Cutoff: {as_of}. Currency: illustrative USD throughout.\n"
        f"24 canonical SKUs, 48 separate warehouse holdings, {5 if include_exceptions else 0} intentional bad records, 50 labelled matches.\n"
        "Demand and safety stock are canonical/global values repeated per holding; they are not summed.\n"
        "Open PO quantities are per holding. Do not load mirrored stock copies as separate physical holdings.\n"
        "The baseline is a synthetic reference using a 3-month horizon, 10 safety units and lifecycle flags.\n"
        "It validates arithmetic and scope handling, not a real company's legacy policy.\n"
        "Transfer recovery is an illustrative internal utilization value, not external cash proceeds.\n"
        "No representative production precision, savings, or speed claim can be made from this pack.\n"
    )
