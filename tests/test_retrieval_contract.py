from datetime import date

import pytest
from pydantic import ValidationError

from inventorypulse.agentic import RetrievalDecision, Runtime, retrieval_facts, validate_retrieval_decision
from inventorypulse.sample import generate
from inventorypulse.supplier_ingestion import FlatSupplierOffer, pack_count_from_unit, product_sections


def test_first_agent_llm_schemas_have_no_arrays_or_nested_objects():
    for model in (RetrievalDecision, FlatSupplierOffer):
        schema = model.model_json_schema()
        assert "$defs" not in schema
        for prop in schema["properties"].values():
            variants = prop.get("anyOf", [prop])
            assert all(v.get("type") not in {"object", "array"} for v in variants)
    assert len(RetrievalDecision.model_fields) == 3


def test_retrieval_cannot_smuggle_matching_suggestions_or_unsafe_proceed():
    with pytest.raises(ValidationError):
        RetrievalDecision(disposition="proceed", reason_code="ready", rationale="ready", match_suggestions=[])
    decision = RetrievalDecision(disposition="proceed", reason_code="ready", rationale="ready")
    with pytest.raises(ValueError, match="contradicts"):
        validate_retrieval_decision(decision, {"accepted_records": 0, "quarantined_records": 48})


def test_retrieval_facts_are_flat_and_zero_rows_stop(tmp_path):
    import asyncio

    generate(tmp_path, include_exceptions=False)
    runtime = Runtime(data=tmp_path, cutoff=date(2026, 11, 30))
    facts = retrieval_facts(asyncio.run(runtime.execute("retrieval")))
    assert facts["accepted_records"] == 0
    assert facts["quarantined_records"] == 48
    assert all(not isinstance(v, (dict, list)) for v in facts.values())
    decision = RetrievalDecision(
        disposition="request_review", reason_code="no_usable_data", rationale="No usable rows"
    )
    validate_retrieval_decision(decision, facts)


def test_document_framing_keeps_product_and_header_separate():
    from pathlib import Path

    folder = Path(__file__).parents[1] / "data" / "vendor-documents"
    for path in folder.glob("*.md"):
        text = path.read_text()
        header, blocks = product_sections(text)
        assert len(blocks) == 2
        assert header in text
        assert all(block in text for block in blocks)
    header, blocks = product_sections((folder / "002-card-01.md").read_text())
    assert "002-PC" in header
    assert "002-PC" not in blocks[0]
    assert "NL-04-02-1" in blocks[0]


def test_pack_conversion_never_uses_kg_as_item_count():
    assert pack_count_from_unit("can") == 1
    assert pack_count_from_unit("each") == 1
    assert pack_count_from_unit("pack of 10") == 10
    assert pack_count_from_unit("unknown") is None
    assert pack_count_from_unit("5 kg") is None
    assert pack_count_from_unit("1 piece (unit price)") == 1
    assert pack_count_from_unit("tub") == 1
    assert pack_count_from_unit("coil") == 1
    assert pack_count_from_unit("bag of 25") == 25
    assert pack_count_from_unit("box of 10") == 10


def test_flat_offer_has_only_nine_llm_fields_and_no_derived_pack_or_quote():
    assert len(FlatSupplierOffer.model_fields) == 9
    assert "pack_count" not in FlatSupplierOffer.model_fields
    assert "source_quote" not in FlatSupplierOffer.model_fields
