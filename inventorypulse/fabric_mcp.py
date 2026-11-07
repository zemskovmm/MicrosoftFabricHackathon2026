"""Published Fabric Data Agent MCP retrieval. Uses official MCP handshake and Entra tokens."""

import hashlib
import json
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .models import Holding, Master


class Pack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of_date: str
    sku_master: list[Master]
    holdings: list[Holding]
    labels: list[dict] = Field(default_factory=list)
    legacy_baseline: dict


async def fetch_pack(
    workspace_id: str, data_agent_id: str, as_of: str, destination: Path, *, credential=None
):
    """Only use this for a bounded prototype dataset; validate and fail closed on generated output."""
    from azure.identity import DefaultAzureCredential
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    UUID(workspace_id)
    UUID(data_agent_id)
    from datetime import date

    date.fromisoformat(as_of)
    endpoint = (
        f"https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspace_id}/dataagents/{data_agent_id}/agent"
    )
    owns_credential = credential is None
    credential = credential or DefaultAzureCredential()
    try:
        token = credential.get_token("https://api.fabric.microsoft.com/.default")
    finally:
        if owns_credential:
            credential.close()
    question = (
        f"Read only the approved InventoryPulse tables at cutoff {as_of}. Return a SINGLE JSON object, "
        "no markdown and no commentary. Never invent rows, identifiers, costs or missing values. "
        "Keys: as_of_date (YYYY-MM-DD), sku_master (canonical_sku,description,lifecycle,transferable,returnable), "
        "holdings (source_system,source_sku,warehouse,description,snapshot_date,quantity,unit_cost,"
        "monthly_demand,safety_stock,last_movement,open_po_quantity), "
        "labels: [] (do not access offline evaluation labels), "
        "legacy_baseline (as_of_date,positions:[{canonical_sku,eo_value}]). "
        "Return every record in the bounded demo scope; if unable, return an error instead of partial results."
    )
    async with streamablehttp_client(endpoint, headers={"Authorization": f"Bearer {token.token}"}) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            if len(tools) != 1:
                raise ValueError("Expected exactly one published Fabric Data Agent tool")
            tool = tools[0]
            properties = tool.inputSchema.get("properties", {})
            if len(properties) != 1 or next(iter(properties.values())).get("type") != "string":
                raise ValueError("Unsupported MCP question schema; review published agent configuration")
            result = await session.call_tool(tool.name, {next(iter(properties)): question})
            if result.isError:
                raise ValueError("Fabric MCP returned an error; no data accepted")
            answer = "\n".join(block.text for block in result.content if block.type == "text")
    pack = Pack.model_validate_json(answer)
    if pack.as_of_date != as_of or any(str(h.snapshot_date) != as_of for h in pack.holdings):
        raise ValueError("MCP response cutoff mismatch")
    if not pack.holdings or not pack.sku_master:
        raise ValueError("Empty MCP retrieval cannot establish a valid inventory scope")
    # Never overwrite an existing pack. Retain the response fingerprint for independent verification.
    destination.mkdir(parents=True, exist_ok=False)
    import csv

    with (destination / "holdings.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(Holding.model_fields))
        writer.writeheader()
        writer.writerows(h.model_dump(mode="json") for h in pack.holdings)
    for name, value in [
        ("sku_master", [m.model_dump(mode="json") for m in pack.sku_master]),
        ("labels", pack.labels),
        ("legacy_baseline", pack.legacy_baseline),
    ]:
        (destination / f"{name}.json").write_text(json.dumps(value, indent=2))
    (destination / "retrieval_evidence.json").write_text(
        json.dumps(
            dict(
                endpoint=endpoint,
                as_of_date=as_of,
                tool_name=tool.name,
                response_sha256=hashlib.sha256(answer.encode()).hexdigest(),
                holding_count=len(pack.holdings),
                warning="Validate completeness against source table row counts before relying on results",
            ),
            indent=2,
        )
    )
