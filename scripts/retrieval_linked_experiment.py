"""Live first-agent check: extracted vendor offers enrich a separate two-holding plant fixture."""

import argparse
import asyncio
import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_framework import WorkflowBuilder

from inventorypulse.agentic import InventoryAgentExecutor, Runtime, StageMessage
from inventorypulse.ollama_clients import OllamaChatClient


async def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    extraction = json.loads(args.extraction.read_text())
    candidates = [
        (d["supplier_name"], offer)
        for d in extraction
        for offer in d["offers"]
        if offer["manufacturer"] == "SKF" and offer["manufacturer_part_number"] == "6205-2RSH"
    ]
    selected = [candidates[0], next(c for c in candidates if c[0] != candidates[0][0])]
    pack = args.output / "plant-input"
    pack.mkdir()
    master = dict(
        canonical_sku="MRO-SKF-6205-2RSH",
        description="SKF sealed bearing 6205-2RSH",
        manufacturer="SKF",
        manufacturer_part_number="6205-2RSH",
        category="mechanical",
    )
    (pack / "sku_master.json").write_text(json.dumps([master]))
    (pack / "labels.json").write_text("[]")
    (pack / "legacy_baseline.json").write_text(
        json.dumps(
            dict(
                as_of_date="2026-10-31",
                positions=[dict(canonical_sku=master["canonical_sku"], eo_value="1560.00")],
            )
        )
    )
    rows = []
    for index, (supplier, offer) in enumerate(selected):
        rows.append(
            dict(
                source_system="ERP",
                supplier_name=supplier,
                source_sku=offer["source_sku"],
                physical_holding_id=f"HOLD-{index + 1}",
                warehouse=("Madrid", "Berlin")[index],
                description="Unresolved supplier item",
                snapshot_date="2026-10-31",
                quantity=(120, 80)[index],
                unit_cost=12,
                monthly_demand=20,
                safety_stock=10,
                last_movement="2026-09-01",
                open_po_quantity=0,
            )
        )
    with (pack / "holdings.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (pack / "SYNTHETIC_DATA.md").write_text(
        "Synthetic two-holding plant fixture. EUR, base unit each. Not supplier stock.\n"
    )
    client = OllamaChatClient(args.model)
    calls = []

    async def capture_request(request):
        if request.url.path == "/api/chat":
            calls.append({"request": json.loads(request.content)})

    async def capture_response(response):
        await response.aread()
        result = response.json()
        result.get("message", {}).pop("thinking", None)
        calls[-1]["response"] = result

    client.http.event_hooks = {"request": [capture_request], "response": [capture_response]}
    runtime = Runtime(
        data=pack,
        cutoff=date(2026, 10, 31),
        supplier_documents=args.documents,
        supplier_extraction=args.extraction,
        provider=f"ollama:{args.model}",
        timeout_seconds=300,
    )
    node = InventoryAgentExecutor("retrieval", runtime, client)
    try:
        await (
            WorkflowBuilder(start_executor=node, output_from=[node])
            .build()
            .run(StageMessage(as_of_date=runtime.cutoff))
        )
        assert runtime.analysis.phase == 1 and len(runtime.trace) == 1
        assert runtime.trace[0]["disposition"] == "proceed"
        assert len(runtime.analysis.holdings) == 2
        assert all(h.manufacturer_part_number == "6205-2RSH" for h, _ in runtime.analysis.holdings)
        result = dict(
            passed=True,
            model=args.model,
            documents_verified=len(extraction),
            offers_verified=sum(len(d["offers"]) for d in extraction),
            plant_holdings_enriched=2,
            assessment=runtime.trace[0],
            handoff=runtime.receipts["retrieval"],
            later_agents_executed=0,
        )
        (args.output / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k not in ("handoff", "assessment")}), flush=True)
    finally:
        (args.output / "requests.json").write_text(json.dumps(calls, indent=2))
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-oss:latest")
    parser.add_argument("--documents", type=Path, default=Path("data/vendor-documents"))
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
