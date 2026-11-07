"""Readable Markdown inputs. This deliberately supports three documented formats, not arbitrary prose."""

import hashlib
import re
from decimal import Decimal
from pathlib import Path


def table(path: Path) -> list[dict]:
    lines = [
        (n, line.strip())
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if line.strip().startswith("|")
    ]
    if not lines:
        raise ValueError(f"No Markdown table in {path.name}")
    headers = [v.strip() for v in lines[0][1].strip("|").split("|")]
    if len(set(headers)) != len(headers):
        raise ValueError(f"Duplicate columns in {path.name}")
    rows = []
    for number, line in lines[2:]:
        values = [v.strip() for v in line.strip("|").split("|")]
        if len(values) != len(headers):
            raise ValueError(f"Malformed Markdown table: {path.name}:{number}")
        rows.append({**dict(zip(headers, values)), "_line": number})
    return rows


def offers(path: Path, style: str) -> list[dict]:
    if style == "table":
        rows = table(path)
    elif style == "cards":
        rows = []
        for block in re.split(r"(?m)^## ", path.read_text())[1:]:
            pairs = re.findall(r"(?m)^- ([a-z_]+): (.*)$", block)
            keys = [k for k, _ in pairs]
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate card field")
            rows.append(dict(pairs))
    elif style == "prose":
        rows = []
        pattern = (
            r"Ordering code `([^`]+)`\. Manufacturer: ([^.]+)\. Manufacturer reference `([^`]+)`\.\s*"
            r"Description: ([^\n]+)\nSupplied as ([0-9]+) items per pack\."
        )
        blocks = re.split(r"(?m)^## ", path.read_text())[1:]
        for block in blocks:
            found = re.search(pattern, block)
            if not found:
                raise ValueError(f"Unsupported supplier prose in {path.name}; review instead of guessing")
            rows.append(
                dict(
                    zip(
                        (
                            "source_sku",
                            "manufacturer",
                            "manufacturer_part_number",
                            "description",
                            "pack_size",
                        ),
                        found.groups(),
                    )
                )
            )
    else:
        raise ValueError("Unsupported supplier format")
    required = {"source_sku", "manufacturer", "manufacturer_part_number", "description", "pack_size"}
    for row in rows:
        if not required.issubset(row) or not all(row[k] for k in required):
            raise ValueError(f"Incomplete supplier record in {path.name}")
        pack = Decimal(row["pack_size"])
        if not pack.is_finite() or pack <= 0:
            raise ValueError("Pack size must be positive and finite")
    return rows


def load(folder: Path) -> dict:
    registry = table(folder / "suppliers.md")
    catalogue, catalog_list = {}, []
    for supplier in registry:
        relative = supplier["file"]
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder.resolve()):
            raise ValueError("Supplier path escapes the data folder")
        for offer in offers(path, supplier["format"]):
            key = (supplier["supplier_id"], offer["source_sku"])
            if key in catalogue:
                raise ValueError("Duplicate supplier SKU within the same supplier")
            record = {k: v for k, v in offer.items() if not k.startswith("_")}
            record["supplier_id"] = supplier["supplier_id"]
            record["source_reference"] = f"{relative}#{offer['source_sku']}"
            record["source_format"] = supplier["format"]
            catalogue[key] = record
            catalog_list.append(record)
    masters = [{k: v for k, v in r.items() if k != "_line"} for r in table(folder / "products.md")]
    demand = {}
    for row in table(folder / "demand.md"):
        if row["holding_id"] in demand:
            raise ValueError("Duplicate demand scope")
        demand[row["holding_id"]] = row
    orders = {}
    for row in table(folder / "purchase-orders.md"):
        if row["holding_id"] in orders:
            raise ValueError("Duplicate purchase order scope")
        orders[row["holding_id"]] = row
    holdings = []
    for path in sorted((folder / "inventory").glob("*.md")):
        for row in table(path):
            offer = catalogue.get((row["supplier_id"], row["source_sku"]))
            if offer is None:
                raise ValueError(f"Unknown supplier SKU at {path.name}:{row['_line']}")
            plan = demand.get(row["holding_id"])
            if plan is None:
                raise ValueError(f"Missing demand for {row['holding_id']}")
            pack_size = Decimal(offer["pack_size"])
            holdings.append(
                dict(
                    source_system=row["supplier_id"],
                    source_sku=row["source_sku"],
                    physical_holding_id=row["holding_id"],
                    warehouse=row["warehouse"],
                    description=offer["description"],
                    manufacturer=offer["manufacturer"],
                    manufacturer_part_number=offer["manufacturer_part_number"],
                    snapshot_date=row["snapshot_date"],
                    quantity=str(Decimal(row["packs_on_hand"]) * pack_size),
                    unit_cost=str(Decimal(row["cost_per_pack_eur"]) / pack_size),
                    monthly_demand=plan["monthly_demand_items"],
                    safety_stock=plan["safety_stock_items"],
                    last_movement=row["last_movement"],
                    open_po_quantity=orders.get(row["holding_id"], {}).get("open_po_items", "0"),
                    source_reference=f"inventory/{path.name}:line:{row['_line']} + {offer['source_reference']}",
                )
            )
    labels = [
        {k: (None if v == "UNMATCHED" else v) for k, v in row.items() if k != "_line"}
        for row in table(folder / "evaluation" / "expected-matches.md")
    ]
    baseline_rows = table(folder / "legacy-monthly-report.md")
    dates = {row["as_of_date"] for row in baseline_rows}
    if len(dates) != 1:
        raise ValueError("Legacy report must have exactly one cutoff")
    baseline = dict(
        as_of_date=dates.pop(),
        positions=[dict(canonical_sku=r["canonical_sku"], eo_value=r["eo_value_eur"]) for r in baseline_rows],
    )
    # Score only independent labelled examples, never use expected canonical IDs during matching.
    files = sorted(folder.rglob("*.md"))
    return dict(
        masters=masters,
        holdings=holdings,
        labels=labels,
        baseline=baseline,
        catalog=catalog_list,
        fingerprints={str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    )
