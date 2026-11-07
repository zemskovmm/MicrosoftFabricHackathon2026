import asyncio
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from agent_framework import BaseChatClient, ChatResponse, Message

from inventorypulse.agentic import Runtime
from inventorypulse.sample import generate
from inventorypulse.supplier_ingestion import ExtractedDocument, extract_documents, validate_extraction

TEXT = "# Example supplier\nSKU: V-101 | Brand: SKF | MPN: 6205-2RSH | Pack: each | EUR 10.00\n"


def extracted():
    return ExtractedDocument(
        supplier_name="Example supplier",
        warnings=[],
        offers=[
            dict(
                source_sku="V-101",
                manufacturer="SKF",
                manufacturer_part_number="6205-2RSH",
                description="Sealed bearing",
                pack_count=1,
                unit_description="each",
                price_text="10.00",
                currency="EUR",
                source_quote="SKU: V-101 | Brand: SKF | MPN: 6205-2RSH | Pack: each | EUR 10.00",
            )
        ],
    )


def test_extraction_requires_verbatim_evidence_and_known_fields():
    parsed = extracted()
    validate_extraction(parsed, TEXT)
    parsed.offers[0].manufacturer_part_number = "6205-2Z"
    with pytest.raises(ValueError, match="absent"):
        validate_extraction(parsed, TEXT)
    parsed = extracted()
    parsed.offers[0].source_quote = "Fabricated quote"
    with pytest.raises(ValueError, match="verbatim"):
        validate_extraction(parsed, TEXT)


class ExtractionModel(BaseChatClient):
    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        return ChatResponse(messages=Message("assistant", [extracted().model_dump_json()]))


def test_real_agent_extracts_and_validates_markdown_without_manual_converter(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "offer.md").write_text(TEXT)
    output = tmp_path / "extraction.json"
    rows = asyncio.run(extract_documents(docs, ExtractionModel(), output))
    assert rows[0]["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert json.loads(output.read_text()) == rows
    with pytest.raises(FileExistsError):
        asyncio.run(extract_documents(docs, ExtractionModel(), output))


def test_50_supplier_documents_present_with_three_formats_and_categories():
    docs = Path(__file__).parents[1] / "data" / "vendor-documents"
    files = list(docs.glob("*.md"))
    assert len(files) == 50
    assert all(p.stat().st_size for p in files)
    assert {"table", "card", "quote"} == {p.name.split("-")[1] for p in files}
    text = "\n".join(p.read_text() for p in files)
    assert all(category in text for category in ("Mechanical", "Electrical", "Consumables"))


def test_source_hash_and_identity_conflicts_block_enrichment(tmp_path):
    pack = tmp_path / "pack"
    generate(pack)
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "offer.md"
    source.write_text(TEXT)
    output = tmp_path / "extraction.json"
    asyncio.run(extract_documents(docs, ExtractionModel(), output))
    runtime = Runtime(
        data=pack,
        cutoff=date(2026, 10, 31),
        supplier_documents=docs,
        supplier_extraction=output,
        provider="simulated_model",
    )
    source.write_text(TEXT + "New revision")
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(runtime.execute("retrieval"))
    assert not runtime.receipts
