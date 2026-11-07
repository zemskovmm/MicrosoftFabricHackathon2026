"""Four bounded agents. Monetary arithmetic stays Decimal until JSON serialization."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pydantic import ValidationError

from .matching import identifier, match, scorecard
from .models import Handoff, Holding, Master, Policy

AGENTS = ("retrieval", "sku-matching", "eo-calculation", "recommendation")
CODE_VERSION = "inventorypulse-0.3.0"


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def jsonable(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def reconcile(positions: list[dict], baseline: dict, cutoff: date) -> dict:
    if baseline["as_of_date"] != cutoff.isoformat():
        raise ValueError("Monthly reconciliation requires the exact same cutoff as the daily run")
    reference = {}
    for row in baseline["positions"]:
        sku, value = (row["canonical_sku"], Decimal(str(row["eo_value"])))
        if sku in reference or not value.is_finite() or value < 0:
            raise ValueError("Duplicate or invalid legacy baseline position")
        reference[sku] = value
    actual = {p["canonical_sku"]: p["eo_value"] for p in positions}
    rows = []
    for sku in sorted(reference.keys() | actual.keys()):
        old, new = (reference.get(sku, Decimal(0)), actual.get(sku, Decimal(0)))
        delta = new - old
        rows.append(
            dict(
                canonical_sku=sku,
                baseline_value=old,
                daily_value=new,
                variance=money(delta),
                absolute_variance=money(abs(delta)),
                variance_pct=money(delta / old * 100) if old else None,
                exception="missing_daily"
                if sku not in actual
                else "missing_baseline"
                if sku not in reference
                else "variance"
                if delta
                else None,
            )
        )
    return dict(
        as_of_date=cutoff,
        rows=rows,
        baseline_total=money(sum(reference.values(), Decimal(0))),
        daily_total=money(sum(actual.values(), Decimal(0))),
        absolute_item_variance=money(sum((r["absolute_variance"] for r in rows), Decimal(0))),
    )


class Analysis:
    """Stateful deterministic tools shared by local and Microsoft Agent Framework orchestration."""

    def __init__(self, folder, cutoff, policy):
        self.folder = folder
        self.cutoff = cutoff
        self.policy = policy
        self.phase = 0
        self.policy = self.policy or Policy()
        self.markdown_pack = None
        if (self.folder / "suppliers.md").exists():
            from .markdown_data import load

            self.markdown_pack = load(self.folder)
            self.fingerprints = self.markdown_pack["fingerprints"]
            master_input, self.raw = (self.markdown_pack["masters"], self.markdown_pack["holdings"])
            self.labels, self.baseline = (self.markdown_pack["labels"], self.markdown_pack["baseline"])
        else:
            required = ("sku_master.json", "holdings.csv", "labels.json", "legacy_baseline.json")
            self.fingerprints = {
                name: hashlib.sha256((self.folder / name).read_bytes()).hexdigest() for name in required
            }
            master_input = json.loads((self.folder / "sku_master.json").read_text())
            self.raw = read_csv(self.folder / "holdings.csv")
            self.labels = json.loads((self.folder / "labels.json").read_text())
            self.baseline = json.loads((self.folder / "legacy_baseline.json").read_text())
        if (self.folder / "retrieval_evidence.json").exists():
            self.fingerprints["retrieval_evidence.json"] = hashlib.sha256(
                (self.folder / "retrieval_evidence.json").read_bytes()
            ).hexdigest()
        self.run_id = hashlib.sha256(
            json.dumps(
                dict(
                    files=self.fingerprints,
                    cutoff=str(self.cutoff),
                    policy=self.policy.model_dump(mode="json"),
                    code=CODE_VERSION,
                ),
                sort_keys=True,
            ).encode()
        ).hexdigest()[:24]
        self.masters = [Master.model_validate(row) for row in master_input]
        if len({identifier(m.canonical_sku) for m in self.masters}) != len(self.masters):
            raise ValueError("Canonical SKU identifiers must be unique after normalization")
        self.exceptions, self.handoffs, self.crosswalk = ([], [], [])

    def emit(self, agent, payload, confidence=1.0):
        self.handoffs.append(
            Handoff(
                run_id=self.run_id,
                as_of_date=self.cutoff,
                agent_id=f"local:{agent}",
                status="review_required" if self.exceptions else "complete",
                confidence=confidence,
                source_references=[f"{k}#sha256:{v}" for k, v in self.fingerprints.items()],
                exception_flags=sorted({e["reason"] for e in self.exceptions}),
                payload=jsonable(payload),
            ).model_dump(mode="json")
        )

    def retrieve(self):
        if self.phase != 0:
            raise ValueError("Agent stages must execute once in order")
        keys = [
            ("physical", r["physical_holding_id"])
            if r.get("physical_holding_id")
            else (r.get("source_system"), r.get("source_sku"), r.get("warehouse"))
            for r in self.raw
        ]
        counts = Counter(keys)
        self.holdings = []
        for index, row in enumerate(self.raw, start=2):
            ref = row.get("source_reference") or f"holdings.csv:row:{index}"
            try:
                holding = Holding.model_validate(row)
                age = (self.cutoff - holding.snapshot_date).days
                if counts[keys[index - 2]] > 1:
                    raise ValueError("duplicate_holding")
                if age < 0 or age > self.policy.max_feed_age_days:
                    raise ValueError("stale_or_future_snapshot")
                if holding.last_movement > holding.snapshot_date:
                    raise ValueError("future_movement")
                self.holdings.append((holding, ref))
            except (ValidationError, ValueError) as error:
                self.exceptions.append(
                    dict(
                        source_reference=ref,
                        source_sku=row.get("source_sku"),
                        reason="invalid_schema" if isinstance(error, ValidationError) else str(error),
                    )
                )
        self.emit("retrieval", dict(accepted=len(self.holdings), quarantined=len(self.exceptions)))
        self.phase = 1
        return self.handoffs[-1]

    def match_skus(self):
        if self.phase != 1:
            raise ValueError("Agent stages must execute once in order")
        self.grouped = defaultdict(list)
        for holding, ref in self.holdings:
            result = match(
                holding.source_sku,
                holding.description,
                self.masters,
                self.policy,
                holding.manufacturer,
                holding.manufacturer_part_number,
            )
            self.crosswalk.append(
                dict(
                    source_reference=ref,
                    source_sku=holding.source_sku,
                    source_system=holding.source_system,
                    crosswalk_version="1",
                    **result,
                )
            )
            if result["canonical_sku"] is None:
                self.exceptions.append(
                    dict(source_reference=ref, source_sku=holding.source_sku, reason="uncertain_match")
                )
            else:
                self.grouped[result["canonical_sku"]].append((holding, ref))
        self.quality = scorecard(self.labels, self.masters, self.policy)
        self.emit(
            "sku-matching",
            dict(crosswalk=self.crosswalk, scorecard=self.quality),
            self.quality["precision"] or 0,
        )
        self.phase = 2
        return self.handoffs[-1]

    def calculate(self):
        if self.phase != 2:
            raise ValueError("Agent stages must execute once in order")
        self.positions = []
        self.master_by_id = {m.canonical_sku: m for m in self.masters}
        for sku, pairs in sorted(self.grouped.items()):
            rows = [h for h, _ in pairs]
            signatures = {(h.unit_cost, h.monthly_demand, h.safety_stock) for h in rows}
            if len(signatures) != 1:
                self.exceptions.append(
                    dict(
                        canonical_sku=sku,
                        reason="conflicting_cost_or_demand",
                        source_references=[ref for _, ref in pairs],
                    )
                )
                continue
            first = rows[0]
            quantity = sum((h.quantity for h in rows), Decimal(0))
            target = first.monthly_demand * self.policy.horizon_months + first.safety_stock
            obsolete = sum(
                (
                    h.quantity
                    for h in rows
                    if self.master_by_id[sku].lifecycle == "obsolete"
                    or (
                        (self.cutoff - h.last_movement).days >= self.policy.obsolete_after_days
                        and first.monthly_demand == 0
                    )
                ),
                Decimal(0),
            )
            excess = max(Decimal(0), quantity - obsolete - target)
            risk_qty = obsolete + excess
            self.positions.append(
                dict(
                    canonical_sku=sku,
                    description=self.master_by_id[sku].description,
                    category=self.master_by_id[sku].category,
                    quantity=quantity,
                    unit_cost=first.unit_cost,
                    monthly_demand=first.monthly_demand,
                    target_stock=target,
                    obsolete_quantity=obsolete,
                    excess_quantity=excess,
                    eo_quantity=risk_qty,
                    eo_value=money(risk_qty * first.unit_cost),
                    inventory_value=money(quantity * first.unit_cost),
                    open_po_quantity=sum((h.open_po_quantity for h in rows), Decimal(0)),
                    max_age_days=max(((self.cutoff - h.last_movement).days for h in rows)),
                    source_references=[ref for _, ref in pairs],
                    rule_version=self.policy.version,
                )
            )
        self.reconciliation = (
            reconcile(self.positions, self.baseline, self.cutoff)
            if self.baseline["as_of_date"] == str(self.cutoff)
            else dict(
                status="not_comparable",
                reason="cutoff_mismatch",
                baseline_cutoff=self.baseline["as_of_date"],
                daily_cutoff=str(self.cutoff),
                rows=[],
            )
        )
        self.emit("eo-calculation", dict(positions=self.positions, reconciliation=self.reconciliation))
        self.phase = 3
        return self.handoffs[-1]

    def recommend(self):
        if self.phase != 3:
            raise ValueError("Agent stages must execute once in order")
        self.recommendations = []
        for position in self.positions:
            if not position["eo_quantity"]:
                continue
            master = self.master_by_id[position["canonical_sku"]]
            options = [("scrap", self.policy.scrap_rate)]
            if master.returnable:
                options.append(("supplier_return", self.policy.return_rate))
            if master.lifecycle != "obsolete":
                options.append(("discount", self.policy.discount_rate))
                if master.transferable:
                    options.append(("transfer", self.policy.transfer_rate))
            ranked = []
            for option, rate in options:
                net = money(
                    max(
                        Decimal(0),
                        position["eo_value"] * rate
                        - position["eo_quantity"] * self.policy.handling_cost_per_unit,
                    )
                )
                rid = hashlib.sha256(f"{self.run_id}:{master.canonical_sku}:{option}".encode()).hexdigest()[
                    :24
                ]
                ranked.append(
                    dict(
                        recommendation_id=rid,
                        canonical_sku=master.canonical_sku,
                        option=option,
                        quantity=position["eo_quantity"],
                        estimated_release=net,
                        approval_state="pending",
                        realized_cash=Decimal(0),
                        rule_version=self.policy.version,
                        assumptions=dict(
                            recovery_rate=rate,
                            handling_per_unit=self.policy.handling_cost_per_unit,
                            economics="Illustrative, validate with business owner",
                        ),
                        explanation=f"{position['eo_quantity']} at-risk units; {option} subject to feasibility confirmation",
                        constraints=[
                            "Human approval required",
                            "ERP execution remains manual",
                            "Confirm destination demand for transfers and supplier acceptance for returns",
                        ],
                        source_references=position["source_references"],
                    )
                )
            ranked.sort(key=lambda r: (-r["estimated_release"], r["option"]))
            for rank, rec in enumerate(ranked, start=1):
                self.recommendations.append(dict(rank=rank, **rec))
        self.emit("recommendation", dict(recommendations=self.recommendations))
        self.phase = 4
        return self.handoffs[-1]

    def result(self):
        if self.phase != 4:
            raise ValueError("Analysis is not complete")
        inventory = sum((p["inventory_value"] for p in self.positions), Decimal(0))
        eo = sum((p["eo_value"] for p in self.positions), Decimal(0))
        opportunity = sum(
            (r["estimated_release"] for r in self.recommendations if r["rank"] == 1), Decimal(0)
        )
        summary = dict(
            inventory_value=money(inventory),
            eo_value=money(eo),
            eo_pct=money(eo / inventory * 100) if inventory else None,
            estimated_release=money(opportunity),
            approved_release=0,
            realized_cash=0,
            analysed_skus=len(self.positions),
            exceptions=len(self.exceptions),
        )
        alerts = (
            [
                dict(
                    type="eo_threshold_breach",
                    value=eo,
                    threshold=self.policy.alert_value,
                    as_of_date=self.cutoff,
                    run_id=self.run_id,
                )
            ]
            if eo > self.policy.alert_value
            else []
        )
        reports = {
            "inventory_operations": f"E&O {eo:,.2f}; {len(self.exceptions)} exceptions. Review at-risk stock and unresolved matches.",
            "procurement": f"Review {sum((p['open_po_quantity'] for p in self.positions))} open PO units against excess positions; no automatic cancellation.",
            "finance": f"E&O exposure {eo:,.2f}; estimated net recovery {opportunity:,.2f}. Approved and realized values are separate; no savings booked.",
        }
        return jsonable(
            dict(
                run_id=self.run_id,
                as_of_date=self.cutoff,
                code_version=CODE_VERSION,
                data_mode="synthetic" if (self.folder / "SYNTHETIC_DATA.md").exists() else "user_supplied",
                governance_mode="local logical roles; Entra / Agent 365 not provisioned",
                policy=self.policy.model_dump(mode="json"),
                source_fingerprints=self.fingerprints,
                summary=summary,
                handoffs=self.handoffs,
                catalog=self.markdown_pack["catalog"] if self.markdown_pack else [],
                crosswalk=self.crosswalk,
                scorecard=self.quality,
                positions=self.positions,
                reconciliation=self.reconciliation,
                exceptions=self.exceptions,
                recommendations=self.recommendations,
                alerts=alerts,
                weekly_reports=reports,
            )
        )


def run_pack(folder: Path, cutoff: date, policy: Policy | None = None) -> dict:
    analysis = Analysis(folder, cutoff, policy)
    analysis.retrieve()
    analysis.match_skus()
    analysis.calculate()
    analysis.recommend()
    return analysis.result()
