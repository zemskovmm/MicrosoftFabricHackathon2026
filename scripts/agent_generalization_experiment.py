"""Isolated live-agent experiments with disjoint development and sealed holdout fixtures."""

import argparse
import asyncio
import csv
import hashlib
import json
import shutil
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_framework import WorkflowBuilder

from inventorypulse.agentic import InventoryAgentExecutor, Runtime, StageMessage, digest
from inventorypulse.engine import AGENTS
from inventorypulse.ollama_clients import OllamaChatClient


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def make_pack(folder, split, variant):
    folder.mkdir(parents=True)
    day = "2026-09-30" if split == "development" else "2027-02-28"
    prefix = "WORKSHOP" if split == "development" else "OBSERVATORY"
    maker = (
        "Copperfield Components (series B)" if split == "development" else "Lumen Optics / qualified grade"
    )
    masters, holdings, baseline = [], [], []
    for i in range(1, 4 if split == "development" else 6):
        sku, mpn = (
            f"{prefix}-{i}",
            f"{'CX' if split == 'development' else 'ZQ'}-{i:02}-{'A' if i % 2 else 'B'}",
        )
        desc = (
            f"{'Pressure valve' if split == 'development' else 'Optical positioning mount'} {i} size {i * 11}"
        )
        masters.append(
            dict(
                canonical_sku=sku,
                description=desc,
                manufacturer=maker,
                manufacturer_part_number=mpn,
                returnable=i % 2 == 0,
                transferable=True,
            )
        )
        quantity = 180 + i * 17 if split == "development" else 73 + i * 29
        demand, safety, cost = (12, 4, 11 + i) if split == "development" else (9, 7, 23 + i)
        holdings.append(
            dict(
                source_system="ERP",
                source_sku=f"{'SUP' if split == 'development' else 'DEPOT'}-{i * 91}",
                warehouse=f"Site-{i}",
                description=desc,
                manufacturer=maker,
                manufacturer_part_number=mpn,
                snapshot_date=day,
                quantity=quantity,
                unit_cost=cost,
                monthly_demand=demand,
                safety_stock=safety,
                last_movement=day,
                open_po_quantity=i * 3,
            )
        )
        baseline.append(dict(canonical_sku=sku, eo_value=str(max(0, quantity - demand * 3 - safety) * cost)))
    if variant == "empty_input":
        for h in holdings:
            h["snapshot_date"] = "2020-01-01"
            h["last_movement"] = "2019-12-01"
    if variant == "partial_input":
        holdings.append({**holdings[0], "source_sku": "UNPRICED-ROW", "unit_cost": -1})
    if variant == "unknown_identity":
        holdings[1]["manufacturer_part_number"] = "UNREGISTERED-EXECUTION"
    if variant == "different_cutoff":
        day_for_baseline = "2020-12-31"
    else:
        day_for_baseline = day
    if variant == "different_total":
        baseline[0]["eo_value"] = str(int(baseline[0]["eo_value"]) + 37)
    if variant == "renamed_permuted":
        holdings = list(reversed(holdings))
        masters = list(reversed(masters))
        baseline = list(reversed(baseline))
        for h in holdings:
            h["source_sku"] = "ALT-" + h["source_sku"]
            h["warehouse"] = "Renamed " + h["warehouse"]
    write(folder / "sku_master.json", masters)
    write(folder / "labels.json", [])
    write(folder / "legacy_baseline.json", dict(as_of_date=day_for_baseline, positions=baseline))
    with (folder / "holdings.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=holdings[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(holdings)
    (folder / "SYNTHETIC_DATA.md").write_text(
        "Invented evaluation fixture. One currency and base unit. No customer records.\n"
    )
    return date.fromisoformat(day)


class CaseRuntime(Runtime):
    variant: str = "clean"

    async def execute(self, role):
        receipt = await super().execute(role)
        if role == "recommendation" and self.variant in {"self_approved", "realized_before_execution"}:
            for r in receipt["handoff"]["payload"]["recommendations"]:
                if self.variant == "self_approved":
                    r["approval_state"] = "approved"
                else:
                    r["realized_cash"] = "42.00"
            receipt["receipt"] = digest(receipt["handoff"])
            # Upstream states are deliberately altered to test the agent, not the numerical engine.
        return receipt


PROTOCOL = {
    "model": "gpt-oss:latest",
    "temperature": 0,
    "development": {
        "retrieval": [["clean", "proceed"], ["partial_input", "proceed"], ["empty_input", "request_review"]],
        "sku-matching": [["clean", "proceed"], ["unknown_identity", "request_review"]],
        "eo-calculation": [
            ["clean", "proceed"],
            ["different_cutoff", "request_review"],
            ["different_total", "request_review"],
        ],
        "recommendation": [["clean", "proceed"], ["self_approved", "request_review"]],
    },
    "holdout": {
        "retrieval": [
            ["clean", "proceed"],
            ["partial_input", "proceed"],
            ["empty_input", "request_review"],
            ["renamed_permuted", "proceed"],
        ],
        "sku-matching": [
            ["clean", "proceed"],
            ["unknown_identity", "request_review"],
            ["renamed_permuted", "proceed"],
        ],
        "eo-calculation": [
            ["clean", "proceed"],
            ["different_cutoff", "request_review"],
            ["different_total", "request_review"],
            ["renamed_permuted", "proceed"],
        ],
        "recommendation": [
            ["clean", "proceed"],
            ["self_approved", "request_review"],
            ["realized_before_execution", "request_review"],
            ["renamed_permuted", "proceed"],
        ],
    },
    "rules": [
        "No model weight training or conversation/session reuse",
        "Only development outputs may inform prompt changes",
        "Freeze source/prompt hashes before the first holdout request; any later change invalidates the holdout",
        "Expected decisions are never sent to the model",
        "Only one model agent runs per case; prerequisites use deterministic tools",
        "Report failures without relabeling them or tuning on the holdout",
        "Compare paired valid/invalid cases and rename/order invariance",
    ],
}


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    write(root / "protocol.json", PROTOCOL)
    manifest = {}
    for split in ("development", "holdout"):
        for role, cases in PROTOCOL[split].items():
            for variant, expected in cases:
                folder = root / split / role / variant
                cutoff = make_pack(folder, split, variant)
                manifest[f"{split}/{role}/{variant}"] = dict(cutoff=str(cutoff), expected=expected)
    write(root / "case-manifest.json", manifest)
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
    write(root / "input-hashes.json", files)
    fingerprint = hashlib.sha256(
        (root / "protocol.json").read_bytes() + (root / "case-manifest.json").read_bytes()
    ).hexdigest()
    write(root / "preregistration.json", dict(protocol_sha256=fingerprint, holdout_opened=False))
    print(json.dumps(dict(prepared=str(root), preregistration=fingerprint)))


async def run(args):
    root = args.fixtures
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "case-manifest.json").read_text())
    source = {
        name: hashlib.sha256((repo / "inventorypulse" / name).read_bytes()).hexdigest()
        for name in ("agentic.py", "ollama_clients.py", "matching.py", "engine.py", "supplier_ingestion.py")
    }
    for name in source:
        shutil.copy2(repo / "inventorypulse" / name, out / name)
    write(out / "frozen-source.json", source)
    expected_files = json.loads((root / "input-hashes.json").read_text())
    if any(
        hashlib.sha256((root / p).read_bytes()).hexdigest() != value for p, value in expected_files.items()
    ):
        raise ValueError("Preregistered input data changed")
    if args.split == "holdout":
        marker = root / "holdout-opened.json"
        if marker.exists():
            raise ValueError("This holdout has already been opened; create a genuinely new evaluation set")
        write(marker, dict(frozen_source=source, output=str(out)))
    client = OllamaChatClient(args.model)
    calls = []

    async def before(request):
        if request.url.path == "/api/chat":
            calls.append({"request": json.loads(request.content)})

    async def after(response):
        if response.request.url.path != "/api/chat":
            return
        await response.aread()
        data = response.json()
        data.get("message", {}).pop("thinking", None)
        calls[-1]["response"] = data

    client.http.event_hooks = {"request": [before], "response": [after]}
    tags = (await client.http.get("/api/tags")).json()
    write(out / "model.json", next(m for m in tags["models"] if m["name"] == args.model))
    results = []
    try:
        for key, case in manifest.items():
            split, role, variant = key.split("/")
            if split != args.split:
                continue
            runtime = CaseRuntime(
                data=root / key,
                cutoff=date.fromisoformat(case["cutoff"]),
                provider=f"ollama:{args.model}",
                timeout_seconds=300,
            )
            runtime.variant = variant
            for earlier in AGENTS[: AGENTS.index(role)]:
                await runtime.execute(earlier)
            prior = runtime.receipts[AGENTS[AGENTS.index(role) - 1]]["receipt"] if role != "retrieval" else ""
            node = InventoryAgentExecutor(role, runtime, client)
            first, start = len(calls), time.monotonic()
            error = None
            try:
                await (
                    WorkflowBuilder(start_executor=node, output_from=[node])
                    .build()
                    .run(StageMessage(as_of_date=runtime.cutoff, previous_receipt=prior))
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            assessment = runtime.trace[-1] if runtime.trace else None
            row = dict(
                case=key,
                role=role,
                expected=case["expected"],
                assessment=assessment,
                error=error,
                passed=error is None
                and assessment is not None
                and assessment["disposition"] == case["expected"],
                seconds=round(time.monotonic() - start, 2),
                model_calls=len(calls) - first,
                active_llm_agents=1,
            )
            write(out / (key.replace("/", "-") + "-requests.json"), calls[first:])
            results.append(row)
            write(out / "results.json", results)
            print(json.dumps(row), flush=True)
    finally:
        await client.close()
    current = {
        name: hashlib.sha256((repo / "inventorypulse" / name).read_bytes()).hexdigest() for name in source
    }
    write(out / "freeze-integrity.json", dict(unchanged=current == source, source=current))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run"])
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--split", choices=["development", "holdout"], default="development")
    p.add_argument("--model", default="gpt-oss:latest")
    a = p.parse_args()
    if a.action == "prepare":
        prepare(a.fixtures)
    else:
        asyncio.run(run(a))
