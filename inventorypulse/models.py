from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Master(Contract):
    canonical_sku: str = Field(min_length=1)
    description: str = Field(min_length=1)
    manufacturer: str = ""
    manufacturer_part_number: str = ""
    category: str = "general"
    lifecycle: Literal["active", "obsolete"] = "active"
    transferable: bool = False
    returnable: bool = False


class Holding(Contract):
    supplier_name: str = ""
    manufacturer: str = ""
    manufacturer_part_number: str = ""
    physical_holding_id: str = ""
    source_reference: str = ""
    source_system: str = Field(min_length=1)
    source_sku: str = Field(min_length=1)
    warehouse: str = Field(min_length=1)
    description: str = Field(min_length=1)
    snapshot_date: date
    quantity: Decimal = Field(ge=0)
    unit_cost: Decimal = Field(gt=0)
    monthly_demand: Decimal = Field(ge=0)
    safety_stock: Decimal = Field(ge=0)
    last_movement: date
    open_po_quantity: Decimal = Field(ge=0, default=0)


class Policy(Contract):
    version: str = "sample-policy-v1"
    horizon_months: Decimal = Field(gt=0, default=Decimal("3"))
    obsolete_after_days: int = Field(gt=0, default=365)
    max_feed_age_days: int = Field(ge=0, default=1)
    match_threshold: float = Field(ge=0, le=1, default=0.86)
    ambiguity_margin: float = Field(ge=0, le=1, default=0.08)
    alert_value: Decimal = Field(ge=0, default=Decimal("50000"))
    return_rate: Decimal = Field(ge=0, le=1, default=Decimal("0.85"))
    transfer_rate: Decimal = Field(ge=0, le=1, default=Decimal("0.75"))
    discount_rate: Decimal = Field(ge=0, le=1, default=Decimal("0.50"))
    scrap_rate: Decimal = Field(ge=0, le=1, default=Decimal("0.05"))
    handling_cost_per_unit: Decimal = Field(ge=0, default=Decimal("1"))


class Handoff(Contract):
    run_id: str
    as_of_date: date
    agent_id: str
    status: Literal["complete", "review_required"]
    input_version: str = "1"
    output_version: str = "1"
    source_references: list[str]
    confidence: float = Field(ge=0, le=1)
    exception_flags: list[str]
    payload: dict


class Decision(Contract):
    recommendation_id: str
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=3, max_length=1000)
