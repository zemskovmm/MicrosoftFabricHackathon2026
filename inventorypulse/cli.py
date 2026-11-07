import argparse
import json
import os
import secrets
from datetime import date
from pathlib import Path

from .engine import run_pack
from .models import Decision, Policy
from .sample import generate
from .store import Store


def export(run, folder):
    import csv

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    for name in ("positions", "recommendations", "exceptions", "crosswalk", "alerts"):
        rows = run[name]
        with (folder / f"{name}.csv").open("w", newline="") as stream:
            fields = sorted({key for row in rows for key in row})
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(
                {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows
            )
    (folder / "weekly_reports.json").write_text(json.dumps(run["weekly_reports"], indent=2))


def main():
    parser = argparse.ArgumentParser(description="InventoryPulse synthetic demo and governed local analysis")
    parser.add_argument("--db", type=Path, default=Path("output/inventorypulse.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("sample")
    gen.add_argument("--folder", type=Path, default=Path("data/sample"))
    gen.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 31))
    run = sub.add_parser("run")
    run.add_argument("--data", type=Path, default=Path("data/sample"))
    run.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 31))
    run.add_argument("--policy", type=Path)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    approve = sub.add_parser("decide")
    approve.add_argument("run_id")
    approve.add_argument("recommendation_id")
    approve.add_argument("decision", choices=["approved", "rejected"])
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--reason", required=True)
    fetch = sub.add_parser("fabric-fetch")
    fetch.add_argument("--workspace", required=True)
    fetch.add_argument("--data-agent", required=True)
    fetch.add_argument("--as-of", type=date.fromisoformat, required=True)
    fetch.add_argument("--destination", type=Path, required=True)
    maf = sub.add_parser("agentic-run")
    maf.add_argument("--data", type=Path, default=Path("data/sample"))
    maf.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 31))
    maf.add_argument("--supplier-documents", type=Path)
    maf.add_argument("--supplier-extraction", type=Path)
    maf.add_argument("--workspace")
    maf.add_argument("--data-agent")
    maf.add_argument("--destination", type=Path)
    maf.add_argument("--policy", type=Path)
    extract = sub.add_parser("extract-suppliers")
    extract.add_argument("--documents", type=Path, default=Path("data/vendor-documents"))
    extract.add_argument("--destination", type=Path, default=Path("output/supplier-offers.json"))
    sub.add_parser("audit")
    args = parser.parse_args()
    if args.command == "sample":
        generate(args.folder, args.as_of)
        print(f"Synthetic pack written to {args.folder}; cutoff {args.as_of}")
        return
    if args.command == "fabric-fetch":
        import asyncio

        from .fabric_mcp import fetch_pack

        asyncio.run(fetch_pack(args.workspace, args.data_agent, str(args.as_of), args.destination))
        print(f"Retrieved bounded pack: {args.destination}. Verify row counts against source SQL.")
        return
    if args.command in ("agentic-run", "extract-suppliers"):
        import asyncio

        from .azure_clients import AzureClients

        async def execute_agents():
            async with AzureClients() as clients:
                if args.command == "extract-suppliers":
                    from .supplier_ingestion import extract_documents

                    rows = await extract_documents(args.documents, clients("retrieval"), args.destination)
                    return {
                        "documents": len(rows),
                        "offers": sum(len(r["offers"]) for r in rows),
                        "output": str(args.destination),
                        "status": "extracted_for_review",
                    }
                from .agentic import Runtime, run_workflow

                policy = Policy.model_validate_json(args.policy.read_text()) if args.policy else Policy()
                runtime = Runtime(
                    data=args.data,
                    cutoff=args.as_of,
                    policy=policy,
                    supplier_documents=args.supplier_documents,
                    supplier_extraction=args.supplier_extraction,
                    fabric_workspace=args.workspace,
                    fabric_data_agent=args.data_agent,
                    fabric_destination=args.destination,
                    fabric_credential=clients.credentials["retrieval"],
                    identity_ids=clients.identity_ids,
                )
                outcome = await run_workflow(runtime, clients)
                folder = Path("output") / outcome.run_id
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "agent-outcome.json").write_text(outcome.model_dump_json(indent=2))
                if outcome.status == "awaiting_human_approval":
                    run = runtime.final_run()
                    Store(args.db).save(run)
                    export(run, folder)
                return {"status": outcome.status, "run_id": outcome.run_id, "output": str(folder)}

        print(json.dumps(asyncio.run(execute_agents()), indent=2))
        return
    store = Store(args.db)
    if args.command == "run":
        policy = Policy.model_validate_json(args.policy.read_text()) if args.policy else Policy()
        result = run_pack(args.data, args.as_of, policy)
        store.save(result)
        folder = Path("output") / result["run_id"]
        export(result, folder)
        print(json.dumps(dict(run_id=result["run_id"], output=str(folder), **result["summary"]), indent=2))
    elif args.command == "serve":
        import uvicorn

        from .api import create_app

        key = os.environ.get("INVENTORYPULSE_APPROVAL_KEY") or secrets.token_urlsafe(32)
        print(f"Local approval key (keep private): {key}", flush=True)
        print(f"Dashboard: http://127.0.0.1:{args.port}", flush=True)
        uvicorn.run(create_app(store, key), host="127.0.0.1", port=args.port)
    elif args.command == "decide":
        result = store.decide(
            args.run_id,
            Decision(
                recommendation_id=args.recommendation_id,
                decision=args.decision,
                reviewer=args.reviewer,
                reason=args.reason,
            ),
        )
        export(result, Path("output") / result["run_id"])
        print(json.dumps(result["summary"], indent=2))
    else:
        print(json.dumps(store.audit(), indent=2))


if __name__ == "__main__":
    main()
